"""Command-line entry point for the VoxFlow diagnostic."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from collections.abc import Iterable
from typing import Sequence

from . import APP_NAME, __version__
from .core.capabilities import CapabilityRecord
from .core.diagnostics import build_diagnostics
from .core.state import SessionStateMachine
from .platform.audio import probe_audio
from .platform.portals import (
    GlobalShortcutsPortal,
    PortalClientError,
    PortalProbeResult,
    RemoteDesktopPortal,
)
from .platform.session import SessionInfo, detect_session


def diagnostic(
    capabilities: Iterable[CapabilityRecord] = (),
    session: SessionStateMachine | None = None,
    platform: dict[str, object] | None = None,
    db_path: str | None = None,
) -> dict[str, object]:
    """Return the core diagnostic without touching desktop resources."""

    current_session = session or SessionStateMachine()
    capability_values = tuple(capabilities)
    if db_path is not None:
        payload = build_diagnostics(
            db_path=db_path,
            capabilities=capability_values,
            state=current_session,
        )
        if platform is not None:
            payload["platform"] = platform
        return payload
    payload: dict[str, object] = {
        "app": APP_NAME,
        "version": __version__,
        "capabilities": [capability.to_dict() for capability in capability_values],
        "state": current_session.to_dict(),
    }
    if platform is not None:
        payload["platform"] = platform
    return payload


def platform_diagnostic(
    session_info: SessionInfo | None = None,
    portal_result: PortalProbeResult | None = None,
    insertion: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a live platform diagnostic from injectable probe results."""

    current_session = session_info or detect_session()
    current_portal = portal_result or asyncio.run(GlobalShortcutsPortal().probe())
    payload: dict[str, object] = {
        "session": current_session.to_dict(),
        "session_capability": current_session.capability.to_dict(),
        "portal": current_portal.to_dict(),
        "recommended_next_action": recommended_next_action(
            current_session,
            current_portal,
        ),
    }
    if insertion is not None:
        payload["insertion"] = insertion
    return payload


async def _probe_insertion_capability() -> dict[str, object]:
    """Probe the injectable insertion boundary without exposing token content."""

    portal = RemoteDesktopPortal()
    try:
        await portal.open_session()
    except PortalClientError:
        pass
    finally:
        try:
            await portal.close()
        except Exception:
            pass
    return {
        "capability": portal.capability.to_dict(),
        "consent_required": portal.consent_required,
        "restore_token_reused": portal.restore_token_reused,
    }


def insertion_platform_diagnostic() -> dict[str, object]:
    """Run the opt-in RemoteDesktop/Clipboard insertion capability probe."""

    return asyncio.run(_probe_insertion_capability())


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


# Fixed allowlist: subcommand -> (module, callable). Never built from argv.
SUBCOMMANDS = {
    "daemon": ("voxflow.daemon", "main"),
    "insert-test": ("voxflow.platform.insert_cli", "main"),
    "models": ("voxflow.providers.catalog_cli", "main"),
    "install-identity": ("voxflow.platform.portals", "install_identity_main"),
    "recovery": ("voxflow.recovery", "main"),
    "settings": ("voxflow.ui.settings", "main"),
}


def _dispatch(name: str, rest: list[str]) -> int:
    module_name, attr = SUBCOMMANDS[name]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        print(f"voxflow {name}: not installed yet ({module_name})")
        return 2
    return int(getattr(module, attr)(rest) or 0)


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a subcommand, or print a machine-readable diagnostic."""

    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in SUBCOMMANDS:
        return _dispatch(args[0], args[1:])
    argv = args
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
    parser.add_argument("--db", "--db-path", dest="db_path", default=None)
    arguments = parser.parse_args(argv)
    if arguments.probe_portals or arguments.probe_audio:
        platform: dict[str, object] = {}
        if arguments.probe_portals:
            platform.update(
                platform_diagnostic(insertion=insertion_platform_diagnostic())
            )
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
        if "insertion" in platform:
            insertion = platform["insertion"]
            assert isinstance(insertion, dict)
            capability = insertion["capability"]
            assert isinstance(capability, dict)
            capabilities.append(
                CapabilityRecord(
                    id=capability["id"],
                    status=capability["status"],
                    reason=capability["reason"],
                )
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
        print(
            json.dumps(
                diagnostic(capabilities, platform=platform, db_path=arguments.db_path),
                sort_keys=True,
            )
        )
    else:
        print(json.dumps(diagnostic(db_path=arguments.db_path), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
