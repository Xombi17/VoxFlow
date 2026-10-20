import json
import os
import stat

import pytest

from voxflow.core.history import (
    AudioRetentionState,
    HistoryRecord,
    HistoryStore,
    InsertionAttemptRecord,
)
from voxflow.core.state import SessionState
from voxflow.providers.asr import Segment, TranscriptResult
from voxflow.text.contracts import RawTranscript, TextRule, WritingResult, WritingSettings


def writing_result() -> WritingResult:
    transcript = TranscriptResult(
        text="private raw transcript /home/user/secret",
        language="en",
        segments=(
            Segment(
                start_ms=0,
                end_ms=10,
                text="private raw transcript /home/user/secret",
            ),
        ),
        provider_id="fake",
        model_id="fixture",
        audio_sha256="a" * 64,
    )
    return WritingResult(
        raw=RawTranscript(transcript),
        final_text="Private final text with a token",
        settings=WritingSettings(
            dictionary_words=("VoxFlow",),
            corrections=(TextRule(1, "teh", "the"),),
        ),
    )


def test_schema_migration_preserves_settings_and_creates_recovery_tables(tmp_path):
    from voxflow import settings

    db = tmp_path / "history.db"
    settings.set_selected_model_id("small.en", db_path=db)
    store = HistoryStore(db)

    with store.transaction() as conn:
        assert conn.execute(
            "SELECT value FROM settings WHERE key = 'selected_model_id'"
        ).fetchone() == ("small.en",)
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'dictation_jobs'"
        ).fetchone() == ("dictation_jobs",)
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'insertion_attempts'"
        ).fetchone() == ("insertion_attempts",)
        assert conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'settings_schema_version'"
        ).fetchone() == (settings.SCHEMA_VERSION,)


def test_list_is_redacted_but_explicit_show_round_trips_full_text_and_settings(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    result = writing_result()
    store.create_job(
        HistoryRecord.from_writing_result(
            "job-1",
            result,
            status=SessionState.SUCCESS,
            audio_retention_state=AudioRetentionState.DELETED,
        )
    )

    listed = store.list_jobs()[0]
    safe = json.dumps(listed.to_safe_dict())
    shown = store.show_job("job-1")

    assert "private raw transcript" not in safe
    assert "Private final text" not in safe
    assert "/home/user" not in safe
    assert "token" not in safe
    assert shown.raw_text == result.raw_text
    assert shown.final_text == result.final_text
    assert shown.settings.corrections[0].replacement == "the"
    assert shown.to_user_dict()["raw_text"] == result.raw_text
    assert shown.to_user_dict()["settings"]["dictionary_words"] == ["voxflow"]


def test_successful_history_records_require_both_texts(tmp_path):
    store = HistoryStore(tmp_path / "success.db")
    record = HistoryRecord(job_id="job-success", status=SessionState.SUCCESS)
    with pytest.raises(ValueError, match="raw and final text"):
        store.create_job(record)


def test_attempt_creation_is_idempotent_and_unknown_side_effect_is_not_retryable(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    store.create_job(HistoryRecord(job_id="job-2"))
    attempt = InsertionAttemptRecord(
        attempt_id="attempt-1",
        job_id="job-2",
        phase="prepared",
        retryable=True,
    )

    first = store.create_insertion_attempt(attempt)
    second = store.create_insertion_attempt(attempt)
    assert first == second
    assert len(store.list_insertion_attempts("job-2")) == 1

    updated = store.update_insertion_attempt(
        "attempt-1",
        phase="ambiguous",
        chord_sent=True,
        outcome="failed",
        side_effect="unknown_after_side_effect",
        retryable=False,
        trace=({"event": "chord_sent", "attempt_id": "attempt-1"},),
    )
    assert updated.chord_sent is True
    assert updated.retryable is False
    assert updated.to_safe_dict()["trace"][0]["event"] == "chord_sent"
    with pytest.raises(RuntimeError, match="compare-and-set"):
        store.update_insertion_attempt(
            "attempt-1",
            expected_phase="prepared",
            phase="completed",
        )


def test_history_transaction_rolls_back_failed_job_insert(tmp_path):
    store = HistoryStore(tmp_path / "history.db")

    with pytest.raises(RuntimeError, match="rollback"):
        with store.transaction() as conn:
            conn.execute(
                "INSERT INTO dictation_jobs "
                "(job_id, created_at, updated_at, status) VALUES (?, ?, ?, ?)",
                ("rolled-back", "now", "now", "failed"),
            )
            raise RuntimeError("rollback")

    assert store.list_jobs() == ()


def test_database_file_is_private_and_memory_connections_skip_chmod(tmp_path):
    db = tmp_path / "private.db"
    HistoryStore(db)
    assert stat.S_IMODE(db.stat().st_mode) == 0o600

    os.chmod(db, 0o644)
    HistoryStore(db)
    assert stat.S_IMODE(db.stat().st_mode) == 0o600

    from voxflow import settings

    connection = settings._connect(":memory:")
    try:
        assert connection.execute("SELECT 1").fetchone() == (1,)
    finally:
        connection.close()
