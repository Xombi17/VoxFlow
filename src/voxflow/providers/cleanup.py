"""Injectable cleanup providers with an explicit remote transport boundary."""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Protocol

from ..providers.asr import CancellationToken
from .config import CleanupProviderConfig, NetworkPolicy, classify_endpoint

if TYPE_CHECKING:
    from ..text.contracts import WritingSettings


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


class CleanupProviderError(RuntimeError):
    """A recoverable cleanup failure with a stable, non-sensitive code."""

    def __init__(self, code: str, reason: str = "Cleanup provider failed.") -> None:
        self.code = code
        self.reason = reason
        super().__init__(reason)


class CleanupCancellationError(CleanupProviderError):
    """Cooperative cancellation reported by a cleanup provider."""

    def __init__(self, reason: str = "Cleanup was cancelled.") -> None:
        super().__init__("cancelled", reason)


@dataclass(frozen=True, slots=True, repr=False)
class CleanupRequest:
    """Transport-neutral cleanup input; text is available only in memory."""

    raw_text: str = field(repr=False)
    settings: WritingSettings = field(repr=False)
    provider_id: str
    timeout_seconds: float
    endpoint: str | None = field(default=None, repr=False)
    credential_env_var: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.raw_text, str) or not self.raw_text.strip():
            raise ValueError("raw_text must not be blank")
        if not _SAFE_IDENTIFIER.fullmatch(self.provider_id):
            raise ValueError("provider_id must be a safe identifier")
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(
            self.timeout_seconds, bool
        ) or not 0 < float(self.timeout_seconds) <= 300:
            raise ValueError("timeout_seconds must be greater than 0 and at most 300")

    @property
    def endpoint_classification(self) -> str | None:
        return classify_endpoint(self.endpoint) if self.endpoint is not None else None

    def to_safe_dict(self) -> dict[str, object]:
        """Return policy metadata without raw text, endpoint, or credentials."""

        return {
            "provider_id": self.provider_id,
            "endpoint_classification": self.endpoint_classification,
            "timeout_seconds": float(self.timeout_seconds),
            "settings": self.settings.to_safe_dict(),
        }


@dataclass(frozen=True, slots=True, repr=False)
class CleanupResponse:
    """Status and decoded payload returned by an injected transport."""

    status_code: int
    payload: Any = field(repr=False)


class CleanupTransport(Protocol):
    """Async boundary for a remote request; implementations own networking."""

    async def request(
        self,
        request: CleanupRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken,
    ) -> CleanupResponse: ...


class CleanupProvider(Protocol):
    """Async provider contract used by the optional writing stage."""

    @property
    def provider_id(self) -> str: ...

    @property
    def network_required(self) -> bool: ...

    @property
    def timeout_seconds(self) -> float: ...

    async def cleanup(self, request: CleanupRequest, cancellation: CancellationToken) -> str: ...


class CleanupTransportError(CleanupProviderError):
    """A transport failure whose response detail must not escape the boundary."""


_SAFE_TRANSPORT_REASONS = {
    "credential_missing": "The configured cleanup credential is unavailable.",
    "network_disabled": "Remote cleanup network access is disabled by the environment.",
    "remote_http_error": "The remote cleanup endpoint returned a non-success status.",
    "remote_invalid_response": "The remote cleanup endpoint returned an invalid response.",
    "remote_timeout": "The remote cleanup request timed out.",
    "remote_transport_failed": "The remote cleanup transport failed.",
}


class UrllibCleanupTransport:
    """Lazy standard-library transport for an explicitly opted-in host call."""

    async def request(
        self,
        request: CleanupRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken,
    ) -> CleanupResponse:
        _raise_if_cancelled(cancellation)
        if os.environ.get("NETWORK_DISABLED") == "1":
            raise CleanupTransportError(
                "network_disabled", _SAFE_TRANSPORT_REASONS["network_disabled"]
            )
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._request_sync, request, timeout_seconds),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise CleanupTransportError(
                "remote_timeout", _SAFE_TRANSPORT_REASONS["remote_timeout"]
            ) from exc
        except asyncio.CancelledError as exc:
            raise CleanupCancellationError() from exc

    @staticmethod
    def _request_sync(request: CleanupRequest, timeout_seconds: float) -> CleanupResponse:
        if not request.endpoint:
            raise CleanupTransportError(
                "remote_transport_failed", _SAFE_TRANSPORT_REASONS["remote_transport_failed"]
            )
        credential = None
        if request.credential_env_var is not None:
            credential = os.environ.get(request.credential_env_var)
            if not credential:
                raise CleanupTransportError(
                    "credential_missing", _SAFE_TRANSPORT_REASONS["credential_missing"]
                )
        try:
            body = json.dumps(
                {
                    "text": request.raw_text,
                    "language": request.settings.language,
                    "style": request.settings.style.value,
                    "provider_id": request.provider_id,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            if credential is not None:
                headers["Authorization"] = f"Bearer {credential}"
            http_request = urllib.request.Request(
                request.endpoint,
                data=body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
                return CleanupResponse(response.status, json.loads(response.read()))
        except urllib.error.HTTPError as exc:
            raise CleanupTransportError(
                "remote_http_error", _SAFE_TRANSPORT_REASONS["remote_http_error"]
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CleanupTransportError(
                "remote_transport_failed", _SAFE_TRANSPORT_REASONS["remote_transport_failed"]
            ) from exc
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CleanupTransportError(
                "remote_invalid_response", _SAFE_TRANSPORT_REASONS["remote_invalid_response"]
            ) from exc


class RemoteCleanupProvider:
    """Remote cleanup provider guarded by the frozen per-job network policy."""

    def __init__(
        self,
        config: CleanupProviderConfig,
        *,
        transport: CleanupTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or UrllibCleanupTransport()

    @property
    def provider_id(self) -> str:
        return self.config.provider_id

    @property
    def network_required(self) -> bool:
        return True

    @property
    def timeout_seconds(self) -> float:
        return self.config.transport_timeout_seconds

    async def cleanup(self, request: CleanupRequest, cancellation: CancellationToken) -> str:
        _raise_if_cancelled(cancellation)
        from ..text.contracts import CleanupPolicy

        if request.settings.cleanup_policy is not CleanupPolicy.PROVIDER:
            raise CleanupProviderError(
                "cleanup_policy_rejected",
                "Remote cleanup requires the provider cleanup policy.",
            )
        if (
            request.settings.cleanup_network_policy is not NetworkPolicy.REMOTE_EXPLICIT
            or not request.settings.cleanup_network_disclosure
            or not self.config.network_disclosure
        ):
            raise CleanupProviderError(
                "network_policy_rejected",
                "Remote cleanup requires remote_explicit policy and network disclosure.",
            )
        if request.provider_id != self.provider_id:
            raise CleanupProviderError(
                "provider_config_mismatch", "The cleanup provider identity changed.",
            )

        transport_timeout_seconds = min(
            request.timeout_seconds,
            self.config.transport_timeout_seconds,
        )
        transport_request = replace(
            request,
            endpoint=self.config.endpoint,
            credential_env_var=self.config.credential_env_var,
            timeout_seconds=transport_timeout_seconds,
        )
        try:
            response = await self.transport.request(
                transport_request,
                timeout_seconds=transport_timeout_seconds,
                cancellation=cancellation,
            )
        except CleanupCancellationError:
            raise
        except asyncio.CancelledError as exc:
            raise CleanupCancellationError() from exc
        except CleanupProviderError as exc:
            if exc.code == "cancelled" or cancellation.is_cancelled:
                raise CleanupCancellationError() from exc
            code = exc.code if exc.code in _SAFE_TRANSPORT_REASONS else "remote_transport_failed"
            raise CleanupProviderError(code, _SAFE_TRANSPORT_REASONS[code]) from exc
        except asyncio.TimeoutError as exc:
            raise CleanupProviderError(
                "remote_timeout", _SAFE_TRANSPORT_REASONS["remote_timeout"]
            ) from exc
        except Exception as exc:
            raise CleanupProviderError(
                "remote_transport_failed", _SAFE_TRANSPORT_REASONS["remote_transport_failed"]
            ) from exc

        _raise_if_cancelled(cancellation)
        if not isinstance(response, CleanupResponse) or not isinstance(response.status_code, int):
            raise CleanupProviderError(
                "remote_invalid_response", _SAFE_TRANSPORT_REASONS["remote_invalid_response"]
            )
        if not 200 <= response.status_code < 300:
            raise CleanupProviderError(
                "remote_http_error", _SAFE_TRANSPORT_REASONS["remote_http_error"]
            )
        value = _result_text(response.payload)
        if value is None:
            raise CleanupProviderError(
                "remote_invalid_response", _SAFE_TRANSPORT_REASONS["remote_invalid_response"]
            )
        return value


def _result_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    for key in ("text", "cleaned_text"):
        result = value.get(key)
        if isinstance(result, str):
            return result
    nested = value.get("result")
    return _result_text(nested) if isinstance(nested, dict) else None


def _raise_if_cancelled(cancellation: CancellationToken) -> None:
    if cancellation.is_cancelled:
        raise CleanupCancellationError()


__all__ = [
    "CleanupCancellationError",
    "CleanupProvider",
    "CleanupProviderError",
    "CleanupRequest",
    "CleanupResponse",
    "CleanupTransport",
    "CleanupTransportError",
    "RemoteCleanupProvider",
    "UrllibCleanupTransport",
]
