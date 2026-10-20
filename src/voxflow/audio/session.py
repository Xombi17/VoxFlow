"""Bounded asynchronous capture sessions built on the Phase 1 audio seam."""

from __future__ import annotations

import asyncio
import os
import queue
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..platform.audio import (
    AudioCapture,
    AudioCaptureError,
    AudioCaptureState,
    AudioErrorCode,
)
from ..platform.audio_devices import AudioFormat, OpenedAudioStream
from .artifacts import AudioArtifact, PCM_SAMPLE_WIDTH_BYTES, write_wav_artifact


class AudioSessionOutcomeType(StrEnum):
    """Terminal capture outcomes exposed to the provider-independent core."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OVERFLOW = "overflow"
    MAX_DURATION = "max_duration"
    FAILED = "failed"


class AudioSessionErrorCode(StrEnum):
    """Stable recoverability codes for session-owned failures."""

    BACKEND_UNAVAILABLE = AudioErrorCode.BACKEND_UNAVAILABLE.value
    UNSUPPORTED_FORMAT = AudioErrorCode.UNSUPPORTED_FORMAT.value
    CAPTURE_FAILED = "capture_failed"
    BUFFER_OVERFLOW = "buffer_overflow"
    MAX_DURATION = "max_duration"
    CANCELLED = "cancelled"
    CLEANUP_FAILED = "cleanup_failed"
    ARTIFACT_WRITE_FAILED = "artifact_write_failed"


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """An immutable PCM chunk copied out of a backend callback."""

    data: bytes
    frame_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise TypeError("audio frame data must be immutable bytes")
        if self.frame_count < 1:
            raise ValueError("audio frame_count must be positive")


@dataclass(frozen=True, slots=True, init=False)
class AudioSessionConfig:
    """Explicit duration, memory, retention, and cleanup bounds for capture."""

    max_duration_ms: int
    max_buffer_frames: int
    retain_artifact: bool
    cleanup_timeout_ms: int

    def __init__(
        self,
        max_duration_ms: int = 30_000,
        max_buffer_frames: int = 48_000 * 30,
        retain_artifact: bool = True,
        cleanup_timeout_ms: int = 1_000,
        *,
        retain_artifacts: bool | None = None,
        retain_audio: bool | None = None,
    ) -> None:
        aliases = [value for value in (retain_artifacts, retain_audio) if value is not None]
        if aliases and any(value != aliases[0] for value in aliases):
            raise ValueError("artifact retention aliases must agree")
        if aliases:
            retain_artifact = aliases[0]
        if max_duration_ms < 1:
            raise ValueError("max_duration_ms must be positive")
        if max_buffer_frames < 1:
            raise ValueError("max_buffer_frames must be positive")
        if cleanup_timeout_ms < 1:
            raise ValueError("cleanup_timeout_ms must be positive")
        object.__setattr__(self, "max_duration_ms", max_duration_ms)
        object.__setattr__(self, "max_buffer_frames", max_buffer_frames)
        object.__setattr__(self, "retain_artifact", bool(retain_artifact))
        object.__setattr__(self, "cleanup_timeout_ms", cleanup_timeout_ms)

    @property
    def retain_artifacts(self) -> bool:
        """Compatibility spelling for callers describing retention as plural."""

        return self.retain_artifact

    @property
    def retain_audio(self) -> bool:
        return self.retain_artifact

    @property
    def retention_policy(self) -> str:
        """Stable policy name used by durable job history."""

        return "retain" if self.retain_artifact else "discard_after_terminal"


@dataclass(frozen=True, slots=True)
class AudioSessionFailure:
    """Safe failure metadata with a typed retry disposition."""

    code: str
    reason: str
    retryable: bool = True
    retry_code: str | None = "retry_capture"

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "reason": self.reason,
            "retryable": self.retryable,
            "retry_code": self.retry_code,
        }


@dataclass(frozen=True, slots=True)
class AudioSessionOutcome:
    """One terminal result from a bounded capture session."""

    kind: AudioSessionOutcomeType
    artifact: AudioArtifact | None
    captured_frames: int
    failure: AudioSessionFailure | None = None
    retryable: bool = False
    retry_code: str | None = None
    diagnostics: dict[str, object] | None = None
    retention_policy: str = "retain"

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", AudioSessionOutcomeType(self.kind))
        if self.captured_frames < 0:
            raise ValueError("captured_frames must not be negative")
        if self.failure is not None and self.failure.retryable != self.retryable:
            raise ValueError("outcome and failure retryability must agree")
        if self.failure is not None and self.failure.retry_code != self.retry_code:
            raise ValueError("outcome and failure retry codes must agree")
        object.__setattr__(
            self,
            "diagnostics",
            dict(self.diagnostics or {}),
        )

    @property
    def status(self) -> AudioSessionOutcomeType:
        return self.kind

    @property
    def artifact_reference(self) -> AudioArtifact | None:
        return self.artifact

    def to_dict(self) -> dict[str, object]:
        """Serialize diagnostics without audio payloads or machine paths."""

        return {
            "outcome": self.kind.value,
            "captured_frames": self.captured_frames,
            "artifact": self.artifact.to_dict() if self.artifact else None,
            "retention_policy": self.retention_policy,
            "failure": self.failure.to_dict() if self.failure else None,
            "retryable": self.retryable,
            "retry_code": self.retry_code,
            "diagnostics": dict(self.diagnostics or {}),
        }


class AudioSession:
    """Own one bounded frame handoff and the underlying ``AudioCapture``."""

    def __init__(
        self,
        capture: AudioCapture,
        artifact_dir: str | Path,
        *,
        config: AudioSessionConfig | None = None,
        artifact_name: str | None = None,
    ) -> None:
        self.capture = capture
        self.artifact_dir = Path(artifact_dir)
        self.config = config or AudioSessionConfig()
        self.artifact_name = artifact_name
        self._frames: queue.Queue[AudioFrame] = queue.Queue(
            maxsize=self.config.max_buffer_frames
        )
        self._lock = threading.Lock()
        self._accepted_frames = 0
        self._queued_frames = 0
        self._chunks: list[bytes] = []
        self._format: AudioFormat | None = None
        self._duration_limit_frames: int | None = None
        self._terminal_kind: AudioSessionOutcomeType | None = None
        self._terminal_failure: AudioSessionFailure | None = None
        self._run_task: asyncio.Task[AudioSessionOutcome] | None = None
        self._outcome: AudioSessionOutcome | None = None
        self._finished = False
        self._registered = False
        self._stop_requested = threading.Event()

    @property
    def format(self) -> AudioFormat | None:
        return self._format

    @property
    def captured_frames(self) -> int:
        with self._lock:
            return self._accepted_frames

    @property
    def buffered_frame_count(self) -> int:
        with self._lock:
            return self._queued_frames

    @property
    def retained_frame_count(self) -> int:
        return self.captured_frames

    @property
    def outcome(self) -> AudioSessionOutcome | None:
        return self._outcome

    async def run(self) -> AudioSessionOutcome:
        """Open, capture, stop, close, and materialize one bounded artifact."""

        if self._outcome is not None:
            return self._outcome
        if self._run_task is not None and self._run_task is not asyncio.current_task():
            return await self._run_task
        self._run_task = asyncio.current_task()

        if self._terminal_kind is not None or self._stop_requested.is_set():
            if self._terminal_kind is None:
                self._request_terminal(AudioSessionOutcomeType.CANCELLED)
            return await self._finish()

        try:
            opened = await self.capture.open()
            self._format = opened.format
            self._duration_limit_frames = max(
                1,
                (opened.format.sample_rate * self.config.max_duration_ms) // 1000,
            )
            if not self._register_callback(opened):
                self._request_terminal(
                    AudioSessionOutcomeType.FAILED,
                    AudioSessionFailure(
                        code=AudioSessionErrorCode.BACKEND_UNAVAILABLE.value,
                        reason="The selected audio stream cannot deliver capture frames.",
                    ),
                )
            elif self._terminal_kind is None:
                self._register_failure_callback(opened)
                await self.capture.start()
        except asyncio.CancelledError:
            self._request_terminal(AudioSessionOutcomeType.CANCELLED)
        except AudioCaptureError as exc:
            self._request_terminal(
                AudioSessionOutcomeType.FAILED,
                AudioSessionFailure(
                    code=exc.failure.code.value,
                    reason=exc.failure.reason,
                ),
            )
        except Exception:
            self._request_terminal(
                AudioSessionOutcomeType.FAILED,
                AudioSessionFailure(
                    code=AudioSessionErrorCode.CAPTURE_FAILED.value,
                    reason="Audio capture failed before a terminal artifact was written.",
                ),
            )

        if self._terminal_kind is None:
            try:
                while self._terminal_kind is None:
                    self._drain_frames()
                    self._apply_pending_terminal_request()
                    if self._terminal_kind is None:
                        await asyncio.sleep(0.001)
                self._drain_frames()
            except asyncio.CancelledError:
                self._request_terminal(AudioSessionOutcomeType.CANCELLED)
                self._drain_frames()

        return await self._finish()

    async def stop(self) -> AudioSessionOutcome | None:
        """Request a normal user stop and wait for the bounded terminal result."""

        self._request_terminal(AudioSessionOutcomeType.COMPLETED)
        return await self._wait_for_run()

    async def cancel(self) -> AudioSessionOutcome | None:
        """Cooperatively cancel capture and wait for bounded cleanup."""

        self._stop_requested.set()
        self._request_terminal(AudioSessionOutcomeType.CANCELLED)
        return await self._wait_for_run()

    def _register_callback(self, opened: OpenedAudioStream) -> bool:
        register = getattr(opened.stream, "register_frame_callback", None)
        if not callable(register):
            register = getattr(opened.stream, "set_frame_callback", None)
        if not callable(register):
            return False
        try:
            register(self._on_frame)
        except Exception:
            return False
        self._registered = True
        return True

    def _register_failure_callback(self, opened: OpenedAudioStream) -> None:
        """Attach an optional backend failure seam without changing stream callers.

        Older capture streams only deliver PCM frames.  Newer backends, such as
        the sounddevice adapter, can report a watchdog or transport failure from
        their own worker.  Keeping this hook optional preserves the existing
        ``AudioStream`` protocol and lets the session own the terminal outcome
        and cleanup ordering.
        """

        register = getattr(opened.stream, "register_failure_callback", None)
        if not callable(register):
            register = getattr(self.capture, "register_failure_callback", None)
        if callable(register):
            register(self._on_capture_failure)

    def _on_capture_failure(self, failure: AudioSessionFailure | object) -> None:
        if isinstance(failure, AudioSessionFailure):
            normalized = failure
        else:
            normalized = AudioSessionFailure(
                code=AudioSessionErrorCode.CAPTURE_FAILED.value,
                reason="Audio capture failed before a terminal artifact was written.",
            )
        self._request_terminal(AudioSessionOutcomeType.FAILED, normalized)

    def _on_frame(self, data: bytes, frame_count: int) -> None:
        """Copy and enqueue only; no disk, model, or event work runs here."""

        try:
            frame = AudioFrame(bytes(data), int(frame_count))
        except (TypeError, ValueError):
            self._request_terminal(
                AudioSessionOutcomeType.FAILED,
                AudioSessionFailure(
                    code=AudioSessionErrorCode.UNSUPPORTED_FORMAT.value,
                    reason="The audio backend delivered an invalid frame chunk.",
                ),
            )
            return

        with self._lock:
            if self._terminal_kind is not None or self._stop_requested.is_set():
                return
            remaining = self.config.max_buffer_frames - self._accepted_frames
            duration_remaining = (
                self._duration_limit_frames - self._accepted_frames
                if self._duration_limit_frames is not None
                else remaining
            )
            if remaining <= 0:
                self._terminal_kind = AudioSessionOutcomeType.OVERFLOW
                self._terminal_failure = AudioSessionFailure(
                    code=AudioSessionErrorCode.BUFFER_OVERFLOW.value,
                    reason="The bounded audio buffer reached its frame limit.",
                )
                return
            if duration_remaining <= 0:
                self._terminal_kind = AudioSessionOutcomeType.MAX_DURATION
                self._terminal_failure = AudioSessionFailure(
                    code=AudioSessionErrorCode.MAX_DURATION.value,
                    reason="The maximum capture duration was reached.",
                )
                return
            allowed = min(remaining, duration_remaining)
            if frame.frame_count > allowed:
                if self._duration_limit_frames is None or allowed != duration_remaining:
                    self._terminal_kind = AudioSessionOutcomeType.OVERFLOW
                    self._terminal_failure = AudioSessionFailure(
                        code=AudioSessionErrorCode.BUFFER_OVERFLOW.value,
                        reason="The bounded audio buffer reached its frame limit.",
                    )
                    return
                bytes_per_frame = PCM_SAMPLE_WIDTH_BYTES * (
                    self._format.channels if self._format else 1
                )
                frame = AudioFrame(
                    frame.data[: allowed * bytes_per_frame],
                    allowed,
                )
            try:
                self._frames.put_nowait(frame)
            except queue.Full:
                self._terminal_kind = AudioSessionOutcomeType.OVERFLOW
                self._terminal_failure = AudioSessionFailure(
                    code=AudioSessionErrorCode.BUFFER_OVERFLOW.value,
                    reason="The bounded audio handoff is full; capture was stopped.",
                )
                return
            self._accepted_frames += frame.frame_count
            self._queued_frames += frame.frame_count
            if (
                self._duration_limit_frames is not None
                and self._accepted_frames >= self._duration_limit_frames
            ):
                self._terminal_kind = AudioSessionOutcomeType.MAX_DURATION
                self._terminal_failure = AudioSessionFailure(
                    code=AudioSessionErrorCode.MAX_DURATION.value,
                    reason="The maximum capture duration was reached.",
                )

    def _drain_frames(self) -> None:
        while True:
            try:
                frame = self._frames.get_nowait()
            except queue.Empty:
                return
            with self._lock:
                self._queued_frames -= frame.frame_count
            self._chunks.append(frame.data)

    def _request_terminal(
        self,
        kind: AudioSessionOutcomeType,
        failure: AudioSessionFailure | None = None,
    ) -> None:
        if kind is AudioSessionOutcomeType.CANCELLED:
            self._stop_requested.set()
            if self._finished:
                return
            self._terminal_kind = kind
            self._terminal_failure = failure or AudioSessionFailure(
                code=AudioSessionErrorCode.CANCELLED.value,
                reason="Capture was cancelled before transcription.",
            )
            return
        if self._terminal_kind is None:
            self._terminal_kind = kind
            self._terminal_failure = failure

    def _apply_pending_terminal_request(self) -> None:
        if self._stop_requested.is_set() and self._terminal_kind is None:
            self._request_terminal(AudioSessionOutcomeType.CANCELLED)

    async def _finish(self) -> AudioSessionOutcome:
        if self._outcome is not None:
            return self._outcome
        self._drain_frames()
        cleanup_failure = await self._cleanup_capture()
        kind = self._terminal_kind or AudioSessionOutcomeType.COMPLETED
        failure = self._terminal_failure
        if cleanup_failure is not None:
            kind = AudioSessionOutcomeType.FAILED
            failure = AudioSessionFailure(
                code=getattr(cleanup_failure, "code", AudioSessionErrorCode.CLEANUP_FAILED),
                reason="Audio capture cleanup did not complete; retry cleanup before reuse.",
            )

        artifact: AudioArtifact | None = None
        if self._chunks and self._format is not None and (
            kind is AudioSessionOutcomeType.COMPLETED or self.config.retain_artifact
        ):
            try:
                artifact = write_wav_artifact(
                    self.artifact_dir,
                    b"".join(self._chunks),
                    self._format,
                    self.captured_frames,
                    artifact_name=self.artifact_name,
                )
            except Exception:
                kind = AudioSessionOutcomeType.FAILED
                failure = AudioSessionFailure(
                    code=AudioSessionErrorCode.ARTIFACT_WRITE_FAILED.value,
                    reason="Captured audio could not be written as a local WAV artifact.",
                )

        if failure is not None:
            retryable = failure.retryable
            retry_code = failure.retry_code
        else:
            retryable = False
            retry_code = None
        safe_diagnostics: dict[str, object] = {
            "captured_frames": self.captured_frames,
            "format": self._format.to_dict() if self._format else None,
            "frame_callback_registered": self._registered,
            "backend_closed": not self.capture.has_active_stream,
        }
        self._outcome = AudioSessionOutcome(
            kind=kind,
            artifact=artifact,
            captured_frames=self.captured_frames,
            failure=failure,
            retryable=retryable,
            retry_code=retry_code,
            diagnostics=safe_diagnostics,
            retention_policy=self.config.retention_policy,
        )
        self._finished = True
        return self._outcome

    def discard_artifact(self, artifact: AudioArtifact | None = None) -> bool:
        """Delete a materialized artifact after its terminal job action.

        Capture still materializes a completed artifact when retention is off so
        the current ASR provider can read it.  The daemon calls this method once
        processing reaches a terminal state; it is idempotent and never exposes
        the local path through diagnostics.
        """

        target = artifact or (self._outcome.artifact if self._outcome else None)
        if target is None:
            return False
        try:
            os.unlink(target.path)
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return True

    async def _cleanup_capture(self) -> Any:
        stop_failure: AudioSessionFailure | None = None
        if self.capture.state is AudioCaptureState.RUNNING:
            try:
                await self._bounded_call(self.capture.stop)
            except AudioCaptureError as exc:
                stop_failure = AudioSessionFailure(
                    code=exc.failure.code.value,
                    reason=exc.failure.reason,
                )
            except Exception:
                stop_failure = AudioSessionFailure(
                    code=AudioSessionErrorCode.CLEANUP_FAILED.value,
                    reason="Audio capture stop did not complete.",
                )
        try:
            close_failure = await self._bounded_call(self.capture.close)
        except Exception:
            return stop_failure or AudioSessionFailure(
                code=AudioSessionErrorCode.CLEANUP_FAILED.value,
                reason="Audio capture close did not complete.",
            )
        return close_failure or stop_failure

    async def _bounded_call(self, operation: Callable[[], Awaitable[Any]]) -> Any:
        task = asyncio.create_task(operation())
        done, _ = await asyncio.wait(
            {task}, timeout=self.config.cleanup_timeout_ms / 1000
        )
        if not done:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise TimeoutError("audio cleanup exceeded its bounded wait")
        return task.result()

    async def _wait_for_run(self) -> AudioSessionOutcome | None:
        task = self._run_task
        if task is None:
            await asyncio.sleep(0)
            task = self._run_task
            if task is None:
                return self._outcome
        if task is asyncio.current_task():
            return None
        try:
            return await asyncio.wait_for(
                asyncio.shield(task),
                timeout=self.config.cleanup_timeout_ms / 1000,
            )
        except TimeoutError:
            return self._outcome
