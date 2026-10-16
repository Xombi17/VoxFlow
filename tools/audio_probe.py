#!/usr/bin/env python3
"""Report safe microphone discovery and open/close findings as JSON.

The probe never starts capture and never writes audio samples.  Missing host
audio support, permission failures, and device changes are normal structured
results rather than process-level errors.
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


def probe(*, backend=None, selected_device_id: str | None = None) -> dict[str, object]:
    """Return redacted audio capability data using an injectable backend."""

    _ensure_source_layout()
    from voxflow import APP_NAME, __version__
    from voxflow.platform.audio import probe_audio

    result = asyncio.run(
        probe_audio(backend, selected_device_id=selected_device_id)
    )
    return {
        "app": APP_NAME,
        "version": __version__,
        **result,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audio_probe")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the safe capability report as JSON (the default output)",
    )
    arguments = parser.parse_args(argv)
    del arguments
    print(json.dumps(probe(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
