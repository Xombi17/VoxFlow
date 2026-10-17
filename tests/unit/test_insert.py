import asyncio
import os

import pytest

from voxflow.platform.eis import EisError, KeymapTooLarge, Unavailable
from voxflow.platform.insert import FALLBACK_HINT, Inserter, InsertResult
from voxflow.platform.portals import PortalClientError, PortalErrorCode


class Env:
    """Shared event log across fake portal and fake EIS."""

    def __init__(self, owner="confirm", transfer=True, portal_error=None, eis_error=None,
                 connect_error=None):
        self.log = []
        self.owner = owner  # confirm | silent | refuse
        self.transfer = transfer
        self.portal_error = portal_error
        self.eis_error = eis_error
        self.connect_error = connect_error
        self.received = b""
        self.cb = {}
        self.chord_keycodes = None
        env = self

        class Portal:
            async def subscribe(self, signal, cb):
                env.cb[signal] = cb

            async def connect_to_eis(self):
                env.log.append("connect_eis")
                return 9

            async def set_selection(self, mimes):
                env.log.append("set_selection")
                if env.portal_error:
                    raise env.portal_error
                if env.owner == "confirm":
                    env.cb["SelectionOwnerChanged"](True)
                    env.log.append("owner_confirmed")
                elif env.owner == "refuse":
                    env.cb["SelectionOwnerChanged"](False)

            async def selection_write(self, serial):
                env.log.append("write_fd")
                r, w = os.pipe()
                env.pipe_r = r
                return w

            async def selection_write_done(self, serial, ok):
                env.log.append(("write_done", ok))
                env.received = os.read(env.pipe_r, 4096) if ok else b""
                if ok:
                    os.close(env.pipe_r)

        class Eis:
            def connect(self, fd):
                if env.connect_error:
                    raise env.connect_error

            def keymap_text(self):
                return "km"

            def send_paste_chord(self, keycodes):
                env.log.append("chord")
                env.chord_keycodes = keycodes
                if env.eis_error:
                    raise env.eis_error
                if env.transfer:
                    env.cb["SelectionTransfer"]("text/plain;charset=utf-8", 3)

            def close(self):
                env.log.append("eis_close")

        self.portal = Portal()
        self.eis = Eis

    def inserter(self, **kw):
        async def nosleep(_):
            env_sleeps.append(_)

        env_sleeps = self.sleeps = []
        return Inserter(self.portal, self.eis, lambda text: (111, 222), nosleep,
                        owner_settle_ms=10, transfer_timeout_ms=50, **kw)


def run(env, text="hello wörld", **kw):
    async def go():
        ins = env.inserter(**kw)
        return await ins.insert(text)

    return asyncio.run(go())


def test_sent_sequence_and_utf8_roundtrip() -> None:
    env = Env()
    out = run(env)
    assert out.result is InsertResult.sent and out.fallback_hint is None
    assert env.received == "hello wörld".encode()
    log = env.log
    assert log.index("set_selection") < log.index("owner_confirmed") < log.index("chord")
    assert log.index("chord") < log.index("write_fd") < log.index(("write_done", True))
    assert log.count("set_selection") == 1  # clipboard is not restored
    assert env.chord_keycodes == (111, 222)  # resolver value passed through
    assert env.sleeps == [0.03]  # release settle


def test_settle_fallback_when_owner_never_signalled() -> None:
    env = Env(owner="silent")
    assert run(env).result is InsertResult.sent
    assert env.log.index("set_selection") < env.log.index("chord")


def test_owner_refused_never_sends_chord() -> None:
    env = Env(owner="refuse")
    out = run(env)
    assert out.result is InsertResult.failed and "chord" not in env.log
    assert out.text == "hello wörld" and out.fallback_hint == FALLBACK_HINT


def test_transfer_timeout_is_failed_and_retains_text() -> None:
    env = Env(transfer=False)
    out = run(env)
    assert out.result is InsertResult.failed
    assert out.text == "hello wörld" and out.fallback_hint == FALLBACK_HINT


def test_empty_text_does_not_touch_portal() -> None:
    env = Env()
    out = run(env, "  \n")
    assert out.result is InsertResult.failed and env.log == []


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"portal_error": PortalClientError(PortalErrorCode.PERMISSION_DENIED, "x")}, "denied"),
        ({"portal_error": PortalClientError(PortalErrorCode.CANCELLED, "x")}, "denied"),
        ({"portal_error": PortalClientError(PortalErrorCode.SERVICE_UNAVAILABLE, "x")}, "unavailable"),
        ({"portal_error": PortalClientError(PortalErrorCode.REQUEST_FAILED, "x")}, "failed"),
        ({"connect_error": Unavailable("no libei")}, "unavailable"),
        ({"connect_error": KeymapTooLarge("big")}, "failed"),
        ({"eis_error": EisError("boom")}, "failed"),
    ],
)
def test_error_mappings(kw, expected) -> None:
    out = run(Env(**kw))
    assert out.result.value == expected
    assert out.text == "hello wörld" and out.fallback_hint == FALLBACK_HINT


def test_no_portal_is_unavailable() -> None:
    out = asyncio.run(Inserter(None).insert("hi"))
    assert out.result is InsertResult.unavailable and out.fallback_hint == FALLBACK_HINT


def test_result_values_never_claim_delivery() -> None:
    assert {r.value for r in InsertResult} == {"sent", "denied", "unavailable", "failed"}
