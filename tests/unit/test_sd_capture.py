import asyncio

import numpy as np

from voxflow.audio.session import AudioSessionFailure
from voxflow.platform.audio import AudioCaptureState
from voxflow.platform.sd_capture import SoundDeviceCapture, resample_to_pcm16


class FakeStream:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def close(self):
        self.calls.append("close")


class FakeSoundDevice:
    class default:
        device = (0, -1)

    def __init__(self):
        self.calls = []
        self.streams = []

    def query_devices(self, *_args):
        return [
            {
                "name": "fake stereo mic",
                "max_input_channels": 2,
                "default_samplerate": 48_000,
            }
        ]

    def InputStream(self, **kwargs):
        self.calls.append(kwargs)
        stream = FakeStream(kwargs["callback"])
        self.streams.append(stream)
        return stream


def test_resample_downmixes_stereo_48k_to_mono_16k_pcm16() -> None:
    source = np.column_stack(
        (np.full(480, 0.25, dtype=np.float32), np.full(480, 0.5, dtype=np.float32))
    )

    data, count = resample_to_pcm16(source, input_rate=48_000, input_channels=2)

    assert count == 160
    assert len(data) == count * 2
    assert np.frombuffer(data, dtype=np.int16)[0] == round(0.375 * 32767)


def test_sounddevice_opens_native_float_stream_and_emits_target_frames() -> None:
    async def scenario():
        sounddevice = FakeSoundDevice()
        capture = SoundDeviceCapture(sounddevice=sounddevice)
        opened = await capture.open()
        received = []
        opened.stream.register_frame_callback(lambda data, count: received.append((data, count)))
        await capture.start()
        source = np.column_stack(
            (np.zeros(480, dtype=np.float32), np.ones(480, dtype=np.float32))
        )
        sounddevice.streams[0].callback(source, 480, None, None)
        await capture.close()
        return capture, opened, received, sounddevice

    capture, opened, received, sounddevice = asyncio.run(scenario())

    assert sounddevice.calls[0]["samplerate"] == 48_000
    assert sounddevice.calls[0]["channels"] == 2
    assert sounddevice.calls[0]["dtype"] == "float32"
    assert opened.format.sample_rate == 16_000
    assert opened.format.channels == 1
    assert received[0][1] == 160
    assert capture.state is AudioCaptureState.CLOSED
    assert sounddevice.streams[0].calls == ["start", "stop", "close"]


def test_watchdog_reports_structured_stall_after_500ms_without_frames() -> None:
    async def scenario():
        now = [10.0]
        sounddevice = FakeSoundDevice()
        capture = SoundDeviceCapture(sounddevice=sounddevice, clock=lambda: now[0])
        opened = await capture.open()
        opened.stream.register_frame_callback(lambda _data, _count: None)
        failures: list[AudioSessionFailure] = []
        capture.register_failure_callback(failures.append)
        await capture.start()
        now[0] += 0.49
        source = np.zeros((480, 2), dtype=np.float32)
        sounddevice.streams[0].callback(source, 480, None, None)
        now[0] += 0.49
        assert capture.check_watchdog() is None
        now[0] += 0.02
        failure = capture.check_watchdog()
        await capture.stop()
        await capture.close()
        return failure, failures, sounddevice

    failure, failures, sounddevice = asyncio.run(scenario())

    assert failure is not None
    assert failure.code == "capture_stalled"
    assert failures == [failure]
    assert sounddevice.streams[0].calls == ["start", "stop", "close"]


def test_capture_does_not_start_or_watchdog_while_idle() -> None:
    async def scenario():
        sounddevice = FakeSoundDevice()
        capture = SoundDeviceCapture(sounddevice=sounddevice)
        await capture.open()
        return capture, sounddevice

    capture, sounddevice = asyncio.run(scenario())

    assert capture.state is AudioCaptureState.OPEN
    assert sounddevice.streams == []
