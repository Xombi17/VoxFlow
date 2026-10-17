import asyncio
import json

from voxflow.audio.session import AudioSession, AudioSessionConfig, AudioSessionOutcomeType
from voxflow.platform.audio import AudioCapture, AudioBackendError, AudioErrorCode
from voxflow.platform.audio_devices import AudioDevice, AudioFormat, OpenedAudioStream


FORMAT = AudioFormat(sample_rate=48_000, channels=1)
PCM_FRAME = b"\x01\x00"


class IntegrationStream:
    def __init__(self, *, stop_error=None, close_error=None):
        self.calls = []
        self.callback = None
        self.started = False
        self.closed = False
        self.stop_error = stop_error
        self.close_error = close_error

    def register_frame_callback(self, callback):
        self.callback = callback

    def emit(self, frame_count):
        assert self.callback is not None
        self.callback(PCM_FRAME * frame_count, frame_count)

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
            raise self.close_error
        self.closed = True
        self.started = False


class IntegrationBackend:
    def __init__(self, stream):
        self.stream = stream
        self.device = AudioDevice(
            id="integration-mic",
            name="Integration microphone",
            is_default=True,
            supported_formats=(FORMAT,),
        )

    async def enumerate_devices(self):
        return (self.device,)

    async def open(self, device_id, requested_format=None):
        assert device_id == self.device.id
        return OpenedAudioStream(self.device, requested_format or FORMAT, self.stream)


async def wait_for_started(stream):
    for _ in range(100):
        if stream.started:
            return
        await asyncio.sleep(0)
    raise AssertionError("integration fake stream did not start")


def test_fake_capture_cleanup_and_recoverable_cancelled_audio(tmp_path) -> None:
    async def scenario(tmp_path):
        stream = IntegrationStream()
        capture = AudioCapture(IntegrationBackend(stream))
        session = AudioSession(capture, tmp_path)
        task = asyncio.create_task(session.run())
        await wait_for_started(stream)
        stream.emit(480)
        outcome = await session.cancel()
        return stream, capture, task, outcome

    stream, capture, task, outcome = asyncio.run(scenario(tmp_path))

    assert task.done()
    assert outcome.kind is AudioSessionOutcomeType.CANCELLED
    assert outcome.artifact is not None
    assert outcome.retryable
    assert outcome.artifact.audio_sha256
    assert stream.calls == ["start", "stop", "close"]
    assert stream.closed
    assert not capture.has_active_stream


def test_fake_backend_disconnect_is_failed_and_sample_free(tmp_path) -> None:
    async def scenario(tmp_path):
        stream = IntegrationStream(
            stop_error=AudioBackendError(
                AudioErrorCode.DISCONNECTED,
                "fake disconnect",
            )
        )
        capture = AudioCapture(IntegrationBackend(stream))
        session = AudioSession(capture, tmp_path)
        task = asyncio.create_task(session.run())
        await wait_for_started(stream)
        stream.emit(2)
        outcome = await session.stop()
        return stream, capture, task, outcome

    stream, capture, task, outcome = asyncio.run(scenario(tmp_path))
    serialized = json.dumps(outcome.to_dict())

    assert task.done()
    assert outcome.kind is AudioSessionOutcomeType.FAILED
    assert outcome.failure is not None
    assert outcome.retryable
    assert outcome.artifact is not None
    assert outcome.artifact.audio_sha256
    assert "fake disconnect" not in serialized
    assert "\x01" not in serialized
    assert stream.calls == ["start", "stop", "close"]
    assert capture.has_active_stream is False


def test_fake_max_duration_and_overflow_stop_before_close_without_network(tmp_path) -> None:
    async def scenario(tmp_path):
        overflow_stream = IntegrationStream()
        overflow_capture = AudioCapture(IntegrationBackend(overflow_stream))
        overflow = AudioSession(
            overflow_capture,
            tmp_path / "overflow",
            config=AudioSessionConfig(max_duration_ms=1000, max_buffer_frames=2),
        )
        overflow_task = asyncio.create_task(overflow.run())
        await wait_for_started(overflow_stream)
        overflow_stream.emit(2)
        overflow_stream.emit(1)
        overflow_result = await overflow_task

        duration_stream = IntegrationStream()
        duration_capture = AudioCapture(IntegrationBackend(duration_stream))
        duration = AudioSession(
            duration_capture,
            tmp_path / "duration",
            config=AudioSessionConfig(max_duration_ms=1),
        )
        duration_task = asyncio.create_task(duration.run())
        await wait_for_started(duration_stream)
        duration_stream.emit(64)
        duration_result = await duration_task
        return overflow_stream, overflow_result, duration_stream, duration_result

    overflow_stream, overflow, duration_stream, duration = asyncio.run(scenario(tmp_path))

    assert overflow.kind is AudioSessionOutcomeType.OVERFLOW
    assert overflow_stream.calls == ["start", "stop", "close"]
    assert duration.kind is AudioSessionOutcomeType.MAX_DURATION
    assert duration.artifact is not None
    assert duration.artifact.frame_count == 48
    assert duration_stream.calls == ["start", "stop", "close"]


def test_fake_close_failure_is_typed_recoverable_and_not_repeated(tmp_path) -> None:
    async def scenario():
        stream = IntegrationStream(
            close_error=AudioBackendError(
                AudioErrorCode.BACKEND_UNAVAILABLE,
                "fake close failure",
            )
        )
        capture = AudioCapture(IntegrationBackend(stream))
        session = AudioSession(capture, tmp_path)
        task = asyncio.create_task(session.run())
        await wait_for_started(stream)
        stream.emit(2)
        outcome = await session.cancel()
        return stream, capture, task, outcome

    stream, capture, task, outcome = asyncio.run(scenario())

    assert task.done()
    assert outcome.kind is AudioSessionOutcomeType.FAILED
    assert outcome.failure is not None
    assert outcome.failure.code == "backend_unavailable"
    assert outcome.retryable
    assert outcome.artifact is not None
    assert stream.calls == ["start", "stop", "close"]
    assert capture.has_active_stream
