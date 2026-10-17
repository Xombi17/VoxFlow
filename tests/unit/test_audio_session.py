import asyncio
import json

from voxflow.audio.session import (
    AudioSession,
    AudioSessionConfig,
    AudioSessionOutcomeType,
)
from voxflow.platform.audio import AudioCapture, AudioBackendError, AudioErrorCode
from voxflow.platform.audio_devices import AudioDevice, AudioFormat, OpenedAudioStream


FORMAT = AudioFormat(sample_rate=48_000, channels=1)
PCM_FRAME = b"\x01\x00"


class FrameStream:
    def __init__(self, *, close_error=None, stop_error=None, supports_frames=True):
        self.calls = []
        self.callback = None
        self.started = False
        self.closed = False
        self.close_error = close_error
        self.stop_error = stop_error
        self.supports_frames = supports_frames

    def register_frame_callback(self, callback):
        if not self.supports_frames:
            raise AttributeError("frame callback unsupported")
        self.callback = callback

    def emit(self, frame_count, data=None):
        assert self.callback is not None
        self.callback(data or PCM_FRAME * frame_count, frame_count)

    async def start(self):
        self.calls.append("start")
        self.started = True

    async def stop(self):
        self.calls.append("stop")
        if self.stop_error:
            raise self.stop_error
        self.started = False

    async def close(self):
        self.calls.append("close")
        if self.close_error:
            error, self.close_error = self.close_error, None
            raise error
        self.started = False
        self.closed = True


class FrameBackend:
    def __init__(self, stream=None):
        self.device = AudioDevice(
            id="fake-mic",
            name="Fake microphone",
            is_default=True,
            supported_formats=(FORMAT,),
        )
        self.stream = stream or FrameStream()

    async def enumerate_devices(self):
        return (self.device,)

    async def open(self, device_id, requested_format=None):
        assert device_id == self.device.id
        return OpenedAudioStream(
            device=self.device,
            format=requested_format or FORMAT,
            stream=self.stream,
        )


async def wait_for_started(stream):
    for _ in range(100):
        if stream.started:
            return
        await asyncio.sleep(0)
    raise AssertionError("fake capture did not start")


def start_session(tmp_path, *, stream=None, config=None):
    backend = FrameBackend(stream)
    capture = AudioCapture(backend)
    session = AudioSession(capture, tmp_path, config=config)
    task = asyncio.create_task(session.run())
    return backend, capture, session, task


def test_completed_session_writes_negotiated_format_artifact(tmp_path) -> None:
    async def scenario():
        backend, capture, session, task = start_session(tmp_path)
        await wait_for_started(backend.stream)
        backend.stream.emit(480, PCM_FRAME * 480)
        outcome = await session.stop()
        return backend, capture, session, task, outcome

    backend, capture, session, task, outcome = asyncio.run(scenario())

    assert task.done()
    assert outcome.kind is AudioSessionOutcomeType.COMPLETED
    assert outcome.artifact is not None
    assert outcome.artifact.source_format == FORMAT
    assert outcome.artifact.path.exists()
    assert backend.stream.calls == ["start", "stop", "close"]
    assert capture.negotiated_format == FORMAT
    assert session.retained_frame_count == 480


def test_overflow_is_typed_and_never_retains_more_than_bound(tmp_path) -> None:
    async def scenario():
        backend, _capture, session, _task = start_session(
            tmp_path,
            config=AudioSessionConfig(max_duration_ms=1000, max_buffer_frames=2),
        )
        await wait_for_started(backend.stream)
        backend.stream.emit(2)
        backend.stream.emit(1)
        outcome = await session.run()
        return backend, session, outcome

    backend, session, outcome = asyncio.run(scenario())

    assert outcome.kind is AudioSessionOutcomeType.OVERFLOW
    assert outcome.failure is not None
    assert outcome.failure.code == "buffer_overflow"
    assert session.retained_frame_count == 2
    assert session.buffered_frame_count == 0
    assert backend.stream.calls == ["start", "stop", "close"]


def test_max_duration_clips_at_source_format_boundary(tmp_path) -> None:
    async def scenario():
        backend, _capture, session, _task = start_session(
            tmp_path,
            config=AudioSessionConfig(max_duration_ms=1, max_buffer_frames=10_000),
        )
        await wait_for_started(backend.stream)
        backend.stream.emit(64, PCM_FRAME * 64)
        return await session.run()

    outcome = asyncio.run(scenario())

    assert outcome.kind is AudioSessionOutcomeType.MAX_DURATION
    assert outcome.artifact is not None
    assert outcome.artifact.frame_count == 48
    assert outcome.captured_frames == 48


def test_cancelled_empty_session_has_no_artifact_or_audio_diagnostics(tmp_path) -> None:
    async def scenario():
        backend, capture, session, task = start_session(tmp_path)
        await wait_for_started(backend.stream)
        outcome = await session.cancel()
        return backend, capture, task, outcome

    backend, capture, task, outcome = asyncio.run(scenario())
    serialized = json.dumps(outcome.to_dict())

    assert task.done()
    assert outcome.kind is AudioSessionOutcomeType.CANCELLED
    assert outcome.artifact is None
    assert outcome.retryable
    assert outcome.retry_code == "retry_capture"
    assert not list(tmp_path.iterdir())
    assert str(tmp_path) not in serialized
    assert "\x01" not in serialized
    assert backend.stream.calls == ["start", "stop", "close"]
    assert not capture.has_active_stream


def test_cancelled_audio_respects_artifact_retention_policy(tmp_path) -> None:
    async def scenario():
        stream = FrameStream()
        backend, _capture, session, _task = start_session(
            tmp_path,
            stream=stream,
            config=AudioSessionConfig(retain_artifact=False),
        )
        await wait_for_started(stream)
        stream.emit(2)
        return await session.cancel()

    outcome = asyncio.run(scenario())

    assert outcome.kind is AudioSessionOutcomeType.CANCELLED
    assert outcome.captured_frames == 2
    assert outcome.artifact is None
    assert not list(tmp_path.iterdir())


def test_stream_without_frame_support_fails_without_starting(tmp_path) -> None:
    async def scenario():
        stream = FrameStream(supports_frames=False)
        backend, _capture, session, _task = start_session(tmp_path, stream=stream)
        return backend, await session.run()

    backend, outcome = asyncio.run(scenario())

    assert outcome.kind is AudioSessionOutcomeType.FAILED
    assert outcome.failure is not None
    assert outcome.failure.code == "backend_unavailable"
    assert backend.stream.calls == ["close"]


def test_close_failure_is_recoverable_and_keeps_phase1_handle_retry(tmp_path) -> None:
    async def scenario():
        stream = FrameStream(
            close_error=AudioBackendError(
                AudioErrorCode.BACKEND_UNAVAILABLE,
                "fake close failure",
            )
        )
        backend, capture, session, _task = start_session(tmp_path, stream=stream)
        await wait_for_started(stream)
        outcome = await session.cancel()
        return backend, capture, outcome

    backend, capture, outcome = asyncio.run(scenario())

    assert outcome.kind is AudioSessionOutcomeType.FAILED
    assert outcome.failure is not None
    assert outcome.failure.code == "backend_unavailable"
    assert outcome.retryable
    assert capture.has_active_stream
    assert backend.stream.calls == ["start", "stop", "close"]
