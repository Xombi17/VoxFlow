import asyncio
import json
import multiprocessing
import os

import pytest

from tests.unit.test_recovery import seed
from voxflow.core.history import HistoryStore
from voxflow.platform.insert import Inserter, InsertOutcome, InsertResult, InsertSideEffect, MIME
from voxflow.recovery import RecoveryCode, RecoveryController


class ClipboardPortal:
    def __init__(self, transfer=True, write_error=False, owner=True):
        self.callbacks = {}
        self.transfer = transfer
        self.write_error = write_error
        self.owner = owner
        self.received = b""
        self.done = []
        self.removed = []

    async def subscribe(self, name, callback):
        self.callbacks[name] = callback
        return lambda: self.removed.append(name)

    async def set_selection(self, mimes):
        assert mimes == [MIME]
        self.callbacks["SelectionOwnerChanged"](self.owner)
        if self.transfer:
            asyncio.get_running_loop().call_soon(self.callbacks["SelectionTransfer"], MIME, 1)

    async def selection_write(self, _serial):
        if self.write_error:
            raise OSError("private transport /home/user/token")
        self.reader, writer = os.pipe()
        return writer

    async def selection_write_done(self, serial, ok):
        self.done.append((serial, ok))
        if hasattr(self, "reader"):
            self.received = os.read(self.reader, 4096)
            os.close(self.reader)


def test_copy_offers_utf8_until_manual_transfer_without_any_eis_or_chord(tmp_path):
    store = HistoryStore(tmp_path / "jobs.db")
    seed(store)
    portal = ClipboardPortal()
    def forbidden():
        pytest.fail("copy must not create an EIS keyboard")
    adapter = Inserter(portal, eis_factory=forbidden)
    result = asyncio.run(RecoveryController(store, inserter=adapter).copy("job-1", timeout_seconds=0.1))
    assert result.code is RecoveryCode.OK
    assert portal.received == "Private final wörld.".encode()
    assert portal.done == [(1, True)]
    assert set(portal.removed) == {"SelectionTransfer", "SelectionOwnerChanged"}
    assert len(store.list_insertion_attempts("job-1")) == 1


@pytest.mark.parametrize("options", [
    {"transfer": False}, {"write_error": True}, {"owner": False},
])
def test_failed_copy_never_reports_success_and_removes_subscriptions(tmp_path, options):
    store = HistoryStore(tmp_path / "jobs.db")
    seed(store)
    portal = ClipboardPortal(**options)
    adapter = Inserter(portal, owner_settle_ms=1)
    result = asyncio.run(RecoveryController(store, inserter=adapter).copy("job-1", timeout_seconds=0.02))
    assert result.code is RecoveryCode.IO_FAILURE
    assert "private transport" not in json.dumps(result.to_dict())
    assert set(portal.removed) == {"SelectionTransfer", "SelectionOwnerChanged"}
    assert store.get_job("job-1").final_text == "Private final wörld."


def _retry_process(db, ready, release, calls, results):
    store = HistoryStore(db)
    class ProcessInserter:
        async def insert(self, text, *, attempt_id):
            calls.put(attempt_id)
            # Keep the first process inside the side-effect window while the
            # other independently opened store attempts the same retry.
            await asyncio.to_thread(release.wait, 5)
            return InsertOutcome(InsertResult.sent, text, attempt_id=attempt_id,
                                 side_effect=InsertSideEffect.COMPLETED)
    ready.wait(5)
    result = asyncio.run(RecoveryController(store, inserter=ProcessInserter()).retry("job-1", delay_seconds=0))
    results.put(int(result.code))


def test_independent_processes_claim_one_retry_before_side_effect(tmp_path):
    db = tmp_path / "jobs.db"
    store = HistoryStore(db)
    seed(store)
    ctx = multiprocessing.get_context("spawn")
    ready, release = ctx.Barrier(2), ctx.Event()
    calls, results = ctx.Queue(), ctx.Queue()
    processes = [ctx.Process(target=_retry_process, args=(db, ready, release, calls, results)) for _ in range(2)]
    try:
        for process in processes:
            process.start()
        attempt_id = calls.get(timeout=10)
        blocked_code = results.get(timeout=10)
        assert blocked_code in {RecoveryCode.UNSAFE, RecoveryCode.AMBIGUOUS}
        record = store.get_job("job-1")
        assert record.retry_count == 1 and record.insertion_attempt_id == attempt_id
        assert record.latest_attempt.phase == "ambiguous"
        release.set()
        assert results.get(timeout=10) == RecoveryCode.OK
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        assert calls.empty()
        reloaded = HistoryStore(db).get_job("job-1")
        assert reloaded.status.value == "success"
        assert len(store.list_insertion_attempts("job-1")) == 2
    finally:
        release.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(5)


def test_cancelled_retry_keeps_a_nonretryable_guard_after_reload(tmp_path):
    db = tmp_path / "jobs.db"
    store = HistoryStore(db)
    seed(store)
    async def scenario():
        entered = asyncio.Event()
        class Adapter:
            async def insert(self, text, *, attempt_id):
                entered.set()
                await asyncio.Event().wait()
        api = RecoveryController(store, inserter=Adapter())
        task = asyncio.create_task(api.retry("job-1", delay_seconds=0))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return await RecoveryController(HistoryStore(db), inserter=Adapter()).retry("job-1", delay_seconds=0)
    assert asyncio.run(scenario()).code is RecoveryCode.AMBIGUOUS
    assert store.get_job("job-1").retry_count == 1
