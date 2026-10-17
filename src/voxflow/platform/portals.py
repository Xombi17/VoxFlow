"""Typed, injectable access to the XDG GlobalShortcuts portal.

The core client talks to a small async connection protocol.  This keeps the
offline test suite independent of D-Bus and lets a host install an optional
``dbus-next`` bridge without making it a runtime dependency of VoxFlow.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import secrets
import shutil
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from enum import StrEnum
from typing import Any, Protocol

from ..core.capabilities import CapabilityRecord, CapabilityStatus

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
GLOBAL_SHORTCUTS_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
SESSION_INTERFACE = "org.freedesktop.portal.Session"
MIN_GLOBAL_SHORTCUTS_VERSION = 2
APP_ID = "dev.voxflow.VoxFlow"
REGISTRY_INTERFACE = "org.freedesktop.host.portal.Registry"
DESKTOP_ENTRY_NAME = f"{APP_ID}.desktop"
REMOTE_DESKTOP_INTERFACE = "org.freedesktop.portal.RemoteDesktop"
CLIPBOARD_INTERFACE = "org.freedesktop.portal.Clipboard"
DEVICE_KEYBOARD = 1  # T-02.1-05: keyboard only, never pointer/ScreenCast
PERSIST_UNTIL_REVOKED = 2


class PortalErrorCode(StrEnum):
    """Stable failure codes emitted by portal capability probes."""

    SERVICE_UNAVAILABLE = "service_unavailable"
    PERMISSION_DENIED = "permission_denied"
    CANCELLED = "cancelled"
    MALFORMED_RESPONSE = "malformed_response"
    REQUEST_FAILED = "request_failed"
    UNSUPPORTED_VERSION = "unsupported_version"


class PortalClientError(RuntimeError):
    """A normalized portal failure with a stable machine-readable code."""

    def __init__(
        self,
        code: PortalErrorCode,
        detail: str,
        *,
        dbus_name: str | None = None,
    ) -> None:
        self.code = PortalErrorCode(code)
        self.detail = detail.strip() or self.code.value
        self.dbus_name = dbus_name
        super().__init__(self.detail)


@dataclass(frozen=True, slots=True)
class PortalFailure:
    """A normalized error suitable for a capability record or diagnostic."""

    code: PortalErrorCode
    status: CapabilityStatus
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "status": self.status.value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PortalInterfaceDescription:
    """The subset of D-Bus introspection needed by the shortcut adapter."""

    interface: str = GLOBAL_SHORTCUTS_INTERFACE
    version: int | None = None
    methods: frozenset[str] = frozenset()
    signals: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.interface.strip():
            raise ValueError("portal interface must not be blank")
        if self.version is not None and self.version < 0:
            raise ValueError("portal interface version must not be negative")
        object.__setattr__(self, "methods", frozenset(self.methods))
        object.__setattr__(self, "signals", frozenset(self.signals))


SignalCallback = Callable[..., object]
Unsubscribe = Callable[[], object]


class PortalConnection(Protocol):
    """Minimal async D-Bus boundary implemented by real and fake transports."""

    async def introspect(
        self,
        bus_name: str,
        object_path: str,
        interface: str,
    ) -> PortalInterfaceDescription | Mapping[str, object]: ...

    async def call(self, method: str, *arguments: object) -> object: ...

    async def call_interface(
        self,
        interface: str,
        method: str,
        signature: str,
        *arguments: object,
    ) -> object: ...

    async def subscribe(self, signal: str, callback: SignalCallback) -> Unsubscribe: ...

    async def close_session(self, session_handle: str) -> object: ...

    async def close(self) -> object: ...


@dataclass(frozen=True, slots=True)
class PortalProbeResult:
    """Serializable result of inspecting GlobalShortcuts."""

    interface: str
    version: int | None
    methods: tuple[str, ...]
    signals: tuple[str, ...]
    capabilities: tuple[CapabilityRecord, ...]
    failure: PortalFailure | None = None

    @property
    def capability(self) -> CapabilityRecord:
        """Compatibility convenience for callers checking the primary feature."""

        return self.capabilities[0]

    @property
    def supported(self) -> bool:
        return self.capability.status is CapabilityStatus.AVAILABLE

    def to_dict(self) -> dict[str, object]:
        return {
            "interface": self.interface,
            "version": self.version,
            "methods": list(self.methods),
            "signals": list(self.signals),
            "capabilities": [capability.to_dict() for capability in self.capabilities],
            "failure": self.failure.to_dict() if self.failure else None,
        }


@dataclass(frozen=True, slots=True)
class BoundShortcut:
    """A shortcut returned by a successful portal binding request."""

    id: str
    description: str
    trigger_description: str


def map_portal_error(error: BaseException, *, interface: str = GLOBAL_SHORTCUTS_INTERFACE) -> PortalFailure:
    """Map transport/D-Bus failures to actionable, typed capability results."""

    if isinstance(error, PortalClientError):
        code = error.code
        detail = error.detail
    else:
        name = str(getattr(error, "name", "")).lower()
        detail = str(error).strip() or error.__class__.__name__
        text = f"{name} {detail}".lower()
        if isinstance(error, asyncio.CancelledError) or "cancel" in text:
            code = PortalErrorCode.CANCELLED
        elif any(
            marker in text
            for marker in (
                "accessdenied",
                "notallowed",
                "permission",
                "not allowed",
                "denied",
            )
        ):
            code = PortalErrorCode.PERMISSION_DENIED
        elif any(
            marker in text
            for marker in (
                "serviceunknown",
                "name has no owner",
                "not found",
                "unavailable",
                "unknownmethod",
                "unknowninterface",
                "unknownobject",
                "dbus-next is not installed",
            )
        ):
            code = PortalErrorCode.SERVICE_UNAVAILABLE
        elif isinstance(error, (TypeError, KeyError, ValueError)):
            code = PortalErrorCode.MALFORMED_RESPONSE
        else:
            code = PortalErrorCode.REQUEST_FAILED

    if code is PortalErrorCode.PERMISSION_DENIED:
        status = CapabilityStatus.NEEDS_USER_ACTION
        reason = (
            f"{interface} permission was denied. Approve the desktop "
            "portal request and try again."
        )
    elif code is PortalErrorCode.CANCELLED:
        status = CapabilityStatus.NEEDS_USER_ACTION
        reason = (
            f"The {interface} request was cancelled. Re-run the setup "
            "and approve the shortcut request when prompted."
        )
    elif code is PortalErrorCode.SERVICE_UNAVAILABLE:
        status = CapabilityStatus.UNSUPPORTED
        reason = (
            f"{interface} is unavailable. Use a desktop portal backend "
            "that implements GlobalShortcuts version 2."
        )
    elif code is PortalErrorCode.UNSUPPORTED_VERSION:
        status = CapabilityStatus.UNSUPPORTED
        reason = (
            f"{interface} does not provide the required version "
            f"{MIN_GLOBAL_SHORTCUTS_VERSION}. Upgrade or select a desktop portal "
            "backend that implements GlobalShortcuts version 2."
        )
    elif code is PortalErrorCode.MALFORMED_RESPONSE:
        status = CapabilityStatus.UNSUPPORTED
        reason = (
            f"{interface} returned a malformed response. Check the "
            "portal backend version before enabling global shortcuts."
        )
    else:
        status = CapabilityStatus.UNSUPPORTED
        reason = f"{interface} request failed. Check the desktop portal logs."

    return PortalFailure(code=code, status=status, reason=reason)


def capability_for_failure(
    failure: PortalFailure,
    *,
    capability_id: str = "shortcut.global",
) -> CapabilityRecord:
    """Turn a normalized portal failure into the shared core capability type."""

    return CapabilityRecord(
        id=capability_id,
        status=failure.status,
        reason=failure.reason,
    )


def _description_from_mapping(
    value: PortalInterfaceDescription | Mapping[str, object],
) -> PortalInterfaceDescription:
    if isinstance(value, PortalInterfaceDescription):
        return value
    try:
        raw_version = value.get("version")
        version = None if raw_version is None else int(raw_version)
        methods = value.get("methods", ())
        signals = value.get("signals", ())
        if isinstance(methods, (str, bytes)) or isinstance(signals, (str, bytes)):
            raise TypeError("methods and signals must be sequences")
        return PortalInterfaceDescription(
            interface=str(value.get("interface", GLOBAL_SHORTCUTS_INTERFACE)),
            version=version,
            methods=frozenset(str(item) for item in methods),
            signals=frozenset(str(item) for item in signals),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise PortalClientError(
            PortalErrorCode.MALFORMED_RESPONSE,
            f"invalid interface description: {exc}",
        ) from exc


def _extract_string(value: object, *, field: str) -> str:
    value = _unwrap_dbus_value(value)
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, Mapping):
        candidate = _unwrap_dbus_value(value.get(field))
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    raise PortalClientError(
        PortalErrorCode.MALFORMED_RESPONSE,
        f"portal response did not contain a non-empty {field}",
    )


def _extract_shortcuts(value: object) -> tuple[BoundShortcut, ...]:
    value = _unwrap_dbus_value(value)
    if isinstance(value, Mapping):
        value = _unwrap_dbus_value(value.get("shortcuts"))
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PortalClientError(
            PortalErrorCode.MALFORMED_RESPONSE,
            "portal response did not contain a shortcuts sequence",
        )

    bound: list[BoundShortcut] = []
    for item in value:
        if not isinstance(item, Sequence) or len(item) != 2:
            raise PortalClientError(
                PortalErrorCode.MALFORMED_RESPONSE,
                "portal shortcut entry must be a two-item sequence",
            )
        shortcut_id, properties = item
        if not isinstance(shortcut_id, str) or not isinstance(properties, Mapping):
            raise PortalClientError(
                PortalErrorCode.MALFORMED_RESPONSE,
                "portal shortcut entry has invalid ID or properties",
            )
        description = _unwrap_dbus_value(properties.get("description", ""))
        trigger = _unwrap_dbus_value(properties.get("trigger_description", ""))
        if not isinstance(description, str) or not isinstance(trigger, str):
            raise PortalClientError(
                PortalErrorCode.MALFORMED_RESPONSE,
                "portal shortcut descriptions must be strings",
            )
        bound.append(
            BoundShortcut(
                id=shortcut_id,
                description=description,
                trigger_description=trigger,
            )
        )
    return tuple(bound)


def _unwrap_dbus_value(value: object) -> object:
    """Read a dbus-next Variant without requiring dbus-next in core tests."""

    if value.__class__.__name__ == "Variant" and hasattr(value, "value"):
        return _unwrap_dbus_value(value.value)
    return value


def _request_token(kind: str) -> str:
    """Return a unique, valid object-path token for one portal request."""

    return f"voxflow_{kind}_{secrets.token_hex(16)}"


class GlobalShortcutsPortal:
    """Portal client for probing and using one GlobalShortcuts session."""

    def __init__(
        self,
        connection: PortalConnection | None = None,
        *,
        close_session: Callable[[str], object] | None = None,
        close: Callable[[], object] | None = None,
    ) -> None:
        self.connection = connection or DbusNextPortalConnection()
        self._close_session_boundary = close_session
        self._close_boundary = close
        self._registered = False
        self.registration_failure: PortalFailure | None = None

    async def register_app_id(self) -> bool:
        """Register APP_ID with the portal Registry once per connection.

        Failure is recorded in ``registration_failure`` and is not fatal:
        older portals lack the Registry interface.
        """

        if self._registered:
            return True
        self._registered = True  # one attempt per connection, even on failure
        try:
            await self.connection.call_interface(
                REGISTRY_INTERFACE, "Register", "sa{sv}", APP_ID, {}
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.registration_failure = map_portal_error(exc, interface=REGISTRY_INTERFACE)
            return False
        self.registration_failure = None
        return True

    async def probe(self) -> PortalProbeResult:
        """Introspect GlobalShortcuts without creating a session or binding keys."""

        result = await self._probe_shortcuts()
        if self.registration_failure is None:
            return result
        unregistered = CapabilityRecord(
            id="portal.app_id",
            status=CapabilityStatus.NEEDS_USER_ACTION,
            reason="app id not registered: run `voxflow install-identity` and retry.",
        )
        return PortalProbeResult(
            interface=result.interface,
            version=result.version,
            methods=result.methods,
            signals=result.signals,
            capabilities=(*result.capabilities, unregistered),
            failure=result.failure,
        )

    async def _probe_shortcuts(self) -> PortalProbeResult:
        await self.register_app_id()
        try:
            raw = await self.connection.introspect(
                PORTAL_BUS_NAME,
                PORTAL_OBJECT_PATH,
                GLOBAL_SHORTCUTS_INTERFACE,
            )
            description = _description_from_mapping(raw)
            methods = tuple(sorted(description.methods))
            signals = tuple(sorted(description.signals))
            if (
                description.version is None
                or description.version < MIN_GLOBAL_SHORTCUTS_VERSION
            ):
                failure = map_portal_error(
                    PortalClientError(
                        PortalErrorCode.UNSUPPORTED_VERSION,
                        "GlobalShortcuts version is missing or older than version 2",
                    )
                )
                return PortalProbeResult(
                    interface=description.interface,
                    version=description.version,
                    methods=methods,
                    signals=signals,
                    capabilities=(capability_for_failure(failure),),
                    failure=failure,
                )
            required_methods = {"CreateSession", "BindShortcuts"}
            if not required_methods.issubset(description.methods):
                failure = map_portal_error(
                    PortalClientError(
                        PortalErrorCode.MALFORMED_RESPONSE,
                        "required CreateSession or BindShortcuts method is missing",
                    )
                )
                return PortalProbeResult(
                    interface=description.interface,
                    version=description.version,
                    methods=methods,
                    signals=signals,
                    capabilities=(capability_for_failure(failure),),
                    failure=failure,
                )

            global_capability = CapabilityRecord(
                id="shortcut.global",
                status=CapabilityStatus.AVAILABLE,
                reason=(
                    f"{GLOBAL_SHORTCUTS_INTERFACE} is available"
                    + (
                        f" at version {description.version}."
                        if description.version is not None
                        else "."
                    )
                    + " Bind a shortcut through the desktop portal before use."
                ),
            )
            if "Activated" in description.signals and "Deactivated" in description.signals:
                hold_capability = CapabilityRecord(
                    id="shortcut.hold",
                    status=CapabilityStatus.NEEDS_USER_ACTION,
                    reason=(
                        "Activation and deactivation signals are exposed. Run the "
                        "binding smoke test to confirm hold/release behavior."
                    ),
                )
            else:
                hold_capability = CapabilityRecord(
                    id="shortcut.hold",
                    status=CapabilityStatus.UNSUPPORTED,
                    reason=(
                        "The portal does not expose both Activated and Deactivated; "
                        "push-to-talk hold/release is unavailable, so use toggle behavior."
                    ),
                )
            return PortalProbeResult(
                interface=description.interface,
                version=description.version,
                methods=methods,
                signals=signals,
                capabilities=(global_capability, hold_capability),
            )
        except Exception as exc:
            failure = map_portal_error(exc)
        return PortalProbeResult(
            interface=GLOBAL_SHORTCUTS_INTERFACE,
            version=None,
            methods=(),
            signals=(),
            capabilities=(capability_for_failure(failure),),
            failure=failure,
        )

    async def create_session(self) -> str:
        """Create a portal session and return its object path."""

        await self.register_app_id()
        handle_token = _request_token("request")
        session_handle_token = _request_token("session")
        try:
            response = await self.connection.call(
                "CreateSession",
                {
                    "handle_token": handle_token,
                    "session_handle_token": session_handle_token,
                },
            )
            return _extract_string(response, field="session_handle")
        except asyncio.CancelledError:
            raise
        except PortalClientError:
            raise
        except Exception as exc:
            failure = map_portal_error(exc)
            raise PortalClientError(failure.code, failure.reason) from exc

    async def bind_shortcut(
        self,
        session_handle: str,
        *,
        shortcut_id: str,
        description: str,
        preferred_trigger: str | None = None,
    ) -> tuple[BoundShortcut, ...]:
        """Perform the portal's one-time binding request for one shortcut."""

        if not session_handle.strip():
            raise ValueError("session_handle must not be blank")
        if not shortcut_id.strip() or not description.strip():
            raise ValueError("shortcut ID and description must not be blank")
        properties: dict[str, str] = {"description": description}
        if preferred_trigger:
            properties["preferred_trigger"] = preferred_trigger
        try:
            response = await self.connection.call(
                "BindShortcuts",
                session_handle,
                ((shortcut_id, properties),),
                "",
                {"handle_token": _request_token("bind")},
            )
            return _extract_shortcuts(response)
        except asyncio.CancelledError:
            raise
        except PortalClientError:
            raise
        except Exception as exc:
            failure = map_portal_error(exc)
            raise PortalClientError(failure.code, failure.reason) from exc

    async def subscribe(self, signal: str, callback: SignalCallback) -> Unsubscribe:
        """Subscribe to one portal signal through the injected connection."""

        if signal not in {"Activated", "Deactivated", "ShortcutsChanged"}:
            raise ValueError(f"unsupported GlobalShortcuts signal: {signal}")
        return await self.connection.subscribe(signal, callback)

    async def close_session(self, session_handle: str) -> None:
        """Release a session when the transport exposes the shared close API.

        Older or minimal injected transports may not implement this boundary.
        In that case the local adapter still clears its state, while the
        transport's documented limitation is that the desktop session can only
        be reclaimed when the client disappears from D-Bus.
        """

        if not session_handle.strip():
            raise ValueError("session_handle must not be blank")
        closer = self._close_session_boundary
        if closer is None:
            closer = getattr(self.connection, "close_session", None)
        if closer is None:
            return
        try:
            result = closer(session_handle)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except PortalClientError:
            raise
        except Exception as exc:
            failure = map_portal_error(exc, interface=SESSION_INTERFACE)
            raise PortalClientError(failure.code, failure.reason) from exc

    async def close(self) -> None:
        """Close the injectable transport if it provides a close boundary."""

        closer = self._close_boundary
        if closer is None:
            closer = getattr(self.connection, "close", None)
        if closer is None:
            return
        try:
            result = closer()
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except PortalClientError:
            raise
        except Exception as exc:
            failure = map_portal_error(exc, interface=SESSION_INTERFACE)
            raise PortalClientError(failure.code, failure.reason) from exc


def _error_code(dbus_name: str | None) -> PortalErrorCode:
    name = (dbus_name or "").lower()
    if "unknown" in name or "serviceunknown" in name:
        return PortalErrorCode.SERVICE_UNAVAILABLE
    if "notallowed" in name or "accessdenied" in name:
        return PortalErrorCode.PERMISSION_DENIED
    return PortalErrorCode.REQUEST_FAILED


def _variant(value: object) -> object:
    from dbus_next import Variant  # type: ignore[import-not-found]

    if isinstance(value, bool):
        return Variant("b", value)
    if isinstance(value, int):
        return Variant("u", value)
    if isinstance(value, str):
        return Variant("s", value)
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return Variant("as", list(value))
    return value


def _variant_dict(options: Mapping[str, object]) -> dict[str, object]:
    return {key: _variant(value) for key, value in options.items()}


class RemoteDesktopPortal:
    """One keyboard RemoteDesktop session with Clipboard enabled (D-08)."""

    def __init__(
        self,
        connection: Any | None = None,
        *,
        token_loader: Callable[[], str | None] | None = None,
        token_saver: Callable[[str], object] | None = None,
    ) -> None:
        from . import restore_token

        self.connection = connection or DbusNextPortalConnection()
        self._load = token_loader or restore_token.load
        self._save = token_saver or restore_token.store
        self.session_handle: str | None = None
        self._unsubscribes: list[Unsubscribe] = []

    async def _guard(self, interface: str, awaitable: Awaitable[Any]) -> Any:
        try:
            return await awaitable
        except (asyncio.CancelledError, PortalClientError):
            raise
        except Exception as exc:
            failure = map_portal_error(exc, interface=interface)
            raise PortalClientError(failure.code, failure.reason) from exc

    async def open_session(self) -> str:
        """CreateSession, SelectDevices, RequestClipboard, Start; persist token."""

        conn = self.connection
        results = await self._guard(
            REMOTE_DESKTOP_INTERFACE,
            conn.call_request(
                REMOTE_DESKTOP_INTERFACE,
                "CreateSession",
                "a{sv}",
                {
                    "handle_token": (t := _request_token("request")),
                    "session_handle_token": _request_token("session"),
                },
                token=t,
            ),
        )
        session = _extract_string(results, field="session_handle")
        self.session_handle = session
        options: dict[str, object] = {
            "types": DEVICE_KEYBOARD,
            "persist_mode": PERSIST_UNTIL_REVOKED,
        }
        stored = self._load()
        if stored:
            options["restore_token"] = stored
        await self._guard(
            REMOTE_DESKTOP_INTERFACE,
            conn.call_request(
                REMOTE_DESKTOP_INTERFACE,
                "SelectDevices",
                "oa{sv}",
                session,
                {**options, "handle_token": (t := _request_token("select"))},
                token=t,
            ),
        )
        await self._guard(
            CLIPBOARD_INTERFACE,
            conn.call_interface(CLIPBOARD_INTERFACE, "RequestClipboard", "oa{sv}", session, {}),
        )
        started = await self._guard(
            REMOTE_DESKTOP_INTERFACE,
            conn.call_request(
                REMOTE_DESKTOP_INTERFACE,
                "Start",
                "osa{sv}",
                session,
                "",
                {"handle_token": (t := _request_token("start"))},
                token=t,
            ),
        )
        new_token = started.get("restore_token") if isinstance(started, Mapping) else None
        if new_token and new_token != stored:
            self._save(str(new_token))
        if not (isinstance(started, Mapping) and started.get("clipboard_enabled")):
            raise PortalClientError(
                PortalErrorCode.SERVICE_UNAVAILABLE,
                "RemoteDesktop session started without clipboard access",
            )
        return session

    def _session(self) -> str:
        if self.session_handle is None:
            raise PortalClientError(
                PortalErrorCode.REQUEST_FAILED, "RemoteDesktop session is not open"
            )
        return self.session_handle

    async def set_selection(self, mime_types: Sequence[str]) -> None:
        await self._guard(
            CLIPBOARD_INTERFACE,
            self.connection.call_interface(
                CLIPBOARD_INTERFACE,
                "SetSelection",
                "oa{sv}",
                self._session(),
                {"mime_types": list(mime_types)},
            ),
        )

    async def selection_write(self, serial: int) -> int:
        return await self._guard(
            CLIPBOARD_INTERFACE,
            self.connection.call_fd(
                CLIPBOARD_INTERFACE, "SelectionWrite", "ou", self._session(), serial
            ),
        )

    async def selection_write_done(self, serial: int, ok: bool) -> None:
        await self._guard(
            CLIPBOARD_INTERFACE,
            self.connection.call_interface(
                CLIPBOARD_INTERFACE,
                "SelectionWriteDone",
                "oub",
                self._session(),
                serial,
                bool(ok),
            ),
        )

    async def connect_to_eis(self) -> int:
        return await self._guard(
            REMOTE_DESKTOP_INTERFACE,
            self.connection.call_fd(
                REMOTE_DESKTOP_INTERFACE, "ConnectToEIS", "oa{sv}", self._session(), {}
            ),
        )

    async def subscribe(self, signal: str, callback: Callable[..., object]) -> None:
        """SelectionTransfer -> callback(mime, serial); SelectionOwnerChanged -> callback(is_owner)."""

        if signal not in {"SelectionTransfer", "SelectionOwnerChanged"}:
            raise ValueError(f"unsupported Clipboard signal: {signal}")
        session = self._session()

        def on_signal(handle: str, *rest: object) -> None:
            if handle != session:
                return
            if signal == "SelectionTransfer":
                mime, serial = rest
                callback(mime, int(serial))  # type: ignore[call-overload]
            else:
                options = rest[0] if rest else {}
                owner = _unwrap_dbus_value(options.get("session_is_owner", False))  # type: ignore[attr-defined]
                callback(bool(owner))

        self._unsubscribes.append(
            await self._guard(
                CLIPBOARD_INTERFACE,
                self.connection.subscribe_signal(CLIPBOARD_INTERFACE, signal, on_signal),
            )
        )

    async def close(self) -> None:
        for off in self._unsubscribes:
            off()
        self._unsubscribes.clear()
        handle, self.session_handle = self.session_handle, None
        try:
            if handle:
                await self.connection.close_session(handle)
        finally:
            await self.connection.close()


class DbusNextPortalConnection:
    """Optional lazy ``dbus-next`` transport for a live desktop probe.

    ``dbus-next`` is intentionally not a package dependency for the offline
    core.  If it is not installed, calls return the same typed unavailable
    result as any other missing portal service.
    """

    def __init__(self) -> None:
        self._bus: Any | None = None
        self._portal_interface: Any | None = None
        self._portal_proxy: Any | None = None

    async def _connect_bus(self) -> Any:
        if self._bus is not None:
            return self._bus
        try:
            from dbus_next.aio import MessageBus  # type: ignore[import-not-found]
            from dbus_next.constants import BusType  # type: ignore[import-not-found]
        except ImportError as exc:
            raise PortalClientError(
                PortalErrorCode.SERVICE_UNAVAILABLE,
                "dbus-next is not installed for the live portal transport",
            ) from exc
        try:
            self._bus = await MessageBus(bus_type=BusType.SESSION, negotiate_unix_fd=True).connect()
        except Exception as exc:
            failure = map_portal_error(exc)
            raise PortalClientError(failure.code, failure.reason) from exc
        return self._bus

    async def call_interface(
        self,
        interface: str,
        method: str,
        signature: str,
        *arguments: object,
    ) -> object:
        """Call a method on the portal object; returns the reply body."""

        from dbus_next import Message, MessageType, Variant  # type: ignore[import-not-found]

        bus = await self._connect_bus()
        reply = await self._send(interface, method, signature, arguments)
        return reply.body

    async def _send(
        self,
        interface: str,
        method: str,
        signature: str,
        arguments: Sequence[object],
        unix_fds: Sequence[int] = (),
    ) -> Any:
        from dbus_next import Message, MessageType  # type: ignore[import-not-found]

        bus = await self._connect_bus()
        body = [
            _variant_dict(a) if isinstance(a, Mapping) else a for a in arguments
        ]
        try:
            reply = await bus.call(
                Message(
                    destination=PORTAL_BUS_NAME,
                    path=PORTAL_OBJECT_PATH,
                    interface=interface,
                    member=method,
                    signature=signature,
                    body=body,
                    unix_fds=list(unix_fds),
                )
            )
        except Exception as exc:
            failure = map_portal_error(exc, interface=interface)
            raise PortalClientError(failure.code, failure.reason) from exc
        if reply.message_type == MessageType.ERROR:
            failure = map_portal_error(
                PortalClientError(
                    _error_code(reply.error_name), f"{reply.error_name} {reply.body}"
                ),
                interface=interface,
            )
            raise PortalClientError(failure.code, failure.reason)
        return reply

    async def call_fd(
        self, interface: str, method: str, signature: str, *arguments: object
    ) -> int:
        """Call a method whose reply is a single unix fd (signature 'h')."""

        reply = await self._send(interface, method, signature, arguments)
        try:
            return int(reply.unix_fds[reply.body[0]])
        except (IndexError, TypeError, ValueError) as exc:
            raise PortalClientError(
                PortalErrorCode.MALFORMED_RESPONSE, f"{method} returned no fd"
            ) from exc

    async def call_request(
        self,
        interface: str,
        method: str,
        signature: str,
        *arguments: object,
        token: str,
    ) -> Mapping[str, object]:
        """Call a Request-style method and return its Response results.

        The Response match is installed before the call so a fast portal
        cannot answer before we listen (handle_token predicts the path).
        """

        from dbus_next import MessageType  # type: ignore[import-not-found]

        bus = await self._connect_bus()
        sender = bus.unique_name[1:].replace(".", "_")
        path = f"{PORTAL_OBJECT_PATH}/request/{sender}/{token}"
        future: asyncio.Future[Mapping[str, object]] = (
            asyncio.get_running_loop().create_future()
        )

        def handler(msg: Any) -> None:
            if (
                msg.message_type != MessageType.SIGNAL
                or msg.path != path
                or msg.member != "Response"
                or future.done()
            ):
                return
            code, results = msg.body
            if code == 0:
                future.set_result(
                    {k: _unwrap_dbus_value(v) for k, v in dict(results).items()}
                )
            elif code == 1:
                future.set_exception(
                    PortalClientError(
                        PortalErrorCode.CANCELLED, "the user cancelled the portal request"
                    )
                )
            else:
                future.set_exception(
                    PortalClientError(
                        PortalErrorCode.REQUEST_FAILED,
                        f"portal request returned response code {code}",
                    )
                )

        await self._add_match(REQUEST_INTERFACE, path)
        bus.add_message_handler(handler)
        try:
            await self._send(interface, method, signature, arguments)
            return await future
        finally:
            bus.remove_message_handler(handler)

    async def _add_match(self, interface: str, path: str | None = None) -> None:
        from dbus_next import Message  # type: ignore[import-not-found]

        rule = f"type='signal',interface='{interface}'"
        if path:
            rule += f",path='{path}'"
        bus = await self._connect_bus()
        await bus.call(
            Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=[rule],
            )
        )

    async def subscribe_signal(
        self, interface: str, signal: str, callback: SignalCallback
    ) -> Unsubscribe:
        """Subscribe to an arbitrary portal signal; callback gets the body."""

        from dbus_next import MessageType  # type: ignore[import-not-found]

        bus = await self._connect_bus()

        def handler(msg: Any) -> None:
            if (
                msg.message_type == MessageType.SIGNAL
                and msg.interface == interface
                and msg.member == signal
            ):
                callback(*msg.body)

        await self._add_match(interface)
        bus.add_message_handler(handler)
        return lambda: bus.remove_message_handler(handler)

    async def _load_portal_interface(self) -> Any:
        if self._portal_interface is not None:
            return self._portal_interface
        await self._connect_bus()
        try:
            introspection = await self._bus.introspect(
                PORTAL_BUS_NAME,
                PORTAL_OBJECT_PATH,
            )
            self._portal_proxy = self._bus.get_proxy_object(
                PORTAL_BUS_NAME,
                PORTAL_OBJECT_PATH,
                introspection,
            )
            self._portal_interface = self._portal_proxy.get_interface(
                GLOBAL_SHORTCUTS_INTERFACE
            )
            return self._portal_interface
        except PortalClientError:
            raise
        except Exception as exc:
            failure = map_portal_error(exc)
            raise PortalClientError(failure.code, failure.reason) from exc

    async def introspect(
        self,
        bus_name: str,
        object_path: str,
        interface: str,
    ) -> PortalInterfaceDescription:
        """Read interface members and the live ``version`` property."""

        if (bus_name, object_path, interface) != (
            PORTAL_BUS_NAME,
            PORTAL_OBJECT_PATH,
            GLOBAL_SHORTCUTS_INTERFACE,
        ):
            raise ValueError("unsupported portal introspection target")
        iface = await self._load_portal_interface()
        try:
            version = await iface.get_version()
        except AttributeError:
            version = None
        methods = set()
        signals = set()
        node = getattr(self._portal_proxy, "introspection", None)
        for item in getattr(node, "interfaces", ()):
            if getattr(item, "name", None) != GLOBAL_SHORTCUTS_INTERFACE:
                continue
            methods.update(getattr(member, "name", "") for member in item.methods)
            signals.update(getattr(member, "name", "") for member in item.signals)
        return PortalInterfaceDescription(
            version=int(version) if version is not None else None,
            methods=frozenset(item for item in methods if item),
            signals=frozenset(item for item in signals if item),
        )

    async def call(self, method: str, *arguments: object) -> object:
        """Call a portal method and await its standard Request::Response."""

        iface = await self._load_portal_interface()
        method_name = re.sub(r"(?<!^)(?=[A-Z])", "_", method).lower()
        caller = getattr(iface, f"call_{method_name}", None)
        if caller is None:
            raise PortalClientError(
                PortalErrorCode.MALFORMED_RESPONSE,
                f"portal method {method} is not available",
            )
        prepared = self._prepare_arguments(method, arguments)
        request_path = await caller(*prepared)
        return await self._await_request(request_path)

    def _prepare_arguments(self, method: str, arguments: Sequence[object]) -> tuple[object, ...]:
        try:
            from dbus_next import Variant  # type: ignore[import-not-found]
        except ImportError:
            return tuple(arguments)

        def variants(value: object) -> dict[str, object]:
            if not isinstance(value, Mapping):
                raise TypeError("portal options must be mappings")
            converted: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("portal option keys must be strings")
                if isinstance(item, bool):
                    converted[key] = Variant("b", item)
                elif isinstance(item, str):
                    converted[key] = Variant("s", item)
                else:
                    converted[key] = item
            return converted

        if method == "CreateSession":
            return (variants(arguments[0]),)
        if method == "BindShortcuts":
            session_handle, shortcuts, parent, options = arguments
            converted_shortcuts = []
            for shortcut_id, properties in shortcuts:  # type: ignore[misc]
                converted_shortcuts.append((shortcut_id, variants(properties)))
            return (
                session_handle,
                converted_shortcuts,
                parent,
                variants(options),
            )
        return tuple(arguments)

    async def _await_request(self, request_path: object) -> Mapping[str, object]:
        if not isinstance(request_path, str) or not request_path.startswith("/"):
            raise PortalClientError(
                PortalErrorCode.MALFORMED_RESPONSE,
                "portal method returned an invalid request object path",
            )
        assert self._bus is not None
        try:
            introspection = await self._bus.introspect(PORTAL_BUS_NAME, request_path)
            proxy = self._bus.get_proxy_object(PORTAL_BUS_NAME, request_path, introspection)
            request = proxy.get_interface(REQUEST_INTERFACE)
        except Exception as exc:
            failure = map_portal_error(exc)
            raise PortalClientError(failure.code, failure.reason) from exc

        loop = asyncio.get_running_loop()
        response_future: asyncio.Future[Mapping[str, object]] = loop.create_future()

        def on_response(response_code: int, results: Mapping[str, object]) -> None:
            if response_future.done():
                return
            if response_code == 0:
                response_future.set_result(dict(results))
            elif response_code == 1:
                response_future.set_exception(
                    PortalClientError(
                        PortalErrorCode.CANCELLED,
                        "the user cancelled the portal request",
                    )
                )
            else:
                response_future.set_exception(
                    PortalClientError(
                        PortalErrorCode.REQUEST_FAILED,
                        f"portal request returned response code {response_code}",
                    )
                )

        request.on_response(on_response)
        try:
            return await response_future
        finally:
            off_response = getattr(request, "off_response", None)
            if off_response is not None:
                off_response(on_response)

    async def subscribe(self, signal: str, callback: SignalCallback) -> Unsubscribe:
        iface = await self._load_portal_interface()
        normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", signal).lower()
        on_signal = getattr(iface, f"on_{normalized}", None)
        off_signal = getattr(iface, f"off_{normalized}", None)
        if on_signal is None:
            raise PortalClientError(
                PortalErrorCode.MALFORMED_RESPONSE,
                f"portal signal {signal} is not available",
            )
        on_signal(callback)

        def unsubscribe() -> None:
            if off_signal is not None:
                off_signal(callback)

        return unsubscribe

    async def close_session(self, session_handle: str) -> None:
        """Close a GlobalShortcuts session through org.freedesktop.portal.Session."""

        if not session_handle.strip():
            raise ValueError("session_handle must not be blank")
        if self._bus is None:
            return
        try:
            introspection = await self._bus.introspect(
                PORTAL_BUS_NAME,
                session_handle,
            )
            proxy = self._bus.get_proxy_object(
                PORTAL_BUS_NAME,
                session_handle,
                introspection,
            )
            session = proxy.get_interface(SESSION_INTERFACE)
            close = getattr(session, "call_close", None)
            if close is None:
                raise PortalClientError(
                    PortalErrorCode.MALFORMED_RESPONSE,
                    "portal session close method is not available",
                )
            await close()
        except asyncio.CancelledError:
            raise
        except PortalClientError:
            raise
        except Exception as exc:
            failure = map_portal_error(exc, interface=SESSION_INTERFACE)
            raise PortalClientError(failure.code, failure.reason) from exc

    async def close(self) -> None:
        """Disconnect the D-Bus transport and forget proxy state."""

        bus = self._bus
        self._bus = None
        self._portal_interface = None
        self._portal_proxy = None
        if bus is None:
            return
        try:
            disconnect = getattr(bus, "disconnect", None)
            if disconnect is not None:
                result = disconnect()
                if inspect.isawaitable(result):
                    await result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = map_portal_error(exc, interface=SESSION_INTERFACE)
            raise PortalClientError(failure.code, failure.reason) from exc


class UnavailablePortalConnection:
    """Explicit fake transport for callers that want no live desktop access."""

    async def introspect(
        self,
        bus_name: str,
        object_path: str,
        interface: str,
    ) -> PortalInterfaceDescription:
        raise PortalClientError(
            PortalErrorCode.SERVICE_UNAVAILABLE,
            f"no connection is available for {interface}",
        )

    async def call(self, method: str, *arguments: object) -> object:
        raise PortalClientError(
            PortalErrorCode.SERVICE_UNAVAILABLE,
            f"no connection is available for {GLOBAL_SHORTCUTS_INTERFACE}",
        )

    async def call_interface(
        self,
        interface: str,
        method: str,
        signature: str,
        *arguments: object,
    ) -> object:
        raise PortalClientError(
            PortalErrorCode.SERVICE_UNAVAILABLE,
            f"no connection is available for {interface}",
        )

    async def subscribe(self, signal: str, callback: SignalCallback) -> Unsubscribe:
        raise PortalClientError(
            PortalErrorCode.SERVICE_UNAVAILABLE,
            f"no connection is available for {GLOBAL_SHORTCUTS_INTERFACE}",
        )

    async def call_request(self, interface: str, *args: object, **kw: object) -> object:
        return await self.call_interface(interface, "", "")

    call_fd = call_request

    async def subscribe_signal(self, interface: str, *args: object) -> Unsubscribe:
        return await self.call_interface(interface, "", "")  # type: ignore[return-value]

    async def close_session(self, session_handle: str) -> None:
        return None

    async def close(self) -> None:
        return None


class DesktopEntryError(RuntimeError):
    """Refusal to install the desktop entry (for example, symlink target)."""


def install_desktop_entry(
    source: Path | None = None,
    data_home: Path | None = None,
) -> Path:
    """Copy the .desktop file into ``$XDG_DATA_HOME/applications``.

    Refuses to write through a symlinked applications directory or destination.
    """

    source = source or Path(__file__).resolve().parents[3] / "packaging" / DESKTOP_ENTRY_NAME
    if data_home is None:
        data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    apps = data_home / "applications"
    destination = apps / DESKTOP_ENTRY_NAME
    for path in (apps, destination):
        if os.path.islink(path):
            raise DesktopEntryError(f"refusing to write through symlink: {path}")
    if not source.is_file():
        raise DesktopEntryError(f"desktop entry source not found: {source}")
    apps.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return destination


def install_identity_main(argv: Sequence[str] = ()) -> int:
    """CLI wrapper for ``voxflow install-identity``."""

    try:
        print(install_desktop_entry())
    except DesktopEntryError as exc:
        print(f"install-identity: {exc}")
        return 1
    return 0
