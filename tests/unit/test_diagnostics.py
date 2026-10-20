import json

from voxflow.__main__ import diagnostic, main
from voxflow.core.capabilities import CapabilityRecord, CapabilityStatus
from voxflow.core.diagnostics import build_diagnostics
from voxflow.core.history import HistoryRecord, HistoryStore
from voxflow.settings import ApplicationSettingsStore


def test_diagnostics_are_allow_listed_and_redact_content_paths_and_secrets(tmp_path, capsys):
    db = tmp_path / "diagnostics.db"
    store = ApplicationSettingsStore(db)
    history = HistoryStore(db)
    history.create_job(
        HistoryRecord(
            job_id="job-1",
            status="failed",
            raw_text="private transcript should never be listed",
            final_text="private final text",
            provider_id="/home/user/provider-token",
            model_id="secret-token",
            provider_metadata={
                "endpoint": "https://private.example/v1",
                "credential": "credential-value",
            },
            failure_reason="private exception /home/user/details",
        )
    )
    payload = build_diagnostics(
        settings_store=store,
        history=history,
        capabilities=(
            CapabilityRecord(
                "fake.capability",
                CapabilityStatus.UNAVAILABLE,
                "backend failed /home/user/private transcript token",
            ),
        ),
    )
    safe = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "private transcript",
        "private final text",
        "https://private.example",
        "credential-value",
        "/home/user",
    ):
        assert forbidden not in safe
    assert payload["history"]["job_count"] == 1
    assert payload["settings"]["asr_network_policy"] == "local_only"

    assert main(["--json", "--db", str(db)]) == 0
    output = capsys.readouterr().out
    for forbidden in ("private transcript", "private final text", "https://private.example", "/home/user"):
        assert forbidden not in output


def test_default_diagnostic_does_not_open_or_serialize_local_history(capsys):
    payload = diagnostic()
    assert payload["app"] == "voxflow"
    assert "history" not in payload
    assert "platform" not in payload
    assert main([]) == 0
    assert "raw_text" not in capsys.readouterr().out
