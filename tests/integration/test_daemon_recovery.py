import asyncio

import pytest

from voxflow.audio.session import AudioSessionConfig
from tests.integration.test_daemon_loop import FakeProvider, make_daemon
from voxflow.core.history import (
    AudioRetentionState,
    HistoryRecord,
    HistoryStore,
)
from voxflow.daemon import RecoveryNotAllowedError
from voxflow.platform.insert import InsertOutcome, InsertResult, InsertSideEffect
from voxflow.platform.shortcuts import ShortcutEventType
from voxflow.providers.asr import ASRProviderError


class SequenceInserter:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def insert(self, text, *, attempt_id=None):
        self.calls.append(text)
        outcome = self.outcomes.pop(0) if self.outcomes else InsertResult.sent
        if isinstance(outcome, InsertResult):
            return InsertOutcome(
                result=outcome,
                text=text,
                fallback_hint=None if outcome is InsertResult.sent else "text retained — save or retry insertion",
                attempt_id=attempt_id or "fake-attempt",
                side_effect=(
                    InsertSideEffect.COMPLETED
                    if outcome is InsertResult.sent
                    else InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT
                ),
                retryable=outcome is not InsertResult.sent,
            )
        return outcome

    def close(self):
        pass


class BlockingWritingPipeline:
    def __init__(self):
        self.started = asyncio.Event()

    async def run_async(self, _transcript, _settings):
        self.started.set()
        await asyncio.Event().wait()


class GuardBlockingInserter:
    def __init__(self, daemon):
        self.daemon = daemon
        self.observed = None
        self.called = asyncio.Event()

    async def insert(self, text, *, attempt_id=None):
        self.observed = self.daemon.history.get_insertion_attempt(attempt_id)
        self.called.set()
        await asyncio.Event().wait()

    def close(self):
        pass


class RetryProvider(FakeProvider):
    def __init__(self):
        super().__init__("retry", [], text="hello world")
        self.calls = 0

    async def transcribe(self, audio, cancellation):
        self.calls += 1
        if self.calls == 1:
            raise ASRProviderError("temporary_failure", "private provider detail")
        return await super().transcribe(audio, cancellation)


def pre_chord_failure():
    return InsertOutcome(
        result=InsertResult.failed,
        text="ignored by durable trace",
        fallback_hint="text retained — save or retry insertion",
        attempt_id="provided-by-daemon",
        side_effect=InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT,
        retryable=True,
        detail="clipboard ownership not granted",
    )


def ambiguous_failure():
    return InsertOutcome(
        result=InsertResult.failed,
        text="ignored by durable trace",
        fallback_hint="text retained — save or retry insertion",
        attempt_id="provided-by-daemon",
        side_effect=InsertSideEffect.UNKNOWN_AFTER_SIDE_EFFECT,
        retryable=False,
        detail="target never requested the text",
        trace=({"event": "chord_sent", "attempt_id": "provided-by-daemon"},),
    )


async def complete_one(daemon, shortcut, captures):
    shortcut.emit(ShortcutEventType.LISTENING_STARTED)
    await asyncio.sleep(0)
    captures[0].stream.emit()
    shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
    await daemon.wait_idle()


def test_pre_chord_retry_is_durable_and_duplicate_retry_is_idempotent(tmp_path):
    async def scenario():
        daemon, shortcut, captures, _old, _notifier, *_ = await make_daemon(tmp_path)
        daemon.audio_config = AudioSessionConfig(retain_audio=True)
        inserter = SequenceInserter([pre_chord_failure(), InsertResult.sent])
        daemon.inserter = inserter
        await complete_one(daemon, shortcut, captures)
        job_id = daemon.history.list_jobs()[0].job_id
        first_attempts = daemon.history.list_insertion_attempts(job_id)
        first_retry = await daemon.retry_insertion(job_id)
        second_attempts = daemon.history.list_insertion_attempts(job_id)
        duplicate_retry = await daemon.retry_insertion(job_id)
        record = HistoryStore(tmp_path / "writing.db").show_job(job_id)
        await daemon.stop()
        return inserter, first_attempts, first_retry, second_attempts, duplicate_retry, record

    inserter, first, retry, second, duplicate, record = asyncio.run(scenario())
    assert len(first) == 1
    assert first[0].retryable is True
    assert retry.result is InsertResult.sent
    assert len(second) == 2
    assert duplicate.result is InsertResult.sent
    assert len(inserter.calls) == 2
    assert record.status.value == "success"
    assert record.audio_retention_state.value == "retained"
    assert HistoryStore(tmp_path / "writing.db").resolve_artifact(record.job_id, tmp_path / "captures") is not None
    assert record.raw_text == "hello world"
    assert record.final_text == "Hello world."


def test_ambiguous_post_chord_failure_requires_explicit_confirmation(tmp_path):
    async def scenario():
        daemon, shortcut, captures, _old, _notifier, *_ = await make_daemon(tmp_path)
        inserter = SequenceInserter([ambiguous_failure(), InsertResult.sent])
        daemon.inserter = inserter
        await complete_one(daemon, shortcut, captures)
        job_id = daemon.history.list_jobs()[0].job_id
        with pytest.raises(RecoveryNotAllowedError, match="explicit confirmation"):
            await daemon.retry_insertion(job_id)
        attempts_before_confirmation = daemon.history.list_insertion_attempts(job_id)
        confirmed = await daemon.retry_insertion(job_id, confirm_ambiguous=True)
        attempts_after_confirmation = daemon.history.list_insertion_attempts(job_id)
        await daemon.stop()
        return confirmed, attempts_before_confirmation, attempts_after_confirmation, inserter

    confirmed, before, after, inserter = asyncio.run(scenario())
    assert confirmed.result is InsertResult.sent
    assert len(before) == 1
    assert len(after) == 2
    assert len(inserter.calls) == 2


def test_disabled_daemon_retention_deletes_artifact_after_insert_terminal_state(tmp_path):
    async def scenario():
        daemon, shortcut, captures, _inserter, _notifier, *_ = await make_daemon(tmp_path)
        await complete_one(daemon, shortcut, captures)
        record = daemon.history.list_jobs()[0]
        files = tuple((tmp_path / "captures").iterdir())
        await daemon.stop()
        return record, files

    record, files = asyncio.run(scenario())
    assert record.audio_retention_state.value == "deleted"
    assert files == ()


def test_cancel_during_asr_persists_recoverable_terminal_state(tmp_path):
    class CancellationAwareProvider(FakeProvider):
        async def transcribe(self, audio, cancellation):
            self.seen_audio = audio
            self.started.set()
            while not cancellation.is_cancelled:
                await asyncio.sleep(0)
            cancellation.raise_if_cancelled()

    async def scenario():
        daemon, shortcut, captures, inserter, _notifier, providers, *_ = await make_daemon(tmp_path)
        provider = CancellationAwareProvider("cancel", [], text="hello world")
        daemon.provider = provider
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
        await provider.started.wait()
        job_id = daemon.active_job_id
        await daemon.stop()
        return daemon.history.show_job(job_id), inserter

    record, inserter = asyncio.run(scenario())
    assert record.status.value == "cancelled"
    assert record.error_code == "cancelled"
    assert record.insertion_attempt_id is None
    assert inserter.texts == []


def test_stop_during_writing_cancels_outer_task_and_persists_recoverable_result(tmp_path):
    async def scenario():
        pipeline = BlockingWritingPipeline()
        daemon, shortcut, captures, _inserter, _notifier, *_ = await make_daemon(
            tmp_path,
            writing_pipeline=pipeline,
        )
        daemon.audio_config = AudioSessionConfig(retain_audio=True)
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
        await pipeline.started.wait()
        job_id = daemon.active_job_id
        before = daemon.history.show_job(job_id)
        await asyncio.wait_for(daemon.stop(), timeout=1)
        return before, daemon.history.show_job(job_id), daemon.last_writing_result

    before, record, result = asyncio.run(scenario())
    assert before.status.value == "processing"
    assert before.raw_text is None
    assert before.final_text is None
    assert record.status.value == "cancelled"
    assert record.retryable is True
    assert record.retry_code == "retry_transcription"
    assert record.raw_text == "hello world"
    assert record.final_text == "hello world"
    assert result is not None
    assert result.fallback_code == "writing_cancelled"


def test_insertion_process_window_is_durable_before_inserter_call(tmp_path):
    async def scenario():
        daemon, shortcut, captures, _old, _notifier, *_ = await make_daemon(tmp_path)
        inserter = GuardBlockingInserter(daemon)
        daemon.inserter = inserter
        shortcut.emit(ShortcutEventType.LISTENING_STARTED)
        await asyncio.sleep(0)
        captures[0].stream.emit()
        shortcut.emit(ShortcutEventType.LISTENING_STOPPED)
        await asyncio.wait_for(inserter.called.wait(), timeout=1)
        assert inserter.observed is not None
        job_id = daemon.active_job_id
        # The inserter is blocked in its side-effect window. Shutdown must
        # leave the guard ambiguous rather than reclassifying it as prepared.
        await asyncio.wait_for(daemon.stop(), timeout=1)
        with pytest.raises(RecoveryNotAllowedError, match="explicit confirmation"):
            await daemon.retry_insertion(job_id)
        return daemon.history.show_job(job_id), inserter

    record, inserter = asyncio.run(scenario())
    assert inserter.observed is not None
    assert inserter.observed.phase == "ambiguous"
    assert inserter.observed.side_effect == InsertSideEffect.UNKNOWN_AFTER_SIDE_EFFECT.value
    assert inserter.observed.retryable is False
    assert record.status.value == "cancelled"


def test_retained_asr_failure_has_a_real_transcription_retry_path(tmp_path):
    async def scenario():
        daemon, shortcut, captures, inserter, _notifier, *_ = await make_daemon(tmp_path)
        daemon.audio_config = AudioSessionConfig(retain_audio=True)
        provider = RetryProvider()
        daemon.provider = provider
        await complete_one(daemon, shortcut, captures)
        failed = daemon.history.list_jobs()[0]
        retried = await daemon.retry_transcription(failed.job_id)
        await daemon.stop()
        return provider, inserter, failed, retried

    provider, inserter, failed, retried = asyncio.run(scenario())
    assert provider.calls == 2
    assert failed.status.value == "failed"
    assert failed.retryable is True
    assert failed.retry_code == "retry_transcription"
    assert retried.status.value == "success"
    assert retried.retry_count == 1
    assert retried.raw_text == "hello world"
    assert retried.final_text == "Hello world."
    assert inserter.texts == ["Hello world."]
    assert retried.audio_retention_state is AudioRetentionState.RETAINED


def test_startup_cleans_disabled_retention_orphans_without_exposing_paths(tmp_path):
    async def scenario():
        db = tmp_path / "writing.db"
        captures_dir = tmp_path / "captures"
        captures_dir.mkdir()
        store = HistoryStore(db)
        store.create_job(
            HistoryRecord(
                job_id="orphan-job",
                status="processing",
                artifact_id="orphan-job.wav",
                artifact_metadata={"duration_ms": 10},
                retain_audio=False,
                audio_retention_state=AudioRetentionState.TRANSIENT,
            )
        )
        (captures_dir / "orphan-job.wav").write_bytes(b"transient")
        (captures_dir / ".voxflow-crash.wav").write_bytes(b"transient")
        daemon, *_ = await make_daemon(tmp_path)
        record = daemon.history.show_job("orphan-job")
        safe = str(record.to_safe_dict())
        await daemon.stop()
        return record, safe, tuple(captures_dir.iterdir())

    record, safe, files = asyncio.run(scenario())
    assert record.status.value == "failed"
    assert record.error_code == "orphaned_cleanup"
    assert record.audio_retention_state is AudioRetentionState.DELETED
    assert "transient" not in safe
    assert str(tmp_path) not in safe
    assert files == ()
