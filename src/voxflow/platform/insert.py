"""Clipboard + libei paste with an honest, typed outcome (D-09, D-10).

Sequence: SetSelection -> owner confirmed (or short settle) -> Ctrl+V chord ->
serve the target's SelectionTransfer -> report ``sent`` only after
SelectionWriteDone.  ``sent`` means the target read our bytes, not that the
text is where the user wanted it, so callers must still tell the user to look.
Terminal Ctrl+Shift+V is a known limitation (D-11); no focused-app detection.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Sequence

from ..core.capabilities import CapabilityRecord, CapabilityStatus
from .eis import EisError, EisKeyboard, Unavailable, resolve_keycodes
from .portals import PortalClientError, PortalErrorCode

MIME = "text/plain;charset=utf-8"
FALLBACK_HINT = "text retained — save or retry insertion"
DEFAULT_CHORD = ("Control_L", "v")
PENDING_CAPABILITY_REASON = (
    "EIS keyboard and compositor keymap readiness has not been verified."
)


class InsertResult(StrEnum):
    sent = "sent"
    denied = "denied"
    unavailable = "unavailable"
    failed = "failed"


class InsertSideEffect(StrEnum):
    """Classification at the paste-chord side-effect boundary."""

    FAILED_BEFORE_SIDE_EFFECT = "failed_before_side_effect"
    UNKNOWN_AFTER_SIDE_EFFECT = "unknown_after_side_effect"
    COMPLETED = "completed"


# Descriptive alias for callers that prefer the longer contract name.
InsertSideEffectClassification = InsertSideEffect


@dataclass(frozen=True, slots=True)
class InsertOutcome:
    result: InsertResult
    text: str
    fallback_hint: str | None = None
    detail: str = ""
    attempt_id: str = ""
    trace: tuple[dict[str, object], ...] = ()
    side_effect: InsertSideEffect | str = InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT
    retryable: bool = False

    @property
    def attempt_trace(self) -> tuple[dict[str, object], ...]:
        """Compatibility/readability alias for the redacted trace."""

        return self.trace

    @property
    def side_effect_classification(self) -> InsertSideEffect:
        return InsertSideEffect(self.side_effect)


@dataclass(frozen=True, slots=True)
class CopyOutcome:
    """A clipboard-only transfer, with no keyboard side effect or text payload."""

    result: InsertResult
    transfer_completed: bool = False


class _Fail(Exception):
    def __init__(self, result: InsertResult, detail: str) -> None:
        self.result, self.detail = result, detail


def normalize_chord(chord: str | Sequence[str]) -> tuple[str, ...]:
    """Normalize a configured key-name chord without introducing text typing."""

    if isinstance(chord, str):
        names = tuple(part.strip() for part in chord.split("+") if part.strip())
    else:
        names = tuple(str(part).strip() for part in chord if str(part).strip())
    aliases = {
        "ctrl": "Control_L",
        "control": "Control_L",
        "control_l": "Control_L",
        "control_r": "Control_R",
        "shift": "Shift_L",
        "shift_l": "Shift_L",
        "shift_r": "Shift_R",
    }
    normalized = tuple(
        aliases.get(name.casefold(), name.lower() if len(name) == 1 and name.isascii() else name)
        for name in names
    )
    if not normalized:
        raise ValueError("configured chord must contain at least one key")
    return normalized


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


async def _write_nonblocking(fd: int, data: bytes) -> None:
    """Allow a bounded clipboard offer to time out even if its reader stalls."""

    loop = asyncio.get_running_loop()
    try:
        os.set_blocking(fd, False)
        remaining = memoryview(data)
        while remaining:
            try:
                written = os.write(fd, remaining)
                if written == 0:
                    raise OSError("clipboard write stalled")
                remaining = remaining[written:]
            except BlockingIOError:
                ready = loop.create_future()
                def writable() -> None:
                    if not ready.done():
                        ready.set_result(None)
                loop.add_writer(fd, writable)
                try:
                    await ready
                finally:
                    loop.remove_writer(fd)
    finally:
        os.close(fd)


class Inserter:
    def __init__(
        self,
        portal: Any | None,
        eis_factory: Callable[[], EisKeyboard] = EisKeyboard,
        resolver: Callable[..., Sequence[int]] = resolve_keycodes,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
        *,
        owner_settle_ms: int = 50,
        release_settle_ms: int = 30,
        transfer_timeout_ms: int = 2000,
        chord: str | Sequence[str] = DEFAULT_CHORD,
    ) -> None:
        self._portal = portal
        self._eis_factory = eis_factory
        self._resolver = resolver
        self._sleep = sleep
        self.owner_settle_ms = owner_settle_ms
        self.release_settle_ms = release_settle_ms
        self.transfer_timeout_ms = transfer_timeout_ms
        self.chord = normalize_chord(chord)
        self._eis: EisKeyboard | None = None
        self._keycodes: tuple[int, ...] | None = None
        self._owner: bool | None = None
        self._owner_event = asyncio.Event()
        self._transfers: asyncio.Queue[tuple[int, str, int]] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._generation = 0
        self._active_generation: int | None = None
        self._attempt_id = ""
        self._attempt_started = 0.0
        self._trace: list[dict[str, object]] = []
        self._side_effect_started = False
        self._owner_confirmed = False
        self._capability = CapabilityRecord(
            id="insertion.portal",
            status=CapabilityStatus.UNAVAILABLE,
            reason=PENDING_CAPABILITY_REASON,
        )

    @property
    def capability(self) -> CapabilityRecord:
        """The latest insertion readiness known by this adapter."""

        return self._capability

    @property
    def clipboard_available(self) -> bool:
        """A session was supplied; actual copy still requires a completed transfer."""

        return self._portal is not None

    def _mark_eis_ready(self) -> None:
        self._capability = CapabilityRecord(
            id="insertion.portal",
            status=CapabilityStatus.AVAILABLE,
            reason="RemoteDesktop, Clipboard, EIS, and the compositor keymap are ready.",
        )
        mark_ready = getattr(self._portal, "mark_eis_ready", None)
        if callable(mark_ready):
            mark_ready()

    def _mark_eis_unavailable(self) -> None:
        self._capability = CapabilityRecord(
            id="insertion.portal",
            status=CapabilityStatus.UNAVAILABLE,
            reason="EIS keyboard or compositor keymap readiness failed; retry insertion.",
        )
        mark_unavailable = getattr(self._portal, "mark_eis_unavailable", None)
        if callable(mark_unavailable):
            mark_unavailable()

    def _trace_event(self, event: str, **status: object) -> None:
        """Append only safe, structured metadata to the current attempt trace."""

        safe_status = {
            key: value
            for key, value in status.items()
            if isinstance(value, (bool, int, float, str))
        }
        self._trace.append(
            {
                "attempt_id": self._attempt_id,
                "event": event,
                "elapsed_ms": max(0, int((time.monotonic() - self._attempt_started) * 1000)),
                **safe_status,
            }
        )

    def _begin_attempt(self, attempt_id: str | None = None) -> None:
        self._attempt_id = attempt_id or uuid.uuid4().hex
        self._attempt_started = time.monotonic()
        self._trace = []
        self._side_effect_started = False
        self._owner_confirmed = False
        self._trace_event("attempt_started")

    def _safe_detail(self, detail: str, *, error: BaseException | None = None) -> str:
        if isinstance(error, PortalClientError):
            return error.code.value
        if isinstance(error, Unavailable):
            return "unavailable"
        if isinstance(error, EisError):
            return "eis_error"
        return detail if detail in {"empty text", "no portal session", "clipboard ownership not granted", "target never requested the text"} else type(error).__name__ if error is not None else detail

    def _record(
        self,
        result: InsertResult,
        text: str,
        detail: str = "",
        *,
        side_effect: InsertSideEffect | None = None,
        retryable: bool | None = None,
        error: BaseException | None = None,
    ) -> InsertOutcome:
        classification = side_effect or (
            InsertSideEffect.UNKNOWN_AFTER_SIDE_EFFECT
            if self._side_effect_started
            else InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT
        )
        can_retry = (
            classification is InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT
            if retryable is None
            else retryable
        )
        safe_detail = self._safe_detail(detail, error=error)
        self._trace_event(
            "outcome_recorded",
            result=result.value,
            side_effect=classification.value,
            retryable=can_retry,
        )
        return InsertOutcome(
            result,
            text,
            None if result is InsertResult.sent else FALLBACK_HINT,
            safe_detail,
            self._attempt_id,
            tuple(dict(item) for item in self._trace),
            classification,
            can_retry,
        )

    async def _start(self) -> None:
        portal = self._portal
        eis = self._eis_factory()
        try:
            eis.connect(await portal.connect_to_eis())
            if self._resolver is resolve_keycodes:
                self._keycodes = tuple(
                    resolve_keycodes(eis.keymap_text(), names=self.chord)
                )
            else:
                self._keycodes = tuple(self._resolver(eis.keymap_text()))
            if len(self._keycodes) != len(self.chord):
                raise EisError("configured chord key count does not match resolver output")
        except BaseException:
            self._mark_eis_unavailable()
            try:
                eis.close()
            except BaseException:
                pass
            close_portal = getattr(portal, "close", None)
            if callable(close_portal):
                try:
                    result = close_portal()
                    if inspect.isawaitable(result):
                        await result
                except BaseException:
                    pass
            raise
        self._eis = eis
        self._mark_eis_ready()

    def _on_owner(self, generation: int, is_owner: bool) -> None:
        if generation != self._active_generation:
            return
        self._owner = is_owner
        self._owner_confirmed = bool(is_owner)
        self._trace_event("ownership_confirmed", confirmed=bool(is_owner))
        self._owner_event.set()

    def _on_transfer(self, generation: int, mime: str, serial: int) -> None:
        if generation != self._active_generation:
            return
        self._transfers.put_nowait((generation, mime, serial))

    def _drain_transfers(self) -> None:
        while True:
            try:
                self._transfers.get_nowait()
            except asyncio.QueueEmpty:
                return

    async def insert(self, text: str, *, attempt_id: str | None = None) -> InsertOutcome:
        async with self._lock:
            self._begin_attempt(attempt_id)
            if not text.strip():
                return self._record(
                    InsertResult.failed,
                    text,
                    "empty text",
                    retryable=False,
                )
            try:
                if self._portal is None:
                    raise _Fail(InsertResult.unavailable, "no portal session")
                if self._eis is None:
                    await self._start()
                await self._paste(text)
            except _Fail as exc:
                return self._record(exc.result, text, exc.detail)
            except PortalClientError as exc:
                return self._record(
                    result_for_portal_error(exc), text, exc.code.value, error=exc
                )
            except Unavailable as exc:
                return self._record(InsertResult.unavailable, text, error=exc)
            except EisError as exc:
                return self._record(InsertResult.failed, text, error=exc)
            except Exception as exc:  # never crash the daemon on an insert
                return self._record(InsertResult.failed, text, error=exc)
            return self._record(
                InsertResult.sent,
                text,
                side_effect=InsertSideEffect.COMPLETED,
                retryable=False,
            )

    async def copy(self, text: str, *, timeout_seconds: float = 15.0) -> CopyOutcome:
        """Offer text until one manual transfer completes, then release callbacks.

        An ephemeral CLI cannot promise clipboard persistence after exit. A
        selection offer alone is therefore never reported as a successful copy.
        EIS is neither initialized nor called on this path.
        """

        async with self._lock:
            self._begin_attempt()
            if not text.strip() or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
                return CopyOutcome(InsertResult.failed)
            if self._portal is None:
                return CopyOutcome(InsertResult.unavailable)
            try:
                await asyncio.wait_for(
                    self._paste(text, paste=False, timeout_seconds=timeout_seconds),
                    timeout=timeout_seconds,
                )
            except _Fail as exc:
                return CopyOutcome(exc.result)
            except PortalClientError as exc:
                return CopyOutcome(result_for_portal_error(exc))
            except Exception:
                return CopyOutcome(InsertResult.failed)
            return CopyOutcome(InsertResult.sent, transfer_completed=True)

    async def _paste(
        self, text: str, *, paste: bool = True, timeout_seconds: float | None = None,
    ) -> None:
        portal = self._portal
        self._generation += 1
        generation = self._generation
        self._active_generation = generation
        self._owner, self._transfers = None, asyncio.Queue()
        self._owner_event.clear()
        subscriptions: list[Callable[[], object]] = []
        try:
            for signal, callback in (
                (
                    "SelectionOwnerChanged",
                    lambda is_owner, generation=generation: self._on_owner(
                        generation, is_owner
                    ),
                ),
                (
                    "SelectionTransfer",
                    lambda mime, serial, generation=generation: self._on_transfer(
                        generation, mime, serial
                    ),
                ),
            ):
                unsubscribe = await portal.subscribe(signal, callback)
                if callable(unsubscribe):
                    subscriptions.append(unsubscribe)
            self._trace_event("selection_set", mime_count=1)
            await portal.set_selection([MIME])
            try:
                await asyncio.wait_for(self._owner_event.wait(), self.owner_settle_ms / 1000)
            except TimeoutError:
                pass  # portal may never emit it: the settle window above stands in
            if self._owner is False:
                raise _Fail(InsertResult.failed, "clipboard ownership not granted")
            if paste:
                await self._sleep(self.release_settle_ms / 1000)
                self._trace_event("release_settled")
                assert self._eis is not None and self._keycodes is not None
                self._side_effect_started = True
                self._trace_event("chord_sent", emitted=True, key_count=len(self._keycodes))
                sender = getattr(self._eis, "send_chord", None)
                if callable(sender):
                    sender(self._keycodes)
                else:
                    self._eis.send_paste_chord(self._keycodes)
            data = text.encode("utf-8")
            deadline = asyncio.get_running_loop().time() + (
                self.transfer_timeout_ms / 1000 if timeout_seconds is None else timeout_seconds
            )
            while True:
                left = deadline - asyncio.get_running_loop().time()
                try:
                    event_generation, mime, serial = await asyncio.wait_for(
                        self._transfers.get(), max(left, 0)
                    )
                except TimeoutError:
                    raise _Fail(InsertResult.failed, "target never requested the text") from None
                if event_generation != generation:
                    continue
                if not paste and self._owner is False:
                    raise _Fail(InsertResult.failed, "clipboard ownership not granted")
                if mime != MIME and not mime.startswith("text/plain"):
                    await portal.selection_write_done(serial, False)
                    continue
                self._trace_event("transfer_received", accepted=True)
                ok = False
                try:
                    fd = await portal.selection_write(serial)
                    if paste:
                        _write_all(fd, data)
                    else:
                        await _write_nonblocking(fd, data)
                    ok = True
                finally:
                    if paste:
                        await portal.selection_write_done(serial, ok)
                    else:
                        await asyncio.wait_for(portal.selection_write_done(serial, ok), 1.0)
                    self._trace_event("selection_write_done", ok=ok)
                return
        finally:
            if self._active_generation == generation:
                self._active_generation = None
            self._drain_transfers()
            for unsubscribe in reversed(subscriptions):
                try:
                    unsubscribe()
                except BaseException:
                    pass

    async def _close(self) -> None:
        """Close the EIS adapter only after any insertion attempt has finished."""

        async with self._lock:
            eis, self._eis = self._eis, None
            self._keycodes = None
            self._active_generation = None
            self._drain_transfers()
            self._capability = CapabilityRecord(
                id="insertion.portal",
                status=CapabilityStatus.UNAVAILABLE,
                reason=PENDING_CAPABILITY_REASON,
            )
            if eis is not None:
                try:
                    eis.close()
                except BaseException:
                    pass

    def close(self) -> asyncio.Task[None] | None:
        """Close safely while retaining the former synchronous call shape.

        In an async caller the returned task can be awaited.  A synchronous
        caller still gets a completed close, while the lock coordinates with
        any insertion already running on that event loop.
        """

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._close())
            return None
        return loop.create_task(self._close())
