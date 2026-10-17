"""Typed domain events emitted by platform adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AudioEventType(StrEnum):
    """Observable lifecycle events for one microphone capture handle."""

    CAPTURE_OPENED = "capture_opened"
    CAPTURE_STARTED = "capture_started"
    CAPTURE_STOPPED = "capture_stopped"
    CAPTURE_CLOSED = "capture_closed"
    CAPTURE_FAILED = "capture_failed"


@dataclass(frozen=True, slots=True)
class AudioEvent:
    """A sample-free audio event safe for core/UI consumers and diagnostics."""

    type: AudioEventType
    sequence: int
    device_id: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    error_code: str | None = None
    error_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", AudioEventType(self.type))
        if self.sequence < 1:
            raise ValueError("audio event sequence must be positive")
        if self.sample_rate is not None and self.sample_rate < 1:
            raise ValueError("audio event sample_rate must be positive")
        if self.channels is not None and self.channels < 1:
            raise ValueError("audio event channels must be positive")
        if self.error_code is None and self.error_reason is not None:
            raise ValueError("audio event error_reason requires error_code")

    def to_dict(self) -> dict[str, object]:
        """Serialize lifecycle metadata without captured audio samples."""

        return {
            "type": self.type.value,
            "sequence": self.sequence,
            "device_id": (
                "<redacted-device-id>"
                if self.device_id is not None and self.device_id.startswith("/")
                else self.device_id
            ),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "error_code": self.error_code,
            "error_reason": self.error_reason,
        }
