import asyncio
import json

import pytest

from tests.unit.test_recovery import Adapter, seed
from voxflow.__main__ import SUBCOMMANDS, main as dispatch
from voxflow.core.history import HistoryStore
from voxflow.platform.portals import PortalClientError, PortalErrorCode
from voxflow.recovery import RecoveryCode, main


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "jobs.db"
    seed(HistoryStore(path))
    return path


def test_allowlisted_dispatch_list_show_save_and_explicit_database(db, tmp_path, capsys):
    assert SUBCOMMANDS["recovery"] == ("voxflow.recovery", "main")
    assert dispatch(["recovery", "--db", str(db), "list"]) == 0
    listed = capsys.readouterr().out
    assert "private raw" not in listed and "Private final" not in listed
    row = json.loads(listed)["data"]["jobs"][0]
    assert row["actions"]["copy"]["state"] == "needs_user_action"
    assert main(["show", "job-1", "--db-path", str(db)]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["raw_text"] == "private raw wörld"
    target = tmp_path / "export.txt"
    assert main(["--db", str(db), "save", "job-1", str(target), "--raw"]) == 0
    assert target.read_text() == "private raw wörld"
    assert str(target) not in capsys.readouterr().out


def test_copy_and_retry_open_lazily_delay_and_close_both_resources(db, capsys):
    adapter = Adapter(HistoryStore(db))
    events = []
    async def close_portal():
        events.append("portal-close")
    async def close_adapter():
        events.append("adapter-close")
    adapter.close = close_adapter
    async def open_():
        events.append("open")
        return adapter, close_portal
    async def sleep(seconds):
        events.append(("delay", seconds))
    assert main(["--db", str(db), "copy", "job-1", "--wait-seconds", "1"], open_inserter=open_) == 0
    assert events == ["open", "adapter-close", "portal-close"]
    assert "transfer" in capsys.readouterr().out
    events.clear()
    assert main(["--db", str(db), "retry", "job-1", "--delay-seconds", "2"], open_inserter=open_, sleep=sleep) == 0
    assert events == ["open", ("delay", 2.0), "adapter-close", "portal-close"]
    assert adapter.calls == ["Private final wörld."]
    assert "Private final" not in capsys.readouterr().out
    assert main(["--db", str(db), "retry", "job-1"], open_inserter=open_, sleep=sleep) == RecoveryCode.UNSAFE
    assert events.count("open") == 1


@pytest.mark.parametrize("command", ["copy", "retry"])
def test_denied_portal_and_cleanup_errors_are_redacted(db, capsys, command):
    async def denied():
        raise PortalClientError(PortalErrorCode.PERMISSION_DENIED, "private path secret-token")
    assert main(["--db", str(db), command, "job-1"], open_inserter=denied) == RecoveryCode.UNAVAILABLE
    assert "secret-token" not in capsys.readouterr().out
    if command == "retry":
        record = HistoryStore(db).get_job("job-1")
        assert record.retry_count == 1
        assert record.latest_attempt.phase == "failed" and record.latest_attempt.retryable


@pytest.mark.parametrize("args", [
    [], ["no-such-action"], ["show"], ["show", "/private/secret-token"],
    ["retry", "job-1", "--force"], ["list", "--limit", "0"],
    ["retry", "job-1", "--delay-seconds", "nan"],
    ["retry", "job-1", "--delay-seconds", "-1"],
    ["copy", "job-1", "--wait-seconds", "inf"],
    ["copy", "job-1", "--wait-seconds", "0"],
    ["copy", "job-1", "--wait-seconds", "private-token"],
])
def test_invalid_arguments_do_not_echo_user_input(db, args, capsys):
    assert main(["--db", str(db), *args]) == RecoveryCode.INVALID
    output = capsys.readouterr()
    assert "/private/" not in output.out + output.err
    assert "secret-token" not in output.out + output.err
    assert "private-token" not in output.out + output.err


def test_help_and_missing_and_io_failures(db, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    capsys.readouterr()
    assert main(["show", "absent", "--db", str(db)]) == RecoveryCode.MISSING
    assert main(["list", "--db", str(tmp_path)]) == RecoveryCode.IO_FAILURE
    output = capsys.readouterr().out
    assert str(tmp_path) not in output


def test_cleanup_runs_even_when_first_close_raises(db, capsys):
    adapter = Adapter(HistoryStore(db))
    events = []
    def close_adapter():
        raise OSError("private close detail")
    adapter.close = close_adapter
    async def close_portal():
        events.append("portal-close")
    async def open_():
        return adapter, close_portal
    assert main(["copy", "job-1", "--db", str(db), "--wait-seconds", "1"], open_inserter=open_) == RecoveryCode.IO_FAILURE
    assert events == ["portal-close"]
    assert "private close" not in capsys.readouterr().out
