"""GlobalShortcuts adapter that emits typed dictation events."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..core.capabilities import CapabilityRecord, CapabilityStatus
from ..core.state import SessionState
from .portals import (
    BoundShortcut,
    GlobalShortcutsPortal,
    PortalClientError,
    PortalErrorCode,
    PortalFailure,
    capability_for_failure,
    map_portal_error,
)


class ShortcutEventType(StrEnum):
    """Events emitted by the compositor-mediated shortcut signal pair."""

    LISTENING_STARTED = "listening_started"
    LISTENING_STOPPED = "listening_stopped"


@dataclass(frozen=True, slots=True)
class ShortcutEvent:
    """A shortcut signal translated into a core-facing dictation event."""

    type: ShortcutEventType
    shortcut_id: str
    session_handle: str
    timestamp: int
    trigger_description: str

    @property
    def state(self) -> SessionState:
        """Return the state boundary the application should enter next."""

        if self.type is ShortcutEventType.LISTENING_STARTED:
            return SessionState.LISTENING
        return SessionState.PROCESSING

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.type.value,
            "shortcut_id": self.shortcut_id,
            "session_handle": self.session_handle,
            "timestamp": self.timestamp,
            "trigger_description": self.trigger_description,
            "state": self.state.value,
        }


@dataclass(frozen=True, slots=True)
class ShortcutSetupResult:
    """Result of configuring the one-time GlobalShortcuts binding."""

    session_handle: str | None
    binding: BoundShortcut | None
    capabilities: tuple[CapabilityRecord, ...]
    failure: PortalFailure | None = None

    @property
    def configured(self) -> bool:
        return self.binding is not None and self.session_handle is not None

    @property
    def hold_supported(self) -> bool:
        return any(
            capability.id == "shortcut.hold"
            and capability.status is CapabilityStatus.AVAILABLE
            for capability in self.capabilities
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "session_handle": self.session_handle,
            "binding": (
                {
                    "id": self.binding.id,
                    "description": self.binding.description,
                    "trigger_description": self.binding.trigger_description,
                }
                if self.binding
                else None
            ),
            "capabilities": [capability.to_dict() for capability in self.capabilities],
            "failure": self.failure.to_dict() if self.failure else None,
        }


EventListener = Callable[[ShortcutEvent], object]


class GlobalShortcutsAdapter:
    """Bind one configured trigger and translate its signals into events.

    The adapter never starts capture itself.  A core orchestrator can attach a
    listener and decide how the event changes the dictation state machine.
    """

    def __init__(
        self,
        portal: GlobalShortcutsPortal,
        *,
        shortcut_id: str = "dictation",
        description: str = "Hold to dictate",
        preferred_trigger: str | None = None,
        listener: EventListener | None = None,
    ) -> None:
        if not shortcut_id.strip():
            raise ValueError("shortcut_id must not be blank")
        if not description.strip():
            raise ValueError("description must not be blank")
        self.portal = portal
        self.shortcut_id = shortcut_id
        self.description = description
        self.preferred_trigger = preferred_trigger
        self._listeners: list[EventListener] = []
        if listener is not None:
            self._listeners.append(listener)
        self._session_handle: str | None = None
        self._binding: BoundShortcut | None = None
        self._portal_signals: set[str] = set()
        self._activated_seen = False
        self._deactivated_seen = False
        self._unsubscribers: list[Callable[[], object]] = []
        self._setup_result: ShortcutSetupResult | None = None

    @property
    def hold_supported(self) -> bool:
        """Only become true after both portal signals were actually observed."""

        return self._activated_seen and self._deactivated_seen

    @property
    def capabilities(self) -> tuple[CapabilityRecord, ...]:
        """Return current binding and hold/release capability records."""

        if self._binding is None:
            if self._setup_result is not None:
                return self._setup_result.capabilities
            return ()

        global_capability = CapabilityRecord(
            id="shortcut.global",
            status=CapabilityStatus.AVAILABLE,
            reason=(
                "Global shortcut is bound through the XDG portal. The configured "
                "trigger description is preserved for the status surface."
            ),
        )
        if "Deactivated" not in self._portal_signals:
            hold_capability = CapabilityRecord(
                id="shortcut.hold",
                status=CapabilityStatus.UNSUPPORTED,
                reason=(
                    "The portal did not expose Deactivated; push-to-talk hold/release "
                    "is unavailable. Use explicit toggle behavior instead."
                ),
            )
        elif self.hold_supported:
            hold_capability = CapabilityRecord(
                id="shortcut.hold",
                status=CapabilityStatus.AVAILABLE,
                reason="Both Activated and Deactivated signals were observed.",
            )
        else:
            hold_capability = CapabilityRecord(
                id="shortcut.hold",
                status=CapabilityStatus.NEEDS_USER_ACTION,
                reason=(
                    "The portal exposes hold/release signals, but both have not yet "
                    "been observed. Press and release the configured trigger in the "
                    "host smoke test."
                ),
            )
        return (global_capability, hold_capability)

    def add_listener(self, listener: EventListener) -> Callable[[], None]:
        """Register an event listener and return a deterministic removal hook."""

        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    async def configure(self) -> ShortcutSetupResult:
        """Probe, create a session, bind once, and subscribe to both signals."""

        if self._setup_result is not None:
            return self._setup_result

        probe = await self.portal.probe()
        if probe.capability.status is not CapabilityStatus.AVAILABLE:
            self._setup_result = ShortcutSetupResult(
                session_handle=None,
                binding=None,
                capabilities=probe.capabilities,
                failure=probe.failure,
            )
            return self._setup_result

        session_handle: str | None = None
        binding: BoundShortcut | None = None
        pending_unsubscribers: list[Callable[[], object]] = []
        committed = False
        failure: PortalFailure | None = None
        try:
            session_handle = await self.portal.create_session()
            bindings = await self.portal.bind_shortcut(
                session_handle,
                shortcut_id=self.shortcut_id,
                description=self.description,
                preferred_trigger=self.preferred_trigger,
            )
            binding = next(
                (candidate for candidate in bindings if candidate.id == self.shortcut_id),
                None,
            )
            if binding is None:
                failure = PortalFailure(
                    code=PortalErrorCode.REQUEST_FAILED,
                    status=CapabilityStatus.NEEDS_USER_ACTION,
                    reason=(
                        "The portal returned no binding for the configured shortcut. "
                        "Choose a trigger in the portal dialog and try again."
                    ),
                )
            else:
                portal_signals = set(probe.signals)
                if "Activated" not in portal_signals:
                    failure = PortalFailure(
                        code=PortalErrorCode.MALFORMED_RESPONSE,
                        status=CapabilityStatus.UNSUPPORTED,
                        reason=(
                            "The portal does not expose Activated; global shortcut "
                            "activation cannot be mapped to dictation start."
                        ),
                    )
                else:
                    unsubscribe_activated = await self.portal.subscribe(
                        "Activated", self._on_activated
                    )
                    pending_unsubscribers.append(unsubscribe_activated)
                    if "Deactivated" in portal_signals:
                        unsubscribe_deactivated = await self.portal.subscribe(
                            "Deactivated", self._on_deactivated
                        )
                        pending_unsubscribers.append(unsubscribe_deactivated)

                    self._session_handle = session_handle
                    self._binding = binding
                    self._portal_signals = portal_signals
                    self._unsubscribers.extend(pending_unsubscribers)
                    pending_unsubscribers.clear()
                    committed = True

        except Exception as exc:
            failure = map_portal_error(exc)
        finally:
            if not committed:
                await self._cleanup_partial_setup(
                    pending_unsubscribers,
                    session_handle,
                )

        if not committed:
            self._clear_local_state()
            assert failure is not None
            self._setup_result = ShortcutSetupResult(
                session_handle=None,
                binding=None,
                capabilities=(capability_for_failure(failure),),
                failure=failure,
            )
            return self._setup_result

        assert session_handle is not None
        assert binding is not None
        self._setup_result = ShortcutSetupResult(
            session_handle=session_handle,
            binding=binding,
            capabilities=self.capabilities,
        )
        return self._setup_result

    async def _cleanup_partial_setup(
        self,
        unsubscribers: list[Callable[[], object]],
        session_handle: str | None,
    ) -> None:
        """Release resources acquired before setup committed.

        Cleanup handles ordinary teardown errors so the original typed setup
        failure remains visible.  Cancellation is intentionally not caught.
        """

        for unsubscribe in reversed(unsubscribers):
            try:
                result = unsubscribe()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                continue
        if session_handle is not None:
            try:
                await self.portal.close_session(session_handle)
            except Exception:
                pass

    def _clear_local_state(self) -> None:
        self._session_handle = None
        self._binding = None
        self._portal_signals.clear()
        self._activated_seen = False
        self._deactivated_seen = False
        self._unsubscribers.clear()

    async def close(self) -> PortalFailure | None:
        """Unsubscribe, release the portal session, and close its transport.

        A transport without a session-release boundary may reclaim the desktop
        session only when the client disappears from D-Bus.  Local state is
        still cleared in all ordinary and cancellation paths.
        """

        failure: PortalFailure | None = None
        try:
            for unsubscribe in reversed(self._unsubscribers):
                try:
                    result = unsubscribe()
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:
                    if failure is None:
                        failure = map_portal_error(exc)

            if self._session_handle is not None:
                try:
                    await self.portal.close_session(self._session_handle)
                except Exception as exc:
                    if failure is None:
                        failure = map_portal_error(exc)

            try:
                await self.portal.close()
            except Exception as exc:
                if failure is None:
                    failure = map_portal_error(exc)
        finally:
            self._clear_local_state()
            self._setup_result = None
        return failure

    def _on_activated(self, *arguments: object) -> ShortcutEvent | None:
        return self._handle_signal(ShortcutEventType.LISTENING_STARTED, arguments)

    def _on_deactivated(self, *arguments: object) -> ShortcutEvent | None:
        return self._handle_signal(ShortcutEventType.LISTENING_STOPPED, arguments)

    def _handle_signal(
        self,
        event_type: ShortcutEventType,
        arguments: tuple[object, ...],
    ) -> ShortcutEvent | None:
        if self._session_handle is None or self._binding is None:
            return None
        session_handle, shortcut_id, timestamp = self._signal_fields(arguments)
        if session_handle != self._session_handle or shortcut_id != self._binding.id:
            return None
        if event_type is ShortcutEventType.LISTENING_STARTED:
            self._activated_seen = True
        else:
            self._deactivated_seen = True
        event = ShortcutEvent(
            type=event_type,
            shortcut_id=shortcut_id,
            session_handle=session_handle,
            timestamp=timestamp,
            trigger_description=self._binding.trigger_description,
        )
        for listener in tuple(self._listeners):
            result = listener(event)
            if inspect.isawaitable(result):
                raise RuntimeError("shortcut event listeners must be synchronous")
        return event

    @staticmethod
    def _signal_fields(arguments: tuple[object, ...]) -> tuple[str, str, int]:
        if len(arguments) == 1 and isinstance(arguments[0], Mapping):
            payload: Mapping[str, Any] = arguments[0]
            session_handle = payload.get("session_handle")
            shortcut_id = payload.get("shortcut_id")
            timestamp = payload.get("timestamp", 0)
        else:
            if len(arguments) < 2:
                raise PortalClientError(
                    PortalErrorCode.MALFORMED_RESPONSE,
                    "portal signal did not contain a session and shortcut ID",
                )
            session_handle = arguments[0]
            shortcut_id = arguments[1]
            timestamp = arguments[2] if len(arguments) >= 3 else 0
        if not isinstance(session_handle, str) or not session_handle.strip():
            raise PortalClientError(
                PortalErrorCode.MALFORMED_RESPONSE,
                "portal signal session handle is invalid",
            )
        if not isinstance(shortcut_id, str) or not shortcut_id.strip():
            raise PortalClientError(
                PortalErrorCode.MALFORMED_RESPONSE,
                "portal signal shortcut ID is invalid",
            )
        if not isinstance(timestamp, int):
            raise PortalClientError(
                PortalErrorCode.MALFORMED_RESPONSE,
                "portal signal timestamp is invalid",
            )
        return session_handle, shortcut_id, timestamp
