"""Session-environment detection for compositor-aware platform adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from os import environ
from collections.abc import Mapping

from ..core.capabilities import CapabilityRecord, CapabilityStatus


class SessionType(StrEnum):
    """Desktop session families relevant to VoxFlow's platform policy."""

    WAYLAND = "wayland"
    X11 = "x11"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """A redacted, serializable description of the current desktop session."""

    session_type: SessionType
    declared_type: str | None
    wayland_display_present: bool
    x11_display_present: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_type", SessionType(self.session_type))

    @property
    def capability(self) -> CapabilityRecord:
        """Return the user-facing capability for the detected session."""

        if self.session_type is SessionType.WAYLAND:
            return CapabilityRecord(
                id="session.wayland",
                status=CapabilityStatus.AVAILABLE,
                reason="Wayland session detected; compositor-mediated adapters can be used.",
            )
        if self.session_type is SessionType.X11:
            return CapabilityRecord(
                id="session.x11",
                status=CapabilityStatus.NEEDS_USER_ACTION,
                reason=(
                    "X11 session detected; VoxFlow's Wayland portal path is not the "
                    "validated integration for this session."
                ),
            )
        return CapabilityRecord(
            id="session.unknown",
            status=CapabilityStatus.UNSUPPORTED,
            reason=(
                "Desktop session type is unknown. Start VoxFlow from a Wayland "
                "session with XDG_SESSION_TYPE or WAYLAND_DISPLAY set."
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize only capability metadata, never raw environment paths."""

        return {
            "session_type": self.session_type.value,
            "declared_type": self.declared_type,
            "wayland_display_present": self.wayland_display_present,
            "x11_display_present": self.x11_display_present,
        }


def detect_session(environment: Mapping[str, str] | None = None) -> SessionInfo:
    """Detect Wayland, X11, or an unknown session from an injected environment.

    Explicit ``XDG_SESSION_TYPE`` wins.  The display variables are fallback
    signals for minimal launchers and test fixtures that omit the declaration.
    Only their presence is retained in the result so diagnostics do not leak
    machine-specific display paths.
    """

    values = environ if environment is None else environment
    declared = values.get("XDG_SESSION_TYPE", "").strip().lower() or None
    wayland_present = bool(values.get("WAYLAND_DISPLAY", "").strip())
    x11_present = bool(values.get("DISPLAY", "").strip())

    if declared is not None:
        if declared == SessionType.WAYLAND.value:
            detected = SessionType.WAYLAND
        elif declared in {SessionType.X11.value, "xorg"}:
            detected = SessionType.X11
        else:
            detected = SessionType.UNKNOWN
    elif wayland_present:
        detected = SessionType.WAYLAND
    elif x11_present:
        detected = SessionType.X11
    else:
        detected = SessionType.UNKNOWN

    return SessionInfo(
        session_type=detected,
        declared_type=declared,
        wayland_display_present=wayland_present,
        x11_display_present=x11_present,
    )
