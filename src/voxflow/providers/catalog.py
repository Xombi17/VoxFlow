"""Pinned local model catalogue: list, explicit verified download, select, remove.

The manifest (``catalog.json``) is the trust root: every file carries a pinned
SHA-256. Nothing here fetches anything except ``download_model`` after explicit
consent, and only with the stdlib ``urllib``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import settings

VERIFIED_MARKER = ".verified"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1 << 20


class CatalogError(RuntimeError):
    """Catalogue, path-safety, or download failure with a readable message."""


class ConsentRequired(CatalogError):
    """Download was not confirmed; nothing was fetched."""


class ModelFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    url: str
    sha256: str

    @field_validator("sha256")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not _SHA_RE.fullmatch(v):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return v

    @field_validator("url")
    @classmethod
    def _https(cls, v: str) -> str:
        if urlsplit(v).scheme != "https" or not urlsplit(v).hostname:
            raise ValueError("model file url must be https")
        return v


class ModelEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    engine: str
    languages: tuple[str, ...]
    size_bytes: int = Field(gt=0)
    tier: str
    source_url: str
    license: str
    files: tuple[ModelFile, ...] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return check_model_id(v)


class Catalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int
    # Hosts a download may be redirected to (CDN); files are hash-verified anyway.
    redirect_host_suffixes: tuple[str, ...] = ()
    models: tuple[ModelEntry, ...]


def check_model_id(model_id: str) -> str:
    if not isinstance(model_id, str) or not _ID_RE.fullmatch(model_id) or ".." in model_id:
        raise CatalogError(f"invalid model id: {model_id!r}")
    return model_id


def load_catalog() -> Catalog:
    text = (Path(__file__).with_name("catalog.json")).read_text(encoding="utf-8")
    return Catalog.model_validate_json(text)


def get_entry(model_id: str, catalog: Catalog | None = None) -> ModelEntry:
    for entry in (catalog or load_catalog()).models:
        if entry.id == model_id:
            return entry
    raise CatalogError(f"unknown model id: {model_id!r}")


def default_models_root() -> Path:
    return settings.data_dir() / "models"


# --- paths -----------------------------------------------------------------


def _inside(root: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` (following symlinks) and require it under ``root``."""

    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise CatalogError("path resolves outside the models root")
    return resolved


def model_dir(root: Path, model_id: str) -> Path:
    check_model_id(model_id)
    return _inside(root, Path(root) / model_id)


def _dest(root: Path, model_id: str, rel: str) -> Path:
    p = Path(rel)
    if not rel or p.is_absolute() or ".." in p.parts or "\\" in rel:
        raise CatalogError(f"unsafe manifest path: {rel!r}")
    return _inside(root, Path(root) / model_id / p)


def is_installed(root: Path, model_id: str) -> bool:
    try:
        return (model_dir(root, model_id) / VERIFIED_MARKER).is_file()
    except CatalogError:
        return False


# --- benchmark results ------------------------------------------------------


def results_path(root: Path) -> Path:
    return Path(root) / "benchmark_results.json"


def load_results(root: Path) -> dict[str, dict[str, Any]]:
    """``{model_id: {p50_ms, p95_ms, wer, fixture, ts}}``; ``{}`` if missing/malformed."""

    try:
        data = json.loads(results_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, dict)}


def save_results(root: Path, results: dict[str, dict[str, Any]]) -> None:
    path = results_path(root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def result_record(p50_ms: float, p95_ms: float, wer: float | None, fixture: str) -> dict[str, Any]:
    """Build one results entry in the documented schema."""

    return {
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "wer": wer,
        "fixture": Path(fixture).name,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# --- list / select / remove -------------------------------------------------


def list_models(root: Path | None = None, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    root = Path(root) if root else default_models_root()
    results = load_results(root)
    selected = settings.selected_model_id(db_path=db_path)
    rows = []
    for e in load_catalog().models:
        r = results.get(e.id, {})
        rows.append(
            {
                "id": e.id,
                "name": e.name,
                "engine": e.engine,
                "tier": e.tier,
                "languages": list(e.languages),
                "size_bytes": e.size_bytes,
                "license": e.license,
                "installed": is_installed(root, e.id),
                "selected": e.id == selected,
                "p50_ms": r.get("p50_ms"),
                "wer": r.get("wer"),
            }
        )
    return rows


def select(model_id: str, root: Path | None = None, *, db_path: Path | None = None) -> None:
    root = Path(root) if root else default_models_root()
    get_entry(model_id)
    if not is_installed(root, model_id):
        raise CatalogError(f"model {model_id!r} is not installed; run: voxflow models download {model_id}")
    settings.set_selected_model_id(model_id, db_path=db_path)


def get_selected(*, db_path: Path | None = None) -> str | None:
    return settings.selected_model_id(db_path=db_path)


def remove(model_id: str, root: Path | None = None, *, db_path: Path | None = None) -> None:
    root = Path(root) if root else default_models_root()
    check_model_id(model_id)
    target = Path(root) / model_id
    if target.is_symlink():
        raise CatalogError("refusing to remove a symlinked model directory")
    target = model_dir(root, model_id)
    if target.is_dir():
        shutil.rmtree(target)
    if settings.selected_model_id(db_path=db_path) == model_id:
        settings.set_selected_model_id(None, db_path=db_path)


# --- download ---------------------------------------------------------------


@dataclass
class FetchResponse:
    url: str  # final URL after redirects
    status: int  # 200 full body, 206 partial content, 416 range not satisfiable
    chunks: Iterable[bytes]


Fetcher = Callable[[str, int, tuple[str, ...]], FetchResponse]


def _host_ok(host: str, base_host: str, suffixes: Iterable[str]) -> bool:
    host = host.lower()
    return host == base_host.lower() or any(host == s or host.endswith("." + s) for s in suffixes)


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, base_host: str, suffixes: tuple[str, ...]) -> None:
        self._base, self._suffixes = base_host, suffixes

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        parts = urlsplit(newurl)
        if parts.scheme != "https" or not parts.hostname or not _host_ok(parts.hostname, self._base, self._suffixes):
            raise CatalogError(f"refusing redirect to {parts.hostname!r}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_urllib_fetcher(url: str, start: int, redirect_suffixes: tuple[str, ...]) -> FetchResponse:
    req = urllib.request.Request(url, headers={"User-Agent": "voxflow-model-download"})
    if start:
        req.add_header("Range", f"bytes={start}-")
    opener = urllib.request.build_opener(_GuardedRedirect(urlsplit(url).hostname or "", redirect_suffixes))
    try:
        resp = opener.open(req, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code == 416:
            return FetchResponse(url, 416, ())
        raise CatalogError(f"download failed: HTTP {exc.code}") from exc
    except OSError as exc:
        raise CatalogError(f"download failed: {exc}") from exc

    def gen() -> Iterable[bytes]:
        with resp:
            while block := resp.read(_CHUNK):
                yield block

    return FetchResponse(resp.geturl(), resp.status, gen())


def network_notice(entry: ModelEntry) -> str:
    hosts = sorted({urlsplit(f.url).hostname or "" for f in entry.files})
    return f"Network use: downloading {entry.size_bytes / 1e6:.0f} MB from {', '.join(hosts)}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(_CHUNK):
            h.update(block)
    return h.hexdigest()


def _fetch_file(f: ModelFile, dest: Path, fetcher: Fetcher, suffixes: tuple[str, ...]) -> None:
    if dest.is_file() and _sha256_file(dest) == f.sha256:
        return
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    base_host = urlsplit(f.url).hostname or ""
    start = part.stat().st_size if part.is_file() else 0
    resp = fetcher(f.url, start, suffixes)
    parts = urlsplit(resp.url)
    if parts.scheme != "https" or not parts.hostname or not _host_ok(parts.hostname, base_host, suffixes):
        part.unlink(missing_ok=True)
        raise CatalogError(f"refusing download served from {parts.hostname!r}")
    if resp.status == 416:
        pass  # part file is already complete; verify it below
    elif resp.status in (200, 206):
        mode = "ab" if (start and resp.status == 206) else "wb"
        with part.open(mode) as fh:
            for block in resp.chunks:
                fh.write(block)
    else:
        raise CatalogError(f"download failed: HTTP {resp.status}")
    if _sha256_file(part) != f.sha256:
        part.unlink(missing_ok=True)
        raise CatalogError(f"SHA-256 mismatch for {f.path}; file discarded")
    os.replace(part, dest)


def download_model(
    entry: ModelEntry,
    root: Path,
    fetcher: Fetcher = default_urllib_fetcher,
    confirm: Callable[[str], bool] = lambda _notice: False,
    *,
    catalog: Catalog | None = None,
) -> Path:
    """Download and verify every file of ``entry``; install only if all verify."""

    root = Path(root)
    suffixes = (catalog or load_catalog()).redirect_host_suffixes
    # Validate every destination before any network access.
    dests = [(f, _dest(root, entry.id, f.path)) for f in entry.files]
    if not confirm(network_notice(entry)):
        raise ConsentRequired("download not confirmed; nothing was fetched")
    target = model_dir(root, entry.id)
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    (target / VERIFIED_MARKER).unlink(missing_ok=True)
    for f, dest in dests:
        _fetch_file(f, dest, fetcher, suffixes)
    (target / VERIFIED_MARKER).write_text(
        json.dumps({f.path: f.sha256 for f in entry.files}, indent=2), encoding="utf-8"
    )
    return target


# --- engine -> provider -----------------------------------------------------


def build_provider(entry: ModelEntry, root: Path, **kwargs: Any):
    """Map catalogue engine to its ASRProvider (lazy imports; no model load)."""

    directory = model_dir(Path(root), entry.id)
    if entry.engine == "faster-whisper":
        from .local_whisper import LocalWhisperProvider, discover_local_model

        discovery = discover_local_model(
            directory, model_id=entry.id, supported_languages=("auto", *entry.languages)
        )
        return LocalWhisperProvider(discovery.profile, **kwargs)
    if entry.engine == "sherpa-onnx":
        from .sherpa_parakeet import SherpaParakeetProvider

        return SherpaParakeetProvider(entry, directory, **kwargs)
    raise CatalogError(f"unknown engine: {entry.engine!r}")
