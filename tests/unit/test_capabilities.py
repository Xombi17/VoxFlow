import json

from voxflow.__main__ import diagnostic, main
from voxflow.core.capabilities import (
    CAPABILITY_STATUS_ORDER,
    CapabilityRecord,
    CapabilityStatus,
    status_rank,
)


def test_bootstrap_diagnostic_is_json_serializable() -> None:
    payload = diagnostic()

    assert json.loads(json.dumps(payload)) == {
        "app": "voxflow",
        "capabilities": [],
        "state": {"failure_reason": None, "state": "idle"},
        "version": "0.1.0",
    }


def test_capability_record_preserves_id_status_and_reason() -> None:
    capability = CapabilityRecord(
        id="shortcut.global",
        status=CapabilityStatus.NEEDS_USER_ACTION,
        reason="Approve the shortcut permission in the desktop portal.",
    )

    assert capability.to_dict() == {
        "id": "shortcut.global",
        "status": "needs_user_action",
        "reason": "Approve the shortcut permission in the desktop portal.",
    }
    assert json.loads(capability.to_json()) == capability.to_dict()


def test_capability_status_order_is_stable() -> None:
    assert CAPABILITY_STATUS_ORDER == (
        CapabilityStatus.AVAILABLE,
        CapabilityStatus.NEEDS_USER_ACTION,
        CapabilityStatus.UNSUPPORTED,
    )
    assert status_rank("available") < status_rank("unsupported")


def test_diagnostic_includes_capability_and_state_contracts() -> None:
    capability = CapabilityRecord(
        id="microphone.default",
        status=CapabilityStatus.AVAILABLE,
        reason="Default input is ready.",
    )

    payload = diagnostic(capabilities=[capability])

    assert payload["capabilities"] == [
        {
            "id": "microphone.default",
            "status": "available",
            "reason": "Default input is ready.",
        }
    ]
    assert payload["state"] == {"state": "idle", "failure_reason": None}


def test_json_entrypoint_emits_parseable_core_diagnostic(capsys) -> None:
    assert main(["--json"]) == 0

    output = json.loads(capsys.readouterr().out)

    assert output["app"] == "voxflow"
    assert output["capabilities"] == []
    assert output["state"]["state"] == "idle"
