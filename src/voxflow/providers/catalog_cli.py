"""``voxflow models list|download|use|remove`` (list/use/remove are offline)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import catalog


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="voxflow models")
    p.add_argument("--root", type=Path, default=None, help="models directory")
    p.add_argument("--db", type=Path, default=None, help="settings database")
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true")
    dl = sub.add_parser("download")
    dl.add_argument("id", nargs="+", help="one or more catalog model IDs")
    dl.add_argument("--yes", action="store_true", help="confirm network use")
    for name in ("use", "remove"):
        sub.add_parser(name).add_argument("id")
    args = p.parse_args(argv)
    root = args.root or catalog.default_models_root()
    try:
        if args.cmd == "list":
            rows = catalog.list_models(root, db_path=args.db)
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                for r in rows:
                    flag = ("*" if r["selected"] else " ") + ("installed" if r["installed"] else "not installed")
                    p50 = f"p50 {r['p50_ms']:.0f} ms" if isinstance(r["p50_ms"], (int, float)) else "p50 -"
                    print(f"{r['id']:<24} {r['tier']:<8} {r['size_bytes'] / 1e6:>7.0f} MB  {flag:<14} {p50}")
        elif args.cmd == "download":
            entries = tuple(catalog.get_entry(model_id) for model_id in args.id)

            def confirm(notice: str) -> bool:
                print(notice)
                if args.yes:
                    return True
                if not sys.stdin.isatty():
                    return False
                return input("Proceed? [y/N] ").strip().lower() in ("y", "yes")

            for entry in entries:
                catalog.download_model(entry, root, confirm=confirm)
                print(f"Installed {entry.id}")
        elif args.cmd == "use":
            catalog.select(args.id, root, db_path=args.db)
            print(f"Selected {args.id}. Restart or reload the VoxFlow daemon to apply.")
        else:
            catalog.remove(args.id, root, db_path=args.db)
            print(f"Removed {args.id}")
    except catalog.CatalogError as exc:
        print(f"voxflow models: {exc}", file=sys.stderr)
        return 1
    return 0
