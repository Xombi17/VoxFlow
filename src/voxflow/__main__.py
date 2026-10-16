"""Command-line entry point for the VoxFlow diagnostic."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Iterable
from typing import Sequence

from . import APP_NAME, __version__
from .core.capabilities import CapabilityRecord
from .core.state import SessionStateMachine
from .platform.audio import probe_audio
from .platform.portals import GlobalShortcutsPortal, PortalProbeResult
from .platform.session import SessionInfo, detect_session


def diagnostic(
    capabilities: Iterable[CapabilityRecord] = (),
    session: SessionStateMachine | None = None,
    platform: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return the core diagnostic without touching desktop resources."""

    current_session = session or SessionStateMachine()
    payload: dict[str, object] = {
        "app": APP_NAME,
        "version": __version__,
        "capabilities": [capability.to_dict() for capability in capabilities],
        "state": current_session.to_dict(),
    }
    if platform is not None:
        payload["platform"] = platform
    return payload


def platform_diagnostic(
    session_info: SessionInfo | None = None,
    portal_result: PortalProbeResult | None = None,
) -> dict[str, object]:
    """Build a live platform diagnostic from injectable probe results."""

    current_session = session_info or detect_session()
    current_portal = portal_result or asyncio.run(GlobalShortcutsPortal().probe())
    return {
        "session": current_session.to_dict(),
        "session_capability": current_session.capability.to_dict(),
        "portal": current_portal.to_dict(),
        "recommended_next_action": recommended_next_action(
            current_session,
            current_portal,
        ),
    }


def audio_platform_diagnostic() -> dict[str, object]:
    """Run the opt-in audio probe without changing the default diagnostic."""

    return asyncio.run(probe_audio())


def recommended_next_action(
    session_info: SessionInfo,
    portal_result: PortalProbeResult,
) -> str:
    """Return a concise action a user can take after the host probe."""

    if session_info.session_type.value != "wayland":
        return "Start VoxFlow from a supported Ubuntu GNOME Wayland session."
    if portal_result.failure is not None:
        return portal_result.failure.reason
    if any(
        capability.status.value == "unsupported"
        for capability in portal_result.capabilities
    ):
        return "Use the portal limitation above and configure toggle behavior if needed."
    return "Bind the dictation shortcut in the desktop portal, then run the smoke test."


def main(argv: Sequence[str] | None = None) -> int:
    """Print a machine-readable diagnostic and exit successfully."""

    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the diagnostic as JSON (the default output)",
    )
    parser.add_argument(
        "--probe-portals",
        action="store_true",
        help="include live session and GlobalShortcuts portal findings",
    )
    parser.add_argument(
        "--probe-audio",
        action="store_true",
        help="include live microphone discovery and open/close findings",
    )
    arguments = parser.parse_args(argv)
    if arguments.probe_portals or arguments.probe_audio:
        platform: dict[str, object] = {}
        if arguments.probe_portals:
            platform.update(platform_diagnostic())
        if arguments.probe_audio:
            platform["audio"] = audio_platform_diagnostic()

        capabilities: list[CapabilityRecord] = []
        if "session_capability" in platform:
            session_capability = platform["session_capability"]
            assert isinstance(session_capability, dict)
            capabilities.append(
                CapabilityRecord(
                    id=session_capability["id"],
                    status=session_capability["status"],
                    reason=session_capability["reason"],
                )
            )
        if "portal" in platform:
            portal = platform["portal"]
            assert isinstance(portal, dict)
            capabilities.extend(
                CapabilityRecord(
                    id=capability["id"],
                    status=capability["status"],
                    reason=capability["reason"],
                )
                for capability in portal["capabilities"]
            )
        if "audio" in platform:
            audio = platform["audio"]
            assert isinstance(audio, dict)
            capabilities.append(
                CapabilityRecord(
                    id=audio["capability"]["id"],
                    status=audio["capability"]["status"],
                    reason=audio["capability"]["reason"],
                )
            )
        print(json.dumps(diagnostic(capabilities, platform=platform), sort_keys=True))
    else:
        print(json.dumps(diagnostic(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
