import asyncio
import os

import pytest

from voxflow.platform.eis import EisError, KeymapTooLarge, Unavailable
from voxflow.core.capabilities import CapabilityStatus
from voxflow.platform.insert import (
    FALLBACK_HINT,
    Inserter,
    InsertResult,
    InsertSideEffect,
    normalize_chord,
)
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
        self.callbacks = {"SelectionOwnerChanged": [], "SelectionTransfer": []}
        self.late_transfer = None
        self.write_serials = []
        self.chord_keycodes = None
        env = self

        class Portal:
            async def subscribe(self, signal, cb):
                env.cb[signal] = cb
                env.callbacks[signal].append(cb)

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
                env.write_serials.append(serial)
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
                    if env.late_transfer is not None:
                        env.late_transfer("text/plain;charset=utf-8", 99)
                    env.cb["SelectionTransfer"]("text/plain;charset=utf-8", 3)

            def close(self):
                env.log.append("eis_close")

        self.portal = Portal()
        self.eis = Eis

    def inserter(self, **kw):
        async def nosleep(_):
            env_sleeps.append(_)

        env_sleeps = self.sleeps = []
        resolver = kw.pop("resolver", lambda _text: (111, 222))
        return Inserter(self.portal, self.eis, resolver, nosleep,
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
    assert out.side_effect is InsertSideEffect.UNKNOWN_AFTER_SIDE_EFFECT
    assert out.retryable is False


def test_late_transfer_from_timed_out_attempt_cannot_satisfy_retry() -> None:
    async def scenario():
        env = Env(transfer=False)
        inserter = env.inserter()
        first = await inserter.insert("first")
        old_transfer = env.callbacks["SelectionTransfer"][0]
        env.late_transfer = old_transfer
        env.transfer = True
        second = await inserter.insert("second")
        return first, second, env.write_serials

    first, second, serials = asyncio.run(scenario())

    assert first.side_effect is InsertSideEffect.UNKNOWN_AFTER_SIDE_EFFECT
    assert first.retryable is False
    assert second.result is InsertResult.sent
    assert serials == [3]


def test_pre_chord_failure_is_retryable_and_trace_is_redacted() -> None:
    secret = "transcript secret /home/private/restore-token"
    out = run(Env(owner="refuse"), text=secret)

    assert out.result is InsertResult.failed
    assert out.side_effect is InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT
    assert out.retryable is True
    assert [event["event"] for event in out.trace] == [
        "attempt_started",
        "selection_set",
        "ownership_confirmed",
        "outcome_recorded",
    ]
    assert out.attempt_id
    assert all(event["attempt_id"] == out.attempt_id for event in out.trace)
    assert secret not in repr(out.trace)
    assert "restore-token" not in repr(out.trace)


def test_success_trace_marks_the_side_effect_boundary() -> None:
    out = run(Env())

    assert [event["event"] for event in out.trace] == [
        "attempt_started",
        "selection_set",
        "ownership_confirmed",
        "release_settled",
        "chord_sent",
        "transfer_received",
        "selection_write_done",
        "outcome_recorded",
    ]
    assert out.trace[4]["key_count"] == 2
    assert out.side_effect is InsertSideEffect.COMPLETED


def test_concurrent_insertions_are_serialized() -> None:
    async def scenario():
        env = Env()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocking_sleep(_seconds):
            entered.set()
            await release.wait()

        inserter = Inserter(
            env.portal,
            env.eis,
            lambda _keymap: (111, 222),
            blocking_sleep,
            owner_settle_ms=10,
            transfer_timeout_ms=50,
        )
        first = asyncio.create_task(inserter.insert("first"))
        await entered.wait()
        second = asyncio.create_task(inserter.insert("second"))
        await asyncio.sleep(0)
        assert not second.done()
        release.set()
        return await asyncio.gather(first, second)

    first, second = asyncio.run(scenario())
    assert first.result is InsertResult.sent
    assert second.result is InsertResult.sent
    assert first.attempt_id != second.attempt_id


def test_setup_failure_cleans_eis_and_portal_session() -> None:
    events = []

    class Portal:
        async def subscribe(self, signal, _callback):
            return lambda: events.append(f"unsubscribe:{signal}")

        async def connect_to_eis(self):
            return 9

        async def close(self):
            events.append("portal-close")

    class BadEis:
        def connect(self, _fd):
            raise EisError("private EIS detail")

        def close(self):
            events.append("eis-close")

    out = asyncio.run(
        Inserter(
            Portal(),
            BadEis,
            lambda _keymap: (111, 222),
        ).insert("hello")
    )

    assert out.result is InsertResult.failed
    assert "eis-close" in events
    assert "portal-close" in events


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
    assert out.retryable is True


def test_configured_ctrl_shift_v_uses_a_key_sequence_without_typing() -> None:
    env = Env()
    assert normalize_chord("Ctrl+Shift+V") == ("Control_L", "Shift_L", "v")
    out = run(
        env,
        chord="Ctrl+Shift+V",
        resolver=lambda _keymap: (111, 222, 333),
    )

    assert out.result is InsertResult.sent
    assert env.chord_keycodes == (111, 222, 333)
    assert out.trace[4]["key_count"] == 3


def test_inserter_capability_waits_for_eis_and_keymap_readiness() -> None:
    async def scenario():
        env = Env()
        inserter = env.inserter()
        before = inserter.capability
        outcome = await inserter.insert("hello")
        after = inserter.capability
        await inserter.close()
        return before, after, outcome

    before, after, outcome = asyncio.run(scenario())

    assert before.status is CapabilityStatus.UNAVAILABLE
    assert after.status is CapabilityStatus.AVAILABLE
    assert outcome.result is InsertResult.sent


def test_inserter_close_waits_for_active_insert_lock() -> None:
    async def scenario():
        env = Env()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocking_sleep(_seconds):
            entered.set()
            await release.wait()

        inserter = Inserter(
            env.portal,
            env.eis,
            lambda _keymap: (111, 222),
            blocking_sleep,
            owner_settle_ms=10,
            transfer_timeout_ms=50,
        )
        insert_task = asyncio.create_task(inserter.insert("hello"))
        await entered.wait()
        close_task = inserter.close()
        assert close_task is not None and not close_task.done()
        release.set()
        outcome = await insert_task
        await close_task
        return outcome, env.log

    outcome, log = asyncio.run(scenario())

    assert outcome.result is InsertResult.sent
    assert log.index("eis_close") > log.index(("write_done", True))


def test_inserter_rollback_does_not_mask_cancellation_from_cleanup() -> None:
    class Portal:
        async def subscribe(self, _signal, _callback):
            return None

        async def connect_to_eis(self):
            return 9

        async def close(self):
            raise asyncio.CancelledError()

    class Eis:
        def connect(self, _fd):
            raise EisError("connect failed")

        def close(self):
            pass

    outcome = asyncio.run(Inserter(Portal(), Eis).insert("hello"))

    assert outcome.result is InsertResult.failed


def test_inserter_rollback_preserves_original_cancellation() -> None:
    class Portal:
        async def connect_to_eis(self):
            return 9

        async def close(self):
            raise asyncio.CancelledError()

    class Eis:
        def connect(self, _fd):
            raise asyncio.CancelledError()

        def close(self):
            pass

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(Inserter(Portal(), Eis).insert("hello"))


def test_result_values_never_claim_delivery() -> None:
    assert {r.value for r in InsertResult} == {"sent", "denied", "unavailable", "failed"}
