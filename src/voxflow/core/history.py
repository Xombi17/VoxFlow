"""Durable, local-only recovery records for dictation jobs.

History is deliberately a different serialization boundary from diagnostics.
The SQLite rows contain the user's raw and final text so an intentional recovery
operation can return it, while list/trace serialization exposes hashes, lengths,
and allow-listed metadata only.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterator, Mapping

from ..audio.artifacts import AudioArtifact
from ..platform.audio_devices import AudioFormat
from ..settings import _connect
from ..text.contracts import TextRule, WritingResult, WritingSettings, text_sha256
from .state import SessionState


class AudioRetentionState(StrEnum):
    """Persisted state of the artifact associated with a durable job."""

    NOT_AVAILABLE = "not_available"
    TRANSIENT = "transient"
    RETAINED = "retained"
    DELETED = "deleted"


ORPHANED_CLEANUP_REASON = (
    "Transient capture data was discarded during startup cleanup."
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_HASH = re.compile(r"^[0-9a-fA-F]{64}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _settings_to_storage(settings: WritingSettings) -> dict[str, object]:
    """Serialize the complete intentional per-job settings snapshot.

    This is only written to the local history database.  Diagnostics continue to
    use ``WritingSettings.to_safe_dict`` and never receive these user-authored
    words, triggers, or replacements.
    """

    def rule_to_dict(rule: TextRule) -> dict[str, object]:
        return {
            "rule_id": rule.rule_id,
            "trigger": rule.trigger,
            "replacement": rule.replacement,
            "enabled": rule.enabled,
        }

    return {
        "language": settings.language,
        "style": settings.style.value,
        "cleanup_policy": settings.cleanup_policy.value,
        "cleanup_provider_id": settings.cleanup_provider_id,
        "cleanup_network_policy": settings.cleanup_network_policy.value,
        "cleanup_network_disclosure": settings.cleanup_network_disclosure,
        "cleanup_timeout_seconds": settings.cleanup_timeout_seconds,
        "dictionary_words": list(settings.dictionary_words),
        "dictionary_rule_ids": list(settings.dictionary_rule_ids),
        "corrections": [rule_to_dict(rule) for rule in settings.corrections],
        "snippets": [rule_to_dict(rule) for rule in settings.snippets],
    }


def _settings_from_storage(value: str | Mapping[str, object]) -> WritingSettings:
    raw = json.loads(value) if isinstance(value, str) else dict(value)

    def rules(name: str) -> tuple[TextRule, ...]:
        return tuple(TextRule(**dict(item)) for item in raw.get(name, []))

    return WritingSettings(
        language=str(raw.get("language", "auto")),
        style=str(raw.get("style", "personal")),
        cleanup_policy=str(raw.get("cleanup_policy", "deterministic")),
        cleanup_provider_id=str(raw.get("cleanup_provider_id", "deterministic")),
        cleanup_network_policy=str(raw.get("cleanup_network_policy", "local_only")),
        cleanup_network_disclosure=bool(raw.get("cleanup_network_disclosure", False)),
        cleanup_timeout_seconds=float(raw.get("cleanup_timeout_seconds", 30.0)),
        dictionary_words=tuple(str(word) for word in raw.get("dictionary_words", [])),
        dictionary_rule_ids=tuple(int(rule_id) for rule_id in raw.get("dictionary_rule_ids", [])),
        corrections=rules("corrections"),
        snippets=rules("snippets"),
    )


def _safe_trace(trace: tuple[dict[str, object], ...]) -> tuple[dict[str, object], ...]:
    allowed = {
        "attempt_id",
        "event",
        "elapsed_ms",
        "confirmed",
        "accepted",
        "emitted",
        "key_count",
        "ok",
        "mime_count",
        "result",
        "side_effect",
        "retryable",
    }
    safe: list[dict[str, object]] = []
    for event in trace:
        safe.append(
            {
                key: value
                for key, value in event.items()
                if key in allowed and isinstance(value, (bool, int, float, str))
            }
        )
    return tuple(safe)


@dataclass(frozen=True, slots=True)
class InsertionAttemptRecord:
    """One durable insertion boundary, including ambiguous outcomes."""

    attempt_id: str
    job_id: str
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    phase: str = "prepared"
    chord_sent: bool = False
    ownership_confirmed: bool = False
    transfer_completed: bool = False
    outcome: str | None = None
    side_effect: str = "failed_before_side_effect"
    retryable: bool = False
    detail: str | None = None
    trace: tuple[dict[str, object], ...] = ()
    retry_of_attempt_id: str | None = None

    def __post_init__(self) -> None:
        if not self.attempt_id.strip() or not self.job_id.strip():
            raise ValueError("attempt_id and job_id must not be blank")
        if self.phase.strip() == "":
            raise ValueError("attempt phase must not be blank")
        object.__setattr__(self, "trace", _safe_trace(tuple(self.trace)))

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "attempt_id": _safe_identity(self.attempt_id),
            "job_id": _safe_identity(self.job_id),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "phase": self.phase,
            "chord_sent": self.chord_sent,
            "ownership_confirmed": self.ownership_confirmed,
            "transfer_completed": self.transfer_completed,
            "outcome": _safe_identity(self.outcome),
            "side_effect": _safe_identity(self.side_effect),
            "retryable": self.retryable,
            "detail": _safe_reason(self.detail),
            "trace": [dict(event) for event in self.trace],
            "retry_of_attempt_id": _safe_identity(self.retry_of_attempt_id),
        }

    to_dict = to_safe_dict


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    """A full local recovery record; text is exposed only by explicit show."""

    job_id: str
    status: SessionState | str = SessionState.PROCESSING
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    raw_text: str | None = None
    final_text: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    provider_metadata: dict[str, object] = field(default_factory=dict)
    settings: WritingSettings = field(default_factory=WritingSettings)
    failure_reason: str | None = None
    error_code: str | None = None
    retryable: bool = False
    retry_code: str | None = None
    retry_count: int = 0
    artifact_id: str | None = None
    audio_sha256: str | None = None
    artifact_metadata: dict[str, object] = field(default_factory=dict)
    retain_audio: bool = False
    audio_retention_state: AudioRetentionState | str = AudioRetentionState.NOT_AVAILABLE
    insertion_attempt_id: str | None = None
    insertion_result: str | None = None
    insertion_side_effect: str | None = None
    insertion_retryable: bool = False
    insertion_detail: str | None = None
    latest_attempt: InsertionAttemptRecord | None = None

    def __post_init__(self) -> None:
        if not self.job_id.strip():
            raise ValueError("job_id must not be blank")
        object.__setattr__(self, "status", SessionState(self.status))
        object.__setattr__(self, "audio_retention_state", AudioRetentionState(self.audio_retention_state))
        if self.final_text is not None and not self.final_text.strip():
            raise ValueError("final_text must not be blank when present")
        if self.retry_count < 0:
            raise ValueError("retry_count must not be negative")
        object.__setattr__(self, "provider_metadata", dict(self.provider_metadata))
        object.__setattr__(self, "artifact_metadata", dict(self.artifact_metadata))

    @classmethod
    def from_writing_result(
        cls,
        job_id: str,
        result: WritingResult,
        *,
        status: SessionState | str = SessionState.PROCESSING,
        provider_metadata: Mapping[str, object] | None = None,
        artifact: AudioArtifact | None = None,
        retain_audio: bool = False,
        audio_retention_state: AudioRetentionState | str = AudioRetentionState.TRANSIENT,
        **changes: object,
    ) -> "HistoryRecord":
        artifact_metadata = artifact.to_dict() if artifact is not None else {}
        return cls(
            job_id=job_id,
            status=status,
            raw_text=result.raw_text,
            final_text=result.final_text,
            provider_id=result.raw.result.provider_id,
            model_id=result.raw.result.model_id,
            provider_metadata=dict(provider_metadata or result.raw.to_safe_dict()),
            settings=result.settings,
            artifact_id=artifact.artifact_id if artifact else None,
            audio_sha256=artifact.audio_sha256 if artifact else result.raw.result.audio_sha256,
            artifact_metadata=artifact_metadata,
            retain_audio=retain_audio,
            audio_retention_state=audio_retention_state,
            **changes,
        )

    def to_safe_dict(self) -> dict[str, object]:
        """Serialize a list/diagnostic view without raw or final text."""

        return {
            "job_id": _safe_identity(self.job_id),
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "raw_text_sha256": text_sha256(self.raw_text) if self.raw_text is not None else None,
            "final_text_sha256": text_sha256(self.final_text) if self.final_text is not None else None,
            "raw_text_length": len(self.raw_text) if self.raw_text is not None else None,
            "final_text_length": len(self.final_text) if self.final_text is not None else None,
            "provider_id": _safe_identity(self.provider_id),
            "model_id": _safe_identity(self.model_id),
            "provider_metadata": _safe_provider_metadata(self.provider_metadata),
            "settings": self.settings.to_safe_dict(),
            "failure_reason": _safe_reason(self.failure_reason),
            "error_code": _safe_identity(self.error_code),
            "retryable": self.retryable,
            "retry_code": _safe_identity(self.retry_code),
            "retry_count": self.retry_count,
            "artifact_id": _safe_identity(self.artifact_id),
            "audio_sha256": _safe_hash(self.audio_sha256),
            "retain_audio": self.retain_audio,
            "audio_retention_state": self.audio_retention_state.value,
            "insertion_attempt_id": _safe_identity(self.insertion_attempt_id),
            "insertion_result": _safe_identity(self.insertion_result),
            "insertion_side_effect": _safe_identity(self.insertion_side_effect),
            "insertion_retryable": self.insertion_retryable,
            "insertion_detail": _safe_reason(self.insertion_detail),
            "latest_attempt": self.latest_attempt.to_safe_dict() if self.latest_attempt else None,
        }

    to_dict = to_safe_dict

    def to_user_dict(self) -> dict[str, object]:
        """Return full text only for an intentional recovery/show operation."""

        value = self.to_safe_dict()
        value.update(
            {
                "raw_text": self.raw_text,
                "final_text": self.final_text,
                "settings": _settings_to_storage(self.settings),
                "artifact_metadata": dict(self.artifact_metadata),
                "failure_reason": self.failure_reason,
                "insertion_detail": self.insertion_detail,
            }
        )
        return value


@dataclass(frozen=True, slots=True)
class HistorySummary:
    """Redacted row returned by history listing APIs."""

    job_id: str
    status: SessionState
    created_at: str
    updated_at: str
    raw_text_sha256: str | None
    final_text_sha256: str | None
    raw_text_length: int | None
    final_text_length: int | None
    provider_id: str | None
    model_id: str | None
    retryable: bool
    retry_code: str | None
    retry_count: int
    artifact_id: str | None
    retain_audio: bool
    audio_retention_state: AudioRetentionState
    insertion_attempt_id: str | None
    insertion_result: str | None
    insertion_side_effect: str | None
    insertion_retryable: bool

    @classmethod
    def from_record(cls, record: HistoryRecord) -> "HistorySummary":
        safe = record.to_safe_dict()
        return cls(
            job_id=safe["job_id"],
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            raw_text_sha256=safe["raw_text_sha256"],
            final_text_sha256=safe["final_text_sha256"],
            raw_text_length=safe["raw_text_length"],
            final_text_length=safe["final_text_length"],
            provider_id=_safe_identity(record.provider_id),
            model_id=_safe_identity(record.model_id),
            retryable=record.retryable,
            retry_code=safe["retry_code"],
            retry_count=record.retry_count,
            artifact_id=safe["artifact_id"],
            retain_audio=record.retain_audio,
            audio_retention_state=record.audio_retention_state,
            insertion_attempt_id=safe["insertion_attempt_id"],
            insertion_result=safe["insertion_result"],
            insertion_side_effect=safe["insertion_side_effect"],
            insertion_retryable=record.insertion_retryable,
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "job_id": _safe_identity(self.job_id),
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "raw_text_sha256": self.raw_text_sha256,
            "final_text_sha256": self.final_text_sha256,
            "raw_text_length": self.raw_text_length,
            "final_text_length": self.final_text_length,
            "provider_id": _safe_identity(self.provider_id),
            "model_id": _safe_identity(self.model_id),
            "retryable": self.retryable,
            "retry_code": _safe_identity(self.retry_code),
            "retry_count": self.retry_count,
            "artifact_id": _safe_identity(self.artifact_id),
            "retain_audio": self.retain_audio,
            "audio_retention_state": self.audio_retention_state.value,
            "insertion_attempt_id": _safe_identity(self.insertion_attempt_id),
            "insertion_result": _safe_identity(self.insertion_result),
            "insertion_side_effect": _safe_identity(self.insertion_side_effect),
            "insertion_retryable": self.insertion_retryable,
        }

    to_dict = to_safe_dict


def _safe_provider_metadata(value: Mapping[str, object]) -> dict[str, object]:
    allowed = {
        "provider_kind",
        "provider_id",
        "model_id",
        "language",
        "language_probability",
        "confidence",
        "segment_count",
        "audio_sha256",
        "network_policy",
        "network_disclosure",
        "endpoint_classification",
    }
    safe: dict[str, object] = {}
    for key, item in value.items():
        if key not in allowed:
            continue
        if key in {"provider_id", "model_id"}:
            safe[key] = _safe_identity(item if isinstance(item, str) else None)
        elif key == "endpoint_classification":
            safe[key] = item if item in {"lan", "http", "https", None} else "redacted"
        elif key == "network_policy":
            safe[key] = item if item in {"local_only", "remote_explicit", None} else "redacted"
        elif key == "language":
            safe[key] = item if isinstance(item, str) and "/" not in item and "\\" not in item else "redacted"
        elif isinstance(item, (bool, int, float, str, type(None))):
            safe[key] = item
    return safe


def _safe_identity(value: object) -> str | None:
    return value if isinstance(value, str) and _SAFE_ID.fullmatch(value) else None


def _safe_hash(value: object) -> str | None:
    return value if isinstance(value, str) and _SAFE_HASH.fullmatch(value) else None


def _safe_reason(value: str | None) -> str | None:
    if value is None:
        return None
    if value in {
        "Audio capture was cancelled before transcription.",
        "The writing pipeline failed; raw text was retained.",
        "Captured audio was unavailable for transcription.",
        "The transcription provider returned empty text.",
        "Dictation was cancelled before insertion.",
        "Remote ASR requires explicit remote_explicit network policy.",
        ORPHANED_CLEANUP_REASON,
    }:
        return value
    return "redacted"


def insertion_retry_state(
    record: HistoryRecord, attempts: tuple[InsertionAttemptRecord, ...],
) -> str:
    """Fail closed on inconsistent rows and on unlinked process-window guards."""

    if record.status is SessionState.SUCCESS or any(
        item.outcome == "sent" or item.side_effect == "completed" or item.transfer_completed
        for item in attempts
    ) or record.insertion_result == "sent" or record.insertion_side_effect == "completed":
        return "unsafe"
    if record.insertion_side_effect == "unknown_after_side_effect" or any(
        item.chord_sent or item.side_effect == "unknown_after_side_effect" or item.phase == "ambiguous"
        for item in attempts
    ):
        return "ambiguous"
    if (
        record.status is not SessionState.FAILED
        or record.raw_text is None or record.final_text is None
        or not record.insertion_retryable
        or record.insertion_side_effect != "failed_before_side_effect"
        or record.insertion_result not in {"failed", "denied", "unavailable"}
        or not attempts or record.insertion_attempt_id != attempts[-1].attempt_id
        or any(
            item.phase != "failed" or not item.retryable
            or item.side_effect != "failed_before_side_effect"
            or item.outcome not in {"failed", "denied", "unavailable"}
            for item in attempts
        )
    ):
        return "unsafe"
    return "safe"


class HistoryStore:
    """SQLite-backed durable job and insertion-attempt boundary."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = db_path
        self.migrate()

    def migrate(self) -> None:
        conn = _connect(self.db_path)
        conn.close()

    @contextmanager
    def transaction(self) -> Iterator[object]:
        """Expose a small transaction seam for grouped durable updates/tests."""

        conn = _connect(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create_job(self, record: HistoryRecord) -> HistoryRecord:
        with self.transaction() as conn:
            self._insert_job(conn, record)
        return self.get_job(record.job_id)

    def upsert_job(self, record: HistoryRecord) -> HistoryRecord:
        with self.transaction() as conn:
            self._insert_job(conn, record, replace_existing=True)
        return self.get_job(record.job_id)

    def update_job(self, job_id: str, **changes: object) -> HistoryRecord:
        current = self.get_job(job_id)
        changes.setdefault("updated_at", utc_now())
        updated = replace(current, **changes)
        return self.upsert_job(updated)

    def get_job(self, job_id: str) -> HistoryRecord:
        conn = _connect(self.db_path)
        try:
            row = conn.execute("SELECT * FROM dictation_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"job not found: {job_id}")
            return self._job_from_row(conn, row)
        finally:
            conn.close()

    show_job = get_job
    show = get_job

    def list_jobs(self, *, limit: int = 100) -> tuple[HistorySummary, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM dictation_jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return tuple(HistorySummary.from_record(self._job_from_row(conn, row)) for row in rows)
        finally:
            conn.close()

    list = list_jobs

    def list_orphaned_jobs(self) -> tuple[HistorySummary, ...]:
        """Return active disabled-retention jobs left by an abnormal exit.

        Only the redacted summary crosses this boundary. The daemon uses the
        opaque artifact ID from the summary to remove transient files, then
        marks each job terminal.
        """

        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM dictation_jobs "
                "WHERE retain_audio = 0 "
                "AND status IN ('listening', 'processing') "
                "AND audio_retention_state IN ('transient', 'not_available') "
                "ORDER BY updated_at"
            ).fetchall()
            return tuple(
                HistorySummary.from_record(self._job_from_row(conn, row)) for row in rows
            )
        finally:
            conn.close()

    def diagnostic_counts(self) -> dict[str, object]:
        """Return aggregate history metadata without loading text-bearing rows."""

        conn = _connect(self.db_path)
        try:
            job_count = int(conn.execute("SELECT COUNT(*) FROM dictation_jobs").fetchone()[0])
            attempt_count = int(
                conn.execute("SELECT COUNT(*) FROM insertion_attempts").fetchone()[0]
            )
            statuses = {
                str(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT status, COUNT(*) FROM dictation_jobs GROUP BY status"
                )
            }
            retention = {
                str(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT audio_retention_state, COUNT(*) FROM dictation_jobs "
                    "GROUP BY audio_retention_state"
                )
            }
            errors = {
                str(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT error_code, COUNT(*) FROM dictation_jobs "
                    "WHERE error_code IS NOT NULL GROUP BY error_code"
                )
            }
            return {
                "job_count": job_count,
                "attempt_count": attempt_count,
                "statuses": statuses,
                "retention": retention,
                "error_codes": errors,
            }
        finally:
            conn.close()

    def clear_artifact(self, job_id: str, artifact_dir: str | Path) -> HistoryRecord:
        """Delete one opaque artifact under ``artifact_dir`` and record deletion."""

        current = self.get_job(job_id)
        artifact_id = current.artifact_id
        if artifact_id is not None:
            if Path(artifact_id).name != artifact_id or artifact_id in {"", ".", ".."}:
                raise ValueError("artifact ID is not a safe opaque filename")
            root = Path(artifact_dir).resolve()
            raw_target = root / artifact_id
            if raw_target.is_symlink():
                raise ValueError("artifact must not be a symlink")
            target = raw_target.resolve()
            if target.parent != root:
                raise ValueError("artifact is outside the configured data directory")
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        with self.transaction() as conn:
            conn.execute(
                "UPDATE dictation_jobs SET updated_at = ?, retryable = 0, retry_code = NULL, "
                "audio_retention_state = 'deleted' WHERE job_id = ?",
                (utc_now(), job_id),
            )
        return self.get_job(job_id)

    delete_artifact = clear_artifact

    def mark_orphaned_job(self, job_id: str) -> HistoryRecord:
        """Persist a redacted terminal state for an abandoned transient job."""

        current = self.get_job(job_id)
        if current.retain_audio or current.status.value not in {"listening", "processing"}:
            return current
        return self.update_job(
            job_id,
            status=SessionState.FAILED,
            failure_reason=ORPHANED_CLEANUP_REASON,
            error_code="orphaned_cleanup",
            retryable=False,
            retry_code=None,
            audio_retention_state=(
                AudioRetentionState.DELETED
                if current.artifact_id
                else AudioRetentionState.NOT_AVAILABLE
            ),
        )

    def create_insertion_attempt(self, record: InsertionAttemptRecord) -> InsertionAttemptRecord:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO insertion_attempts ("
                "attempt_id, job_id, created_at, updated_at, phase, chord_sent, "
                "ownership_confirmed, transfer_completed, outcome, side_effect, "
                "retryable, detail, trace_json, retry_of_attempt_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._attempt_values(record),
            )
            existing = conn.execute(
                "SELECT * FROM insertion_attempts WHERE attempt_id = ?", (record.attempt_id,)
            ).fetchone()
            if existing is None or existing[1] != record.job_id:
                raise ValueError("attempt ID is already associated with another job")
        return self.get_insertion_attempt(record.attempt_id)

    def claim_insertion_retry(
        self, job_id: str, *, expected_attempt_id: str, attempt_id: str, timestamp: str,
    ) -> HistoryRecord | None:
        """Claim and guard a retry atomically across independently opened processes.

        The old per-object lock cannot cover the read/prepare race between CLI
        processes. BEGIN IMMEDIATE serializes that decision with the new attempt
        and job pointer/count, before any portal or keyboard side effect.
        """

        with self.transaction() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM dictation_jobs WHERE job_id = ?", (job_id,),
            ).fetchone()
            if row is None:
                return None
            current = self._job_from_row(conn, row)
            attempts = tuple(self._attempt_from_row(item) for item in conn.execute(
                "SELECT * FROM insertion_attempts WHERE job_id = ? ORDER BY rowid", (job_id,),
            ))
            if (
                insertion_retry_state(current, attempts) != "safe"
                or current.insertion_attempt_id != expected_attempt_id
            ):
                return None
            attempt = InsertionAttemptRecord(
                attempt_id, job_id, created_at=timestamp, updated_at=timestamp,
                phase="ambiguous", side_effect="unknown_after_side_effect",
                retryable=False, retry_of_attempt_id=expected_attempt_id,
            )
            conn.execute(
                "INSERT INTO insertion_attempts ("
                "attempt_id, job_id, created_at, updated_at, phase, chord_sent, "
                "ownership_confirmed, transfer_completed, outcome, side_effect, "
                "retryable, detail, trace_json, retry_of_attempt_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._attempt_values(attempt),
            )
            claimed = replace(
                current, status=SessionState.PROCESSING, updated_at=timestamp,
                retry_count=current.retry_count + 1, retryable=False, retry_code=None,
                insertion_attempt_id=attempt_id, insertion_result=None,
                insertion_side_effect="unknown_after_side_effect", insertion_retryable=False,
                insertion_detail=None, latest_attempt=attempt,
            )
            self._insert_job(conn, claimed, replace_existing=True)
        return claimed

    def update_insertion_attempt(self, attempt_id: str, **changes: object) -> InsertionAttemptRecord:
        current = self.get_insertion_attempt(attempt_id)
        expected_phase = changes.pop("expected_phase", None)
        if expected_phase is not None and current.phase != expected_phase:
            raise RuntimeError("insertion attempt compare-and-set phase mismatch")
        changes.setdefault("updated_at", utc_now())
        updated = replace(current, **changes)
        with self.transaction() as conn:
            query = (
                "UPDATE insertion_attempts SET updated_at = ?, phase = ?, chord_sent = ?, "
                "ownership_confirmed = ?, transfer_completed = ?, outcome = ?, side_effect = ?, "
                "retryable = ?, detail = ?, trace_json = ?, retry_of_attempt_id = ? "
                "WHERE attempt_id = ?"
            )
            params: list[object] = [
                    updated.updated_at,
                    updated.phase,
                    int(updated.chord_sent),
                    int(updated.ownership_confirmed),
                    int(updated.transfer_completed),
                    updated.outcome,
                    updated.side_effect,
                    int(updated.retryable),
                    updated.detail,
                    _json(list(updated.trace)),
                    updated.retry_of_attempt_id,
                    attempt_id,
            ]
            if expected_phase is not None:
                query += " AND phase = ?"
                params.append(expected_phase)
            cursor = conn.execute(query, params)
            if cursor.rowcount != 1:
                raise RuntimeError("insertion attempt compare-and-set phase mismatch")
        return self.get_insertion_attempt(attempt_id)

    def get_insertion_attempt(self, attempt_id: str) -> InsertionAttemptRecord:
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM insertion_attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"insertion attempt not found: {attempt_id}")
            return self._attempt_from_row(row)
        finally:
            conn.close()

    def list_insertion_attempts(self, job_id: str) -> tuple[InsertionAttemptRecord, ...]:
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM insertion_attempts WHERE job_id = ? ORDER BY rowid",
                (job_id,),
            ).fetchall()
            return tuple(self._attempt_from_row(row) for row in rows)
        finally:
            conn.close()

    def resolve_artifact(self, job_id: str, artifact_dir: str | Path) -> AudioArtifact | None:
        """Resolve a retained artifact only when the caller explicitly supplies its directory."""

        record = self.get_job(job_id)
        if record.audio_retention_state is not AudioRetentionState.RETAINED:
            return None
        metadata = record.artifact_metadata
        source = metadata.get("source_format")
        if not record.artifact_id or not isinstance(source, Mapping):
            return None
        artifact_name = Path(record.artifact_id).name
        if artifact_name != record.artifact_id:
            return None
        path = Path(artifact_dir) / artifact_name
        if not path.is_file():
            return None
        return AudioArtifact(
            path=path,
            audio_sha256=str(record.audio_sha256 or metadata.get("audio_sha256")),
            source_format=AudioFormat(int(source["sample_rate"]), int(source["channels"])),
            frame_count=int(metadata["frame_count"]),
            duration_ms=int(metadata["duration_ms"]),
            sample_width_bytes=int(metadata.get("sample_width_bytes", 2)),
            encoding=str(metadata.get("encoding", "PCM_S16LE")),
            wav_byte_count=int(metadata["wav_byte_count"]),
        )

    def _insert_job(self, conn: object, record: HistoryRecord, *, replace_existing: bool = False) -> None:
        if record.status is SessionState.SUCCESS and (
            record.raw_text is None or record.final_text is None
        ):
            raise ValueError("successful jobs must include raw and final text")
        values = self._job_values(record)
        if replace_existing:
            conn.execute(
                "INSERT INTO dictation_jobs ("
                "job_id, created_at, updated_at, status, raw_text, final_text, raw_text_sha256, "
                "final_text_sha256, provider_id, model_id, provider_metadata_json, settings_json, "
                "failure_reason, error_code, retryable, retry_code, retry_count, artifact_id, "
                "audio_sha256, artifact_metadata_json, retain_audio, audio_retention_state, "
                "insertion_attempt_id, insertion_result, insertion_side_effect, insertion_retryable, "
                "insertion_detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(job_id) DO UPDATE SET created_at=excluded.created_at, "
                "updated_at=excluded.updated_at, status=excluded.status, raw_text=excluded.raw_text, "
                "final_text=excluded.final_text, raw_text_sha256=excluded.raw_text_sha256, "
                "final_text_sha256=excluded.final_text_sha256, provider_id=excluded.provider_id, "
                "model_id=excluded.model_id, provider_metadata_json=excluded.provider_metadata_json, "
                "settings_json=excluded.settings_json, failure_reason=excluded.failure_reason, "
                "error_code=excluded.error_code, retryable=excluded.retryable, retry_code=excluded.retry_code, "
                "retry_count=excluded.retry_count, artifact_id=excluded.artifact_id, "
                "audio_sha256=excluded.audio_sha256, artifact_metadata_json=excluded.artifact_metadata_json, "
                "retain_audio=excluded.retain_audio, audio_retention_state=excluded.audio_retention_state, "
                "insertion_attempt_id=excluded.insertion_attempt_id, insertion_result=excluded.insertion_result, "
                "insertion_side_effect=excluded.insertion_side_effect, insertion_retryable=excluded.insertion_retryable, "
                "insertion_detail=excluded.insertion_detail",
                values,
            )
        else:
            conn.execute(
                "INSERT INTO dictation_jobs ("
                "job_id, created_at, updated_at, status, raw_text, final_text, raw_text_sha256, "
                "final_text_sha256, provider_id, model_id, provider_metadata_json, settings_json, "
                "failure_reason, error_code, retryable, retry_code, retry_count, artifact_id, "
                "audio_sha256, artifact_metadata_json, retain_audio, audio_retention_state, "
                "insertion_attempt_id, insertion_result, insertion_side_effect, insertion_retryable, "
                "insertion_detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                values,
            )

    @staticmethod
    def _job_values(record: HistoryRecord) -> tuple[object, ...]:
        return (
            record.job_id,
            record.created_at,
            record.updated_at,
            record.status.value,
            record.raw_text,
            record.final_text,
            text_sha256(record.raw_text) if record.raw_text is not None else None,
            text_sha256(record.final_text) if record.final_text is not None else None,
            record.provider_id,
            record.model_id,
            _json(_safe_provider_metadata(record.provider_metadata)),
            _json(_settings_to_storage(record.settings)),
            _safe_reason(record.failure_reason),
            record.error_code,
            int(record.retryable),
            record.retry_code,
            record.retry_count,
            record.artifact_id,
            record.audio_sha256,
            _json(record.artifact_metadata),
            int(record.retain_audio),
            record.audio_retention_state.value,
            record.insertion_attempt_id,
            record.insertion_result,
            record.insertion_side_effect,
            int(record.insertion_retryable),
            _safe_reason(record.insertion_detail),
        )

    @staticmethod
    def _attempt_values(record: InsertionAttemptRecord) -> tuple[object, ...]:
        return (
            record.attempt_id,
            record.job_id,
            record.created_at,
            record.updated_at,
            record.phase,
            int(record.chord_sent),
            int(record.ownership_confirmed),
            int(record.transfer_completed),
            record.outcome,
            record.side_effect,
            int(record.retryable),
            _safe_reason(record.detail),
            _json(list(record.trace)),
            record.retry_of_attempt_id,
        )

    def _job_from_row(self, conn: object, row: tuple[object, ...]) -> HistoryRecord:
        attempt = None
        if row[22] is not None:
            attempt_row = conn.execute(
                "SELECT * FROM insertion_attempts WHERE attempt_id = ?", (row[22],)
            ).fetchone()
            attempt = self._attempt_from_row(attempt_row) if attempt_row else None
        return HistoryRecord(
            job_id=str(row[0]),
            created_at=str(row[1]),
            updated_at=str(row[2]),
            status=str(row[3]),
            raw_text=row[4],
            final_text=row[5],
            provider_id=row[8],
            model_id=row[9],
            provider_metadata=json.loads(str(row[10])),
            settings=_settings_from_storage(str(row[11])),
            failure_reason=row[12],
            error_code=row[13],
            retryable=bool(row[14]),
            retry_code=row[15],
            retry_count=int(row[16]),
            artifact_id=row[17],
            audio_sha256=row[18],
            artifact_metadata=json.loads(str(row[19])),
            retain_audio=bool(row[20]),
            audio_retention_state=str(row[21]),
            insertion_attempt_id=row[22],
            insertion_result=row[23],
            insertion_side_effect=row[24],
            insertion_retryable=bool(row[25]),
            insertion_detail=row[26],
            latest_attempt=attempt,
        )

    @staticmethod
    def _attempt_from_row(row: tuple[object, ...]) -> InsertionAttemptRecord:
        return InsertionAttemptRecord(
            attempt_id=str(row[0]),
            job_id=str(row[1]),
            created_at=str(row[2]),
            updated_at=str(row[3]),
            phase=str(row[4]),
            chord_sent=bool(row[5]),
            ownership_confirmed=bool(row[6]),
            transfer_completed=bool(row[7]),
            outcome=row[8],
            side_effect=str(row[9]),
            retryable=bool(row[10]),
            detail=row[11],
            trace=tuple(json.loads(str(row[12]))),
            retry_of_attempt_id=row[13],
        )


def history_record_from_writing_result(
    job_id: str,
    result: WritingResult,
    **kwargs: object,
) -> HistoryRecord:
    """Public helper used by the daemon and recovery-focused callers."""

    return HistoryRecord.from_writing_result(job_id, result, **kwargs)


__all__ = [
    "AudioRetentionState",
    "HistoryRecord",
    "HistorySummary",
    "HistoryStore",
    "InsertionAttemptRecord",
    "ORPHANED_CLEANUP_REASON",
    "history_record_from_writing_result",
]
