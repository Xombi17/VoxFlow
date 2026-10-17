"""Injectable microphone discovery and bounded capture lifecycle contracts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..core.capabilities import CapabilityRecord, CapabilityStatus
from ..core.events import AudioEvent, AudioEventType
from .audio_devices import (
    AudioBackend,
    AudioDevice,
    AudioDeviceSelection,
    AudioFrameCallback,
    AudioFormat,
    AudioStream,
    OpenedAudioStream,
)


class AudioErrorCode(StrEnum):
    """Stable failure codes shared by host backends and diagnostics."""

    NO_DEVICE = "no_device"
    PERMISSION_DENIED = "permission_denied"
    DISCONNECTED = "disconnected"
    MUTED = "muted"
    UNSUPPORTED_FORMAT = "unsupported_format"
    BACKEND_UNAVAILABLE = "backend_unavailable"


class AudioBackendError(RuntimeError):
    """A backend failure carrying a stable error code and implementation detail."""

    def __init__(self, code: AudioErrorCode, detail: str) -> None:
        self.code = AudioErrorCode(code)
        self.detail = detail.strip() or self.code.value
        super().__init__(self.detail)


@dataclass(frozen=True, slots=True)
class AudioFailure:
    """An actionable audio error safe to expose to the user and UI."""

    code: AudioErrorCode
    status: CapabilityStatus
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "status": self.status.value,
            "reason": self.reason,
        }


def map_audio_error(error: BaseException) -> AudioFailure:
    """Normalize backend exceptions without exposing raw host exception text."""

    if isinstance(error, AudioBackendError):
        code = error.code
        detail = error.detail
    else:
        detail = str(error).strip() or error.__class__.__name__
        text = detail.lower()
        if isinstance(error, PermissionError) or any(
            marker in text
            for marker in ("permission", "access denied", "not permitted", "denied")
        ):
            code = AudioErrorCode.PERMISSION_DENIED
        elif any(
            marker in text
            for marker in ("disconnect", "unplug", "no such device", "invalid device")
        ):
            code = AudioErrorCode.DISCONNECTED
        elif any(marker in text for marker in ("muted", "mute")):
            code = AudioErrorCode.MUTED
        elif any(
            marker in text
            for marker in ("format", "sample rate", "samplerate", "channel")
        ):
            code = AudioErrorCode.UNSUPPORTED_FORMAT
        elif isinstance(error, (FileNotFoundError, ImportError, ModuleNotFoundError)):
            code = AudioErrorCode.BACKEND_UNAVAILABLE
        else:
            code = AudioErrorCode.BACKEND_UNAVAILABLE

    if code is AudioErrorCode.NO_DEVICE:
        status = CapabilityStatus.UNSUPPORTED
        reason = (
            "No input microphone is available. Connect or enable a microphone, "
            "then refresh the device list."
        )
    elif code is AudioErrorCode.PERMISSION_DENIED:
        status = CapabilityStatus.NEEDS_USER_ACTION
        reason = (
            "Microphone permission was denied. Allow VoxFlow microphone access in "
            "desktop settings, then try again."
        )
    elif code is AudioErrorCode.DISCONNECTED:
        status = CapabilityStatus.NEEDS_USER_ACTION
        reason = (
            "The selected microphone disconnected. Reconnect it, select it again, "
            "and retry capture."
        )
    elif code is AudioErrorCode.MUTED:
        status = CapabilityStatus.NEEDS_USER_ACTION
        reason = (
            "The selected microphone is muted. Unmute it in system audio settings "
            "and retry capture."
        )
    elif code is AudioErrorCode.UNSUPPORTED_FORMAT:
        status = CapabilityStatus.UNSUPPORTED
        reason = (
            "The selected microphone does not support the requested sample rate or "
            "channel count. Choose a format advertised by the device."
        )
    else:
        status = CapabilityStatus.UNSUPPORTED
        reason = (
            "No supported audio backend is available. Install/configure a "
            "PipeWire-compatible input backend and retry the probe."
        )

    # Keep the stable code in the diagnostic while deliberately omitting raw
    # backend details, which may contain host paths or device internals.
    del detail
    return AudioFailure(code=code, status=status, reason=reason)


def capability_for_audio_failure(
    failure: AudioFailure,
    *,
    capability_id: str = "audio.input",
) -> CapabilityRecord:
    return CapabilityRecord(
        id=capability_id,
        status=failure.status,
        reason=failure.reason,
    )


@dataclass(frozen=True, slots=True)
class AudioDiscoveryResult:
    """Device selection plus the capability result for the input boundary."""

    selection: AudioDeviceSelection
    capability: CapabilityRecord
    failure: AudioFailure | None = None

    @property
    def devices(self) -> tuple[AudioDevice, ...]:
        return self.selection.devices

    @property
    def default_device_id(self) -> str | None:
        return self.selection.default_device_id

    @property
    def selected_device_id(self) -> str | None:
        return self.selection.selected_device_id


class AudioDeviceDiscovery:
    """Discover and select one input without touching a capture stream."""

    def __init__(self, backend: AudioBackend) -> None:
        self.backend = backend

    async def discover(self, selected_device_id: str | None = None) -> AudioDiscoveryResult:
        try:
            raw_devices = await self.backend.enumerate_devices()
            devices = tuple(self._validate_devices(raw_devices))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = map_audio_error(exc)
            return self._failed_result(failure)

        if not devices:
            failure = map_audio_error(
                AudioBackendError(AudioErrorCode.NO_DEVICE, "device enumeration was empty")
            )
            return self._failed_result(failure)

        default_device = next((device for device in devices if device.is_default), devices[0])
        if selected_device_id is not None:
            selected_device = next(
                (device for device in devices if device.id == selected_device_id),
                None,
            )
            if selected_device is None:
                failure = map_audio_error(
                    AudioBackendError(
                        AudioErrorCode.NO_DEVICE,
                        "the requested device was not found",
                    )
                )
                return AudioDiscoveryResult(
                    selection=AudioDeviceSelection(
                        devices=devices,
                        default_device_id=default_device.id,
                        selected_device_id=None,
                    ),
                    capability=capability_for_audio_failure(failure),
                    failure=failure,
                )
        else:
            selected_device = default_device

        if selected_device.is_muted:
            failure = map_audio_error(
                AudioBackendError(AudioErrorCode.MUTED, "selected device is muted")
            )
            return AudioDiscoveryResult(
                selection=AudioDeviceSelection(
                    devices=devices,
                    default_device_id=default_device.id,
                    selected_device_id=selected_device.id,
                ),
                capability=capability_for_audio_failure(failure),
                failure=failure,
            )

        return AudioDiscoveryResult(
            selection=AudioDeviceSelection(
                devices=devices,
                default_device_id=default_device.id,
                selected_device_id=selected_device.id,
            ),
            capability=CapabilityRecord(
                id="audio.input",
                status=CapabilityStatus.AVAILABLE,
                reason=(
                    f"Input device '{selected_device.name}' is available. Open it to "
                    "negotiate a capture format."
                ),
            ),
        )

    @staticmethod
    def _validate_devices(devices: Sequence[AudioDevice]) -> tuple[AudioDevice, ...]:
        validated = tuple(devices)
        if any(not isinstance(device, AudioDevice) for device in validated):
            raise AudioBackendError(
                AudioErrorCode.BACKEND_UNAVAILABLE,
                "audio backend returned an invalid device record",
            )
        if len({device.id for device in validated}) != len(validated):
            raise AudioBackendError(
                AudioErrorCode.BACKEND_UNAVAILABLE,
                "audio backend returned duplicate device IDs",
            )
        return validated

    @staticmethod
    def _failed_result(failure: AudioFailure) -> AudioDiscoveryResult:
        return AudioDiscoveryResult(
            selection=AudioDeviceSelection(
                devices=(),
                default_device_id=None,
                selected_device_id=None,
            ),
            capability=capability_for_audio_failure(failure),
            failure=failure,
        )


class AudioCaptureState(StrEnum):
    """Lifecycle states for one backend-owned audio handle."""

    CLOSED = "closed"
    OPEN = "open"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AudioCaptureConfig:
    """Bounded capture settings without making an ASR/model commitment."""

    requested_format: AudioFormat | None = None
    max_buffer_frames: int = 128

    def __post_init__(self) -> None:
        if self.max_buffer_frames < 1:
            raise ValueError("max_buffer_frames must be positive")


class AudioCaptureError(RuntimeError):
    """A capture operation failure with a stable user-facing failure record."""

    def __init__(self, failure: AudioFailure) -> None:
        self.failure = failure
        super().__init__(f"{failure.code.value}: {failure.reason}")


EventListener = Callable[[AudioEvent], object]


class AudioCapture:
    """Open, start, stop, and close an injectable audio stream deterministically."""

    def __init__(
        self,
        backend: AudioBackend,
        *,
        selected_device_id: str | None = None,
        requested_format: AudioFormat | None = None,
        config: AudioCaptureConfig | None = None,
        max_buffer_frames: int = 128,
        listener: EventListener | None = None,
    ) -> None:
        if config is not None and requested_format is not None:
            raise ValueError("use config or requested_format, not both")
        self.backend = backend
        self.selected_device_id = selected_device_id
        self.config = config or AudioCaptureConfig(
            requested_format=requested_format,
            max_buffer_frames=max_buffer_frames,
        )
        self._listeners: list[EventListener] = []
        if listener is not None:
            self._listeners.append(listener)
        self._state = AudioCaptureState.CLOSED
        self._sequence = 0
        self._stream: AudioStream | None = None
        self._device: AudioDevice | None = None
        self._format: AudioFormat | None = None
        self._last_failure: AudioFailure | None = None
        self._discovery: AudioDiscoveryResult | None = None

    @property
    def state(self) -> AudioCaptureState:
        return self._state

    @property
    def device(self) -> AudioDevice | None:
        return self._device

    @property
    def negotiated_format(self) -> AudioFormat | None:
        return self._format

    @property
    def last_failure(self) -> AudioFailure | None:
        return self._last_failure

    @property
    def has_active_stream(self) -> bool:
        return self._stream is not None

    @property
    def discovery(self) -> AudioDiscoveryResult | None:
        return self._discovery

    def add_listener(self, listener: EventListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    async def open(self) -> OpenedAudioStream:
        if self._state not in {AudioCaptureState.CLOSED, AudioCaptureState.FAILED}:
            raise RuntimeError(f"cannot open capture while state is {self._state.value}")
        if self._state is AudioCaptureState.FAILED and self._stream is not None:
            close_failure = await self.close()
            if close_failure is not None:
                raise AudioCaptureError(close_failure)

        discovery = await AudioDeviceDiscovery(self.backend).discover(
            self.selected_device_id
        )
        self._discovery = discovery
        if discovery.failure is not None or discovery.selected_device_id is None:
            failure = discovery.failure or map_audio_error(
                AudioBackendError(AudioErrorCode.NO_DEVICE, "no device was selected")
            )
            self._record_failure(failure)
            raise AudioCaptureError(failure)

        opened: OpenedAudioStream | None = None
        try:
            opened = await self.backend.open(
                discovery.selected_device_id,
                self.config.requested_format,
            )
            if isinstance(opened, OpenedAudioStream):
                self._stream = opened.stream
                self._device = opened.device
                self._format = opened.format
                self._state = AudioCaptureState.OPEN
            self._validate_opened_stream(opened, discovery.selected_device_id)
        except asyncio.CancelledError:
            if isinstance(opened, OpenedAudioStream):
                cleanup_failure = await self._close_failed_stream(opened.stream)
                if cleanup_failure is None:
                    self._stream = None
                    self._state = AudioCaptureState.CLOSED
                else:
                    self._record_failure(cleanup_failure)
            raise
        except Exception as exc:
            if isinstance(opened, OpenedAudioStream):
                cleanup_failure = await self._close_failed_stream(opened.stream)
                if cleanup_failure is None:
                    self._stream = None
                else:
                    self._record_failure(cleanup_failure)
                    raise AudioCaptureError(cleanup_failure) from exc
            failure = map_audio_error(exc)
            self._record_failure(failure)
            raise AudioCaptureError(failure) from exc

        self._stream = opened.stream
        self._device = opened.device
        self._format = opened.format
        self._last_failure = None
        self._state = AudioCaptureState.OPEN
        self._emit(
            AudioEventType.CAPTURE_OPENED,
            device_id=opened.device.id,
            sample_rate=opened.format.sample_rate,
            channels=opened.format.channels,
        )
        return opened

    async def start(self) -> None:
        if self._state not in {AudioCaptureState.OPEN, AudioCaptureState.STOPPED}:
            raise RuntimeError(f"cannot start capture while state is {self._state.value}")
        assert self._stream is not None
        stream = self._stream
        try:
            await stream.start()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = map_audio_error(exc)
            cleanup_failure = await self._close_failed_stream(stream)
            if cleanup_failure is None:
                self._stream = None
            else:
                self._record_failure(cleanup_failure)
                raise AudioCaptureError(cleanup_failure) from exc
            self._record_failure(failure)
            raise AudioCaptureError(failure) from exc
        self._state = AudioCaptureState.RUNNING
        self._emit(
            AudioEventType.CAPTURE_STARTED,
            device_id=self._device.id if self._device else None,
            sample_rate=self._format.sample_rate if self._format else None,
            channels=self._format.channels if self._format else None,
        )

    async def stop(self) -> None:
        if self._state is not AudioCaptureState.RUNNING:
            return
        assert self._stream is not None
        try:
            await self._stream.stop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = map_audio_error(exc)
            self._record_failure(failure)
            raise AudioCaptureError(failure) from exc
        self._state = AudioCaptureState.STOPPED
        self._emit(
            AudioEventType.CAPTURE_STOPPED,
            device_id=self._device.id if self._device else None,
            sample_rate=self._format.sample_rate if self._format else None,
            channels=self._format.channels if self._format else None,
        )

    async def close(self) -> AudioFailure | None:
        """Stop and close the backend handle even when stop reports a failure."""

        failure: AudioFailure | None = None
        stream = self._stream
        if stream is None:
            self._state = AudioCaptureState.CLOSED
            return None

        if self._state is AudioCaptureState.RUNNING:
            try:
                await stream.stop()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failure = map_audio_error(exc)
                self._record_failure(failure)

        try:
            await stream.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Keep the backend handle for a retry. Reporting it as closed here
            # would make the probe and the next lifecycle operation lie.
            close_failure = map_audio_error(exc)
            self._record_failure(close_failure)
            return close_failure

        self._stream = None
        self._state = AudioCaptureState.CLOSED
        self._emit(
            AudioEventType.CAPTURE_CLOSED,
            device_id=self._device.id if self._device else None,
            sample_rate=self._format.sample_rate if self._format else None,
            channels=self._format.channels if self._format else None,
        )
        return failure

    async def __aenter__(self) -> AudioCapture:
        await self.open()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    def _record_failure(self, failure: AudioFailure) -> None:
        self._last_failure = failure
        self._state = AudioCaptureState.FAILED
        self._emit(
            AudioEventType.CAPTURE_FAILED,
            device_id=self._device.id if self._device else self.selected_device_id,
            sample_rate=self._format.sample_rate if self._format else None,
            channels=self._format.channels if self._format else None,
            error_code=failure.code.value,
            error_reason=failure.reason,
        )

    async def _close_failed_stream(self, stream: AudioStream) -> AudioFailure | None:
        """Close a backend handle that failed before capture became open."""

        try:
            await stream.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return map_audio_error(exc)
        return None

    def _emit(
        self,
        event_type: AudioEventType,
        *,
        device_id: str | None = None,
        sample_rate: int | None = None,
        channels: int | None = None,
        error_code: str | None = None,
        error_reason: str | None = None,
    ) -> None:
        self._sequence += 1
        event = AudioEvent(
            type=event_type,
            sequence=self._sequence,
            device_id=device_id,
            sample_rate=sample_rate,
            channels=channels,
            error_code=error_code,
            error_reason=error_reason,
        )
        for listener in tuple(self._listeners):
            listener(event)

    def _validate_opened_stream(
        self,
        opened: OpenedAudioStream,
        selected_device_id: str,
    ) -> None:
        if not isinstance(opened, OpenedAudioStream):
            raise AudioBackendError(
                AudioErrorCode.BACKEND_UNAVAILABLE,
                "audio backend returned an invalid opened stream",
            )
        if opened.device.id != selected_device_id:
            raise AudioBackendError(
                AudioErrorCode.DISCONNECTED,
                "audio backend opened a different device",
            )
        if self.config.requested_format is not None:
            requested = self.config.requested_format
            if opened.format != requested:
                raise AudioBackendError(
                    AudioErrorCode.UNSUPPORTED_FORMAT,
                    "audio backend did not negotiate the requested format",
                )


class SoundDeviceBackend:
    """Optional host backend using ``sounddevice`` over the PipeWire/Pulse stack."""

    def __init__(self) -> None:
        self._sounddevice: Any | None = None

    def _module(self) -> Any:
        if self._sounddevice is not None:
            return self._sounddevice
        try:
            import sounddevice as sounddevice  # type: ignore[import-not-found]
        except ImportError as exc:
            raise AudioBackendError(
                AudioErrorCode.BACKEND_UNAVAILABLE,
                "sounddevice is not installed for the live audio transport",
            ) from exc
        self._sounddevice = sounddevice
        return sounddevice

    async def enumerate_devices(self) -> Sequence[AudioDevice]:
        sounddevice = self._module()
        try:
            raw_devices = sounddevice.query_devices()
            default = getattr(sounddevice.default, "device", (-1, -1))
            default_input = default[0] if isinstance(default, (tuple, list)) else -1
            devices: list[AudioDevice] = []
            for index, raw in enumerate(raw_devices):
                max_input_channels = int(raw.get("max_input_channels", 0))
                if max_input_channels < 1:
                    continue
                default_rate = int(round(float(raw.get("default_samplerate", 0))))
                if default_rate < 1:
                    raise AudioBackendError(
                        AudioErrorCode.UNSUPPORTED_FORMAT,
                        "input device has no usable default sample rate",
                    )
                devices.append(
                    AudioDevice(
                        id=str(index),
                        name=str(raw.get("name", f"Input device {index}")),
                        is_default=index == default_input,
                        supported_formats=(
                            AudioFormat(
                                sample_rate=default_rate,
                                channels=max_input_channels,
                            ),
                        ),
                    )
                )
            return devices
        except AudioBackendError:
            raise
        except Exception as exc:
            failure = map_audio_error(exc)
            raise AudioBackendError(
                failure.code,
                "sounddevice could not enumerate input devices",
            ) from exc

    async def open(
        self,
        device_id: str,
        requested_format: AudioFormat | None = None,
    ) -> OpenedAudioStream:
        sounddevice = self._module()
        devices = tuple(await self.enumerate_devices())
        device = next((candidate for candidate in devices if candidate.id == device_id), None)
        if device is None:
            raise AudioBackendError(AudioErrorCode.NO_DEVICE, "selected input device is absent")
        if not device.supported_formats:
            raise AudioBackendError(
                AudioErrorCode.UNSUPPORTED_FORMAT,
                "input device has no advertised format",
            )
        default_format = device.supported_formats[0]
        negotiated = requested_format or default_format
        if negotiated.channels > default_format.channels:
            raise AudioBackendError(
                AudioErrorCode.UNSUPPORTED_FORMAT,
                "requested format is outside the host probe contract",
            )

        stream_adapter = _SoundDeviceStream()
        try:
            stream = sounddevice.InputStream(
                device=int(device.id),
                samplerate=negotiated.sample_rate,
                channels=negotiated.channels,
                dtype="int16",
                callback=stream_adapter.backend_callback,
            )
        except Exception as exc:
            failure = map_audio_error(exc)
            raise AudioBackendError(
                failure.code,
                "sounddevice could not open the selected input device",
            ) from exc
        stream_adapter.attach(stream)
        return OpenedAudioStream(
            device=device,
            format=negotiated,
            stream=stream_adapter,
        )


class _SoundDeviceStream:
    """Async facade for sounddevice's synchronous stream lifecycle."""

    def __init__(self, stream: Any | None = None) -> None:
        self._stream = stream
        self._frame_callback: AudioFrameCallback | None = None

    def attach(self, stream: Any) -> None:
        self._stream = stream

    def register_frame_callback(self, callback: AudioFrameCallback) -> None:
        """Register the only callback that receives copied PCM16 chunks."""

        self._frame_callback = callback

    set_frame_callback = register_frame_callback

    def backend_callback(
        self,
        input_data: Any,
        frame_count: int,
        _time_info: object,
        _status: object,
    ) -> None:
        """Copy backend-owned callback memory before handing it to the session."""

        callback = self._frame_callback
        if callback is None:
            return
        callback(bytes(input_data), int(frame_count))

    async def start(self) -> None:
        if self._stream is None:
            raise AudioBackendError(
                AudioErrorCode.BACKEND_UNAVAILABLE,
                "sounddevice stream was not attached",
            )
        await asyncio.to_thread(self._stream.start)

    async def stop(self) -> None:
        if self._stream is None:
            return
        await asyncio.to_thread(self._stream.stop)

    async def close(self) -> None:
        if self._stream is None:
            return
        await asyncio.to_thread(self._stream.close)


def default_audio_backend() -> AudioBackend:
    """Return the lazy host backend without importing audio libraries."""

    return SoundDeviceBackend()


def _safe_device_id(device_id: str | None) -> str | None:
    if device_id is None:
        return None
    return "<redacted-path>" if device_id.startswith("/") else "<redacted-device-id>"


async def probe_audio(
    backend: AudioBackend | None = None,
    *,
    selected_device_id: str | None = None,
) -> dict[str, object]:
    """Enumerate and open/close one device without starting or retaining audio."""

    selected_backend = backend or default_audio_backend()
    discovery = await AudioDeviceDiscovery(selected_backend).discover(selected_device_id)
    safe_device_ids = {
        device.id: f"<device-{index}>" for index, device in enumerate(discovery.devices)
    }
    report: dict[str, object] = {
        "probe": "audio",
        "backend": type(selected_backend).__name__,
        "devices": [
            device.to_safe_dict(label=safe_device_ids[device.id])
            for device in discovery.devices
        ],
        "default_device_id": (
            safe_device_ids.get(discovery.default_device_id)
            or _safe_device_id(discovery.default_device_id)
        ),
        "selected_device_id": (
            safe_device_ids.get(discovery.selected_device_id)
            or _safe_device_id(discovery.selected_device_id)
        ),
        "capability": discovery.capability.to_dict(),
        "negotiated_format": None,
        "failure": discovery.failure.to_dict() if discovery.failure else None,
        "capture": {"started": False, "closed": True, "active": False},
    }
    if discovery.failure is not None or discovery.selected_device_id is None:
        return report

    capture = AudioCapture(
        selected_backend,
        selected_device_id=discovery.selected_device_id,
    )
    try:
        opened = await capture.open()
        report["negotiated_format"] = opened.format.to_dict()
        report["capability"] = CapabilityRecord(
            id="audio.input",
            status=CapabilityStatus.AVAILABLE,
            reason=(
                "The selected input device opened successfully. The probe did not "
                "start capture or retain audio data."
            ),
        ).to_dict()
    except AudioCaptureError as exc:
        report["capability"] = capability_for_audio_failure(exc.failure).to_dict()
        report["failure"] = exc.failure.to_dict()
    finally:
        close_failure = await capture.close()
        report["capture"] = {
            "started": False,
            "closed": not capture.has_active_stream,
            "active": capture.has_active_stream,
        }
        if close_failure is not None and report["failure"] is None:
            report["failure"] = close_failure.to_dict()
        if close_failure is not None:
            report["capability"] = capability_for_audio_failure(close_failure).to_dict()
    return report


audio_probe = probe_audio
