# VoxFlow

VoxFlow is a local-first voice writing assistant for Ubuntu GNOME on Wayland.
Phase 1 currently provides typed, injectable session, portal shortcut, and
microphone boundaries plus safe host probes. The live D-Bus and audio
transports remain optional host capabilities.

## Runtime and setup

The project targets Python 3.12. The runtime pin is in `.python-version` and
the dependency lockfile is `uv.lock`.

With a cached Python 3.12 runtime:

```bash
uv venv --python 3.12
```

The Phase 1 package has no required runtime dependencies. `dbus-next` and
`sounddevice` are optional host transports and are intentionally not required
by the offline suite.

## Test and checks

```bash
make test
make lint
```

`make test` first tries the project-local `.venv` through uv with
`--offline --no-sync`, so it never downloads dependencies. If pytest is not
cached there, it uses the configured `PYTHON` command as an explicit host
fallback and prints that choice. No pytest version is claimed by the lockfile
unless it is actually available in the project environment.

For the full Phase 1 verification commands:

```bash
PYTHONPATH=src python3 -m compileall -q src tests tools
PYTHONPATH=src python3 tools/portal_probe.py --json
PYTHONPATH=src python3 tools/audio_probe.py --json
git diff --check
```

The probes do not bind shortcuts or start audio capture. Their JSON reports
capabilities, negotiated metadata, and cleanup state without audio samples or
raw device identifiers.

## Run

The provider-free diagnostic is:

```bash
PYTHONPATH=src python3 -m voxflow --json
```

Opt into host capability probes only when running from the target desktop
session:

```bash
PYTHONPATH=src python3 -m voxflow --json --probe-portals --probe-audio
```

## Deployment

VoxFlow is a desktop application rather than a hosted service. Deployment is
the project checkout plus its pinned Python 3.12 environment and any explicitly
selected host transports. Use `.planning/phases/01-wayland-foundation/
HOST-ACCEPTANCE.md` for the Ubuntu GNOME Wayland acceptance steps.
