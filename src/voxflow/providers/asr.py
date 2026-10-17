"""Provider-independent ASR contracts.

Concrete providers receive only the current bounded audio artifact and an
immutable configuration snapshot.  The models in this module are the single
validation boundary for provider output.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from pydantic import field_validator, model_validator

from ..audio.artifacts import AudioArtifact
from ..platform.audio_devices import AudioFormat
from .config import (
    ASRJobConfig,
    NetworkPolicy,
    ProviderConfigSnapshot,
    ProviderKind,
    ProviderSelectionSnapshot,
)


SHA256_PATTERN = r"^[0-9a-fA-F]{64}$"


class ASRContractError(ValueError):
    """Base error for invalid provider input or output."""

    code = "asr_contract_error"


class ASRValidationError(ASRContractError):
    """Provider output failed the typed contract."""

    code = "invalid_result"


class ASRProviderError(RuntimeError):
    """A recoverable provider/model failure with a stable code."""

    def __init__(self, code: str, reason: str = "ASR provider failed.") -> None:
        self.code = code
        self.reason = reason
        super().__init__(reason)


class ASRCancellationError(ASRProviderError):
    """Cooperative provider cancellation."""

    def __init__(self, reason: str = "ASR transcription was cancelled.") -> None:
        super().__init__("cancelled", reason)


class AudioInput(BaseModel):
    """One immutable audio artifact handed to an ASR provider."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
        strict=True,
    )

    path: Path
    audio_sha256: StrictStr = Field(pattern=SHA256_PATTERN)
    source_format: AudioFormat
    duration_ms: StrictInt = Field(gt=0)
    config: ProviderSelectionSnapshot

    @classmethod
    def from_artifact(
        cls,
        artifact: AudioArtifact,
        config: ProviderSelectionSnapshot,
    ) -> Self:
        return cls(
            path=artifact.path,
            audio_sha256=artifact.audio_sha256,
            source_format=artifact.source_format,
            duration_ms=artifact.duration_ms,
            config=config,
        )

    @field_validator("audio_sha256")
    @classmethod
    def validate_checksum(cls, value: str) -> str:
        try:
            int(value, 16)
        except ValueError as exc:
            raise ValueError("audio_sha256 must be hexadecimal") from exc
        return value

    def to_dict(self) -> dict[str, object]:
        """Return safe metadata without a local path or audio payload."""

        return {
            "artifact_id": self.path.name,
            "audio_sha256": self.audio_sha256,
            "source_format": self.source_format.to_dict(),
            "duration_ms": self.duration_ms,
            "config": self.config.to_dict(),
        }


class Segment(BaseModel):
    """One ordered, timestamped transcript segment."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    start_ms: StrictInt = Field(ge=0)
    end_ms: StrictInt = Field(gt=0)
    text: StrictStr = Field(min_length=1)
    confidence: StrictFloat | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError("segment end_ms must be greater than start_ms")
        if not self.text.strip():
            raise ValueError("segment text must not be blank")
        return self


class TranscriptResult(BaseModel):
    """Validated output that remains bound to the exact input artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    text: StrictStr
    language: StrictStr | None = None
    language_probability: StrictFloat | None = Field(default=None, ge=0, le=1)
    confidence: StrictFloat | None = Field(default=None, ge=0, le=1)
    # JSON transports naturally represent segments as arrays. Pydantic converts
    # that structural container to the immutable tuple used by the contract,
    # while still validating every segment strictly.
    segments: tuple[Segment, ...] = Field(default_factory=tuple, strict=False)
    provider_id: StrictStr = Field(min_length=1)
    model_id: StrictStr = Field(min_length=1)
    audio_sha256: StrictStr = Field(pattern=SHA256_PATTERN)

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("language must not be blank")
        return value

    @field_validator("audio_sha256")
    @classmethod
    def validate_result_checksum(cls, value: str) -> str:
        try:
            int(value, 16)
        except ValueError as exc:
            raise ValueError("audio_sha256 must be hexadecimal") from exc
        return value

    @model_validator(mode="after")
    def validate_segments(self) -> Self:
        previous_end = 0
        for segment in self.segments:
            if segment.start_ms < previous_end:
                raise ValueError("transcript segments must not overlap")
            previous_end = segment.end_ms
        return self

    def assert_matches(self, audio_sha256: str) -> Self:
        if self.audio_sha256 != audio_sha256:
            raise ASRValidationError("provider result does not match the input audio")
        return self

    def to_safe_dict(self) -> dict[str, object]:
        """Serialize diagnostic metadata while omitting transcript text."""

        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "audio_sha256": self.audio_sha256,
            "language": self.language,
            "language_probability": self.language_probability,
            "confidence": self.confidence,
            "segment_count": len(self.segments),
            "segment_bounds_ms": [
                {"start_ms": segment.start_ms, "end_ms": segment.end_ms}
                for segment in self.segments
            ],
        }


class ProviderCapabilities(BaseModel):
    """Capabilities exposed to selection/settings surfaces."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    provider_id: StrictStr = Field(min_length=1)
    model_id: StrictStr = Field(min_length=1)
    offline: StrictBool
    network_required: StrictBool
    supports_cancellation: StrictBool
    supported_languages: tuple[StrictStr, ...] = ()
    supported_devices: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def validate_network_policy(self) -> Self:
        if self.offline and self.network_required:
            raise ValueError("offline providers cannot require a network")
        return self

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class CancellationToken:
    """Thread-safe cooperative cancellation signal for sync model iterators."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise ASRCancellationError()


class ASRProvider(Protocol):
    """Async provider boundary shared by local and optional remote adapters."""

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def transcribe(
        self,
        audio: AudioInput,
        cancellation: CancellationToken,
    ) -> TranscriptResult: ...


def validate_provider_result(
    value: TranscriptResult | Mapping[str, object],
    audio_sha256: str,
) -> TranscriptResult:
    """Validate provider output exactly once at the core boundary."""

    try:
        result = value if isinstance(value, TranscriptResult) else TranscriptResult.model_validate(value)
    except Exception as exc:
        raise ASRValidationError("provider returned an invalid transcript result") from exc
    return result.assert_matches(audio_sha256)


def is_sha256(value: str) -> bool:
    """Small public predicate for callers validating fixture metadata."""

    return len(value) == hashlib.sha256().digest_size * 2 and all(
        character in "0123456789abcdefABCDEF" for character in value
    )


# Compatibility alias for callers that used the short selection name.
ProviderSelection = ProviderSelectionSnapshot
