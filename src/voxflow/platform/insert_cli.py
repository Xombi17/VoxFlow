"""`voxflow insert-test`: paste text into the focused window via the portal."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from .insert import FALLBACK_HINT, Inserter, InsertResult, result_for_portal_error
from .portals import PortalClientError, RemoteDesktopPortal


async def _open_inserter() -> tuple[Inserter, Callable[[], Awaitable[object]]]:
    portal = RemoteDesktopPortal()
    await portal.open_session()
    return Inserter(portal), portal.close


def main(
    argv: Sequence[str] = (),
    *,
    open_inserter: Callable[[], Awaitable[tuple[Any, Callable[[], Awaitable[object]]]]] = _open_inserter,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> int:
    parser = argparse.ArgumentParser(
        prog="voxflow insert-test",
        description="Paste TEXT into the focused window through the RemoteDesktop portal.",
    )
    parser.add_argument("text")
    parser.add_argument(
        "--delay-seconds", type=float, default=3.0,
        help="wait before pasting so you can focus a window (default 3)",
    )
    args = parser.parse_args(list(argv))

    async def run() -> dict[str, object]:
        try:
            inserter, close = await open_inserter()
        except PortalClientError as exc:
            return {"result": result_for_portal_error(exc).value, "fallback_hint": FALLBACK_HINT}
        try:
            await sleep(args.delay_seconds)
            outcome = await inserter.insert(args.text)
        finally:
            result = inserter.close()
            if inspect.isawaitable(result):
                await result
            await close()
        return {"result": outcome.result.value, "fallback_hint": outcome.fallback_hint}

    payload = asyncio.run(run())
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["result"] == InsertResult.sent else 1
