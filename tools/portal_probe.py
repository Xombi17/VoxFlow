#!/usr/bin/env python3
"""Report safe session and GlobalShortcuts portal findings as JSON.

This probe never binds a shortcut, records input, reads audio, or emits
transcripts.  A missing desktop service is a normal structured result.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence


def _ensure_source_layout() -> None:
    """Allow the direct repository command to work before package installation."""

    source = Path(__file__).resolve().parents[1] / "src"
    source_text = str(source)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)


def probe() -> dict[str, object]:
    """Return redacted, structured platform findings."""

    _ensure_source_layout()
    from voxflow import APP_NAME, __version__
    from voxflow.platform.portals import GlobalShortcutsPortal
    from voxflow.platform.session import detect_session

    session = detect_session()
    portal = asyncio.run(GlobalShortcutsPortal().probe())
    if session.session_type.value != "wayland":
        next_action = "Start VoxFlow from a supported Ubuntu GNOME Wayland session."
    elif portal.failure is not None:
        next_action = portal.failure.reason
    elif any(capability.status.value == "unsupported" for capability in portal.capabilities):
        next_action = "Use the reported portal limitation and configure toggle behavior if needed."
    else:
        next_action = "Bind the dictation shortcut in the desktop portal, then run the smoke test."
    return {
        "app": APP_NAME,
        "version": __version__,
        "probe": "portal",
        "session": session.to_dict(),
        "session_capability": session.capability.to_dict(),
        "portal": portal.to_dict(),
        "recommended_next_action": next_action,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="portal_probe")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the safe capability report as JSON (the default output)",
    )
    parser.parse_args(argv)
    print(json.dumps(probe(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
