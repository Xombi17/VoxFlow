import asyncio

import pytest

from voxflow.daemon import DictationDaemon
from voxflow.providers.asr import Segment, TranscriptResult
from voxflow.providers.cleanup import CleanupCancellationError, CleanupProviderError
from voxflow.providers.config import NetworkPolicy
from voxflow.text.contracts import CleanupPolicy, TextRule, WritingSettings
from voxflow.text.pipeline import DeterministicWritingPipeline
from voxflow import settings as settings_store
from voxflow.text.rules import RuleKind


def make_transcript(text: str) -> TranscriptResult:
    return TranscriptResult(
        text=text,
        language="en",
        segments=(Segment(start_ms=0, end_ms=100, text=text),),
        provider_id="fake",
        model_id="small.en",
        audio_sha256="c" * 64,
    )


class FakeCleanupProvider:
    provider_id = "fake-cleanup"
    network_required = False
    timeout_seconds = 0.01

    def __init__(self, outcome="success", output="Provider cleaned text."):
        self.outcome = outcome
        self.output = output
        self.requests = []

    async def cleanup(self, request, _cancellation):
        self.requests.append(request)
        if self.outcome == "error":
            raise CleanupProviderError("provider_failed", "private transcript provider detail")
        if self.outcome == "timeout":
            await asyncio.sleep(0.05)
        if self.outcome == "slow_success":
            await asyncio.sleep(0.02)
        if self.outcome == "cancelled":
            raise CleanupCancellationError()
        if self.outcome == "task_cancelled":
            raise asyncio.CancelledError()
        if self.outcome == "empty":
            return ""
        return self.output


def provider_settings(**overrides) -> WritingSettings:
    values = {
        "cleanup_policy": CleanupPolicy.PROVIDER,
        "cleanup_provider_id": "fake-cleanup",
    }
    values.update(overrides)
    return WritingSettings(**values)


def test_raw_transcript_survives_personalized_final_text_generation():
    raw_text = "um please send the report"
    result = DeterministicWritingPipeline().run(
        make_transcript(raw_text),
        WritingSettings(
            snippets=(TextRule(1, "send the report", "send the report to Alice"),),
        ),
    )

    assert result.raw_text == raw_text
    assert result.final_text == "Please send the report to Alice."
    assert result.raw.result.text == raw_text
    assert result.to_safe_dict()["raw_text_sha256"] != result.to_safe_dict()["final_text_sha256"]


def test_deterministic_pipeline_never_requires_network(monkeypatch):
    monkeypatch.setenv("NETWORK_DISABLED", "1")

    result = DeterministicWritingPipeline().run(make_transcript("hello"))

    assert result.final_text == "Hello."
    assert result.fallback is False


def test_persisted_snapshot_reaches_pipeline_without_live_database_access(tmp_path):
    store = settings_store.WritingSettingsStore(tmp_path / "writing.db")
    store.add_snippet("send report", "send the report to Alice")
    snapshot = store.load_writing_settings()
    store.update_rule(RuleKind.SNIPPET, snapshot.snippets[0].rule_id, replacement="changed")

    result = DeterministicWritingPipeline().run(make_transcript("please send report"), snapshot)

    assert result.raw_text == "please send report"
    assert result.final_text == "Please send the report to Alice."
    assert result.settings is snapshot


def test_async_cleanup_success_receives_raw_text_and_records_provider_identity():
    raw_text = "um please send the report"
    provider = FakeCleanupProvider()

    result = asyncio.run(
        DeterministicWritingPipeline(provider).run_async(
            make_transcript(raw_text), provider_settings()
        )
    )

    assert result.raw_text == raw_text
    assert result.final_text == "Provider cleaned text."
    assert result.cleanup_provider_id == "fake-cleanup"
    assert result.fallback is False
    assert provider.requests[0].raw_text == raw_text
    assert "please send" not in str(provider.requests[0].to_safe_dict())


def test_job_cleanup_timeout_is_the_outer_deadline_not_provider_default():
    provider = FakeCleanupProvider(outcome="slow_success")
    settings = provider_settings(cleanup_timeout_seconds=0.05)

    result = asyncio.run(
        DeterministicWritingPipeline(provider).run_async(make_transcript("raw input"), settings)
    )

    assert result.final_text == "Provider cleaned text."
    assert result.fallback is False
    assert provider.requests[0].timeout_seconds == 0.05


def test_async_cleanup_preserves_provider_output_literally():
    output = "  literal comma, and spacing  \n"

    result = asyncio.run(
        DeterministicWritingPipeline(FakeCleanupProvider(output=output)).run_async(
            make_transcript("raw input"), provider_settings()
        )
    )

    assert result.final_text == output


@pytest.mark.parametrize(
    ("outcome", "fallback_code"),
    [
        ("error", "cleanup_provider_failed"),
        ("timeout", "cleanup_timeout"),
        ("cancelled", "cleanup_cancelled"),
        ("task_cancelled", "cleanup_cancelled"),
        ("empty", "cleanup_empty_output"),
    ],
)
def test_provider_failures_always_insert_exact_raw_transcript(outcome, fallback_code):
    raw_text = "um keep this exact transcript"
    provider = FakeCleanupProvider(outcome)

    result = asyncio.run(
        DeterministicWritingPipeline(provider).run_async(
            make_transcript(raw_text),
            provider_settings(cleanup_timeout_seconds=0.01 if outcome == "timeout" else 30.0),
        )
    )

    assert result.raw_text == raw_text
    assert result.final_text == raw_text
    assert result.fallback is True
    assert result.fallback_code == fallback_code
    assert result.to_safe_dict()["fallback_code"] == fallback_code
    assert "private transcript" not in str(result.to_safe_dict())


def test_provider_identity_mismatch_falls_back_before_dispatch():
    raw_text = "keep this exact transcript"
    provider = FakeCleanupProvider()
    provider.provider_id = "different-cleanup"

    result = asyncio.run(
        DeterministicWritingPipeline(provider).run_async(
            make_transcript(raw_text), provider_settings()
        )
    )

    assert result.final_text == raw_text
    assert result.fallback is True
    assert result.fallback_code == "cleanup_provider_mismatch"
    assert result.cleanup_provider_id == "fake-cleanup"
    assert provider.requests == []


def test_remote_provider_is_rejected_without_explicit_network_policy():
    provider = FakeCleanupProvider()
    provider.network_required = True

    result = asyncio.run(
        DeterministicWritingPipeline(provider).run_async(
            make_transcript("keep this raw"),
            provider_settings(
                cleanup_network_policy=NetworkPolicy.LOCAL_ONLY,
                cleanup_network_disclosure=False,
            ),
        )
    )

    assert result.final_text == "keep this raw"
    assert result.fallback_code == "cleanup_network_policy_rejected"
    assert provider.requests == []


def test_daemon_injects_cleanup_provider_into_default_pipeline(tmp_path):
    provider = FakeCleanupProvider()
    daemon = DictationDaemon(
        shortcut_adapter=object(),
        cleanup_provider=provider,
        artifact_dir=tmp_path,
    )

    assert daemon.writing_pipeline.cleanup_provider is provider
    asyncio.run(daemon.stop())


def test_daemon_default_settings_factory_loads_persisted_settings(tmp_path):
    db = tmp_path / "writing.db"
    settings_store.WritingSettingsStore(db).set_cleanup_preferences(
        cleanup_policy=CleanupPolicy.PROVIDER,
        cleanup_provider_id="remote-cleanup",
        cleanup_network_policy=NetworkPolicy.REMOTE_EXPLICIT,
        cleanup_network_disclosure=True,
        cleanup_timeout_seconds=9.5,
    )
    daemon = DictationDaemon(shortcut_adapter=object(), db_path=db, artifact_dir=tmp_path)

    loaded = daemon.writing_settings_factory()

    assert loaded.cleanup_policy is CleanupPolicy.PROVIDER
    assert loaded.cleanup_provider_id == "remote-cleanup"
    assert loaded.cleanup_network_policy is NetworkPolicy.REMOTE_EXPLICIT
    assert loaded.cleanup_network_disclosure is True
    assert loaded.cleanup_timeout_seconds == 9.5
    asyncio.run(daemon.stop())


def test_daemon_preserves_injected_writing_settings_factory(tmp_path):
    expected = WritingSettings(language="fr", style="email")
    factory = lambda: expected
    daemon = DictationDaemon(
        shortcut_adapter=object(),
        db_path=tmp_path / "writing.db",
        artifact_dir=tmp_path,
        writing_settings_factory=factory,
    )

    assert daemon.writing_settings_factory is factory
    assert daemon.writing_settings_factory() is expected
    asyncio.run(daemon.stop())
