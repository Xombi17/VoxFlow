import asyncio
import json
import stat
from dataclasses import replace

import pytest

from voxflow.core.history import HistoryRecord, HistoryStore, InsertionAttemptRecord
from voxflow.platform.insert import CopyOutcome, InsertOutcome, InsertResult, InsertSideEffect
from voxflow.recovery import RecoveryCode, RecoveryController


def seed(store, job_id="job-1", **changes):
    record = HistoryRecord(
        job_id=job_id, status="failed", raw_text="private raw wörld",
        final_text="Private final wörld.", retryable=True, retry_code="retry_insertion",
        insertion_attempt_id=f"{job_id}-attempt", insertion_result="failed",
        insertion_side_effect="failed_before_side_effect", insertion_retryable=True,
        provider_id="/private/provider/credential", model_id="secret-token",
        failure_reason="private exception detail",
    )
    store.create_job(replace(record, **changes))
    store.create_insertion_attempt(InsertionAttemptRecord(
        attempt_id=record.insertion_attempt_id, job_id=job_id, phase="failed",
        outcome="failed", retryable=True,
    ))
    return job_id


class Adapter:
    clipboard_available = True

    def __init__(self, store):
        self.store = store
        self.calls = []
        self.copies = []
        self.outcome = None

    async def insert(self, text, *, attempt_id):
        record = self.store.get_job("job-1")
        attempt = self.store.get_insertion_attempt(attempt_id)
        assert record.insertion_attempt_id == attempt_id
        assert record.retry_count == 1
        assert attempt.phase == "ambiguous" and not attempt.retryable
        self.calls.append(text)
        return self.outcome or InsertOutcome(
            InsertResult.sent, text, attempt_id=attempt_id,
            side_effect=InsertSideEffect.COMPLETED,
            trace=({"event": "chord_sent"}, {"event": "selection_write_done", "ok": True}),
        )

    async def copy(self, text, *, timeout_seconds):
        self.copies.append((text, timeout_seconds))
        return CopyOutcome(InsertResult.sent, transfer_completed=True)


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "history.db")


def test_list_is_narrow_metadata_and_action_availability_is_truthful(store):
    seed(store)
    api = RecoveryController(store)
    result = api.list()
    assert result.code is RecoveryCode.OK
    payload = result.to_dict()
    safe = json.dumps(payload)
    for secret in ("private raw", "Private final", "/private/", "secret-token", "exception"):
        assert secret not in safe
    row = payload["data"]["jobs"][0]
    assert row["job_id"] == "job-1"
    assert row["actions"]["show"]["state"] == "available"
    assert row["actions"]["save"]["state"] == "available"
    assert row["actions"]["copy"]["state"] == "unavailable"
    assert row["actions"]["retry"]["state"] == "unavailable"


def test_show_is_explicit_and_does_not_expose_settings_or_error_details(store):
    seed(store)
    shown = RecoveryController(store).show("job-1")
    assert shown.code is RecoveryCode.OK
    assert shown.data["raw_text"] == "private raw wörld"
    assert shown.data["final_text"] == "Private final wörld."
    assert "exception" not in json.dumps(shown.to_dict())
    assert "private raw" not in repr(shown)


def test_save_is_utf8_private_explicit_and_never_overwrites(store, tmp_path):
    seed(store)
    api = RecoveryController(store)
    target = tmp_path / "selected.txt"
    assert api.save("job-1", target).code is RecoveryCode.OK
    assert target.read_text() == "Private final wörld."
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert str(target) not in json.dumps(api.save("job-1", target).to_dict())
    assert api.save("job-1", target, raw=True).code is RecoveryCode.IO_FAILURE
    assert target.read_text() == "Private final wörld."
    raw = tmp_path / "raw.txt"
    assert api.save("job-1", raw, raw=True).code is RecoveryCode.OK
    assert raw.read_text() == "private raw wörld"
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    assert api.save("job-1", link).code is RecoveryCode.IO_FAILURE
    assert target.read_text() == "Private final wörld."
    assert api.save("job-1", tmp_path / "absent" / "out").code is RecoveryCode.IO_FAILURE


def test_save_failure_keeps_database_and_existing_files_intact(store, tmp_path, monkeypatch):
    import voxflow.recovery as recovery

    seed(store)
    def fail(_fd, _data):
        raise OSError("private path and credential")
    monkeypatch.setattr(recovery.os, "write", fail)
    target = tmp_path / "failed.txt"
    result = RecoveryController(store).save("job-1", target)
    assert result.code is RecoveryCode.IO_FAILURE
    assert not target.exists()
    assert "credential" not in json.dumps(result.to_dict())
    assert store.get_job("job-1").final_text == "Private final wörld."


def test_copy_requires_a_real_copy_method_and_a_completed_transfer(store):
    seed(store)
    adapter = Adapter(store)
    api = RecoveryController(store, inserter=adapter)
    assert asyncio.run(api.copy("job-1", timeout_seconds=1)).code is RecoveryCode.OK
    assert adapter.copies == [("Private final wörld.", 1)]
    assert adapter.calls == []
    adapter.copy = None
    assert asyncio.run(api.copy("job-1")).code is RecoveryCode.UNAVAILABLE

    async def incomplete(*_args, **_kwargs):
        return CopyOutcome(InsertResult.sent, transfer_completed=False)
    adapter.copy = incomplete
    assert asyncio.run(api.copy("job-1")).code is RecoveryCode.IO_FAILURE


def test_retry_persists_guard_and_count_before_delay_and_paste(store):
    seed(store)
    adapter = Adapter(store)
    delays = []
    async def sleep(seconds):
        delays.append(seconds)
        assert store.get_job("job-1").latest_attempt.phase == "ambiguous"
        assert adapter.calls == []
    api = RecoveryController(store, inserter=adapter, sleep=sleep, clock=lambda: "2026-10-19T12:00:00+00:00")
    assert asyncio.run(api.retry("job-1", delay_seconds=2)).code is RecoveryCode.OK
    assert delays == [2]
    assert adapter.calls == ["Private final wörld."]
    assert store.get_job("job-1").status.value == "success"
    assert store.get_job("job-1").retry_count == 1
    assert asyncio.run(api.retry("job-1")).code is RecoveryCode.UNSAFE
    assert len(adapter.calls) == 1


@pytest.mark.parametrize("changes,code", [
    ({"phase": "ambiguous", "side_effect": "unknown_after_side_effect"}, RecoveryCode.AMBIGUOUS),
    ({"chord_sent": True}, RecoveryCode.AMBIGUOUS),
    ({"phase": "completed", "outcome": "sent", "side_effect": "completed"}, RecoveryCode.UNSAFE),
    ({"retryable": False}, RecoveryCode.UNSAFE),
    ({"phase": "prepared"}, RecoveryCode.UNSAFE),
])
def test_retry_rejects_unsafe_and_ambiguous_attempts_without_opening(store, changes, code):
    seed(store)
    store.update_insertion_attempt("job-1-attempt", **changes)
    async def forbidden():
        pytest.fail("unsafe retry opened a portal")
    api = RecoveryController(store, open_inserter=forbidden)
    assert asyncio.run(api.retry("job-1", delay_seconds=0)).code is code
    assert len(store.list_insertion_attempts("job-1")) == 1


def test_unlinked_crash_guard_blocks_retry_even_if_job_still_advertises_retry(store):
    seed(store)
    store.create_insertion_attempt(InsertionAttemptRecord(
        "crash-guard", "job-1", phase="ambiguous", side_effect="unknown_after_side_effect",
    ))
    api = RecoveryController(store, inserter=Adapter(store))
    assert asyncio.run(api.retry("job-1", delay_seconds=0)).code is RecoveryCode.AMBIGUOUS


def test_unexpected_inserter_error_stays_ambiguous_and_redacted(store):
    seed(store)
    adapter = Adapter(store)
    async def fail(*_args, **_kwargs):
        raise RuntimeError("private transcript /home/user token")
    adapter.insert = fail
    result = asyncio.run(RecoveryController(store, inserter=adapter).retry("job-1", delay_seconds=0))
    assert result.code is RecoveryCode.AMBIGUOUS
    record = store.get_job("job-1")
    assert record.latest_attempt.side_effect == "unknown_after_side_effect"
    assert not record.insertion_retryable
    assert "token" not in json.dumps(result.to_dict())


def test_missing_invalid_and_absent_text_have_stable_codes(store, tmp_path):
    api = RecoveryController(store)
    assert api.show("missing").code is RecoveryCode.MISSING
    assert api.show("/private/job-token").code is RecoveryCode.INVALID
    assert api.list(limit=0).code is RecoveryCode.INVALID
    seed(store, raw_text=None, final_text=None)
    assert api.save("job-1", tmp_path / "out").code is RecoveryCode.UNAVAILABLE
    assert asyncio.run(api.copy("job-1")).code is RecoveryCode.UNAVAILABLE
    assert asyncio.run(api.retry("job-1", delay_seconds=float("nan"))).code is RecoveryCode.INVALID
