"""Command-line entry point for the VoxFlow diagnostic."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from . import APP_NAME, __version__


def diagnostic() -> dict[str, object]:
    """Return the bootstrap diagnostic without touching desktop resources."""

    return {
        "app": APP_NAME,
        "version": __version__,
        "capabilities": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Print a machine-readable diagnostic and exit successfully."""

    parser = argparse.ArgumentParser(prog=APP_NAME)
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the diagnostic as JSON (the default output)",
    )
    parser.parse_args(argv)
    print(json.dumps(diagnostic(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
