import json

from voxflow.__main__ import main as cli_main
from voxflow.ui import settings as settings_ui


def test_headless_settings_controller_loads_updates_reloads_and_redacts(tmp_path):
    controller = settings_ui.SettingsController(tmp_path / "settings.db")
    initial = controller.load().to_dict()
    assert initial["settings"]["asr_network_policy"] == "local_only"
    assert initial["settings"]["retain_audio"] is False

    updated = controller.update(
        microphone_id="fake-mic",
        shortcut_trigger="Ctrl+Space",
        shortcut_mode="toggle",
        language="en-GB",
        style="work",
        selected_model_id="small.en",
        retain_audio=True,
        paste_chord=["Control_L", "Shift_L", "v"],
    )
    assert updated.ok is True
    reloaded = controller.load().to_dict()["settings"]
    assert reloaded["microphone_id"] == "fake-mic"
    assert reloaded["shortcut_mode"] == "toggle"
    assert reloaded["language"] == "en-GB"
    assert reloaded["retain_audio"] is True
    assert reloaded["paste_chord"] == ["Control_L", "Shift_L", "v"]

    invalid = controller.update(shortcut_trigger="/not-a-trigger")
    assert invalid.ok is False
    assert invalid.code == "invalid_settings"
    assert controller.snapshot().shortcut_mode.value == "toggle"


def test_settings_json_dispatch_is_headless_and_does_not_import_gtk(tmp_path, capsys):
    db = tmp_path / "settings.db"
    assert cli_main(["settings", "--json", "--db", str(db)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["settings"]["asr_network_policy"] == "local_only"
    assert payload["settings"]["retain_audio"] is False
    assert "gi" not in settings_ui.__dict__


def test_settings_reports_typed_missing_gtk_result_without_host_checks(tmp_path, monkeypatch, capsys):
    def missing_gtk():
        raise settings_ui.GtkUnavailable

    monkeypatch.setattr(settings_ui, "_gtk_modules", missing_gtk)
    assert settings_ui.main(["--db", str(tmp_path / "settings.db")]) == 4
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["code"] == "gtk_unavailable"
    assert result["data"]["capability"]["status"] == "unavailable"
