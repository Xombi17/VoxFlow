"""Clipboard + libei paste with an honest, typed outcome (D-09, D-10).

Sequence: SetSelection -> owner confirmed (or short settle) -> Ctrl+V chord ->
serve the target's SelectionTransfer -> report ``sent`` only after
SelectionWriteDone.  ``sent`` means the target read our bytes, not that the
text is where the user wanted it, so callers must still tell the user to look.
Terminal Ctrl+Shift+V is a known limitation (D-11); no focused-app detection.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .eis import EisError, EisKeyboard, Unavailable, resolve_keycodes
from .portals import PortalClientError, PortalErrorCode

MIME = "text/plain;charset=utf-8"
FALLBACK_HINT = "copied — press Ctrl+V"


class InsertResult(StrEnum):
    sent = "sent"
    denied = "denied"
    unavailable = "unavailable"
    failed = "failed"


@dataclass(frozen=True, slots=True)
class InsertOutcome:
    result: InsertResult
    text: str
    fallback_hint: str | None = None
    detail: str = ""


class _Fail(Exception):
    def __init__(self, result: InsertResult, detail: str) -> None:
        self.result, self.detail = result, detail


def result_for_portal_error(exc: PortalClientError) -> InsertResult:
    if exc.code in (PortalErrorCode.CANCELLED, PortalErrorCode.PERMISSION_DENIED):
        return InsertResult.denied
    if exc.code is PortalErrorCode.SERVICE_UNAVAILABLE:
        return InsertResult.unavailable
    return InsertResult.failed


def _write_all(fd: int, data: bytes) -> None:
    # ponytail: blocking write; fine for dictation-sized text (< pipe buffer).
    # Move to a thread/non-blocking write if long pastes ever stall the loop.
    with os.fdopen(fd, "wb", closefd=True) as f:
        f.write(data)


class Inserter:
    def __init__(
        self,
        portal: Any | None,
        eis_factory: Callable[[], EisKeyboard] = EisKeyboard,
        resolver: Callable[[str], tuple[int, int]] = resolve_keycodes,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
        *,
        owner_settle_ms: int = 50,
        release_settle_ms: int = 30,
        transfer_timeout_ms: int = 2000,
    ) -> None:
        self._portal = portal
        self._eis_factory = eis_factory
        self._resolver = resolver
        self._sleep = sleep
        self.owner_settle_ms = owner_settle_ms
        self.release_settle_ms = release_settle_ms
        self.transfer_timeout_ms = transfer_timeout_ms
        self._eis: EisKeyboard | None = None
        self._keycodes: tuple[int, int] | None = None
        self._owner: bool | None = None
        self._owner_event = asyncio.Event()
        self._transfers: asyncio.Queue[tuple[str, int]] = asyncio.Queue()

    async def _start(self) -> None:
        portal = self._portal
        await portal.subscribe("SelectionOwnerChanged", self._on_owner)
        await portal.subscribe("SelectionTransfer", self._on_transfer)
        eis = self._eis_factory()
        try:
            eis.connect(await portal.connect_to_eis())
            self._keycodes = self._resolver(eis.keymap_text())
        except BaseException:
            eis.close()
            raise
        self._eis = eis

    def _on_owner(self, is_owner: bool) -> None:
        self._owner = is_owner
        self._owner_event.set()

    def _on_transfer(self, mime: str, serial: int) -> None:
        self._transfers.put_nowait((mime, serial))

    async def insert(self, text: str) -> InsertOutcome:
        if not text.strip():
            return InsertOutcome(InsertResult.failed, text, None, "empty text")
        try:
            if self._portal is None:
                raise _Fail(InsertResult.unavailable, "no portal session")
            if self._eis is None:
                await self._start()
            await self._paste(text)
        except _Fail as exc:
            return self._bad(exc.result, text, exc.detail)
        except PortalClientError as exc:
            return self._bad(result_for_portal_error(exc), text, exc.code.value)
        except Unavailable as exc:
            return self._bad(InsertResult.unavailable, text, str(exc))
        except EisError as exc:
            return self._bad(InsertResult.failed, text, str(exc))
        except Exception as exc:  # never crash the daemon on an insert
            return self._bad(InsertResult.failed, text, type(exc).__name__)
        return InsertOutcome(InsertResult.sent, text)

    @staticmethod
    def _bad(result: InsertResult, text: str, detail: str) -> InsertOutcome:
        return InsertOutcome(result, text, FALLBACK_HINT, detail)

    async def _paste(self, text: str) -> None:
        portal = self._portal
        self._owner, self._transfers = None, asyncio.Queue()
        self._owner_event.clear()
        await portal.set_selection([MIME])
        try:
            await asyncio.wait_for(self._owner_event.wait(), self.owner_settle_ms / 1000)
        except TimeoutError:
            pass  # portal may never emit it: the settle window above stands in
        if self._owner is False:
            raise _Fail(InsertResult.failed, "clipboard ownership not granted")
        await self._sleep(self.release_settle_ms / 1000)
        assert self._eis is not None and self._keycodes is not None
        self._eis.send_paste_chord(self._keycodes)
        data = text.encode("utf-8")
        deadline = asyncio.get_running_loop().time() + self.transfer_timeout_ms / 1000
        while True:
            left = deadline - asyncio.get_running_loop().time()
            try:
                mime, serial = await asyncio.wait_for(self._transfers.get(), max(left, 0))
            except TimeoutError:
                raise _Fail(InsertResult.failed, "target never requested the text") from None
            if mime != MIME and not mime.startswith("text/plain"):
                await portal.selection_write_done(serial, False)
                continue
            ok = False
            try:
                _write_all(await portal.selection_write(serial), data)
                ok = True
            finally:
                await portal.selection_write_done(serial, ok)
            return

    def close(self) -> None:
        if self._eis is not None:
            self._eis.close()
            self._eis = None
