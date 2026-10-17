import asyncio

import pytest

from voxflow.platform.portals import (
    CLIPBOARD_INTERFACE,
    REMOTE_DESKTOP_INTERFACE,
    PortalClientError,
    PortalErrorCode,
    RemoteDesktopPortal,
)

S = "/org/freedesktop/portal/desktop/session/x/s1"


class FakeConn:
    def __init__(self, start=None, fail_on=None) -> None:
        self.log = []
        self.start = start if start is not None else {"clipboard_enabled": True, "restore_token": "tok2"}
        self.fail_on = fail_on or {}
        self.signals = {}
        self.closed = []

    def _maybe_fail(self, method):
        if method in self.fail_on:
            raise self.fail_on[method]

    async def call_request(self, interface, method, signature, *args, token):
        self.log.append((method, args))
        self._maybe_fail(method)
        assert args[-1]["handle_token"] == token
        if method == "CreateSession":
            return {"session_handle": S}
        if method == "Start":
            return self.start
        return {}

    async def call_interface(self, interface, method, signature, *args):
        self.log.append((method, args))
        self._maybe_fail(method)
        return []

    async def call_fd(self, interface, method, signature, *args):
        self.log.append((method, args))
        return 7

    async def subscribe_signal(self, interface, signal, callback):
        self.signals[signal] = callback
        return lambda: self.signals.pop(signal, None)

    async def close_session(self, handle):
        self.closed.append(handle)

    async def close(self):
        self.closed.append("conn")


def make(conn, stored=None):
    saved = []
    p = RemoteDesktopPortal(conn, token_loader=lambda: stored, token_saver=saved.append)
    return p, saved


def run(coro):
    return asyncio.run(coro)


def test_call_order_options_and_token_persisted() -> None:
    conn = FakeConn()
    p, saved = make(conn, stored="tok1")

    async def go():
        await p.open_session()
        await p.connect_to_eis()

    run(go())
    assert [m for m, _ in conn.log] == [
        "CreateSession", "SelectDevices", "RequestClipboard", "Start", "ConnectToEIS",
    ]
    select = conn.log[1][1][1]
    assert select["types"] == 1 and select["persist_mode"] == 2
    assert select["restore_token"] == "tok1"
    assert saved == ["tok2"]


def test_no_stored_token_omits_restore_token_and_same_token_not_rewritten() -> None:
    conn = FakeConn()
    p, saved = make(conn)
    run(p.open_session())
    assert "restore_token" not in conn.log[1][1][1]
    conn2 = FakeConn()
    p2, saved2 = make(conn2, stored="tok2")
    run(p2.open_session())
    assert saved2 == []


def test_cancel_is_denied_and_missing_interface_unavailable() -> None:
    p, _ = make(FakeConn(fail_on={"Start": PortalClientError(PortalErrorCode.CANCELLED, "x")}))
    with pytest.raises(PortalClientError) as e:
        run(p.open_session())
    assert e.value.code is PortalErrorCode.CANCELLED
    p, _ = make(FakeConn(fail_on={"RequestClipboard": RuntimeError("org.freedesktop.DBus.Error.UnknownMethod")}))
    with pytest.raises(PortalClientError) as e:
        run(p.open_session())
    assert e.value.code is PortalErrorCode.SERVICE_UNAVAILABLE


def test_clipboard_not_enabled_is_unavailable() -> None:
    p, _ = make(FakeConn(start={"clipboard_enabled": False}))
    with pytest.raises(PortalClientError) as e:
        run(p.open_session())
    assert e.value.code is PortalErrorCode.SERVICE_UNAVAILABLE


def test_clipboard_methods_and_signals_filtered_by_session() -> None:
    conn = FakeConn()
    p, _ = make(conn)
    got = []

    async def go():
        await p.open_session()
        await p.subscribe("SelectionTransfer", lambda m, s: got.append(("t", m, s)))
        await p.subscribe("SelectionOwnerChanged", lambda o: got.append(("o", o)))
        await p.set_selection(["text/plain;charset=utf-8"])
        assert await p.selection_write(5) == 7
        await p.selection_write_done(5, True)
        conn.signals["SelectionTransfer"]("other", "m", 1)
        conn.signals["SelectionTransfer"](S, "text/plain", 5)
        conn.signals["SelectionOwnerChanged"](S, {"session_is_owner": True})
        await p.close()

    run(go())
    assert got == [("t", "text/plain", 5), ("o", True)]
    names = [m for m, _ in conn.log]
    assert names[-3:] == ["SetSelection", "SelectionWrite", "SelectionWriteDone"]
    assert conn.closed == [S, "conn"]
