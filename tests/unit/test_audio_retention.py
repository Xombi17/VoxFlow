import asyncio

from voxflow.audio.session import AudioSession, AudioSessionConfig
from voxflow.platform.audio import AudioCapture, AudioCaptureState
from voxflow.platform.audio_devices import AudioDevice, AudioFormat, OpenedAudioStream
from voxflow.settings import WritingSettingsStore


FORMAT = AudioFormat(48_000, 1)
PCM = b"\x01\x00"


class Stream:
    def __init__(self):
        self.callback = None
        self.started = False

    def register_frame_callback(self, callback):
        self.callback = callback

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    async def close(self):
        self.started = False

    def emit(self, count):
        self.callback(PCM * count, count)


class Backend:
    def __init__(self):
        self.stream = Stream()
        self.device = AudioDevice("fake", "Fake", supported_formats=(FORMAT,))

    async def enumerate_devices(self):
        return (self.device,)

    async def open(self, device_id, requested_format=None):
        assert device_id == self.device.id
        return OpenedAudioStream(self.device, requested_format or FORMAT, self.stream)


def test_retention_policy_is_persisted_and_defaults_to_disabled(tmp_path):
    store = WritingSettingsStore(tmp_path / "settings.db")
    assert store.get_audio_retention() is False
    assert store.set_audio_retention(True) is True
    assert store.get_retain_audio() is True
    assert store.set_retain_audio(False) is False
    assert store.get_audio_retention() is False


def test_disabled_retention_materializes_for_asr_then_deletes_at_terminal_action(tmp_path):
    async def scenario():
        backend = Backend()
        capture = AudioCapture(backend)
        session = AudioSession(
            capture,
            tmp_path,
            config=AudioSessionConfig(retain_audio=False),
        )
        task = asyncio.create_task(session.run())
        for _ in range(100):
            if backend.stream.started:
                break
            await asyncio.sleep(0)
        backend.stream.emit(2)
        outcome = await session.stop()
        assert outcome.artifact is not None
        assert outcome.artifact.path.exists()
        assert session.discard_artifact(outcome.artifact) is True
        return outcome

    outcome = asyncio.run(scenario())
    assert outcome.retention_policy == "discard_after_terminal"
    assert not list(tmp_path.iterdir())


def test_enabled_retention_keeps_artifact_for_retry(tmp_path):
    async def scenario():
        backend = Backend()
        session = AudioSession(
            AudioCapture(backend),
            tmp_path,
            config=AudioSessionConfig(retain_audio=True),
        )
        task = asyncio.create_task(session.run())
        for _ in range(100):
            if backend.stream.started:
                break
            await asyncio.sleep(0)
        backend.stream.emit(2)
        outcome = await session.stop()
        return task, outcome

    task, outcome = asyncio.run(scenario())
    assert task.done()
    assert outcome.artifact is not None
    assert outcome.retention_policy == "retain"
    assert outcome.artifact.path.exists()
