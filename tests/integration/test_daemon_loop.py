import asyncio
from types import SimpleNamespace

from voxflow.audio.session import AudioSessionFailure
from voxflow.core.capabilities import CapabilityStatus
from voxflow.platform.audio import AudioCaptureState
from voxflow.platform.audio_devices import AudioDevice, AudioFormat, OpenedAudioStream
from voxflow.platform.insert import InsertOutcome, InsertResult
from voxflow.platform.insert import InsertSideEffect
from voxflow.platform.portals import PortalClientError, PortalErrorCode
from voxflow.platform.shortcuts import ShortcutEvent, ShortcutEventType
from voxflow.providers.asr import (
    CancellationToken,
    ProviderCapabilities,
    ProviderConfigSnapshot,
    Segment,
    TranscriptResult,
)
from voxflow.daemon import DictationDaemon


FORMAT = AudioFormat(16_000, 1)
DEVICE = AudioDevice("fake-mic", "Fake microphone", True, supported_formats=(FORMAT,))


class FakeStream:
    def __init__(self, events):
        self.events = events
        self.callback = None
        self.failure_callback = None
        self.started = False

    def register_frame_callback(self, callback):
        self.callback = callback

    def register_failure_callback(self, callback):
        self.failure_callback = callback

    async def start(self):
        self.started = True
        self.events.append("capture-start")

    async def stop(self):
        self.started = False
        self.events.append("capture-stop")

    async def close(self):
        self.started = False
        self.events.append("capture-close")

    def emit(self, text=b"\x01\x00" * 160):
        assert self.callback is not None
        self.callback(text, len(text) // 2)

    def fail_stalled(self):
        assert self.failure_callback is not None
        self.failure_callback(
            AudioSessionFailure(
                code="capture_stalled",
                reason="No fake frames arrived.",
            )
        )


class FakeCapture:
    def __init__(self, events):
        self.events = events
        self.stream = FakeStream(events)
        self.state = AudioCaptureState.CLOSED
        self.open_count = 0

    @property
    def has_active_stream(self):
        return self.state in {AudioCaptureState.OPEN, AudioCaptureState.RUNNING}

    async def open(self):
        self.open_count += 1
        self.events.append("capture-open")
        self.state = AudioCaptureState.OPEN
        return OpenedAudioStream(DEVICE, FORMAT, self.stream)

    async def start(self):
        self.state = AudioCaptureState.RUNNING
        await self.stream.start()

    async def stop(self):
        if self.state is AudioCaptureState.RUNNING:
            await self.stream.stop()
        self.state = AudioCaptureState.STOPPED

    async def close(self):
        await self.stream.close()
        self.state = AudioCaptureState.CLOSED


class FakeProvider:
    def __init__(self, model_id, events, *, wait=False, text="hello world"):
        self.config = ProviderConfigSnapshot(provider_id="fake", model_id=model_id)
        self.events = events
        self.wait = wait
        self.text = text
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def capabilities(self):
        return ProviderCapabilities(
            provider_id="fake",
            model_id=self.config.model_id,
            offline=True,
            network_required=False,
            supports_cancellation=True,
        )

    async def transcribe(self, audio, cancellation: CancellationToken):
        self.started.set()
        if self.wait:
            await self.release.wait()
        return TranscriptResult(
            text=self.text,
            language="en",
            segments=(
                (Segment(start_ms=0, end_ms=10, text=self.text),)
                if self.text.strip()
                else ()
            ),
            provider_id="fake",
            model_id=self.config.model_id,
            audio_sha256=audio.audio_sha256,
        )


class FakeInserter:
    def __init__(self, events, result=InsertResult.sent):
        self.events = events
        self.result = result
        self.texts = []

    async def insert(self, text):
        self.events.append("insert")
        self.texts.append(text)
        return InsertOutcome(
            self.result,
            text,
            "text retained — save or retry insertion"
            if self.result != InsertResult.sent
            else None,
        )

    def close(self):
        self.events.append("inserter-close")


class DeniedRemotePortal:
    def __init__(self):
        self.closed = False

    async def open_session(self):
        raise PortalClientError(
            PortalErrorCode.PERMISSION_DENIED,
            "private portal backend detail",
        )

    async def close(self):
        self.closed = True


class FakeNotifier:
    def __init__(self):
        self.messages = []

    def notify(self, message):
        self.messages.append(message)


class FailingWritingPipeline:
    def run(self, _transcript, _settings):
        raise RuntimeError("fixture failure")


class FakeShortcut:
    def __init__(self, *, hold_supported=True):
        self.hold_supported = hold_supported
        self.listener = None
        self.closed = False

    def add_listener(self, listener):
        self.listener = listener
        return lambda: setattr(self, "listener", None)

    async def configure(self):
        return SimpleNamespace(
            configured=True,
            failure=None,
            capabilities=(
                SimpleNamespace(id="shortcut.hold", status=CapabilityStatus.AVAILABLE),
            ),
        )

    async def close(self):
        self.closed = True

    def emit(self, event_type):
        event = ShortcutEvent(event_type, "dictation", "/fake/session", 1, "Ctrl+Space")
        assert self.listener is not None
        self.listener(event)


class FakeCatalog:
    def __init__(self, providers):
        self.selected = "small.en"
        self.providers = providers

    def default_models_root(self):
        return "/fake/models"

    def get_selected(self, **_kwargs):
        return self.selected

    def get_entry(self, model_id):
        return SimpleNamespace(id=model_id)

    def is_installed(self, _root, _model_id):
        return True

    def build_provider(self, entry, _root):
        return self.providers[entry.id]


async def make_daemon(
    tmp_path,
    *,
    hold=True,
    insert_result=InsertResult.sent,
    wait=False,
    writing_pipeline=None,
    provider_text="hello world",
    use_inserter=True,
    remote_portal=None,
):
    events = []
    shortcut = FakeShortcut(hold_supported=hold)
    captures = []
    providers = {
        "small.en": FakeProvider("small.en", events, wait=wait, text=provider_text),
        "medium.en": FakeProvider("medium.en", events),
    }
    fake_catalog = FakeCatalog(providers)

    def make_capture():
        capture = FakeCapture(events)
        captures.append(capture)
        return capture

    inserter = FakeInserter(events, insert_result) if use_inserter else None
    notifier = FakeNotifier()
    daemon = DictationDaemon(
        shortcut,
        capture_factory=make_capture,
        catalog_module=fake_catalog,
        models_root=tmp_path / "models",
        inserter=inserter,
        remote_portal=remote_portal,
        notifier=notifier,
        artifact_dir=tmp_path / "captures",
        db_path=tmp_path / "writing.db",
        writing_pipeline=writing_pipeline,
    )
    await daemon.start()
    return daemon, shortcut, captures, inserter, notifier, providers, events, fake_catalog


def test_hold_release_transcribes_after_capture_closes_and_inserts_once(tmp_path):
    async def scenario():
        daemon, shortcut, captures, inserter, _notifier, _providers, events, _catalog = await make_daemon(tmp_path)
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
        await daemon.wait_idle()
        await daemon.stop()
        return events, inserter.texts, daemon.last_writing_result

    events, texts, writing_result = asyncio.run(scenario())
    assert texts == ["Hello world."]
    assert writing_result is not None
    assert writing_result.raw_text == "hello world"
    assert writing_result.final_text == "Hello world."
    assert events.index("capture-close") < events.index("insert")
    assert events.count("insert") == 1


def test_daemon_prints_lifecycle_status_without_transcript_content(tmp_path, capsys):
    async def scenario():
        daemon, shortcut, captures, _inserter, _notifier, *_ = await make_daemon(tmp_path)
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
        await daemon.wait_idle()
        await daemon.stop()

    asyncio.run(scenario())

    output = capsys.readouterr().out
    assert "VoxFlow: ready" in output
    assert "VoxFlow: listening" in output
    assert "VoxFlow: processing locally" in output
    assert "VoxFlow: inserted transcript" in output
    assert "hello world" not in output.lower()


def test_idle_daemon_never_opens_capture(tmp_path):
    async def scenario():
        daemon, _shortcut, captures, *_ = await make_daemon(tmp_path)
        await asyncio.sleep(0)
        await daemon.stop()
        return captures

    assert asyncio.run(scenario()) == []


def test_second_press_during_processing_does_not_duplicate_insert(tmp_path):
    async def scenario():
        daemon, shortcut, captures, inserter, _notifier, _providers, _events, *_ = await make_daemon(tmp_path, wait=True)
        provider = _providers["small.en"]
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
        await provider.started.wait()
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        provider.release.set()
        await daemon.wait_idle()
        await daemon.stop()
        return inserter.texts, len(captures)

    texts, capture_count = asyncio.run(scenario())
    assert texts == ["Hello world."]
    assert capture_count == 1


def test_denied_insert_keeps_text_and_notifies_fallback(tmp_path):
    async def scenario():
        daemon, shortcut, captures, inserter, notifier, *_ = await make_daemon(
            tmp_path, insert_result=InsertResult.denied
        )
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
        await daemon.wait_idle()
        await daemon.stop()
        return inserter.texts, notifier.messages

    texts, messages = asyncio.run(scenario())
    assert texts == ["Hello world."]
    assert messages == ["text retained — save or retry insertion"]


def test_portal_denial_keeps_daemon_usable_and_writing_result(tmp_path):
    async def scenario():
        remote = DeniedRemotePortal()
        daemon, shortcut, captures, inserter, notifier, *_ = await make_daemon(
            tmp_path,
            use_inserter=False,
            remote_portal=remote,
        )
        assert inserter is None
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
        await daemon.wait_idle()
        result = daemon.last_writing_result
        outcome = daemon.last_insert_outcome
        running = daemon.running
        await daemon.stop()
        return result, outcome, notifier.messages, running, remote.closed

    result, outcome, messages, running, remote_closed = asyncio.run(scenario())
    assert running is True
    assert remote_closed is True
    assert result is not None
    assert result.final_text == "Hello world."
    assert outcome is not None
    assert outcome.result is InsertResult.unavailable
    assert outcome.text == "Hello world."
    assert outcome.attempt_id
    assert outcome.trace[0]["attempt_id"] == outcome.attempt_id
    assert outcome.side_effect is InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT
    assert outcome.retryable is True
    assert any("insertion unavailable" in message for message in messages)
    assert all("copied" not in message.lower() for message in messages)


def test_no_inserter_fallback_attempt_metadata_is_unique_and_retryable(tmp_path):
    first = DictationDaemon._unavailable_insert_outcome("one")
    second = DictationDaemon._unavailable_insert_outcome("two")

    assert first.attempt_id != second.attempt_id
    assert first.retryable is second.retryable is True
    assert all("one" not in repr(event) for event in first.trace)
    assert all("two" not in repr(event) for event in second.trace)


def test_writing_failure_retains_raw_transcript_for_recovery(tmp_path):
    async def scenario():
        daemon, shortcut, captures, inserter, notifier, *_ = await make_daemon(
            tmp_path,
            writing_pipeline=FailingWritingPipeline(),
        )
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
        await daemon.wait_idle()
        await daemon.stop()
        return daemon.last_writing_result, inserter.texts, notifier.messages

    result, texts, messages = asyncio.run(scenario())
    assert result is not None
    assert result.raw_text == "hello world"
    assert result.final_text == "hello world"
    assert result.fallback_code == "writing_pipeline_failed"
    assert texts == []
    assert messages == ["writing failed: writing_pipeline_failed"]


def test_blank_asr_text_notifies_recoverable_empty_transcript(tmp_path):
    async def scenario():
        daemon, shortcut, captures, inserter, notifier, *_ = await make_daemon(
            tmp_path, provider_text="   "
        )
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
        await daemon.wait_idle()
        await daemon.stop()
        return daemon.last_writing_result, inserter.texts, notifier.messages

    result, texts, messages = asyncio.run(scenario())

    assert result is None
    assert texts == []
    assert messages == ["dictation failed: empty_transcript"]


def test_capture_stall_is_structured_and_does_not_insert(tmp_path):
    async def scenario():
        daemon, shortcut, captures, inserter, notifier, *_ = await make_daemon(tmp_path)
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.fail_stalled()
        await daemon.wait_idle()
        await daemon.stop()
        return captures[0], inserter.texts, notifier.messages

    capture, texts, messages = asyncio.run(scenario())
    assert capture.state is AudioCaptureState.CLOSED
    assert texts == []
    assert messages == ["capture failed: capture_stalled"]


def test_activation_again_stops_capture_when_deactivated_is_unavailable(tmp_path):
    async def scenario():
        daemon, shortcut, captures, inserter, *_ = await make_daemon(tmp_path, hold=False)
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await daemon.wait_idle()
        await daemon.stop()
        return inserter.texts

    assert asyncio.run(scenario()) == ["Hello world."]


def test_provider_is_selected_from_catalog_and_reload_uses_changed_selection(tmp_path):
    async def scenario():
        daemon, shortcut, captures, inserter, *_rest = await make_daemon(tmp_path)
        providers = _rest[-3]
        fake_catalog = _rest[-1]
        assert daemon.provider is providers["small.en"]
        fake_catalog.selected = "medium.en"
        daemon.reload_provider()
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
        await daemon.wait_idle()
        await daemon.stop()
        return daemon.provider, providers["medium.en"], inserter.texts

    provider, expected, texts = asyncio.run(scenario())
    assert provider is expected
    assert texts == ["Hello world."]
