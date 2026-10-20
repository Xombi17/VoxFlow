"""Typed, local recovery actions and the explicit ``voxflow recovery`` CLI.

Only show and save expose user text. Retry claims its durable side-effect guard
before opening a portal; copy serves a bounded manual transfer without a chord.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, AsyncIterator

from .core.history import HistoryRecord, HistoryStore, insertion_retry_state, utc_now
from .platform.insert import CopyOutcome, InsertOutcome, InsertResult, InsertSideEffect
from .platform.insert_cli import _open_inserter
from .platform.portals import PortalClientError
from .settings import data_dir


class RecoveryCode(IntEnum):
    OK = 0
    INVALID = 2
    MISSING = 3
    UNAVAILABLE = 4
    UNSAFE = 5
    AMBIGUOUS = 6
    IO_FAILURE = 7


_MESSAGES = {
    RecoveryCode.OK: "Action completed.",
    RecoveryCode.INVALID: "Invalid recovery arguments; see voxflow recovery --help.",
    RecoveryCode.MISSING: "Job not found.",
    RecoveryCode.UNAVAILABLE: "Requested text or desktop capability is unavailable.",
    RecoveryCode.UNSAFE: "Job is not retry-safe; use show or save.",
    RecoveryCode.AMBIGUOUS: "Paste may already have occurred; retry refused. Use show or save.",
    RecoveryCode.IO_FAILURE: "Local I/O or clipboard transfer failed; text remains in history.",
}


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    code: RecoveryCode
    data: dict[str, object] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code.name.lower(), "message": _MESSAGES[self.code], "data": self.data}


class ActionState(StrEnum):
    AVAILABLE = "available"
    NEEDS_USER_ACTION = "needs_user_action"
    UNAVAILABLE = "unavailable"
    UNSAFE = "unsafe"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ActionAvailability:
    state: ActionState

    def to_dict(self) -> dict[str, str]:
        return {"state": self.state.value}


class _Failure(Exception):
    def __init__(self, code: RecoveryCode) -> None:
        self.code = code
        super().__init__(_MESSAGES[code])


OpenInserter = Callable[[], Awaitable[tuple[Any, Callable[[], Awaitable[object]]]]]
_JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        print("voxflow recovery: invalid arguments", file=sys.stderr)
        raise SystemExit(2)


def _duration(value: float, *, allow_zero: bool) -> None:
    if not math.isfinite(value) or value < 0 or value > 120 or (value == 0 and not allow_zero):
        raise _Failure(RecoveryCode.INVALID)


def _timestamp(value: str) -> str | None:
    try:
        return datetime.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        return None


def _failure_result(exc: Exception) -> RecoveryResult:
    if isinstance(exc, _Failure):
        return RecoveryResult(exc.code)
    if isinstance(exc, KeyError):
        return RecoveryResult(RecoveryCode.MISSING)
    return RecoveryResult(RecoveryCode.IO_FAILURE)


class RecoveryController:
    """Provider/GTK-free API over the durable history and insertion boundary.

    A supplied inserter is borrowed. An opener supplies an owned session that
    is closed after the action. Listing never opens or probes desktop resources.
    """

    def __init__(
        self, history: HistoryStore, *, inserter: Any | None = None,
        open_inserter: OpenInserter | None = None,
        clock: Callable[[], str] = utc_now,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        self.history = history
        self.inserter = inserter
        self.open_inserter = open_inserter
        self.clock = clock
        self.sleep = sleep

    def _record(self, job_id: str) -> HistoryRecord:
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise _Failure(RecoveryCode.INVALID)
        return self.history.get_job(job_id)

    def _retry_state(self, record: HistoryRecord) -> str:
        return insertion_retry_state(record, self.history.list_insertion_attempts(record.job_id))

    def _desktop_state(self, method: str) -> ActionState:
        if self.inserter is not None:
            if not callable(getattr(self.inserter, method, None)):
                return ActionState.UNAVAILABLE
            if getattr(self.inserter, "clipboard_available", True) is False:
                return ActionState.UNAVAILABLE
            capability = getattr(self.inserter, "capability", None)
            if method == "insert" and capability is not None and capability.status.value != "available":
                return ActionState.NEEDS_USER_ACTION
            return ActionState.AVAILABLE
        return ActionState.NEEDS_USER_ACTION if self.open_inserter else ActionState.UNAVAILABLE

    def _metadata(self, record: HistoryRecord) -> dict[str, object]:
        retry = self._retry_state(record)
        has_final = record.final_text is not None
        available = ActionState.AVAILABLE
        unavailable = ActionState.UNAVAILABLE
        states = {
            "show": available,
            "save": available if has_final else unavailable,
            "save_raw": available if record.raw_text is not None else unavailable,
            "copy": self._desktop_state("copy") if has_final else unavailable,
            "retry": self._desktop_state("insert") if retry == "safe" else ActionState(retry),
        }
        return {
            "job_id": record.job_id if _JOB_ID.fullmatch(record.job_id) else "redacted",
            "status": record.status.value,
            "created_at": _timestamp(record.created_at),
            "updated_at": _timestamp(record.updated_at),
            "raw_text_length": len(record.raw_text) if record.raw_text is not None else None,
            "final_text_length": len(record.final_text) if has_final else None,
            "retry_count": record.retry_count,
            "audio_retention_state": record.audio_retention_state.value,
            "actions": {name: ActionAvailability(state).to_dict() for name, state in states.items()},
        }

    def list(self, *, limit: int = 100) -> RecoveryResult:
        try:
            if not isinstance(limit, int) or not 1 <= limit <= 1000:
                raise _Failure(RecoveryCode.INVALID)
            jobs = [self._metadata(self.history.get_job(row.job_id))
                    for row in self.history.list_jobs(limit=limit)]
            return RecoveryResult(RecoveryCode.OK, {"jobs": jobs})
        except Exception as exc:
            return _failure_result(exc)

    def show(self, job_id: str) -> RecoveryResult:
        try:
            record = self._record(job_id)
            return RecoveryResult(RecoveryCode.OK, {
                **self._metadata(record), "raw_text": record.raw_text, "final_text": record.final_text,
            })
        except Exception as exc:
            return _failure_result(exc)

    def save(self, job_id: str, path: str | Path, *, raw: bool = False) -> RecoveryResult:
        try:
            record = self._record(job_id)
            text = record.raw_text if raw else record.final_text
            if text is None:
                raise _Failure(RecoveryCode.UNAVAILABLE)
            target = Path(path)
            # Publish a complete, private file with an exclusive hard link. This
            # refuses existing files (including symlinks) without truncating any.
            fd, temporary = tempfile.mkstemp(prefix=".voxflow-export-", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    data = memoryview(text.encode("utf-8"))
                    while data:
                        written = os.write(stream.fileno(), data)
                        if written == 0:
                            raise OSError("export write stalled")
                        data = data[written:]
                    os.fsync(stream.fileno())
                os.link(temporary, target)
            finally:
                os.unlink(temporary)
            return RecoveryResult(RecoveryCode.OK, {"saved": True, "source": "raw" if raw else "final"})
        except Exception as exc:
            return _failure_result(exc)

    def delete(self, job_id: str, artifact_dir: str | Path | None = None) -> RecoveryResult:
        """Explicitly clear one retained artifact without returning its path."""

        try:
            self._record(job_id)
            record = self.history.clear_artifact(job_id, artifact_dir or data_dir() / "captures")
            return RecoveryResult(
                RecoveryCode.OK,
                {
                    "artifact_deleted": record.audio_retention_state.value == "deleted",
                    "audio_retention_state": record.audio_retention_state.value,
                },
            )
        except ValueError as exc:
            del exc
            return RecoveryResult(RecoveryCode.INVALID)
        except Exception as exc:
            return _failure_result(exc)

    clear = delete

    @asynccontextmanager
    async def _adapter(self) -> AsyncIterator[Any]:
        if self.inserter is not None:
            yield self.inserter
            return
        if self.open_inserter is None:
            raise _Failure(RecoveryCode.UNAVAILABLE)
        try:
            adapter, close_portal = await self.open_inserter()
        except PortalClientError:
            raise _Failure(RecoveryCode.UNAVAILABLE) from None
        except Exception:
            # The opener has not handed back a usable session, so no paste
            # chord could have been emitted. Keep this retry-safe.
            raise _Failure(RecoveryCode.UNAVAILABLE) from None
        failed = False
        try:
            yield adapter
        except BaseException:
            failed = True
            raise
        finally:
            cleanup_failed = False
            for close in (getattr(adapter, "close", None), close_portal):
                if not callable(close):
                    continue
                try:
                    result = close()
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    cleanup_failed = True
            if cleanup_failed and not failed:
                raise _Failure(RecoveryCode.IO_FAILURE)

    async def copy(self, job_id: str, *, timeout_seconds: float = 15.0) -> RecoveryResult:
        try:
            _duration(timeout_seconds, allow_zero=False)
            record = self._record(job_id)
            if record.final_text is None or self._desktop_state("copy") is ActionState.UNAVAILABLE:
                raise _Failure(RecoveryCode.UNAVAILABLE)
            async with self._adapter() as adapter:
                copy = getattr(adapter, "copy", None)
                if not callable(copy):
                    raise _Failure(RecoveryCode.UNAVAILABLE)
                outcome = await copy(record.final_text, timeout_seconds=timeout_seconds)
                if not isinstance(outcome, CopyOutcome):
                    raise _Failure(RecoveryCode.IO_FAILURE)
                if outcome.result in {InsertResult.denied, InsertResult.unavailable}:
                    raise _Failure(RecoveryCode.UNAVAILABLE)
                if outcome.result is not InsertResult.sent or not outcome.transfer_completed:
                    raise _Failure(RecoveryCode.IO_FAILURE)
            return RecoveryResult(RecoveryCode.OK, {
                "transfer_completed": True, "clipboard_persistence": "not_guaranteed",
            })
        except Exception as exc:
            return _failure_result(exc)

    async def retry(self, job_id: str, *, delay_seconds: float = 3.0) -> RecoveryResult:
        """Retry one known pre-chord failure, with a database claim first."""

        try:
            _duration(delay_seconds, allow_zero=True)
            record = self._record(job_id)
            attempts = self.history.list_insertion_attempts(job_id)
            latest = attempts[-1] if attempts else None
            if latest is None:
                raise _Failure(RecoveryCode.UNSAFE)
            state = insertion_retry_state(record, attempts)
            if state == "ambiguous":
                raise _Failure(RecoveryCode.AMBIGUOUS)
            if state != "safe":
                raise _Failure(RecoveryCode.UNSAFE)
            attempt_id = uuid.uuid4().hex
            claimed = self.history.claim_insertion_retry(
                job_id, expected_attempt_id=latest.attempt_id,
                attempt_id=attempt_id, timestamp=self.clock(),
            )
            if claimed is None:
                # A second process won the CAS claim or the durable state changed.
                current = self.history.get_job(job_id)
                state = self._retry_state(current)
                raise _Failure(
                    RecoveryCode.AMBIGUOUS if state == "ambiguous" else RecoveryCode.UNSAFE
                )
            async with self._adapter() as adapter:
                await self.sleep(delay_seconds)
                insert = getattr(adapter, "insert", None)
                if not callable(insert):
                    raise _Failure(RecoveryCode.UNAVAILABLE)
                try:
                    parameters = inspect.signature(insert).parameters
                    accepts_attempt_id = "attempt_id" in parameters or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters.values()
                    )
                except (TypeError, ValueError):
                    accepts_attempt_id = False
                call = insert(claimed.final_text or "", attempt_id=attempt_id) if accepts_attempt_id else insert(claimed.final_text or "")
                outcome = await call if inspect.isawaitable(call) else call
                if not isinstance(outcome, InsertOutcome):
                    raise RuntimeError("invalid insertion outcome")
            side_effect = InsertSideEffect(outcome.side_effect)
            events = {str(event.get("event")): event for event in outcome.trace}
            chord_sent = "chord_sent" in events or side_effect is not InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT
            if side_effect is InsertSideEffect.COMPLETED:
                phase, retryable, status = "completed", False, "success"
            elif side_effect is InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT:
                phase, retryable, status = "failed", True, "failed"
            else:
                phase, retryable, status = "ambiguous", False, "failed"
            self.history.update_insertion_attempt(
                attempt_id, expected_phase="ambiguous", phase=phase,
                chord_sent=chord_sent,
                ownership_confirmed=bool(events.get("ownership_confirmed", {}).get("confirmed", False)),
                transfer_completed=bool(events.get("selection_write_done", {}).get("ok", False)),
                outcome=outcome.result.value, side_effect=side_effect.value,
                retryable=retryable, detail=outcome.detail, trace=outcome.trace,
            )
            self.history.update_job(
                job_id, status=status, retryable=retryable,
                retry_code="retry_insertion" if retryable else None,
                error_code=None if outcome.result is InsertResult.sent else f"insertion_{outcome.result.value}",
                failure_reason=None if outcome.result is InsertResult.sent else outcome.detail,
                insertion_attempt_id=attempt_id, insertion_result=outcome.result.value,
                insertion_side_effect=side_effect.value, insertion_retryable=retryable,
                insertion_detail=outcome.detail,
            )
            return RecoveryResult(RecoveryCode.OK, {"result": outcome.result.value})
        except _Failure as exc:
            if "attempt_id" in locals() and self._attempt_is_ambiguous(attempt_id):
                if exc.code is RecoveryCode.UNAVAILABLE:
                    self._record_pre_side_effect_failure(attempt_id, job_id, "unavailable")
            return RecoveryResult(exc.code)
        except PortalClientError:
            # An exception from an already opened adapter is after the durable
            # claim; keep it ambiguous rather than guessing where the chord was.
            return RecoveryResult(RecoveryCode.AMBIGUOUS)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Once claimed, an unknown exception is intentionally ambiguous.
            return RecoveryResult(RecoveryCode.AMBIGUOUS)

    def _attempt_is_ambiguous(self, attempt_id: str) -> bool:
        try:
            return self.history.get_insertion_attempt(attempt_id).phase == "ambiguous"
        except (KeyError, sqlite3.Error):
            return False

    def _record_pre_side_effect_failure(self, attempt_id: str, job_id: str, outcome: str) -> None:
        self.history.update_insertion_attempt(
            attempt_id, expected_phase="ambiguous", phase="failed",
            outcome=outcome, side_effect=InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT.value,
            retryable=True, detail="insertion unavailable",
        )
        self.history.update_job(
            job_id, status="failed", retryable=True, retry_code="retry_insertion",
            error_code=f"insertion_{outcome}", failure_reason="insertion unavailable",
            insertion_result=outcome,
            insertion_side_effect=InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT.value,
            insertion_retryable=True, insertion_detail="insertion unavailable",
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(prog="voxflow recovery")
    def db_option(target: argparse.ArgumentParser, *, suppress: bool = False) -> None:
        target.add_argument(
            "--db", "--db-path", dest="db",
            default=argparse.SUPPRESS if suppress else None,
            help="SQLite history database",
        )

    db_option(parser)
    sub = parser.add_subparsers(dest="action", required=True, parser_class=_SafeArgumentParser)
    listing = sub.add_parser("list")
    db_option(listing, suppress=True)
    listing.add_argument("--limit", type=int, default=100)
    showing = sub.add_parser("show")
    db_option(showing, suppress=True)
    showing.add_argument("job_id")
    saving = sub.add_parser("save")
    db_option(saving, suppress=True)
    saving.add_argument("job_id")
    saving.add_argument("path", type=Path)
    saving.add_argument("--raw", action="store_true")
    copying = sub.add_parser("copy")
    db_option(copying, suppress=True)
    copying.add_argument("job_id")
    copying.add_argument("--wait-seconds", type=float, default=15.0)
    retrying = sub.add_parser("retry")
    db_option(retrying, suppress=True)
    retrying.add_argument("job_id")
    retrying.add_argument("--delay-seconds", type=float, default=3.0)
    deleting = sub.add_parser("delete")
    db_option(deleting, suppress=True)
    deleting.add_argument("job_id")
    deleting.add_argument("--artifact-dir", type=Path, default=None)
    return parser


def main(
    argv: Sequence[str] = (), *,
    open_inserter: OpenInserter = _open_inserter,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        if exc.code == 0:
            raise
        return int(RecoveryCode.INVALID)
    try:
        history = HistoryStore(args.db)
    except (OSError, sqlite3.Error, RuntimeError):
        result = RecoveryResult(RecoveryCode.IO_FAILURE)
    else:
        controller = RecoveryController(history, open_inserter=open_inserter, sleep=sleep)
        if args.action == "list":
            result = controller.list(limit=args.limit)
        elif args.action == "show":
            result = controller.show(args.job_id)
        elif args.action == "save":
            result = controller.save(args.job_id, args.path, raw=args.raw)
        elif args.action == "copy":
            result = asyncio.run(controller.copy(args.job_id, timeout_seconds=args.wait_seconds))
        elif args.action == "retry":
            result = asyncio.run(controller.retry(args.job_id, delay_seconds=args.delay_seconds))
        elif args.action == "delete":
            result = controller.delete(args.job_id, args.artifact_dir)
        else:
            result = RecoveryResult(RecoveryCode.INVALID)
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return int(result.code)


__all__ = ["ActionAvailability", "ActionState", "RecoveryCode", "RecoveryController", "RecoveryResult", "main"]
