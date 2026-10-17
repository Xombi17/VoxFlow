"""Validated provider selection and network-policy configuration.

Provider settings are copied into a frozen snapshot before a dictation job is
dispatched. A credential is never part of the snapshot: remote providers may
refer to the name of an environment variable, and only a concrete transport
may resolve that name at request time.
"""

from __future__ import annotations

import ipaddress
import re
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr
from pydantic import field_validator, model_validator


class ProviderKind(StrEnum):
    """The explicitly selected class of ASR implementation."""

    LOCAL = "local"
    REMOTE = "remote"


class NetworkPolicy(StrEnum):
    """Network permission captured with each provider selection."""

    LOCAL_ONLY = "local_only"
    REMOTE_EXPLICIT = "remote_explicit"


_ENVIRONMENT_VARIABLE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _validate_endpoint(value: str) -> str:
    """Validate an HTTP(S) endpoint without retaining credentials in a URL."""

    if not value.strip() or value != value.strip():
        raise ValueError("remote endpoint must not be blank or padded")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("remote endpoint must not contain whitespace")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("remote endpoint is malformed") from exc
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError("remote endpoint must use http or https")
    if not hostname:
        raise ValueError("remote endpoint must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("remote endpoint must not embed credentials")
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("remote endpoint port is invalid")
    if parsed.fragment:
        raise ValueError("remote endpoint must not include a fragment")
    return value.rstrip("/")


def _validate_environment_variable(value: str | None) -> str | None:
    if value is None:
        return None
    if not _ENVIRONMENT_VARIABLE.fullmatch(value):
        raise ValueError("credential_env_var must be an environment-variable name")
    return value


def _validate_optional_endpoint(value: str | None) -> str | None:
    return None if value is None else _validate_endpoint(value)


class RemoteProviderConfig(BaseModel):
    """User-supplied remote provider settings without a credential value."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    provider_id: StrictStr = Field(default="remote-asr", min_length=1)
    model_id: StrictStr = Field(min_length=1)
    endpoint: StrictStr = Field(min_length=1)
    transport_timeout_seconds: float = Field(default=30.0, gt=0, le=300, strict=False)
    network_disclosure: StrictBool = True
    credential_env_var: StrictStr | None = None

    _endpoint_validator = field_validator("endpoint")(_validate_endpoint)
    _credential_validator = field_validator("credential_env_var")(_validate_environment_variable)

    @field_validator("model_id", "provider_id")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provider and model IDs must not be blank")
        return value

    @property
    def endpoint_classification(self) -> str:
        """Return a safe coarse endpoint class without exposing host/path data."""

        return classify_endpoint(self.endpoint)

    def to_safe_dict(self) -> dict[str, object]:
        """Return diagnostics with no endpoint, credential, or machine data."""

        return {
            "provider_kind": ProviderKind.REMOTE.value,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "endpoint_classification": self.endpoint_classification,
            "transport_timeout_seconds": self.transport_timeout_seconds,
            "network_disclosure": self.network_disclosure,
        }

    def to_selection(
        self,
        *,
        network_policy: NetworkPolicy = NetworkPolicy.REMOTE_EXPLICIT,
        language_hint: str | None = None,
        vad_filter: bool = True,
        vad_min_silence_duration_ms: int | None = None,
        beam_size: int = 5,
        device: str = "cpu",
        thread_count: int = 1,
        max_duration_ms: int = 30_000,
    ) -> "ProviderSelectionSnapshot":
        return ProviderSelectionSnapshot(
            provider_kind=ProviderKind.REMOTE,
            provider_id=self.provider_id,
            model_id=self.model_id,
            language_hint=language_hint,
            vad_filter=vad_filter,
            vad_min_silence_duration_ms=vad_min_silence_duration_ms,
            beam_size=beam_size,
            device=device,
            thread_count=thread_count,
            max_duration_ms=max_duration_ms,
            network_policy=network_policy,
            endpoint=self.endpoint,
            transport_timeout_seconds=self.transport_timeout_seconds,
            network_disclosure=self.network_disclosure,
            credential_env_var=self.credential_env_var,
        )


class ProviderSelectionSnapshot(BaseModel):
    """Frozen provider/model/network decision attached to one job."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    provider_kind: ProviderKind = ProviderKind.LOCAL
    provider_id: StrictStr = Field(default="local-whisper", min_length=1)
    model_id: StrictStr = Field(default="local-default", min_length=1)
    language_hint: StrictStr | None = None
    vad_filter: StrictBool = True
    vad_min_silence_duration_ms: StrictInt | None = Field(default=None, gt=0)
    beam_size: StrictInt = Field(default=5, gt=0, le=32)
    device: StrictStr = Field(default="cpu", min_length=1)
    thread_count: StrictInt = Field(default=1, gt=0, le=256)
    max_duration_ms: StrictInt = Field(default=30_000, gt=0)
    network_policy: NetworkPolicy = NetworkPolicy.LOCAL_ONLY
    endpoint: StrictStr | None = None
    transport_timeout_seconds: float = Field(default=30.0, gt=0, le=300, strict=False)
    network_disclosure: StrictBool | None = None
    credential_env_var: StrictStr | None = None

    _endpoint_validator = field_validator("endpoint")(_validate_optional_endpoint)
    _credential_validator = field_validator("credential_env_var")(_validate_environment_variable)

    @field_validator("provider_id", "model_id", "device")
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provider, model, and device values must not be blank")
        return value

    @field_validator("language_hint")
    @classmethod
    def validate_language_hint(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("language_hint must not be blank")
        return value

    @model_validator(mode="after")
    def validate_selection(self) -> "ProviderSelectionSnapshot":
        is_remote = self.provider_kind is ProviderKind.REMOTE
        if is_remote and self.endpoint is None:
            raise ValueError("remote provider selections require an endpoint")
        if not is_remote and self.endpoint is not None:
            raise ValueError("local provider selections must not include a remote endpoint")
        if self.network_disclosure is None:
            object.__setattr__(self, "network_disclosure", is_remote)
        if not is_remote and self.network_disclosure:
            raise ValueError("local provider selections must not disclose network use")
        if is_remote and not self.network_disclosure:
            raise ValueError("remote provider selections must disclose network use")
        return self

    @classmethod
    def local(
        cls,
        *,
        provider_id: str = "local-whisper",
        model_id: str = "local-default",
        **settings: object,
    ) -> "ProviderSelectionSnapshot":
        return cls(
            provider_kind=ProviderKind.LOCAL,
            provider_id=provider_id,
            model_id=model_id,
            **settings,
        )

    @property
    def endpoint_classification(self) -> str | None:
        return classify_endpoint(self.endpoint) if self.endpoint is not None else None

    @property
    def dispatch_allowed(self) -> bool:
        """Whether this frozen selection permits its provider kind to run."""

        return self.provider_kind is ProviderKind.LOCAL or (
            self.network_policy is NetworkPolicy.REMOTE_EXPLICIT
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize safe job metadata without endpoint paths or credential values."""

        return {
            "provider_kind": self.provider_kind.value,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "language_hint": self.language_hint,
            "vad_filter": self.vad_filter,
            "vad_min_silence_duration_ms": self.vad_min_silence_duration_ms,
            "beam_size": self.beam_size,
            "device": self.device,
            "thread_count": self.thread_count,
            "max_duration_ms": self.max_duration_ms,
            "network_policy": self.network_policy.value,
            "endpoint_classification": self.endpoint_classification,
            "transport_timeout_seconds": self.transport_timeout_seconds,
            "network_disclosure": self.network_disclosure,
        }

    def to_safe_diagnostic(self) -> dict[str, object]:
        """Serialize only the allowlisted provider identity and policy fields."""

        return {
            "provider_kind": self.provider_kind.value,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "endpoint_classification": self.endpoint_classification,
            "network_policy": self.network_policy.value,
            "network_disclosure": self.network_disclosure,
        }


def classify_endpoint(endpoint: str) -> str:
    """Classify an endpoint without returning its host, port, or path."""

    parsed = urlsplit(endpoint)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".local"):
        return "lan"
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private or address.is_loopback or address.is_link_local
    ):
        return "lan"
    if parsed.scheme.lower() == "https":
        return "https"
    return "http"


# Compatibility names retain the Phase 2 Plan 02 imports.
ProviderConfigSnapshot = ProviderSelectionSnapshot
ASRJobConfig = ProviderSelectionSnapshot


# SQLite settings key holding the catalogue id of the selected local model.
SELECTED_MODEL_SETTING = "selected_model_id"
