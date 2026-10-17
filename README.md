# VoxFlow

VoxFlow is a local-first voice writing assistant for Ubuntu GNOME on Wayland.
Phase 1 currently provides typed, injectable session, portal shortcut, and
microphone boundaries plus safe host probes. The live D-Bus and audio
transports remain optional host capabilities.

## Runtime and setup

The project targets Python 3.12. The runtime pin is in `.python-version` and
the dependency lockfile is `uv.lock`. Pytest is pinned as project dev tooling.

From a clean checkout, install the project-local environment and dev tooling:

```bash
uv venv --python 3.12
uv sync --dev
```

Runtime dependencies (`dbus-next`, `sounddevice`, `numpy`, `sherpa-onnx`) are
exact-pinned in `pyproject.toml` and `uv.lock`. The offline suite uses fakes and
never needs a desktop session or model download.

## Host setup

```bash
uv sync --dev
sudo apt install libportaudio2 libei1
```

- `libportaudio2` is the system library required by `sounddevice`.
- `libei1` is required for EIS (libei) keyboard injection.
- If a GTK fallback window is ever needed, create the venv with
  `uv venv --python 3.12 --system-site-packages` to use the distro PyGObject.
  No GTK dependency is added now.

## Test and checks

```bash
NETWORK_DISABLED=1 make test
make lint
```

After setup, `make test` uses only `.venv/bin/python` through uv with
`--offline --no-sync`; it rejects a missing environment or a Python version
outside `>=3.12,<3.13` rather than falling back to an arbitrary host Python.

For the full Phase 1 verification commands:

```bash
PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python \
  python -m compileall -q src tests tools
PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python \
  python tools/portal_probe.py --json
PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python \
  python tools/audio_probe.py --json
git diff --check
```

The probes do not bind shortcuts or start audio capture. Their JSON reports
capabilities, negotiated metadata, and cleanup state without audio samples or
raw device identifiers.

## Run

The provider-free diagnostic is:

```bash
PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python \
  python -m voxflow --json
```

Opt into host capability probes only when running from the target desktop
session:

```bash
PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python \
  python -m voxflow --json --probe-portals --probe-audio
```

## Deployment

VoxFlow is a desktop application rather than a hosted service. Deployment is
the project checkout plus its pinned Python 3.12 environment and any explicitly
selected host transports. Use `.planning/phases/01-wayland-foundation/
HOST-ACCEPTANCE.md` for the Ubuntu GNOME Wayland acceptance steps.
