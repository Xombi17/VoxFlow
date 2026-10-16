"""Replaceable input-device and audio-stream contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AudioFormat:
    """A negotiated input format exposed to the next pipeline stage."""

    sample_rate: int
    channels: int

    def __post_init__(self) -> None:
        if self.sample_rate < 1:
            raise ValueError("sample_rate must be positive")
        if self.channels < 1:
            raise ValueError("channels must be positive")

    def to_dict(self) -> dict[str, int]:
        return {
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }


@dataclass(frozen=True, slots=True)
class AudioDevice:
    """Stable input-device identity and the format metadata it advertises."""

    id: str
    name: str
    is_default: bool = False
    is_muted: bool = False
    supported_formats: tuple[AudioFormat, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("audio device id must not be blank")
        if not self.name.strip():
            raise ValueError("audio device name must not be blank")
        object.__setattr__(self, "supported_formats", tuple(self.supported_formats))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "is_default": self.is_default,
            "is_muted": self.is_muted,
            "supported_formats": [
                audio_format.to_dict() for audio_format in self.supported_formats
            ],
        }

    def to_safe_dict(self, *, label: str | None = None) -> dict[str, object]:
        """Return probe-safe metadata without emitting device identifiers."""

        return {
            "id": label or "<redacted-device-id>",
            "name": "<redacted-device-name>",
            "is_default": self.is_default,
            "is_muted": self.is_muted,
            "supported_formats": [
                audio_format.to_dict() for audio_format in self.supported_formats
            ],
        }


@dataclass(frozen=True, slots=True)
class AudioDeviceSelection:
    """The default and selected device IDs returned by discovery."""

    devices: tuple[AudioDevice, ...]
    default_device_id: str | None
    selected_device_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "devices", tuple(self.devices))

    @property
    def selected_device(self) -> AudioDevice | None:
        return next(
            (
                device
                for device in self.devices
                if device.id == self.selected_device_id
            ),
            None,
        )


class AudioStream(Protocol):
    """Async lifecycle boundary for a backend-owned capture stream."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OpenedAudioStream:
    """A backend's opened handle and the format it actually negotiated."""

    device: AudioDevice
    format: AudioFormat
    stream: AudioStream


class AudioBackend(Protocol):
    """Injectable backend contract used by discovery, capture, and probes."""

    async def enumerate_devices(self) -> Sequence[AudioDevice]: ...

    async def open(
        self,
        device_id: str,
        requested_format: AudioFormat | None = None,
    ) -> OpenedAudioStream: ...


# Names used by the later audio pipeline remain explicit aliases at this
# boundary, so callers do not need to know which host backend supplies them.
InputDevice = AudioDevice
NegotiatedAudioFormat = AudioFormat
