"""Opt-in remote ASR adapter behind an injectable transport boundary.

The provider itself performs no socket work. Tests and application wiring can
inject a transport, while the lazy urllib transport is available only to an
explicit host probe or an explicitly configured application path.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from .asr import (
    ASRCancellationError,
    ASRProvider,
    ASRProviderError,
    ASRValidationError,
    AudioInput,
    CancellationToken,
    ProviderCapabilities,
    TranscriptResult,
    validate_provider_result,
)
from .config import NetworkPolicy, ProviderKind, ProviderSelectionSnapshot, RemoteProviderConfig


@dataclass(frozen=True, slots=True, repr=False)
class RemoteASRRequest:
    """Transport-neutral request containing only one bounded audio input."""

    audio: AudioInput = field(repr=False)
    endpoint: str = field(repr=False)
    provider_id: str
    model_id: str
    language_hint: str | None
    credential_env_var: str | None = field(default=None, repr=False)

    def to_safe_dict(self) -> dict[str, object]:
        """Return request metadata without path, audio bytes, or credentials."""

        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "language_hint": self.language_hint,
            "audio_sha256": self.audio.audio_sha256,
            "source_format": self.audio.source_format.to_dict(),
            "duration_ms": self.audio.duration_ms,
        }


@dataclass(frozen=True, slots=True, repr=False)
class RemoteASRResponse:
    """Status and already-decoded payload returned by a transport."""

    status_code: int
    payload: Any = field(repr=False)


class RemoteTransport(Protocol):
    """Async boundary for a remote request; implementations own networking."""

    async def request(
        self,
        request: RemoteASRRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken,
    ) -> RemoteASRResponse: ...


class RemoteTransportError(ASRProviderError):
    """A transport failure with a stable code and no response-body detail."""


_SAFE_TRANSPORT_REASONS = {
    "credential_missing": "The configured remote credential is unavailable.",
    "network_disabled": "Remote network access is disabled by the environment.",
    "remote_http_error": "The remote ASR endpoint returned a non-success status.",
    "remote_invalid_response": "The remote ASR endpoint returned an invalid response.",
    "remote_timeout": "The remote ASR request timed out.",
    "remote_transport_failed": "The remote ASR transport failed.",
}


class UrllibRemoteTransport:
    """Lazy standard-library transport for an explicitly opted-in host call."""

    async def request(
        self,
        request: RemoteASRRequest,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken,
    ) -> RemoteASRResponse:
        cancellation.raise_if_cancelled()
        if os.environ.get("NETWORK_DISABLED") == "1":
            raise RemoteTransportError("network_disabled", _SAFE_TRANSPORT_REASONS["network_disabled"])
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._request_sync, request, timeout_seconds),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise RemoteTransportError("remote_timeout", _SAFE_TRANSPORT_REASONS["remote_timeout"]) from exc
        except asyncio.CancelledError as exc:
            raise ASRCancellationError() from exc

    @staticmethod
    def _request_sync(request: RemoteASRRequest, timeout_seconds: float) -> RemoteASRResponse:
        if not request.audio.path.is_file():
            raise RemoteTransportError(
                "remote_transport_failed",
                "The current audio artifact is unavailable to the remote transport.",
            )
        credential = None
        if request.credential_env_var is not None:
            credential = os.environ.get(request.credential_env_var)
            if not credential:
                raise RemoteTransportError(
                    "credential_missing",
                    _SAFE_TRANSPORT_REASONS["credential_missing"],
                )
        try:
            audio_bytes = request.audio.path.read_bytes()
            body = json.dumps(
                {
                    "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                    "audio_sha256": request.audio.audio_sha256,
                    "source_format": request.audio.source_format.to_dict(),
                    "duration_ms": request.audio.duration_ms,
                    "model_id": request.model_id,
                    "language": request.language_hint,
                },
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
                response_body = response.read()
                payload = json.loads(response_body)
                return RemoteASRResponse(status_code=response.status, payload=payload)
        except urllib.error.HTTPError as exc:
            raise RemoteTransportError(
                "remote_http_error",
                _SAFE_TRANSPORT_REASONS["remote_http_error"],
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RemoteTransportError(
                "remote_transport_failed",
                _SAFE_TRANSPORT_REASONS["remote_transport_failed"],
            ) from exc
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RemoteTransportError(
                "remote_invalid_response",
                _SAFE_TRANSPORT_REASONS["remote_invalid_response"],
            ) from exc


class RemoteASRProvider(ASRProvider):
    """Remote provider that maps transport results into the shared ASR contract."""

    def __init__(
        self,
        config: ProviderSelectionSnapshot | RemoteProviderConfig,
        *,
        transport: RemoteTransport | None = None,
    ) -> None:
        if isinstance(config, RemoteProviderConfig):
            config = config.to_selection()
        if config.provider_kind is not ProviderKind.REMOTE:
            raise ValueError("RemoteASRProvider requires a remote provider selection")
        self.config = config
        self.transport = transport or UrllibRemoteTransport()

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.config.provider_id,
            model_id=self.config.model_id,
            offline=False,
            network_required=True,
            supports_cancellation=True,
        )

    async def transcribe(
        self,
        audio: AudioInput,
        cancellation: CancellationToken,
    ) -> TranscriptResult:
        cancellation.raise_if_cancelled()
        if audio.config.provider_kind is not ProviderKind.REMOTE:
            raise ASRProviderError(
                "provider_config_mismatch",
                "The remote provider received a non-remote job selection.",
            )
        if audio.config.network_policy is not NetworkPolicy.REMOTE_EXPLICIT:
            raise ASRProviderError(
                "network_policy_rejected",
                "Remote ASR requires explicit remote_explicit network policy.",
            )
        if (
            audio.config.provider_id != self.config.provider_id
            or audio.config.model_id != self.config.model_id
        ):
            raise ASRProviderError(
                "provider_config_mismatch",
                "The remote provider received a changed provider selection.",
            )

        request = RemoteASRRequest(
            audio=audio,
            endpoint=self.config.endpoint or "",
            provider_id=self.config.provider_id,
            model_id=self.config.model_id,
            language_hint=audio.config.language_hint,
            credential_env_var=self.config.credential_env_var,
        )
        try:
            response = await self.transport.request(
                request,
                timeout_seconds=self.config.transport_timeout_seconds,
                cancellation=cancellation,
            )
        except ASRCancellationError:
            raise
        except asyncio.CancelledError as exc:
            raise ASRCancellationError() from exc
        except ASRProviderError as exc:
            if exc.code == "cancelled" or cancellation.is_cancelled:
                raise ASRCancellationError() from exc
            code = exc.code if exc.code in _SAFE_TRANSPORT_REASONS else "remote_transport_failed"
            raise ASRProviderError(code, _SAFE_TRANSPORT_REASONS[code]) from exc
        except asyncio.TimeoutError as exc:
            raise ASRProviderError(
                "remote_timeout",
                _SAFE_TRANSPORT_REASONS["remote_timeout"],
            ) from exc
        except Exception as exc:
            raise ASRProviderError(
                "remote_transport_failed",
                _SAFE_TRANSPORT_REASONS["remote_transport_failed"],
            ) from exc

        cancellation.raise_if_cancelled()
        if not isinstance(response, RemoteASRResponse) or not isinstance(
            response.status_code, int
        ):
            raise ASRProviderError(
                "remote_invalid_response",
                _SAFE_TRANSPORT_REASONS["remote_invalid_response"],
            )
        if not 200 <= response.status_code < 300:
            raise ASRProviderError(
                "remote_http_error",
                _SAFE_TRANSPORT_REASONS["remote_http_error"],
            )
        payload = _result_payload(response.payload)
        try:
            result = validate_provider_result(payload, audio.audio_sha256)
        except ASRValidationError as exc:
            if isinstance(payload, dict) and payload.get("audio_sha256") not in {
                None,
                audio.audio_sha256,
            }:
                raise ASRValidationError(
                    "remote response checksum does not match input audio"
                ) from exc
            raise ASRValidationError("remote response failed transcript validation") from exc
        if result.provider_id != self.config.provider_id:
            raise ASRValidationError("remote response provider identity does not match selection")
        if result.model_id != self.config.model_id:
            raise ASRValidationError("remote response model identity does not match selection")
        return result


def _result_payload(value: Any) -> Any:
    """Extract a result object without rendering arbitrary response data."""

    if not isinstance(value, dict):
        return value
    nested = value.get("result")
    return nested if isinstance(nested, dict) else value
