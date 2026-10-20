import json

import pytest

from voxflow.__main__ import diagnostic, main, platform_diagnostic
from voxflow.core.capabilities import (
    CAPABILITY_STATUS_ORDER,
    CapabilityRecord,
    CapabilityStatus,
    status_rank,
)
from voxflow.platform.portals import (
    GLOBAL_SHORTCUTS_INTERFACE,
    PortalProbeResult,
    PortalClientError,
    PortalErrorCode,
    insertion_capability_for_error,
)
from voxflow.platform.session import detect_session


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
        CapabilityStatus.UNAVAILABLE,
        CapabilityStatus.UNSUPPORTED,
    )
    assert status_rank("available") < status_rank("unsupported")


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            PortalClientError(PortalErrorCode.PERMISSION_DENIED, "/private/secret"),
            CapabilityStatus.NEEDS_USER_ACTION,
        ),
        (
            PortalClientError(PortalErrorCode.SERVICE_UNAVAILABLE, "/private/secret"),
            CapabilityStatus.UNAVAILABLE,
        ),
        (
            PortalClientError(PortalErrorCode.MALFORMED_RESPONSE, "/private/secret"),
            CapabilityStatus.UNSUPPORTED,
        ),
        (
            PortalClientError(PortalErrorCode.UNSUPPORTED_METHOD, "/private/secret"),
            CapabilityStatus.UNSUPPORTED,
        ),
    ],
)
def test_insertion_capability_maps_actionable_redacted_statuses(error, expected) -> None:
    capability = insertion_capability_for_error(error)

    assert capability.status is expected
    assert capability.id == "insertion.portal"
    assert "/private/secret" not in capability.reason


def test_platform_diagnostic_exposes_insertion_probe_metadata() -> None:
    portal = PortalProbeResult(
        interface=GLOBAL_SHORTCUTS_INTERFACE,
        version=1,
        methods=("BindShortcuts", "CreateSession"),
        signals=("Activated", "Deactivated"),
        capabilities=(
            CapabilityRecord(
                "shortcut.global",
                CapabilityStatus.AVAILABLE,
                "shortcut portal ready",
            ),
        ),
    )
    result = platform_diagnostic(
        session_info=detect_session({"XDG_SESSION_TYPE": "wayland"}),
        portal_result=portal,
        insertion={
            "capability": CapabilityRecord(
                "insertion.portal",
                CapabilityStatus.NEEDS_USER_ACTION,
                "Approve insertion consent.",
            ).to_dict(),
            "consent_required": True,
            "restore_token_reused": False,
        },
    )

    assert result["insertion"] == {
        "capability": {
            "id": "insertion.portal",
            "status": "needs_user_action",
            "reason": "Approve insertion consent.",
        },
        "consent_required": True,
        "restore_token_reused": False,
    }


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
