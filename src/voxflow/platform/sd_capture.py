"""Lazy sounddevice capture with in-memory mono 16 kHz conversion.

The host stream is opened at the device's advertised native rate and emits
float32 frames.  The adapter copies, downmixes, resamples, and converts each
callback chunk before handing immutable PCM16 bytes to ``AudioSession``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

from ..audio.session import AudioSessionErrorCode, AudioSessionFailure
from .audio import AudioCaptureError, AudioCaptureState, map_audio_error
from .audio_devices import AudioDevice, AudioFormat, OpenedAudioStream


TARGET_SAMPLE_RATE = 16_000
WATCHDOG_TIMEOUT_SECONDS = 0.5


def _load_sounddevice() -> Any:
    try:
        import sounddevice  # type: ignore[import-not-found]
    except ImportError as exc:
        raise AudioCaptureError(map_audio_error(exc)) from exc
    return sounddevice


def resample_to_pcm16(
    input_data: Any,
    *,
    input_rate: int,
    input_channels: int,
    target_rate: int = TARGET_SAMPLE_RATE,
) -> tuple[bytes, int]:
    """Downmix and linearly resample one sounddevice float chunk in memory.

    # ponytail: scipy.signal.resample_poly is the upgrade path if quality or
    # long-stream edge handling requires a higher quality resampler.
    """

    if input_rate < 1 or input_channels < 1 or target_rate < 1:
        raise ValueError("audio rates and channel counts must be positive")
    samples = np.asarray(input_data, dtype=np.float32)
    if samples.ndim == 1:
        if input_channels > 1:
            usable = samples.size - (samples.size % input_channels)
            samples = samples[:usable].reshape(-1, input_channels)
        else:
            samples = samples.reshape(-1, 1)
    elif samples.ndim == 2:
        if samples.shape[1] != input_channels:
            raise ValueError("audio callback channel count does not match the stream")
    else:
        raise ValueError("audio callback data must be one or two dimensional")
    if samples.size == 0:
        return b"", 0

    mono = samples.mean(axis=1, dtype=np.float32)
    if input_rate != target_rate and mono.size > 1:
        output_count = max(1, round(mono.size * target_rate / input_rate))
        mono = np.interp(
            np.linspace(0, mono.size - 1, output_count),
            np.arange(mono.size),
            mono,
        ).astype(np.float32)
    clipped = np.clip(mono, -1.0, 1.0)
    pcm = np.rint(clipped * 32767.0).astype(np.int16)
    return pcm.tobytes(), int(pcm.size)


class SoundDeviceCapture:
    """An ``AudioSession``-compatible capture opener backed by sounddevice."""

    def __init__(
        self,
        *,
        sounddevice: Any | None = None,
        device: int | str | None = None,
        target_rate: int = TARGET_SAMPLE_RATE,
        watchdog_timeout_ms: int = 500,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        if target_rate < 1:
            raise ValueError("target_rate must be positive")
        if watchdog_timeout_ms < 1:
            raise ValueError("watchdog_timeout_ms must be positive")
        self._sounddevice = sounddevice
        self.device_id = device
        self.target_rate = target_rate
        self.watchdog_timeout_seconds = watchdog_timeout_ms / 1000
        self.clock = clock
        self._sleep = sleep
        self._state = AudioCaptureState.CLOSED
        self._stream: _ResamplingStream | None = None
        self._native_rate: int | None = None
        self._native_channels: int | None = None
        self._device: AudioDevice | None = None
        self._callback: Callable[[bytes, int], object] | None = None
        self._failure_callback: Callable[[AudioSessionFailure], object] | None = None
        self._last_frame_at: float | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._watchdog_failure: AudioSessionFailure | None = None

    @property
    def state(self) -> AudioCaptureState:
        return self._state

    @property
    def has_active_stream(self) -> bool:
        return self._stream is not None

    @property
    def format(self) -> AudioFormat | None:
        if self._native_rate is None:
            return None
        return AudioFormat(self.target_rate, 1)

    @property
    def watchdog_failure(self) -> AudioSessionFailure | None:
        return self._watchdog_failure

    def register_frame_callback(self, callback: Callable[[bytes, int], object]) -> None:
        self._callback = callback
        if self._stream is not None:
            self._stream.register_frame_callback(callback)

    set_frame_callback = register_frame_callback

    def register_failure_callback(
        self,
        callback: Callable[[AudioSessionFailure], object],
    ) -> None:
        self._failure_callback = callback

    async def open(self) -> OpenedAudioStream:
        if self._state not in {AudioCaptureState.CLOSED, AudioCaptureState.FAILED}:
            raise RuntimeError(f"cannot open capture while state is {self._state.value}")
        sounddevice = self._sounddevice or _load_sounddevice()
        try:
            raw, selected_id = self._query_input(sounddevice)
            native_rate = int(round(float(raw.get("default_samplerate", 0))))
            native_channels = int(raw.get("max_input_channels", 0))
            if native_rate < 1 or native_channels < 1:
                raise ValueError("sounddevice returned no usable input format")
            stream = _ResamplingStream(
                input_rate=native_rate,
                input_channels=native_channels,
                target_rate=self.target_rate,
                on_frame=self._mark_frame,
            )
        except AudioCaptureError:
            raise
        except Exception as exc:
            failure = map_audio_error(exc)
            self._state = AudioCaptureState.FAILED
            raise AudioCaptureError(failure) from exc

        self._sounddevice = sounddevice
        self.device_id = selected_id
        self._native_rate = native_rate
        self._native_channels = native_channels
        self._device = AudioDevice(
            id=str(selected_id),
            name=str(raw.get("name", f"Input device {selected_id}")),
            is_default=True,
            supported_formats=(AudioFormat(native_rate, native_channels),),
        )
        self._stream = stream
        if self._callback is not None:
            stream.register_frame_callback(self._callback)
        self._state = AudioCaptureState.OPEN
        return OpenedAudioStream(self._device, AudioFormat(self.target_rate, 1), stream)

    async def start(self) -> None:
        if self._state not in {AudioCaptureState.OPEN, AudioCaptureState.STOPPED}:
            raise RuntimeError(f"cannot start capture while state is {self._state.value}")
        if self._stream is None:
            raise RuntimeError("sounddevice stream is not open")
        try:
            if not self._stream.attached:
                self._stream.attach(
                    self._sounddevice.InputStream(
                        device=self.device_id,
                        samplerate=self._native_rate,
                        channels=self._native_channels,
                        dtype="float32",
                        callback=self._stream.backend_callback,
                    )
                )
            await self._stream.start()
        except Exception as exc:
            self._state = AudioCaptureState.FAILED
            raise AudioCaptureError(map_audio_error(exc)) from exc
        self._last_frame_at = self.clock()
        self._watchdog_failure = None
        self._state = AudioCaptureState.RUNNING
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def stop(self) -> None:
        if self._state is not AudioCaptureState.RUNNING:
            return
        await self._cancel_watchdog()
        if self._stream is not None:
            await self._stream.stop()
        self._state = AudioCaptureState.STOPPED

    async def close(self) -> None:
        if self._stream is None:
            self._state = AudioCaptureState.CLOSED
            return
        if self._state is AudioCaptureState.RUNNING:
            await self.stop()
        try:
            await self._stream.close()
        except Exception as exc:
            self._state = AudioCaptureState.FAILED
            raise AudioCaptureError(map_audio_error(exc)) from exc
        self._stream = None
        self._state = AudioCaptureState.CLOSED

    def check_watchdog(self, now: float | None = None) -> AudioSessionFailure | None:
        """Check the deterministic stall boundary, useful for tests and hosts."""

        if self._state is not AudioCaptureState.RUNNING or self._last_frame_at is None:
            return None
        current = self.clock() if now is None else now
        if current - self._last_frame_at < self.watchdog_timeout_seconds:
            return None
        if self._watchdog_failure is None:
            self._watchdog_failure = AudioSessionFailure(
                code="capture_stalled",
                reason="No microphone frames arrived within the capture watchdog window.",
            )
            if self._failure_callback is not None:
                self._failure_callback(self._watchdog_failure)
        return self._watchdog_failure

    def _mark_frame(self) -> None:
        self._last_frame_at = self.clock()

    async def _watchdog_loop(self) -> None:
        interval = min(0.05, self.watchdog_timeout_seconds / 4)
        try:
            while self._state is AudioCaptureState.RUNNING:
                await self._sleep(interval)
                failure = self.check_watchdog()
                if failure is not None:
                    # Stop the host handle here as well as notifying AudioSession;
                    # the session then performs its normal bounded close.
                    if self._stream is not None:
                        await self._stream.stop()
                    self._state = AudioCaptureState.STOPPED
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = AudioSessionFailure(
                code=AudioSessionErrorCode.CAPTURE_FAILED.value,
                reason="Audio capture watchdog failed safely.",
            )
            if self._failure_callback is not None:
                self._failure_callback(failure)
            self._state = AudioCaptureState.FAILED
            del exc

    async def _cancel_watchdog(self) -> None:
        task, self._watchdog_task = self._watchdog_task, None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def _query_input(self, sounddevice: Any) -> tuple[Mapping[str, object], int | str]:
        requested = self.device_id
        try:
            raw = sounddevice.query_devices(requested) if requested is not None else sounddevice.query_devices()
        except TypeError:
            raw = sounddevice.query_devices()
        if isinstance(raw, Mapping):
            selected = requested
            if selected is None:
                default = getattr(getattr(sounddevice, "default", None), "device", (0, -1))
                selected = default[0] if isinstance(default, (tuple, list)) else default
            return raw, 0 if selected is None else selected
        if not isinstance(raw, (tuple, list)) or not raw:
            raise ValueError("sounddevice returned no input devices")
        selected = requested
        if selected is None:
            default = getattr(getattr(sounddevice, "default", None), "device", (0, -1))
            selected = default[0] if isinstance(default, (tuple, list)) else 0
        if isinstance(selected, str) and not selected.isdigit():
            index = next(
                (
                    candidate_index
                    for candidate_index, candidate in enumerate(raw)
                    if str(candidate.get("name", "")) == selected
                ),
                -1,
            )
            if index < 0:
                raise ValueError("requested sounddevice input device was not found")
        else:
            index = int(selected)
        return raw[index], index


class _ResamplingStream:
    def __init__(
        self,
        *,
        input_rate: int,
        input_channels: int,
        target_rate: int,
        on_frame: Callable[[], None],
    ):
        self.input_rate = input_rate
        self.input_channels = input_channels
        self.target_rate = target_rate
        self._on_frame = on_frame
        self._stream: Any | None = None
        self._frame_callback: Callable[[bytes, int], object] | None = None

    @property
    def attached(self) -> bool:
        return self._stream is not None

    def attach(self, stream: Any) -> None:
        self._stream = stream

    def register_frame_callback(self, callback: Callable[[bytes, int], object]) -> None:
        self._frame_callback = callback

    set_frame_callback = register_frame_callback

    def backend_callback(self, input_data: Any, frame_count: int, _time_info: object, _status: object) -> None:
        del frame_count
        if self._frame_callback is None:
            return
        data, count = resample_to_pcm16(
            input_data,
            input_rate=self.input_rate,
            input_channels=self.input_channels,
            target_rate=self.target_rate,
        )
        if count:
            self._on_frame()
            self._frame_callback(data, count)

    async def start(self) -> None:
        if self._stream is None:
            raise RuntimeError("sounddevice stream is not attached")
        await asyncio.to_thread(self._stream.start)

    async def stop(self) -> None:
        if self._stream is not None:
            await asyncio.to_thread(self._stream.stop)

    async def close(self) -> None:
        if self._stream is not None:
            await asyncio.to_thread(self._stream.close)


__all__ = ["SoundDeviceCapture", "TARGET_SAMPLE_RATE", "WATCHDOG_TIMEOUT_SECONDS", "resample_to_pcm16"]
