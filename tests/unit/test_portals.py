import asyncio

from voxflow.core.capabilities import CapabilityStatus
from voxflow.platform.portals import (
    GLOBAL_SHORTCUTS_INTERFACE,
    GlobalShortcutsPortal,
    PortalClientError,
    PortalErrorCode,
    PortalInterfaceDescription,
)
from voxflow.platform.session import SessionType, detect_session


class FakePortalConnection:
    def __init__(self, introspection=None, error=None) -> None:
        self.introspection = introspection
        self.error = error

    async def introspect(self, bus_name, object_path, interface):
        assert bus_name == "org.freedesktop.portal.Desktop"
        assert object_path == "/org/freedesktop/portal/desktop"
        assert interface == GLOBAL_SHORTCUTS_INTERFACE
        if self.error:
            raise self.error
        return self.introspection

    async def call(self, method, *arguments):
        raise AssertionError(f"unexpected call in portal probe: {method}")

    async def subscribe(self, signal, callback):
        raise AssertionError(f"unexpected subscription in portal probe: {signal}")


def test_session_detection_prefers_explicit_wayland_declaration() -> None:
    info = detect_session(
        {
            "XDG_SESSION_TYPE": "wayland",
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":0",
        }
    )

    assert info.session_type is SessionType.WAYLAND
    assert info.to_dict() == {
        "session_type": "wayland",
        "declared_type": "wayland",
        "wayland_display_present": True,
        "x11_display_present": True,
    }


def test_session_detection_uses_display_fallbacks_and_unknown() -> None:
    assert detect_session({"DISPLAY": ":0"}).session_type is SessionType.X11
    assert detect_session({"WAYLAND_DISPLAY": "wayland-0"}).session_type is SessionType.WAYLAND
    assert detect_session({}).session_type is SessionType.UNKNOWN


def test_portal_probe_reports_version_and_hold_signals() -> None:
    connection = FakePortalConnection(
        PortalInterfaceDescription(
            version=2,
            methods=frozenset({"CreateSession", "BindShortcuts", "ListShortcuts"}),
            signals=frozenset({"Activated", "Deactivated"}),
        )
    )

    result = asyncio.run(GlobalShortcutsPortal(connection).probe())

    assert result.version == 2
    assert result.capability.status is CapabilityStatus.AVAILABLE
    assert result.capabilities[1].id == "shortcut.hold"
    assert result.capabilities[1].status is CapabilityStatus.NEEDS_USER_ACTION


def test_missing_portal_service_is_typed_and_actionable() -> None:
    connection = FakePortalConnection(
        error=PortalClientError(
            PortalErrorCode.SERVICE_UNAVAILABLE,
            "session bus name has no owner",
        )
    )

    result = asyncio.run(GlobalShortcutsPortal(connection).probe())

    assert result.capability.status is CapabilityStatus.UNSUPPORTED
    assert GLOBAL_SHORTCUTS_INTERFACE in result.capability.reason
    assert result.failure is not None
    assert result.failure.code is PortalErrorCode.SERVICE_UNAVAILABLE


def test_permission_denial_and_cancellation_are_not_raw_exceptions() -> None:
    for error, expected in (
        (
            PortalClientError(PortalErrorCode.PERMISSION_DENIED, "user denied"),
            CapabilityStatus.NEEDS_USER_ACTION,
        ),
        (
            asyncio.CancelledError(),
            CapabilityStatus.NEEDS_USER_ACTION,
        ),
    ):
        result = asyncio.run(GlobalShortcutsPortal(FakePortalConnection(error=error)).probe())
        assert result.capability.status is expected
        assert result.failure is not None
        assert result.failure.code in {
            PortalErrorCode.PERMISSION_DENIED,
            PortalErrorCode.CANCELLED,
        }


def test_malformed_portal_description_is_unsupported() -> None:
    result = asyncio.run(
        GlobalShortcutsPortal(
            FakePortalConnection({"version": 2, "methods": "CreateSession"})
        ).probe()
    )

    assert result.capability.status is CapabilityStatus.UNSUPPORTED
    assert result.failure is not None
    assert result.failure.code is PortalErrorCode.MALFORMED_RESPONSE
