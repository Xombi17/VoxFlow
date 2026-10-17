import asyncio
import hashlib
from pathlib import Path

from voxflow.audio.artifacts import AudioArtifact
from voxflow.core.jobs import DictationJobRunner
from voxflow.core.state import SessionState
from voxflow.platform.audio_devices import AudioFormat
from voxflow.providers.asr import (
    ASRProviderError,
    ASRCancellationError,
    CancellationToken,
    ProviderCapabilities,
    ProviderConfigSnapshot,
    Segment,
    TranscriptResult,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "audio" / "short_utterance.wav"
CHECKSUM = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
FORMAT = AudioFormat(48_000, 1)
CONFIG = ProviderConfigSnapshot(provider_id="fake", model_id="fixture")


def artifact() -> AudioArtifact:
    return AudioArtifact(
        path=FIXTURE,
        audio_sha256=CHECKSUM,
        source_format=FORMAT,
        frame_count=480,
        duration_ms=10,
        wav_byte_count=FIXTURE.stat().st_size,
    )


class FakeProvider:
    def __init__(self, result=None, *, failure=None, wait_for_cancel=False):
        self.result = result
        self.failure = failure
        self.wait_for_cancel = wait_for_cancel
        self.seen_audio = None
        self.seen_token = None

    @property
    def capabilities(self):
        return ProviderCapabilities(
            provider_id="fake",
            model_id="fixture",
            offline=True,
            network_required=False,
            supports_cancellation=True,
        )

    async def transcribe(self, audio, cancellation):
        self.seen_audio = audio
        self.seen_token = cancellation
        if self.wait_for_cancel:
            while not cancellation.is_cancelled:
                await asyncio.sleep(0)
            raise ASRCancellationError()
        if self.failure is not None:
            raise self.failure
        return self.result


def valid_result(checksum: str = CHECKSUM) -> TranscriptResult:
    return TranscriptResult(
        text=" hello",
        language="en",
        language_probability=0.9,
        segments=(Segment(start_ms=0, end_ms=10, text=" hello"),),
        provider_id="fake",
        model_id="fixture",
        audio_sha256=checksum,
    )


def test_runner_validates_result_and_reaches_success() -> None:
    provider = FakeProvider(valid_result())

    snapshot = asyncio.run(
        DictationJobRunner(provider, artifact(), config=CONFIG, job_id="job-1").run()
    )

    assert snapshot.state is SessionState.SUCCESS
    assert snapshot.result is not None
    assert snapshot.result.audio_sha256 == CHECKSUM
    assert snapshot.artifact_reference.audio_sha256 == CHECKSUM
    assert provider.seen_audio.audio_sha256 == CHECKSUM


def test_runner_rejects_mismatched_result_and_preserves_artifact() -> None:
    provider = FakeProvider(valid_result("1" * 64))
    runner = DictationJobRunner(provider, artifact(), config=CONFIG, job_id="job-2")

    snapshot = asyncio.run(runner.run())

    assert snapshot.state is SessionState.FAILED
    assert snapshot.error_code == "checksum_mismatch"
    assert snapshot.retryable
    assert snapshot.artifact_reference.audio_sha256 == CHECKSUM
    assert str(FIXTURE) not in str(snapshot.to_dict())
    assert "hello" not in str(snapshot.to_dict())


def test_runner_maps_provider_failure_to_recoverable_state() -> None:
    provider = FakeProvider(failure=ASRProviderError("model_failed", "private detail"))

    snapshot = asyncio.run(DictationJobRunner(provider, artifact(), config=CONFIG).run())

    assert snapshot.state is SessionState.FAILED
    assert snapshot.error_code == "model_failed"
    assert snapshot.retry_code == "retry_transcription"
    assert "private detail" not in str(snapshot.to_dict())


def test_runner_cancellation_is_terminal_and_never_success() -> None:
    async def scenario():
        provider = FakeProvider(wait_for_cancel=True)
        runner = DictationJobRunner(provider, artifact(), config=CONFIG, job_id="job-3")
        task = asyncio.create_task(runner.run())
        for _ in range(100):
            if provider.seen_token is not None:
                break
            await asyncio.sleep(0)
        cancelled = await runner.cancel()
        return task, cancelled

    task, snapshot = asyncio.run(scenario())

    assert task.done()
    assert snapshot.state is SessionState.CANCELLED
    assert snapshot.retryable
    assert snapshot.artifact_reference.audio_sha256 == CHECKSUM


def test_core_job_module_has_no_concrete_faster_whisper_import() -> None:
    source = Path(__file__).parents[2] / "src" / "voxflow" / "core" / "jobs.py"
    assert "faster_whisper" not in source.read_text()
