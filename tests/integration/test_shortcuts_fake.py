import asyncio

import pytest

from voxflow.core.capabilities import CapabilityStatus
from voxflow.core.state import SessionState
from voxflow.platform.portals import (
    GlobalShortcutsPortal,
    PortalClientError,
    PortalErrorCode,
    PortalInterfaceDescription,
)
from voxflow.platform.shortcuts import (
    GlobalShortcutsAdapter,
    ShortcutEventType,
)


class FakePortalConnection:
    def __init__(
        self,
        *,
        bindings=None,
        bind_error=None,
        include_deactivated=True,
        subscribe_errors=None,
    ):
        self.bindings = bindings
        self.bind_error = bind_error
        self.include_deactivated = include_deactivated
        self.subscribe_errors = subscribe_errors or {}
        self.callbacks = {}
        self.calls = []
        self.closed_sessions = []
        self.closed = False

    async def introspect(self, bus_name, object_path, interface):
        signals = {"Activated"}
        if self.include_deactivated:
            signals.add("Deactivated")
        return PortalInterfaceDescription(
            version=2,
            methods=frozenset({"CreateSession", "BindShortcuts"}),
            signals=frozenset(signals),
        )

    async def call(self, method, *arguments):
        self.calls.append((method, arguments))
        if method == "CreateSession":
            return {"session_handle": "/org/freedesktop/portal/session/1"}
        if self.bind_error:
            raise self.bind_error
        if method == "BindShortcuts":
            return {
                "shortcuts": self.bindings
                if self.bindings is not None
                else [
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

    async def subscribe(self, signal, callback):
        if signal in self.subscribe_errors:
            raise self.subscribe_errors[signal]
        self.callbacks[signal] = callback

        def unsubscribe():
            self.callbacks.pop(signal, None)

        return unsubscribe

    async def close_session(self, session_handle):
        self.closed_sessions.append(session_handle)

    async def close(self):
        self.closed = True

    def emit(self, signal, *arguments):
        return self.callbacks[signal](*arguments)


def test_fake_activation_and_deactivation_emit_core_events() -> None:
    async def scenario():
        connection = FakePortalConnection()
        events = []
        adapter = GlobalShortcutsAdapter(
            GlobalShortcutsPortal(connection), listener=events.append
        )

        setup = await adapter.configure()
        started = connection.emit(
            "Activated",
            "/org/freedesktop/portal/session/1",
            "dictation",
            10,
            {},
        )
        stopped = connection.emit(
            "Deactivated",
            "/org/freedesktop/portal/session/1",
            "dictation",
            20,
            {},
        )

        return setup, adapter, events, started, stopped

    setup, adapter, events, started, stopped = asyncio.run(scenario())

    assert setup.configured
    assert started.type is ShortcutEventType.LISTENING_STARTED
    assert started.state is SessionState.LISTENING
    assert stopped.type is ShortcutEventType.LISTENING_STOPPED
    assert stopped.state is SessionState.PROCESSING
    assert started.trigger_description == "Ctrl+Space"
    assert events == [started, stopped]
    assert adapter.hold_supported
    assert setup.capabilities[1].status is CapabilityStatus.NEEDS_USER_ACTION
    assert adapter.capabilities[1].status is CapabilityStatus.AVAILABLE


def test_activation_only_portal_reports_toggle_limitation() -> None:
    async def scenario():
        connection = FakePortalConnection(include_deactivated=False)
        adapter = GlobalShortcutsAdapter(GlobalShortcutsPortal(connection))
        setup = await adapter.configure()
        event = connection.emit(
            "Activated",
            "/org/freedesktop/portal/session/1",
            "dictation",
            10,
            {},
        )
        return setup, adapter, event

    setup, adapter, event = asyncio.run(scenario())

    assert event.type is ShortcutEventType.LISTENING_STARTED
    assert not adapter.hold_supported
    assert setup.capabilities[1].status is CapabilityStatus.UNSUPPORTED
    assert "toggle" in setup.capabilities[1].reason


def test_binding_error_is_typed_and_actionable() -> None:
    async def scenario():
        connection = FakePortalConnection(
            bind_error=PortalClientError(
                PortalErrorCode.PERMISSION_DENIED,
                "user denied the portal dialog",
            )
        )
        return await GlobalShortcutsAdapter(GlobalShortcutsPortal(connection)).configure()

    setup = asyncio.run(scenario())

    assert not setup.configured
    assert setup.failure is not None
    assert setup.failure.code is PortalErrorCode.PERMISSION_DENIED
    assert setup.capabilities[0].status is CapabilityStatus.NEEDS_USER_ACTION
    assert "Approve" in setup.capabilities[0].reason


def test_empty_binding_is_a_typed_configuration_failure() -> None:
    async def scenario():
        connection = FakePortalConnection(bindings=[])
        return await GlobalShortcutsAdapter(GlobalShortcutsPortal(connection)).configure()

    setup = asyncio.run(scenario())

    assert not setup.configured
    assert setup.failure is not None
    assert setup.failure.code is PortalErrorCode.REQUEST_FAILED
    assert setup.capabilities[0].status is CapabilityStatus.NEEDS_USER_ACTION
    assert "no binding" in setup.capabilities[0].reason


def test_deactivated_subscription_failure_cleans_up_activated_and_session() -> None:
    async def scenario():
        connection = FakePortalConnection(
            subscribe_errors={
                "Deactivated": PortalClientError(
                    PortalErrorCode.REQUEST_FAILED,
                    "backend leaked private detail",
                )
            }
        )
        adapter = GlobalShortcutsAdapter(GlobalShortcutsPortal(connection))
        setup = await adapter.configure()
        return connection, adapter, setup

    connection, adapter, setup = asyncio.run(scenario())

    assert not setup.configured
    assert setup.session_handle is None
    assert setup.binding is None
    assert setup.failure is not None
    assert setup.failure.code is PortalErrorCode.REQUEST_FAILED
    assert "backend leaked private detail" not in setup.failure.reason
    assert connection.callbacks == {}
    assert connection.closed_sessions == ["/org/freedesktop/portal/session/1"]
    assert not adapter.hold_supported


def test_configuration_cancellation_propagates_and_cleans_partial_setup() -> None:
    async def scenario():
        connection = FakePortalConnection(
            subscribe_errors={"Deactivated": asyncio.CancelledError()}
        )
        adapter = GlobalShortcutsAdapter(GlobalShortcutsPortal(connection))
        with pytest.raises(asyncio.CancelledError):
            await adapter.configure()
        return connection, adapter

    connection, adapter = asyncio.run(scenario())

    assert connection.callbacks == {}
    assert connection.closed_sessions == ["/org/freedesktop/portal/session/1"]
    assert not adapter.hold_supported


def test_close_unsubscribes_releases_session_and_closes_transport() -> None:
    async def scenario():
        connection = FakePortalConnection()
        adapter = GlobalShortcutsAdapter(GlobalShortcutsPortal(connection))
        setup = await adapter.configure()
        failure = await adapter.close()
        return connection, adapter, setup, failure

    connection, adapter, setup, failure = asyncio.run(scenario())

    assert setup.configured
    assert failure is None
    assert connection.callbacks == {}
    assert connection.closed_sessions == ["/org/freedesktop/portal/session/1"]
    assert connection.closed
    assert not adapter.capabilities
    assert not adapter.hold_supported
