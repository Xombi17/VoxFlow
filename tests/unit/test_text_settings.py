import sqlite3

import pytest

from voxflow import settings
from voxflow.providers.config import NetworkPolicy
from voxflow.text.contracts import CleanupPolicy, WritingStyle
from voxflow.text.rules import RuleKind


def test_migration_is_versioned_idempotent_and_preserves_selected_model(tmp_path):
    db = tmp_path / "writing.db"
    settings.set_selected_model_id("small.en", db_path=db)
    store = settings.WritingSettingsStore(db)
    store.migrate()

    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'settings_schema_version'"
        ).fetchone() == (settings.SCHEMA_VERSION,)
        assert conn.execute(
            "SELECT value FROM settings WHERE key = 'selected_model_id'"
        ).fetchone() == ("small.en",)


def test_legacy_writing_preferences_gain_cleanup_defaults_during_migration(tmp_path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE writing_preferences ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), "
            "language TEXT NOT NULL DEFAULT 'auto', "
            "style TEXT NOT NULL DEFAULT 'personal')"
        )
        conn.execute(
            "INSERT INTO writing_preferences (id, language, style) VALUES (1, 'en-US', 'work')"
        )
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('settings_schema_version', 1)"
        )
        conn.commit()

    snapshot = settings.WritingSettingsStore(db).load_writing_settings()

    assert snapshot.language == "en-US"
    assert snapshot.style is WritingStyle.WORK
    assert snapshot.cleanup_policy is CleanupPolicy.DETERMINISTIC
    assert snapshot.cleanup_provider_id == "deterministic"
    assert snapshot.cleanup_network_policy is NetworkPolicy.LOCAL_ONLY
    assert snapshot.cleanup_network_disclosure is False
    assert snapshot.cleanup_timeout_seconds == 30.0


def test_preferences_rules_crud_and_enabled_state_round_trip(tmp_path):
    store = settings.WritingSettingsStore(tmp_path / "writing.db")

    assert store.load_writing_settings().language == "auto"
    store.set_preferences(language="en-US", style=WritingStyle.EMAIL)
    dictionary = store.add_dictionary_word(" VoxFlow ")
    correction = store.add_correction("adress", "address")
    snippet = store.add_snippet("my status", "I am making progress")

    assert store.get_language() == "en-US"
    assert store.get_style() is WritingStyle.EMAIL
    assert store.get_dictionary_word(dictionary.rule_id).word == "VoxFlow"
    assert store.test_dictionary_word(dictionary.rule_id, "VoxFlow is here") is True
    assert store.get_rule(RuleKind.CORRECTION, correction.rule_id).replacement == "address"
    assert store.test_rule(RuleKind.SNIPPET, snippet.rule_id, "my status") == "I am making progress"

    store.update_dictionary_word(dictionary.rule_id, word="Vox Flow", enabled=False)
    store.update_rule(RuleKind.CORRECTION, correction.rule_id, replacement="address", enabled=False)
    assert store.list_dictionary_words(include_disabled=False) == ()
    assert store.list_rules(RuleKind.CORRECTION, include_disabled=False) == ()

    store.remove_dictionary_word(dictionary.rule_id)
    store.remove_rule(RuleKind.SNIPPET, snippet.rule_id)
    assert store.list_dictionary_words() == ()
    assert store.list_rules(RuleKind.SNIPPET) == ()


def test_cleanup_preferences_persist_in_writing_snapshot(tmp_path):
    store = settings.WritingSettingsStore(tmp_path / "writing.db")

    configured = store.set_cleanup_preferences(
        cleanup_policy=CleanupPolicy.PROVIDER,
        cleanup_provider_id="remote-cleanup",
        cleanup_network_policy=NetworkPolicy.REMOTE_EXPLICIT,
        cleanup_network_disclosure=True,
        cleanup_timeout_seconds=12.5,
    )
    snapshot = store.load_writing_settings()

    assert configured.cleanup_policy is CleanupPolicy.PROVIDER
    assert snapshot.cleanup_policy is CleanupPolicy.PROVIDER
    assert snapshot.cleanup_provider_id == "remote-cleanup"
    assert snapshot.cleanup_network_policy is NetworkPolicy.REMOTE_EXPLICIT
    assert snapshot.cleanup_network_disclosure is True
    assert snapshot.cleanup_timeout_seconds == 12.5


def test_invalid_values_are_rejected_without_partial_updates(tmp_path):
    store = settings.WritingSettingsStore(tmp_path / "writing.db")
    correction = store.add_correction("adress", "address")

    with pytest.raises(ValueError, match="replacement"):
        store.update_rule(RuleKind.CORRECTION, correction.rule_id, replacement=" ")
    with pytest.raises(ValueError, match="language"):
        store.set_language("not a language")
    with pytest.raises(ValueError, match="style"):
        store.set_style("unsupported")
    with pytest.raises(ValueError, match="trigger"):
        store.add_snippet("  ", "replacement")
    with pytest.raises(ValueError, match="replacement"):
        store.add_snippet("trigger", " ")

    assert store.get_rule(RuleKind.CORRECTION, correction.rule_id).replacement == "address"
    assert store.load_writing_settings().language == "auto"
    assert store.load_writing_settings().style is WritingStyle.PERSONAL


def test_loaded_writing_settings_are_isolated_from_later_database_edits(tmp_path):
    store = settings.WritingSettingsStore(tmp_path / "writing.db")
    store.set_preferences(language="en-GB", style="work")
    dictionary = store.add_dictionary_word("PostgreSQL")
    correction = store.add_correction("teh", "the")
    snippet = store.add_snippet("stand up", "daily stand-up")

    snapshot = store.load_writing_settings()
    store.update_dictionary_word(dictionary.rule_id, word="SQLite")
    store.update_rule(RuleKind.CORRECTION, correction.rule_id, replacement="a")
    store.remove_rule(RuleKind.SNIPPET, snippet.rule_id)
    store.set_preferences(language="fr", style="other")

    assert snapshot.language == "en-GB"
    assert snapshot.style is WritingStyle.WORK
    assert snapshot.dictionary_words == ("postgresql",)
    assert snapshot.dictionary_rule_ids == (dictionary.rule_id,)
    assert snapshot.corrections[0].replacement == "the"
    assert snapshot.snippets[0].replacement == "daily stand-up"
    safe = str(snapshot.to_safe_dict())
    assert "PostgreSQL" not in safe
    assert "daily stand-up" not in safe


def test_application_snapshot_keeps_writing_rules_and_selected_model_authoritative(tmp_path):
    db = tmp_path / "application.db"
    store = settings.ApplicationSettingsStore(db)
    correction = store.add_correction("teh", "the")
    settings.set_selected_model_id("small.en", db_path=db)

    store.update_application_settings(language="en-GB", style=WritingStyle.WORK, retain_audio=True)
    snapshot = store.load_application_settings()

    assert snapshot.selected_model_id == "small.en"
    assert snapshot.language == "en-GB"
    assert snapshot.style is WritingStyle.WORK
    assert snapshot.retain_audio is True
    assert store.get_rule(RuleKind.CORRECTION, correction.rule_id).replacement == "the"
