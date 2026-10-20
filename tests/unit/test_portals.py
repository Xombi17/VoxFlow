import asyncio

import pytest

from voxflow.core.capabilities import CapabilityStatus
from voxflow.platform.portals import (
    GLOBAL_SHORTCUTS_INTERFACE,
    DbusNextPortalConnection,
    GlobalShortcutsPortal,
    APP_ID,
    DesktopEntryError,
    PortalClientError,
    PortalErrorCode,
    PortalInterfaceDescription,
    install_desktop_entry,
)
from voxflow.platform.session import SessionType, detect_session


class FakePortalConnection:
    def __init__(self, introspection=None, error=None) -> None:
        self.introspection = introspection
        self.error = error
        self.calls = []
        self.closed_sessions = []
        self.closed = False

    async def introspect(self, bus_name, object_path, interface):
        assert bus_name == "org.freedesktop.portal.Desktop"
        assert object_path == "/org/freedesktop/portal/desktop"
        assert interface == GLOBAL_SHORTCUTS_INTERFACE
        if self.error:
            raise self.error
        return self.introspection

    async def call(self, method, *arguments):
        self.calls.append((method, arguments))
        raise AssertionError(f"unexpected call in portal probe: {method}")

    async def subscribe(self, signal, callback):
        raise AssertionError(f"unexpected subscription in portal probe: {signal}")

    async def close_session(self, session_handle):
        self.closed_sessions.append(session_handle)

    async def close(self):
        self.closed = True


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
    assert detect_session(
        {
            "XDG_SESSION_TYPE": "mir",
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":0",
        }
    ).session_type is SessionType.UNKNOWN


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


def test_portal_probe_accepts_version_one_for_binding() -> None:
    connection = FakePortalConnection(
        PortalInterfaceDescription(
            version=1,
            methods=frozenset({"CreateSession", "BindShortcuts"}),
            signals=frozenset({"Activated", "Deactivated"}),
        )
    )

    result = asyncio.run(GlobalShortcutsPortal(connection).probe())

    assert result.version == 1
    assert result.capability.status is CapabilityStatus.AVAILABLE
    assert result.failure is None


@pytest.mark.parametrize("version", [None, 0])
def test_portal_probe_rejects_missing_or_older_global_shortcuts_version(version) -> None:
    connection = FakePortalConnection(
        PortalInterfaceDescription(
            version=version,
            methods=frozenset({"CreateSession", "BindShortcuts"}),
            signals=frozenset({"Activated", "Deactivated"}),
        )
    )

    result = asyncio.run(GlobalShortcutsPortal(connection).probe())

    assert result.version is version
    assert result.capability.status is CapabilityStatus.UNSUPPORTED
    assert result.failure is not None
    assert result.failure.code is PortalErrorCode.UNSUPPORTED_VERSION
    assert "version 1" in result.failure.reason


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


def test_portal_failure_reason_does_not_expose_backend_details() -> None:
    secret = "/private/desktop/socket backend detail"
    result = asyncio.run(
        GlobalShortcutsPortal(
            FakePortalConnection(
                error=PortalClientError(
                    PortalErrorCode.REQUEST_FAILED,
                    secret,
                )
            )
        ).probe()
    )

    assert result.failure is not None
    assert result.failure.code is PortalErrorCode.REQUEST_FAILED
    assert secret not in result.failure.reason
    assert "Check the desktop portal logs" in result.failure.reason


def test_raw_portal_exception_details_are_not_user_facing() -> None:
    secret = "dbus socket /private/path: backend traceback"
    result = asyncio.run(
        GlobalShortcutsPortal(FakePortalConnection(error=RuntimeError(secret))).probe()
    )

    assert result.failure is not None
    assert result.failure.code is PortalErrorCode.REQUEST_FAILED
    assert secret not in result.failure.reason


def test_permission_denial_is_not_a_raw_exception() -> None:
    error = PortalClientError(PortalErrorCode.PERMISSION_DENIED, "user denied")
    result = asyncio.run(GlobalShortcutsPortal(FakePortalConnection(error=error)).probe())

    assert result.capability.status is CapabilityStatus.NEEDS_USER_ACTION
    assert result.failure is not None
    assert result.failure.code is PortalErrorCode.PERMISSION_DENIED


def test_portal_probe_propagates_task_cancellation() -> None:
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            GlobalShortcutsPortal(
                FakePortalConnection(error=asyncio.CancelledError())
            ).probe()
        )


class TokenPortalConnection(FakePortalConnection):
    async def call(self, method, *arguments):
        self.calls.append((method, arguments))
        if method == "CreateSession":
            return {"session_handle": "/org/freedesktop/portal/session/1"}
        if method == "BindShortcuts":
            return {
                "shortcuts": [
                    (
                        "dictation",
                        {
                            "description": "Hold to dictate",
                            "trigger_description": "Ctrl+Space",
                        },
                    )
                ]
            }
        raise AssertionError(method)


def test_portal_request_tokens_are_unique_and_not_fixed() -> None:
    async def scenario():
        connection = TokenPortalConnection()
        portal = GlobalShortcutsPortal(connection)
        await portal.create_session()
        await portal.bind_shortcut(
            "/org/freedesktop/portal/session/1",
            shortcut_id="dictation",
            description="Hold to dictate",
        )
        return connection.calls

    calls = asyncio.run(scenario())
    create_options = calls[0][1][0]
    bind_options = calls[1][1][3]
    tokens = {
        create_options["handle_token"],
        create_options["session_handle_token"],
        bind_options["handle_token"],
    }
    assert len(tokens) == 3
    assert all(token.startswith("voxflow_") for token in tokens)
    assert "voxflow_session" not in tokens


def test_dbus_bind_shortcuts_uses_list_structs() -> None:
    connection = DbusNextPortalConnection()

    prepared = connection._prepare_arguments(
        "BindShortcuts",
        (
            "/org/freedesktop/portal/session/1",
            (("dictation", {"description": "Hold to dictate"}),),
            "",
            {"handle_token": "voxflow_bind_test"},
        ),
    )

    assert isinstance(prepared[1], list)
    assert isinstance(prepared[1][0], list)
    assert prepared[1][0][0] == "dictation"


def test_dbus_global_shortcuts_use_signal_safe_request_transport() -> None:
    class RequestProbe(DbusNextPortalConnection):
        def __init__(self) -> None:
            super().__init__()
            self.calls = []

        async def call_request(self, interface, method, signature, *arguments, token):
            self.calls.append((interface, method, signature, arguments, token))
            return {}

    connection = RequestProbe()

    async def scenario() -> None:
        await connection.call(
            "CreateSession",
            {
                "handle_token": "voxflow_create_test",
                "session_handle_token": "voxflow_session_test",
            },
        )
        await connection.call(
            "BindShortcuts",
            "/org/freedesktop/portal/session/1",
            (("dictation", {"description": "Hold to dictate"}),),
            "",
            {"handle_token": "voxflow_bind_test"},
        )

    asyncio.run(scenario())

    assert connection.calls[0][1:3] == ("CreateSession", "a{sv}")
    assert connection.calls[0][-1] == "voxflow_create_test"
    assert connection.calls[1][1:3] == ("BindShortcuts", "oa(sa{sv})sa{sv}")
    assert connection.calls[1][-1] == "voxflow_bind_test"


def test_dbus_shortcut_signal_adapter_matches_signal_arity() -> None:
    class SignalInterface:
        def __init__(self) -> None:
            self.activated = None
            self.removed = None

        def on_activated(self, callback) -> None:
            self.activated = callback

        def off_activated(self, callback) -> None:
            self.removed = callback

    interface = SignalInterface()
    connection = DbusNextPortalConnection()
    connection._portal_interface = interface
    received = []

    async def scenario() -> None:
        unsubscribe = await connection.subscribe(
            "Activated", lambda *arguments: received.append(arguments)
        )
        assert interface.activated is not None
        interface.activated("/session", "dictation", 42, {})
        unsubscribe()

    asyncio.run(scenario())

    assert received == [("/session", "dictation", 42, {})]
    assert interface.removed is interface.activated


def test_portal_close_uses_injected_session_and_transport_boundaries() -> None:
    closed_sessions = []
    closed_transports = []
    portal = GlobalShortcutsPortal(
        FakePortalConnection(),
        close_session=lambda handle: closed_sessions.append(handle),
        close=lambda: closed_transports.append(True),
    )

    async def scenario():
        await portal.close_session("/org/freedesktop/portal/session/1")
        await portal.close()

    asyncio.run(scenario())

    assert closed_sessions == ["/org/freedesktop/portal/session/1"]
    assert closed_transports == [True]


def test_malformed_portal_description_is_unsupported() -> None:
    result = asyncio.run(
        GlobalShortcutsPortal(
            FakePortalConnection({"version": 2, "methods": "CreateSession"})
        ).probe()
    )

    assert result.capability.status is CapabilityStatus.UNSUPPORTED
    assert result.failure is not None
    assert result.failure.code is PortalErrorCode.MALFORMED_RESPONSE


class RegistryConnection(FakePortalConnection):
    def __init__(self, register_error=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.register_error = register_error
        self.events = []

    async def introspect(self, bus_name, object_path, interface):
        self.events.append("introspect")
        return await super().introspect(bus_name, object_path, interface)

    async def call(self, method, *arguments):
        self.events.append(method)
        return {"session_handle": "/s"}

    async def call_interface(self, interface, method, signature, *arguments):
        self.events.append((interface, method, signature, arguments))
        if self.register_error:
            raise self.register_error


DESCRIPTION = PortalInterfaceDescription(
    version=2,
    methods={"CreateSession", "BindShortcuts"},
    signals={"Activated", "Deactivated"},
)


def test_register_app_id_runs_once_before_shortcuts_calls() -> None:
    conn = RegistryConnection(introspection=DESCRIPTION)
    portal = GlobalShortcutsPortal(conn)

    async def run():
        await portal.probe()
        await portal.create_session()

    asyncio.run(run())
    assert conn.events[0][1:] == ("Register", "sa{sv}", (APP_ID, {}))
    assert conn.events[1:] == ["introspect", "CreateSession"]


def test_register_app_id_failure_is_typed_warning_not_fatal() -> None:
    conn = RegistryConnection(
        register_error=PortalClientError(PortalErrorCode.SERVICE_UNAVAILABLE, "no registry"),
        introspection=DESCRIPTION,
    )
    portal = GlobalShortcutsPortal(conn)
    result = asyncio.run(portal.probe())
    assert result.supported
    assert portal.registration_failure.code is PortalErrorCode.SERVICE_UNAVAILABLE
    assert "app id not registered" in result.capabilities[-1].reason
    assert sum(1 for e in conn.events if isinstance(e, tuple)) == 1  # not retried


def test_install_desktop_entry_copies_and_refuses_symlinks(tmp_path) -> None:
    src = tmp_path / "src.desktop"
    src.write_text("[Desktop Entry]\n")
    dest = install_desktop_entry(src, tmp_path / "ok")
    assert dest.read_text() == "[Desktop Entry]\n"

    target = tmp_path / "elsewhere"
    target.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "applications").symlink_to(target)
    with pytest.raises(DesktopEntryError):
        install_desktop_entry(src, linked)
    assert not list(target.iterdir())

    file_link = tmp_path / "fl"
    (file_link / "applications").mkdir(parents=True)
    (file_link / "applications" / "dev.voxflow.VoxFlow.desktop").symlink_to(tmp_path / "x")
    with pytest.raises(DesktopEntryError):
        install_desktop_entry(src, file_link)
    assert not (tmp_path / "x").exists()


def test_install_desktop_entry_pins_absolute_exec(tmp_path) -> None:
    # GLib drops entries whose Exec program is unresolvable; portal then says "App info not found".
    src = tmp_path / "src.desktop"
    src.write_text("[Desktop Entry]\nExec=voxflow daemon\nName=X\n")
    text = install_desktop_entry(src, tmp_path / "ok").read_text()
    exec_line = next(line for line in text.splitlines() if line.startswith("Exec="))
    assert exec_line.split()[0].startswith("Exec=/")
    assert "Name=X" in text
