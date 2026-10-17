"""0600 store for the RemoteDesktop restore token (T-02.1-04).

The token re-grants input control without a dialog, so it is a secret: never
echo its value anywhere.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

_VALID = re.compile(r"[\x21-\x7e]{1,256}")


def token_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "voxflow" / "remote_desktop.token"


def valid(token: object) -> bool:
    return isinstance(token, str) and _VALID.fullmatch(token) is not None


def load(path: Path | None = None) -> str | None:
    """Return the stored token, or None (forcing fresh consent) if unsafe."""

    path = path or token_path()
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:  # missing, or a symlink
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            return None
        text = os.read(fd, 1024).decode("ascii", "ignore").strip()
    finally:
        os.close(fd)
    return text if valid(text) else None


def store(token: str, path: Path | None = None) -> None:
    """Atomically write ``token`` with mode 0600 in a 0700 directory."""

    if not valid(token):
        raise ValueError("invalid restore token")
    path = path or token_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, token.encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
