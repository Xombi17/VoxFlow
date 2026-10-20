"""SQLite-backed application and writing-personalization settings."""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, replace
from enum import StrEnum
from collections.abc import Mapping
from pathlib import Path

from .platform.insert import DEFAULT_CHORD, normalize_chord
from .providers.config import NetworkPolicy, ProviderKind, SELECTED_MODEL_SETTING
from .text.contracts import CleanupPolicy, WritingSettings, WritingStyle
from .text.rules import DictionaryEntry, RuleKind, StoredRule, apply_rules, normalize_trigger


SCHEMA_VERSION = 4
AUDIO_RETENTION_SETTING = "retain_audio"
_DBPath = str | os.PathLike[str] | None


class ShortcutMode(StrEnum):
    HOLD = "hold"
    TOGGLE = "toggle"


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_TRIGGER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+ -]{0,127}$")
_SAFE_ENV = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_KEY_NAME = re.compile(r"^(?:[a-z0-9]|F(?:[1-9]|1[0-2])|XF86[A-Za-z0-9_]+)$")
_NAMED_KEYS = frozenset(
    {
        "Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R",
        "Super_L", "Super_R", "Meta_L", "Meta_R", "space", "Return", "Tab",
        "Escape", "BackSpace", "Delete", "Home", "End", "Page_Up", "Page_Down",
        "Up", "Down", "Left", "Right", "Insert", "Print", "Pause",
    }
)


def _safe_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{field_name} must be a safe identifier")
    return value


def _optional_identifier(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _safe_identifier(value, field_name)


def _validate_env(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SAFE_ENV.fullmatch(value):
        raise ValueError("credential environment variable must be a valid name")
    return value


def _validate_chord(value: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = normalize_chord(value)
    if len(normalized) > 6:
        raise ValueError("paste_chord must contain at most six keys")
    for key in normalized:
        if key not in _NAMED_KEYS and not _KEY_NAME.fullmatch(key):
            raise ValueError("paste_chord contains a key that is not a valid keymap name")
    return normalized


def _bounded_int(value: int, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    """Immutable, validated settings used by the desktop surface and daemon."""

    microphone_id: str | None = None
    shortcut_trigger: str = "Ctrl+Space"
    shortcut_mode: ShortcutMode = ShortcutMode.HOLD
    language: str = "auto"
    style: WritingStyle = WritingStyle.PERSONAL
    asr_provider_kind: ProviderKind = ProviderKind.LOCAL
    asr_provider_id: str = "local-whisper"
    selected_model_id: str = "local-default"
    asr_network_policy: NetworkPolicy = NetworkPolicy.LOCAL_ONLY
    asr_network_disclosure: bool = False
    asr_endpoint_classification: str | None = None
    asr_credential_env_var: str | None = None
    cleanup_policy: CleanupPolicy = CleanupPolicy.DETERMINISTIC
    cleanup_provider_id: str = "deterministic"
    cleanup_network_policy: NetworkPolicy = NetworkPolicy.LOCAL_ONLY
    cleanup_network_disclosure: bool = False
    cleanup_timeout_seconds: float = 30.0
    retain_audio: bool = False
    paste_chord: tuple[str, ...] = DEFAULT_CHORD
    restore_clipboard: bool = True
    owner_settle_ms: int = 50
    release_settle_ms: int = 30
    transfer_timeout_ms: int = 2_000
    max_duration_ms: int = 30_000

    def __post_init__(self) -> None:
        if self.microphone_id is not None:
            _safe_identifier(self.microphone_id, "microphone_id")
        if not isinstance(self.shortcut_trigger, str) or not _SAFE_TRIGGER.fullmatch(
            self.shortcut_trigger
        ):
            raise ValueError("shortcut_trigger must be a safe portal trigger ID")
        object.__setattr__(self, "shortcut_mode", ShortcutMode(self.shortcut_mode))
        writing = WritingSettings(
            language=self.language,
            style=self.style,
            cleanup_policy=self.cleanup_policy,
            cleanup_provider_id=self.cleanup_provider_id,
            cleanup_network_policy=self.cleanup_network_policy,
            cleanup_network_disclosure=self.cleanup_network_disclosure,
            cleanup_timeout_seconds=self.cleanup_timeout_seconds,
        )
        object.__setattr__(self, "language", writing.language)
        object.__setattr__(self, "style", writing.style)
        object.__setattr__(self, "cleanup_policy", writing.cleanup_policy)
        object.__setattr__(self, "cleanup_provider_id", writing.cleanup_provider_id)
        object.__setattr__(self, "cleanup_network_policy", writing.cleanup_network_policy)
        object.__setattr__(self, "cleanup_network_disclosure", writing.cleanup_network_disclosure)
        object.__setattr__(self, "cleanup_timeout_seconds", writing.cleanup_timeout_seconds)
        object.__setattr__(self, "asr_provider_kind", ProviderKind(self.asr_provider_kind))
        _safe_identifier(self.asr_provider_id, "asr_provider_id")
        _safe_identifier(self.selected_model_id, "selected_model_id")
        object.__setattr__(self, "asr_network_policy", NetworkPolicy(self.asr_network_policy))
        if not isinstance(self.asr_network_disclosure, bool):
            raise ValueError("asr_network_disclosure must be a boolean")
        if self.asr_provider_kind is ProviderKind.LOCAL:
            if self.asr_network_policy is not NetworkPolicy.LOCAL_ONLY:
                raise ValueError("local ASR must use local_only network policy")
            if self.asr_network_disclosure or self.asr_endpoint_classification:
                raise ValueError("local ASR must not disclose or classify network use")
        else:
            if (
                self.asr_network_policy is not NetworkPolicy.REMOTE_EXPLICIT
                or not self.asr_network_disclosure
                or self.asr_endpoint_classification not in {"lan", "http", "https"}
            ):
                raise ValueError(
                    "remote ASR requires remote_explicit policy, disclosure, and endpoint class"
                )
        object.__setattr__(self, "asr_credential_env_var", _validate_env(self.asr_credential_env_var))
        if self.cleanup_network_policy is NetworkPolicy.REMOTE_EXPLICIT:
            if not self.cleanup_network_disclosure or self.cleanup_policy is not CleanupPolicy.PROVIDER:
                raise ValueError("remote cleanup requires provider policy and network disclosure")
        elif self.cleanup_network_disclosure:
            raise ValueError("local cleanup must not disclose network use")
        if not isinstance(self.retain_audio, bool):
            raise ValueError("retain_audio must be a boolean")
        if not isinstance(self.restore_clipboard, bool):
            raise ValueError("restore_clipboard must be a boolean")
        object.__setattr__(self, "paste_chord", _validate_chord(self.paste_chord))
        object.__setattr__(self, "owner_settle_ms", _bounded_int(self.owner_settle_ms, "owner_settle_ms", 0, 5_000))
        object.__setattr__(self, "release_settle_ms", _bounded_int(self.release_settle_ms, "release_settle_ms", 0, 5_000))
        object.__setattr__(self, "transfer_timeout_ms", _bounded_int(self.transfer_timeout_ms, "transfer_timeout_ms", 1, 30_000))
        object.__setattr__(self, "max_duration_ms", _bounded_int(self.max_duration_ms, "max_duration_ms", 1, 300_000))

    @property
    def asr_model_id(self) -> str:
        return self.selected_model_id

    @property
    def provider_kind(self) -> ProviderKind:
        return self.asr_provider_kind

    @property
    def provider_id(self) -> str:
        return self.asr_provider_id

    @property
    def model_id(self) -> str:
        return self.selected_model_id

    @property
    def network_policy(self) -> NetworkPolicy:
        return self.asr_network_policy

    @property
    def asr_dispatch_allowed(self) -> bool:
        return self.asr_provider_kind is ProviderKind.LOCAL or (
            self.asr_network_policy is NetworkPolicy.REMOTE_EXPLICIT
            and self.asr_network_disclosure
        )

    def to_safe_dict(self, *, writing: WritingSettings | None = None) -> dict[str, object]:
        """Return only policy, IDs, coarse classes, counts, and bounded values."""

        return {
            "microphone_id": self.microphone_id,
            "microphone_configured": self.microphone_id is not None,
            "shortcut_trigger": self.shortcut_trigger,
            "shortcut_mode": self.shortcut_mode.value,
            "language": self.language,
            "style": self.style.value,
            "asr_provider_kind": self.asr_provider_kind.value,
            "asr_provider_id": self.asr_provider_id,
            "selected_model_id": self.selected_model_id,
            "asr_network_policy": self.asr_network_policy.value,
            "asr_network_disclosure": self.asr_network_disclosure,
            "asr_endpoint_classification": self.asr_endpoint_classification,
            "cleanup_policy": self.cleanup_policy.value,
            "cleanup_provider_id": self.cleanup_provider_id,
            "cleanup_network_policy": self.cleanup_network_policy.value,
            "cleanup_network_disclosure": self.cleanup_network_disclosure,
            "cleanup_timeout_seconds": self.cleanup_timeout_seconds,
            "retain_audio": self.retain_audio,
            "paste_chord": list(self.paste_chord),
            "restore_clipboard": self.restore_clipboard,
            "owner_settle_ms": self.owner_settle_ms,
            "release_settle_ms": self.release_settle_ms,
            "transfer_timeout_ms": self.transfer_timeout_ms,
            "max_duration_ms": self.max_duration_ms,
            "writing": writing.to_safe_dict() if writing is not None else None,
        }


_WORD_BOUNDARY = r"(?<!\w){value}(?!\w)"
def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "voxflow"


def default_db_path() -> Path:
    return data_dir() / "voxflow.db"


def _path(db_path: _DBPath) -> str | Path:
    if db_path is None:
        return default_db_path()
    return str(db_path) if str(db_path) == ":memory:" else Path(db_path)


def _connect(db_path: _DBPath) -> sqlite3.Connection:
    path = _path(db_path)
    if path != ":memory:":
        Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    if path != ":memory:":
        os.chmod(path, 0o600)
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Migrate legacy settings in one transaction and fail closed if newer."""

    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)"
    )
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'settings_schema_version'"
    ).fetchone()
    current_version = 0 if row is None else int(row[0])
    if current_version > SCHEMA_VERSION:
        raise RuntimeError("settings database schema is newer than this application")
    with conn:
        _ensure_legacy_schema(conn)
        while current_version < SCHEMA_VERSION:
            migration = _MIGRATIONS.get(current_version)
            if migration is None:
                raise RuntimeError(f"no migration registered for schema v{current_version}")
            migration(conn)
            current_version += 1
            conn.execute(
                "INSERT INTO schema_meta (key, value) VALUES ('settings_schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (current_version,),
            )
        _ensure_application_preferences(conn)


def _ensure_legacy_schema(conn: sqlite3.Connection) -> None:
    """Create or extend the v1-v3 tables without rewriting existing rows."""

    conn.execute(
        "CREATE TABLE IF NOT EXISTS writing_preferences ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "language TEXT NOT NULL DEFAULT 'auto', "
        "style TEXT NOT NULL DEFAULT 'personal', "
        "cleanup_policy TEXT NOT NULL DEFAULT 'deterministic', "
        "cleanup_provider_id TEXT NOT NULL DEFAULT 'deterministic', "
        "cleanup_network_policy TEXT NOT NULL DEFAULT 'local_only', "
        "cleanup_network_disclosure INTEGER NOT NULL DEFAULT 0, "
        "cleanup_timeout_seconds REAL NOT NULL DEFAULT 30.0, "
        "retain_audio INTEGER NOT NULL DEFAULT 0 CHECK (retain_audio IN (0, 1)))"
    )
    preference_columns = {
        "cleanup_policy": "TEXT NOT NULL DEFAULT 'deterministic'",
        "cleanup_provider_id": "TEXT NOT NULL DEFAULT 'deterministic'",
        "cleanup_network_policy": "TEXT NOT NULL DEFAULT 'local_only'",
        "cleanup_network_disclosure": "INTEGER NOT NULL DEFAULT 0",
        "cleanup_timeout_seconds": "REAL NOT NULL DEFAULT 30.0",
        "retain_audio": "INTEGER NOT NULL DEFAULT 0 CHECK (retain_audio IN (0, 1))",
    }
    existing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(writing_preferences)")
    }
    for column, declaration in preference_columns.items():
        if column not in existing_columns:
            conn.execute(
                f"ALTER TABLE writing_preferences ADD COLUMN {column} {declaration}"
            )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dictionary_rules ("
        "rule_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "word TEXT NOT NULL, normalized_word TEXT NOT NULL UNIQUE, "
        "enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS writing_rules ("
        "rule_id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "kind TEXT NOT NULL CHECK (kind IN ('correction', 'snippet')), "
        "trigger TEXT NOT NULL, normalized_trigger TEXT NOT NULL, "
        "replacement TEXT NOT NULL, "
        "enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dictation_jobs ("
        "job_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "status TEXT NOT NULL, raw_text TEXT, final_text TEXT, raw_text_sha256 TEXT, "
        "final_text_sha256 TEXT, provider_id TEXT, model_id TEXT, "
        "provider_metadata_json TEXT NOT NULL DEFAULT '{}', "
        "settings_json TEXT NOT NULL DEFAULT '{}', failure_reason TEXT, error_code TEXT, "
        "retryable INTEGER NOT NULL DEFAULT 0, retry_code TEXT, retry_count INTEGER NOT NULL DEFAULT 0, "
        "artifact_id TEXT, audio_sha256 TEXT, artifact_metadata_json TEXT NOT NULL DEFAULT '{}', "
        "retain_audio INTEGER NOT NULL DEFAULT 0 CHECK (retain_audio IN (0, 1)), "
        "audio_retention_state TEXT NOT NULL DEFAULT 'not_available', insertion_attempt_id TEXT, "
        "insertion_result TEXT, insertion_side_effect TEXT, insertion_retryable INTEGER NOT NULL DEFAULT 0, "
        "insertion_detail TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS insertion_attempts ("
        "attempt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, phase TEXT NOT NULL, chord_sent INTEGER NOT NULL DEFAULT 0, "
        "ownership_confirmed INTEGER NOT NULL DEFAULT 0, transfer_completed INTEGER NOT NULL DEFAULT 0, "
        "outcome TEXT, side_effect TEXT NOT NULL, retryable INTEGER NOT NULL DEFAULT 0, detail TEXT, "
        "trace_json TEXT NOT NULL DEFAULT '[]', retry_of_attempt_id TEXT, "
        "FOREIGN KEY(job_id) REFERENCES dictation_jobs(job_id) ON DELETE CASCADE)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS insertion_attempts_job_created "
        "ON insertion_attempts(job_id, created_at)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO writing_preferences (id, language, style) "
        "VALUES (1, 'auto', 'personal')"
    )


def _ensure_application_preferences(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS application_preferences ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "microphone_id TEXT, shortcut_trigger TEXT NOT NULL DEFAULT 'Ctrl+Space', "
        "shortcut_mode TEXT NOT NULL DEFAULT 'hold', "
        "asr_provider_kind TEXT NOT NULL DEFAULT 'local', "
        "asr_provider_id TEXT NOT NULL DEFAULT 'local-whisper', "
        "asr_network_policy TEXT NOT NULL DEFAULT 'local_only', "
        "asr_network_disclosure INTEGER NOT NULL DEFAULT 0 CHECK (asr_network_disclosure IN (0, 1)), "
        "asr_endpoint_classification TEXT, asr_credential_env_var TEXT, "
        "paste_chord TEXT NOT NULL DEFAULT 'Control_L+v', "
        "restore_clipboard INTEGER NOT NULL DEFAULT 1 CHECK (restore_clipboard IN (0, 1)), "
        "owner_settle_ms INTEGER NOT NULL DEFAULT 50, "
        "release_settle_ms INTEGER NOT NULL DEFAULT 30, "
        "transfer_timeout_ms INTEGER NOT NULL DEFAULT 2000, "
        "max_duration_ms INTEGER NOT NULL DEFAULT 30000)"
    )
    conn.execute("INSERT OR IGNORE INTO application_preferences (id) VALUES (1)")


def _migration_v0_to_v1(conn: sqlite3.Connection) -> None:
    del conn


def _migration_v1_to_v2(conn: sqlite3.Connection) -> None:
    del conn


def _migration_v2_to_v3(conn: sqlite3.Connection) -> None:
    del conn


def _migration_v3_to_v4(conn: sqlite3.Connection) -> None:
    _ensure_application_preferences(conn)


_MIGRATIONS = {
    0: _migration_v0_to_v1,
    1: _migration_v1_to_v2,
    2: _migration_v2_to_v3,
    3: _migration_v3_to_v4,
}


def get(key: str, default: str | None = None, *, db_path: _DBPath = None) -> str | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return default if row is None else row[0]


def set(key: str, value: str | None, *, db_path: _DBPath = None) -> None:  # noqa: A001
    """Store ``value``; ``None`` deletes the key."""

    conn = _connect(db_path)
    try:
        with conn:
            if value is None:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
    finally:
        conn.close()


def selected_model_id(*, db_path: _DBPath = None) -> str | None:
    return get(SELECTED_MODEL_SETTING, db_path=db_path)


def set_selected_model_id(model_id: str | None, *, db_path: _DBPath = None) -> None:
    set(SELECTED_MODEL_SETTING, model_id, db_path=db_path)


class WritingSettingsStore:
    """Typed persistence boundary for settings used by future writing jobs."""

    def __init__(self, db_path: _DBPath = None) -> None:
        self.db_path = db_path
        self.migrate()

    def migrate(self) -> None:
        conn = _connect(self.db_path)
        conn.close()

    def _application_preferences(self, conn: sqlite3.Connection) -> tuple[object, ...]:
        row = conn.execute(
            "SELECT microphone_id, shortcut_trigger, shortcut_mode, asr_provider_kind, "
            "asr_provider_id, asr_network_policy, asr_network_disclosure, "
            "asr_endpoint_classification, asr_credential_env_var, paste_chord, "
            "restore_clipboard, owner_settle_ms, release_settle_ms, transfer_timeout_ms, "
            "max_duration_ms FROM application_preferences WHERE id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("application preferences are not initialized")
        return row

    def load_application_settings(self) -> ApplicationSettings:
        """Load one immutable application snapshot, including writing policy."""

        conn = _connect(self.db_path)
        try:
            row = self._application_preferences(conn)
            writing = self._preferences(conn)
            selected = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (SELECTED_MODEL_SETTING,)
            ).fetchone()
            return ApplicationSettings(
                microphone_id=row[0],
                shortcut_trigger=row[1],
                shortcut_mode=row[2],
                language=writing.language,
                style=writing.style,
                asr_provider_kind=row[3],
                asr_provider_id=row[4],
                selected_model_id=(selected[0] if selected is not None else "local-default"),
                asr_network_policy=row[5],
                asr_network_disclosure=bool(row[6]),
                asr_endpoint_classification=row[7],
                asr_credential_env_var=row[8],
                cleanup_policy=writing.cleanup_policy,
                cleanup_provider_id=writing.cleanup_provider_id,
                cleanup_network_policy=writing.cleanup_network_policy,
                cleanup_network_disclosure=writing.cleanup_network_disclosure,
                cleanup_timeout_seconds=writing.cleanup_timeout_seconds,
                retain_audio=self.get_audio_retention_from_connection(conn),
                paste_chord=row[9],
                restore_clipboard=bool(row[10]),
                owner_settle_ms=int(row[11]),
                release_settle_ms=int(row[12]),
                transfer_timeout_ms=int(row[13]),
                max_duration_ms=int(row[14]),
            )
        finally:
            conn.close()

    get_application_settings = load_application_settings

    @staticmethod
    def get_audio_retention_from_connection(conn: sqlite3.Connection) -> bool:
        row = conn.execute("SELECT retain_audio FROM writing_preferences WHERE id = 1").fetchone()
        return bool(row[0]) if row is not None else False

    def update_application_settings(
        self,
        settings: ApplicationSettings | Mapping[str, object] | None = None,
        **changes: object,
    ) -> ApplicationSettings:
        """Validate the complete candidate before one transaction writes it."""

        current = self.load_application_settings()
        if settings is not None:
            candidate = (
                settings
                if isinstance(settings, ApplicationSettings)
                else ApplicationSettings(**dict(settings))
            )
            if changes:
                candidate = replace(candidate, **changes)
        else:
            candidate = replace(current, **changes)
        if not isinstance(candidate, ApplicationSettings):
            raise TypeError("settings must be an ApplicationSettings snapshot")
        conn = _connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    "UPDATE application_preferences SET microphone_id = ?, shortcut_trigger = ?, "
                    "shortcut_mode = ?, asr_provider_kind = ?, asr_provider_id = ?, "
                    "asr_network_policy = ?, asr_network_disclosure = ?, "
                    "asr_endpoint_classification = ?, asr_credential_env_var = ?, paste_chord = ?, "
                    "restore_clipboard = ?, owner_settle_ms = ?, release_settle_ms = ?, "
                    "transfer_timeout_ms = ?, max_duration_ms = ? WHERE id = 1",
                    (
                        candidate.microphone_id,
                        candidate.shortcut_trigger,
                        candidate.shortcut_mode.value,
                        candidate.asr_provider_kind.value,
                        candidate.asr_provider_id,
                        candidate.asr_network_policy.value,
                        int(candidate.asr_network_disclosure),
                        candidate.asr_endpoint_classification,
                        candidate.asr_credential_env_var,
                        "+".join(candidate.paste_chord),
                        int(candidate.restore_clipboard),
                        candidate.owner_settle_ms,
                        candidate.release_settle_ms,
                        candidate.transfer_timeout_ms,
                        candidate.max_duration_ms,
                    ),
                )
                conn.execute(
                    "UPDATE writing_preferences SET language = ?, style = ?, cleanup_policy = ?, "
                    "cleanup_provider_id = ?, cleanup_network_policy = ?, "
                    "cleanup_network_disclosure = ?, cleanup_timeout_seconds = ?, retain_audio = ? "
                    "WHERE id = 1",
                    (
                        candidate.language,
                        candidate.style.value,
                        candidate.cleanup_policy.value,
                        candidate.cleanup_provider_id,
                        candidate.cleanup_network_policy.value,
                        int(candidate.cleanup_network_disclosure),
                        candidate.cleanup_timeout_seconds,
                        int(candidate.retain_audio),
                    ),
                )
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (SELECTED_MODEL_SETTING, candidate.selected_model_id),
                )
        finally:
            conn.close()
        return candidate

    set_application_settings = update_application_settings

    def _preferences(self, conn: sqlite3.Connection) -> WritingSettings:
        row = conn.execute(
            "SELECT language, style, cleanup_policy, cleanup_provider_id, "
            "cleanup_network_policy, cleanup_network_disclosure, cleanup_timeout_seconds "
            "FROM writing_preferences WHERE id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("writing preferences are not initialized")
        return WritingSettings(
            language=row[0],
            style=row[1],
            cleanup_policy=row[2],
            cleanup_provider_id=row[3],
            cleanup_network_policy=row[4],
            cleanup_network_disclosure=bool(row[5]),
            cleanup_timeout_seconds=row[6],
        )

    def get_language(self) -> str:
        conn = _connect(self.db_path)
        try:
            return self._preferences(conn).language
        finally:
            conn.close()

    def get_style(self) -> WritingStyle:
        conn = _connect(self.db_path)
        try:
            return self._preferences(conn).style
        finally:
            conn.close()

    def set_language(self, language: str) -> str:
        validated = WritingSettings(language=language).language
        conn = _connect(self.db_path)
        try:
            with conn:
                conn.execute("UPDATE writing_preferences SET language = ? WHERE id = 1", (validated,))
        finally:
            conn.close()
        return validated

    def set_style(self, style: WritingStyle | str) -> WritingStyle:
        validated = WritingSettings(style=style).style
        conn = _connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    "UPDATE writing_preferences SET style = ? WHERE id = 1",
                    (validated.value,),
                )
        finally:
            conn.close()
        return validated

    def set_preferences(
        self,
        *,
        language: str | None = None,
        style: WritingStyle | str | None = None,
        cleanup_policy: CleanupPolicy | str | None = None,
        cleanup_provider_id: str | None = None,
        cleanup_network_policy: NetworkPolicy | str | None = None,
        cleanup_network_disclosure: bool | None = None,
        cleanup_timeout_seconds: float | None = None,
        retain_audio: bool | None = None,
    ) -> WritingSettings:
        conn = _connect(self.db_path)
        try:
            current = self._preferences(conn)
            retention_row = conn.execute(
                "SELECT retain_audio FROM writing_preferences WHERE id = 1"
            ).fetchone()
            current_retain_audio = bool(retention_row[0]) if retention_row is not None else False
            if retain_audio is not None and not isinstance(retain_audio, bool):
                raise TypeError("retain_audio must be a boolean")
            validated = WritingSettings(
                language=current.language if language is None else language,
                style=current.style if style is None else style,
                cleanup_policy=(
                    current.cleanup_policy if cleanup_policy is None else cleanup_policy
                ),
                cleanup_provider_id=(
                    current.cleanup_provider_id
                    if cleanup_provider_id is None
                    else cleanup_provider_id
                ),
                cleanup_network_policy=(
                    current.cleanup_network_policy
                    if cleanup_network_policy is None
                    else cleanup_network_policy
                ),
                cleanup_network_disclosure=(
                    current.cleanup_network_disclosure
                    if cleanup_network_disclosure is None
                    else cleanup_network_disclosure
                ),
                cleanup_timeout_seconds=(
                    current.cleanup_timeout_seconds
                    if cleanup_timeout_seconds is None
                    else cleanup_timeout_seconds
                ),
            )
            with conn:
                conn.execute(
                    "UPDATE writing_preferences SET language = ?, style = ?, "
                    "cleanup_policy = ?, cleanup_provider_id = ?, "
                    "cleanup_network_policy = ?, cleanup_network_disclosure = ?, "
                    "cleanup_timeout_seconds = ?, retain_audio = ? WHERE id = 1",
                    (
                        validated.language,
                        validated.style.value,
                        validated.cleanup_policy.value,
                        validated.cleanup_provider_id,
                        validated.cleanup_network_policy.value,
                        int(validated.cleanup_network_disclosure),
                        validated.cleanup_timeout_seconds,
                        int(current_retain_audio if retain_audio is None else retain_audio),
                    ),
                )
            return validated
        finally:
            conn.close()

    def set_cleanup_preferences(
        self,
        *,
        cleanup_policy: CleanupPolicy | str | None = None,
        cleanup_provider_id: str | None = None,
        cleanup_network_policy: NetworkPolicy | str | None = None,
        cleanup_network_disclosure: bool | None = None,
        cleanup_timeout_seconds: float | None = None,
        retain_audio: bool | None = None,
    ) -> WritingSettings:
        return self.set_preferences(
            cleanup_policy=cleanup_policy,
            cleanup_provider_id=cleanup_provider_id,
            cleanup_network_policy=cleanup_network_policy,
            cleanup_network_disclosure=cleanup_network_disclosure,
            cleanup_timeout_seconds=cleanup_timeout_seconds,
            retain_audio=retain_audio,
        )

    def get_audio_retention(self) -> bool:
        """Return the persisted recovery policy; disabled is the safe default."""

        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT retain_audio FROM writing_preferences WHERE id = 1"
            ).fetchone()
            return bool(row[0]) if row is not None else False
        finally:
            conn.close()

    def get_retain_audio(self) -> bool:
        """Compatibility spelling matching the database setting name."""

        return self.get_audio_retention()

    def set_audio_retention(self, retain_audio: bool) -> bool:
        if not isinstance(retain_audio, bool):
            raise TypeError("retain_audio must be a boolean")
        conn = _connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    "UPDATE writing_preferences SET retain_audio = ? WHERE id = 1",
                    (int(retain_audio),),
                )
        finally:
            conn.close()
        return retain_audio

    def set_retain_audio(self, retain_audio: bool) -> bool:
        return self.set_audio_retention(retain_audio)

    def add_dictionary_word(self, word: str, *, enabled: bool = True) -> DictionaryEntry:
        normalized = normalize_trigger(word).casefold()
        conn = _connect(self.db_path)
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO dictionary_rules (word, normalized_word, enabled) VALUES (?, ?, ?)",
                    (normalize_trigger(word), normalized, int(enabled)),
                )
                rule_id = int(cursor.lastrowid)
            return DictionaryEntry(rule_id, normalize_trigger(word), enabled)
        finally:
            conn.close()

    def update_dictionary_word(
        self,
        rule_id: int,
        *,
        word: str | None = None,
        enabled: bool | None = None,
    ) -> DictionaryEntry:
        if word is None and enabled is None:
            return self.get_dictionary_word(rule_id)
        conn = _connect(self.db_path)
        try:
            current = self._dictionary_row(conn, rule_id)
            next_word = normalize_trigger(word) if word is not None else current[1]
            next_enabled = bool(enabled) if enabled is not None else bool(current[2])
            with conn:
                conn.execute(
                    "UPDATE dictionary_rules SET word = ?, normalized_word = ?, enabled = ? "
                    "WHERE rule_id = ?",
                    (next_word, next_word.casefold(), int(next_enabled), rule_id),
                )
            return DictionaryEntry(rule_id, next_word, next_enabled)
        finally:
            conn.close()

    def remove_dictionary_word(self, rule_id: int) -> None:
        self._remove("dictionary_rules", rule_id)

    def set_dictionary_enabled(self, rule_id: int, enabled: bool) -> DictionaryEntry:
        return self.update_dictionary_word(rule_id, enabled=enabled)

    def delete_dictionary_word(self, rule_id: int) -> None:
        self.remove_dictionary_word(rule_id)

    def get_dictionary_word(self, rule_id: int) -> DictionaryEntry:
        conn = _connect(self.db_path)
        try:
            row = self._dictionary_row(conn, rule_id)
            return DictionaryEntry(int(row[0]), row[1], bool(row[2]))
        finally:
            conn.close()

    def list_dictionary_words(self, *, include_disabled: bool = True) -> tuple[DictionaryEntry, ...]:
        conn = _connect(self.db_path)
        try:
            query = "SELECT rule_id, word, enabled FROM dictionary_rules"
            if not include_disabled:
                query += " WHERE enabled = 1"
            query += " ORDER BY rule_id"
            return tuple(DictionaryEntry(int(row[0]), row[1], bool(row[2])) for row in conn.execute(query))
        finally:
            conn.close()

    def add_rule(
        self,
        kind: RuleKind | str,
        trigger: str,
        replacement: str,
        *,
        enabled: bool = True,
    ) -> StoredRule:
        rule_kind = RuleKind(kind)
        normalized_trigger = normalize_trigger(trigger)
        if not isinstance(replacement, str) or not replacement.strip():
            raise ValueError("rule replacement must not be blank")
        conn = _connect(self.db_path)
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO writing_rules "
                    "(kind, trigger, normalized_trigger, replacement, enabled) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        rule_kind.value,
                        normalized_trigger,
                        normalized_trigger.casefold(),
                        replacement,
                        int(enabled),
                    ),
                )
                rule_id = int(cursor.lastrowid)
            return StoredRule(rule_id, rule_kind, normalized_trigger, replacement, enabled)
        finally:
            conn.close()

    def add_correction(self, trigger: str, replacement: str, *, enabled: bool = True) -> StoredRule:
        return self.add_rule(RuleKind.CORRECTION, trigger, replacement, enabled=enabled)

    def add_snippet(self, trigger: str, replacement: str, *, enabled: bool = True) -> StoredRule:
        return self.add_rule(RuleKind.SNIPPET, trigger, replacement, enabled=enabled)

    def get_rule(self, kind: RuleKind | str, rule_id: int) -> StoredRule:
        rule_kind = RuleKind(kind)
        conn = _connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT rule_id, kind, trigger, replacement, enabled FROM writing_rules "
                "WHERE rule_id = ? AND kind = ?",
                (rule_id, rule_kind.value),
            ).fetchone()
            if row is None:
                raise KeyError("writing rule not found")
            return StoredRule(int(row[0]), RuleKind(row[1]), row[2], row[3], bool(row[4]))
        finally:
            conn.close()

    def update_rule(
        self,
        kind: RuleKind | str,
        rule_id: int,
        *,
        trigger: str | None = None,
        replacement: str | None = None,
        enabled: bool | None = None,
    ) -> StoredRule:
        current = self.get_rule(kind, rule_id)
        next_trigger = normalize_trigger(trigger) if trigger is not None else current.trigger
        next_replacement = replacement if replacement is not None else current.replacement
        if not isinstance(next_replacement, str) or not next_replacement.strip():
            raise ValueError("rule replacement must not be blank")
        next_enabled = bool(enabled) if enabled is not None else current.enabled
        conn = _connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    "UPDATE writing_rules SET trigger = ?, normalized_trigger = ?, "
                    "replacement = ?, enabled = ? WHERE rule_id = ? AND kind = ?",
                    (
                        next_trigger,
                        next_trigger.casefold(),
                        next_replacement,
                        int(next_enabled),
                        rule_id,
                        current.kind.value,
                    ),
                )
            return StoredRule(
                rule_id,
                current.kind,
                next_trigger,
                next_replacement,
                next_enabled,
            )
        finally:
            conn.close()

    def remove_rule(self, kind: RuleKind | str, rule_id: int) -> None:
        rule_kind = RuleKind(kind)
        conn = _connect(self.db_path)
        try:
            with conn:
                cursor = conn.execute(
                    "DELETE FROM writing_rules WHERE rule_id = ? AND kind = ?",
                    (rule_id, rule_kind.value),
                )
                if cursor.rowcount != 1:
                    raise KeyError("writing rule not found")
        finally:
            conn.close()

    def set_rule_enabled(
        self,
        kind: RuleKind | str,
        rule_id: int,
        enabled: bool,
    ) -> StoredRule:
        return self.update_rule(kind, rule_id, enabled=enabled)

    def delete_rule(self, kind: RuleKind | str, rule_id: int) -> None:
        self.remove_rule(kind, rule_id)

    def list_rules(
        self,
        kind: RuleKind | str,
        *,
        include_disabled: bool = True,
    ) -> tuple[StoredRule, ...]:
        rule_kind = RuleKind(kind)
        conn = _connect(self.db_path)
        try:
            query = (
                "SELECT rule_id, kind, trigger, replacement, enabled FROM writing_rules "
                "WHERE kind = ?"
            )
            params: list[object] = [rule_kind.value]
            if not include_disabled:
                query += " AND enabled = 1"
            query += " ORDER BY rule_id"
            return tuple(
                StoredRule(int(row[0]), RuleKind(row[1]), row[2], row[3], bool(row[4]))
                for row in conn.execute(query, params)
            )
        finally:
            conn.close()

    def test_rule(self, kind: RuleKind | str, rule_id: int, text: str) -> str:
        rule = self.get_rule(kind, rule_id)
        result, _ = apply_rules(text, (rule.to_text_rule(),))
        return result

    def test_dictionary_word(self, rule_id: int, text: str) -> bool:
        word = self.get_dictionary_word(rule_id)
        if not word.enabled:
            return False
        return re.search(
            _WORD_BOUNDARY.format(value=re.escape(word.word)),
            text,
            flags=re.IGNORECASE,
        ) is not None

    def load_writing_settings(self) -> WritingSettings:
        conn = _connect(self.db_path)
        try:
            preferences = self._preferences(conn)
            dictionary = tuple(
                DictionaryEntry(int(row[0]), row[1], bool(row[2]))
                for row in conn.execute(
                    "SELECT rule_id, word, enabled FROM dictionary_rules "
                    "WHERE enabled = 1 ORDER BY rule_id"
                )
            )
            corrections = tuple(
                StoredRule(int(row[0]), RuleKind(row[1]), row[2], row[3], bool(row[4])).to_text_rule()
                for row in conn.execute(
                    "SELECT rule_id, kind, trigger, replacement, enabled FROM writing_rules "
                    "WHERE kind = 'correction' AND enabled = 1 ORDER BY rule_id"
                )
            )
            snippets = tuple(
                StoredRule(int(row[0]), RuleKind(row[1]), row[2], row[3], bool(row[4])).to_text_rule()
                for row in conn.execute(
                    "SELECT rule_id, kind, trigger, replacement, enabled FROM writing_rules "
                    "WHERE kind = 'snippet' AND enabled = 1 ORDER BY rule_id"
                )
            )
            return WritingSettings(
                language=preferences.language,
                style=preferences.style,
                cleanup_policy=preferences.cleanup_policy,
                cleanup_provider_id=preferences.cleanup_provider_id,
                cleanup_network_policy=preferences.cleanup_network_policy,
                cleanup_network_disclosure=preferences.cleanup_network_disclosure,
                cleanup_timeout_seconds=preferences.cleanup_timeout_seconds,
                dictionary_words=tuple(entry.word for entry in dictionary),
                dictionary_rule_ids=tuple(entry.rule_id for entry in dictionary),
                corrections=corrections,
                snippets=snippets,
            )
        finally:
            conn.close()

    def _dictionary_row(self, conn: sqlite3.Connection, rule_id: int) -> tuple[object, ...]:
        row = conn.execute(
            "SELECT rule_id, word, enabled FROM dictionary_rules WHERE rule_id = ?",
            (rule_id,),
        ).fetchone()
        if row is None:
            raise KeyError("dictionary word not found")
        return row

    def _remove(self, table: str, rule_id: int) -> None:
        if table != "dictionary_rules":
            raise ValueError("unsupported settings table")
        conn = _connect(self.db_path)
        try:
            with conn:
                cursor = conn.execute("DELETE FROM dictionary_rules WHERE rule_id = ?", (rule_id,))
                if cursor.rowcount != 1:
                    raise KeyError("dictionary word not found")
        finally:
            conn.close()


class ApplicationSettingsStore(WritingSettingsStore):
    """Named application-settings facade retaining the writing-store API."""


def load_writing_settings(*, db_path: _DBPath = None) -> WritingSettings:
    """Load one immutable per-job writing snapshot."""

    return WritingSettingsStore(db_path).load_writing_settings()


def load_application_settings(*, db_path: _DBPath = None) -> ApplicationSettings:
    return ApplicationSettingsStore(db_path).load_application_settings()


def get_audio_retention(*, db_path: _DBPath = None) -> bool:
    return WritingSettingsStore(db_path).get_audio_retention()


def set_audio_retention(retain_audio: bool, *, db_path: _DBPath = None) -> bool:
    return WritingSettingsStore(db_path).set_audio_retention(retain_audio)


__all__ = [
    "SCHEMA_VERSION",
    "AUDIO_RETENTION_SETTING",
    "ApplicationSettings",
    "ApplicationSettingsStore",
    "ShortcutMode",
    "WritingSettingsStore",
    "data_dir",
    "default_db_path",
    "get",
    "get_audio_retention",
    "load_application_settings",
    "load_writing_settings",
    "selected_model_id",
    "set",
    "set_audio_retention",
    "set_selected_model_id",
]
