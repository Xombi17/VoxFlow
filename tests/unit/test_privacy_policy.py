import json
import sqlite3

import pytest

from voxflow import settings
from voxflow.core.history import AudioRetentionState, HistoryRecord, HistoryStore
from voxflow.providers.config import NetworkPolicy, ProviderKind


def test_application_defaults_are_local_private_and_immutable(tmp_path):
    store = settings.ApplicationSettingsStore(tmp_path / "settings.db")
    snapshot = store.load_application_settings()

    assert snapshot.asr_provider_kind is ProviderKind.LOCAL
    assert snapshot.asr_network_policy is NetworkPolicy.LOCAL_ONLY
    assert snapshot.asr_dispatch_allowed is True
    assert snapshot.retain_audio is False
    assert snapshot.paste_chord == ("Control_L", "v")
    assert "credential" not in json.dumps(snapshot.to_safe_dict()).lower()

    updated = store.update_application_settings(
        microphone_id="fake-mic",
        shortcut_mode="toggle",
        selected_model_id="small.en",
        restore_clipboard=False,
    )
    assert updated.shortcut_mode.value == "toggle"
    assert store.load_application_settings().selected_model_id == "small.en"


@pytest.mark.parametrize(
    "changes",
    [
        {"microphone_id": "/tmp/mic"},
        {"shortcut_trigger": "../trigger"},
        {"shortcut_mode": "press-and-hold"},
        {"paste_chord": "Control_L+NotAKey"},
        {"transfer_timeout_ms": 30_001},
        {"asr_provider_kind": ProviderKind.REMOTE},
        {"cleanup_network_disclosure": True},
    ],
)
def test_invalid_application_updates_are_rejected_before_any_write(tmp_path, changes):
    store = settings.ApplicationSettingsStore(tmp_path / "settings.db")
    before = store.load_application_settings()

    with pytest.raises((TypeError, ValueError)):
        store.update_application_settings(**changes)

    assert store.load_application_settings() == before


def test_remote_settings_require_explicit_disclosure_and_only_safe_metadata(tmp_path):
    store = settings.ApplicationSettingsStore(tmp_path / "settings.db")
    remote = store.update_application_settings(
        asr_provider_kind=ProviderKind.REMOTE,
        asr_provider_id="remote-asr",
        selected_model_id="remote-model",
        asr_network_policy=NetworkPolicy.REMOTE_EXPLICIT,
        asr_network_disclosure=True,
        asr_endpoint_classification="https",
        asr_credential_env_var="VOXFLOW_ASR_TOKEN",
    )

    assert remote.asr_dispatch_allowed is True
    safe = json.dumps(remote.to_safe_dict())
    assert "VOXFLOW_ASR_TOKEN" not in safe
    assert "https://" not in safe


def test_legacy_v1_v2_and_v3_shapes_migrate_forward_and_preserve_rows(tmp_path):
    for version in (1, 2):
        db = tmp_path / f"legacy-{version}.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute(
                "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE writing_preferences ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), language TEXT NOT NULL, style TEXT NOT NULL)"
            )
            conn.execute("INSERT INTO settings VALUES ('selected_model_id', 'small.en')")
            conn.execute("INSERT INTO writing_preferences VALUES (1, 'en-GB', 'work')")
            conn.execute("INSERT INTO schema_meta VALUES ('settings_schema_version', ?)", (version,))
            conn.commit()
        migrated = settings.ApplicationSettingsStore(db)
        assert migrated.load_application_settings().selected_model_id == "small.en"
        assert migrated.get_language() == "en-GB"
        migrated.migrate()
        with sqlite3.connect(db) as conn:
            assert conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'settings_schema_version'"
            ).fetchone() == (settings.SCHEMA_VERSION,)

    db = tmp_path / "legacy-v3.db"
    store = settings.ApplicationSettingsStore(db)
    settings.set_selected_model_id("small.en", db_path=db)
    store.add_correction("teh", "the")
    history = HistoryStore(db)
    history.create_job(HistoryRecord(job_id="kept", status="failed"))
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE schema_meta SET value = 3 WHERE key = 'settings_schema_version'")
        conn.execute("DROP TABLE application_preferences")
        conn.commit()
    migrated = settings.ApplicationSettingsStore(db)
    assert migrated.load_application_settings().selected_model_id == "small.en"
    assert migrated.list_rules("correction")[0].replacement == "the"
    assert HistoryStore(db).show_job("kept").job_id == "kept"
    migrated.migrate()


def test_newer_schema_fails_closed(tmp_path):
    db = tmp_path / "newer.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)"
        )
        conn.execute("INSERT INTO schema_meta VALUES ('settings_schema_version', 999)")
        conn.commit()

    with pytest.raises(RuntimeError, match="newer"):
        settings.ApplicationSettingsStore(db)


def test_explicit_artifact_cleanup_is_opaque_idempotent_and_bounded(tmp_path):
    db = tmp_path / "history.db"
    captures = tmp_path / "captures"
    captures.mkdir()
    store = HistoryStore(db)
    store.create_job(
        HistoryRecord(
            job_id="job-1",
            status="failed",
            artifact_id="job-1.wav",
            retain_audio=True,
            audio_retention_state=AudioRetentionState.RETAINED,
        )
    )
    (captures / "job-1.wav").write_bytes(b"audio")

    cleared = store.clear_artifact("job-1", captures)
    assert cleared.audio_retention_state is AudioRetentionState.DELETED
    assert not (captures / "job-1.wav").exists()
    assert store.clear_artifact("job-1", captures).audio_retention_state is AudioRetentionState.DELETED
