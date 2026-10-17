import json

import pytest

from voxflow.platform.insert import InsertOutcome, InsertResult
from voxflow.platform.insert_cli import main
from voxflow.platform.portals import PortalClientError, PortalErrorCode


class FakeInserter:
    def __init__(self, result):
        self.result, self.texts, self.closed = result, [], False

    async def insert(self, text):
        self.texts.append(text)
        hint = None if self.result is InsertResult.sent else "copied — press Ctrl+V"
        return InsertOutcome(self.result, text, hint, "secret-detail")

    def close(self):
        self.closed = True


def opener(ins):
    async def close():
        pass

    async def open_():
        return ins, close

    return open_


def test_help_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0


def test_sent_json_exit_zero_and_default_delay(capsys) -> None:
    ins, delays = FakeInserter(InsertResult.sent), []

    async def sleep(s):
        delays.append(s)

    assert main(["hello wörld"], open_inserter=opener(ins), sleep=sleep) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"result": "sent", "fallback_hint": None}
    assert ins.texts == ["hello wörld"] and delays == [3.0] and ins.closed


def test_non_sent_exit_one_and_custom_delay(capsys) -> None:
    delays = []

    async def sleep(s):
        delays.append(s)

    rc = main(["x", "--delay-seconds", "0"], open_inserter=opener(FakeInserter(InsertResult.failed)), sleep=sleep)
    assert rc == 1 and delays == [0.0]
    assert set(json.loads(capsys.readouterr().out)) == {"result", "fallback_hint"}


def test_session_denied_is_reported(capsys) -> None:
    async def open_():
        raise PortalClientError(PortalErrorCode.CANCELLED, "no")

    assert main(["x"], open_inserter=open_) == 1
    assert json.loads(capsys.readouterr().out)["result"] == "denied"
