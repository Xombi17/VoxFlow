# VoxFlow

VoxFlow is a local-first voice writing assistant for Ubuntu GNOME on Wayland.
The core package provides typed settings, local provider orchestration, writing
cleanup, recovery, and safe host capability boundaries. Live D-Bus, audio,
RemoteDesktop/EIS, and GTK transports remain host capabilities.

## Runtime and setup

The project uses Python 3.12.14. The runtime pin is in `.python-version`, the
project metadata requires that same patch version, and `uv.lock` is the frozen
dependency graph. Pytest is pinned as project dev tooling.

From a clean checkout, install the project-local environment and dev tooling:

```bash
uv venv --python 3.12.14
uv sync --frozen --dev
uv lock --check --offline
```

Runtime dependencies (`dbus-next`, `sounddevice`, `numpy`, `sherpa-onnx`) are
exact-pinned in `pyproject.toml` and `uv.lock`; `av`, `faster-whisper`, and
`pydantic` are pinned as well. The offline suite uses fakes and never needs a
desktop session or model download.

## Host setup

```bash
uv sync --frozen --dev
sudo apt install libportaudio2 libei1
```

- `libportaudio2` is the system library required by `sounddevice`.
- `libei1` is required for EIS (libei) keyboard injection.
- If a GTK fallback window is ever needed, create the venv with
  `uv venv --python 3.12.14 --system-site-packages` to use the distro
  PyGObject. No GTK dependency is added to the Python package.

## Test and checks

```bash
make test
make lint
make check
make build
```

`make test` is the single offline regression command. It uses only the
project-local `.venv/bin/python` through `uv run --offline --no-sync`, sets
`NETWORK_DISABLED=1`, and rejects a missing environment or a Python version
other than 3.12.14. It never runs `uv sync` or downloads dependencies. `make
lint` performs the compile check; `make check` adds lock, metadata, whitespace,
and artifact path/secret checks; `make build` creates a wheel and sdist in
`dist/` without running a provider or model.

The setup commands may access package indexes to create the environment. After
setup, the commands above are offline. The build/test image is a separate
non-GUI check:

```bash
docker build --tag voxflow:local .
docker run --rm --network none voxflow:local
```

The Docker build downloads only the pinned base image, system packages, and
locked Python artifacts needed to construct the image. Its default runtime
command runs the same provider-free pytest suite with networking disabled.
Docker does not validate GTK, portal consent, microphone access, EIS, or
focused-application insertion.

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

## Local model catalogue

VoxFlow includes a pinned local catalogue for faster-whisper and Parakeet
profiles. Multiple models can be installed side by side. Only the explicit
`download` command can use the network, and each downloaded file is verified
against its manifest SHA-256 before it becomes usable.

```bash
# Offline catalogue and installation state
voxflow models list --json

# Install one or more profiles; --yes is required for non-interactive use
voxflow models download small.en distil-large-v3 --yes

# Switch the model used by new daemon sessions
voxflow models use small.en
voxflow models list

# Remove an inactive model
voxflow models remove distil-large-v3
```

Selection is stored as a model ID in the local SQLite settings store. The
daemon reads the selected profile at startup and reloads it on `SIGHUP`; it
never downloads a model while dictating. The first real-host benchmark compares
installed profiles and records redacted p50/p95 and WER results:

```bash
PYTHONPATH=src uv run --offline --no-sync --python .venv/bin/python \
  python tools/asr_benchmark.py \
  --catalog \
  --fixture tests/fixtures/audio/short_utterance.wav \
  --reference-text "Please send the report to Alice by Friday afternoon, and remind her about the budget meeting." \
  --json
```

## Settings and privacy

The headless settings surface is useful on machines without GTK and is also
the contract used by the native settings window:

```bash
voxflow settings --json
voxflow settings --json --set shortcut_trigger='"Ctrl+Space"'
voxflow settings --json --set retain_audio=false
```

Settings cover the microphone, shortcut trigger and hold/toggle behavior,
language, writing style, ASR provider/model, cleanup policy, audio retention,
and insertion timing/chord. Values are validated before one SQLite update.
Local ASR, deterministic cleanup, `local_only`, `Ctrl+V`, and
`retain_audio=false` are the safe defaults. Remote ASR or cleanup must be
selected explicitly with a disclosure and a coarse endpoint class; only a
credential environment-variable name is accepted, never the credential value.

The normal settings, diagnostic, model-list, daemon, and recovery-list output
is redacted. It may contain IDs, policies, counts, hashes, stable error codes,
and capability reasons, but not transcript/audio/clipboard content, tokens,
credential values, endpoint URLs, or machine paths. The intentional recovery
actions `show` and `save` are the only text-bearing recovery surfaces.

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

Start the local dictation daemon after installing at least one model:

```bash
voxflow daemon
```

The daemon prints non-sensitive lifecycle status to the terminal: the bound
trigger, `listening`, `processing locally`, and `inserted transcript`. Hold the
trigger it reports while speaking, then release it. Transcription stays local;
the daemon does not print transcript text. Settings changes apply to new daemon
jobs; restart the user service after changing a setting that is read at startup.

## Recover a dictation

Recovery reads the same local SQLite database as the daemon. Pass `--db` (or
`--db-path`) when using a non-default database. Listing is redacted; only the
explicit `show` action prints transcript text.

```bash
voxflow recovery list
voxflow recovery show JOB_ID
voxflow recovery save JOB_ID ./selected-output.txt
voxflow recovery save JOB_ID ./selected-raw.txt --raw
voxflow recovery copy JOB_ID
voxflow recovery retry JOB_ID
```

`copy` offers the final text through the portal for a bounded manual transfer;
it does not send a paste chord and it reports failure when the transfer is not
confirmed. `retry` only runs for a known pre-chord failure. It refuses jobs
whose paste result is ambiguous or already successful. Recovery commands keep
standard output redacted except for the intentional `show` payload, and saved
files are created with mode `0600` without replacing an existing file.

For an alternate database, place the option before or after the action:

```bash
voxflow recovery --db "$HOME/.local/share/voxflow/voxflow.db" list
voxflow recovery show JOB_ID --db-path "$HOME/.local/share/voxflow/voxflow.db"
```

The commands use only the local history and host portal when an action needs
one. They do not download models or call cloud providers.

## Writing cleanup and privacy

The writing pipeline is deterministic by default. It runs offline and keeps the
immutable raw transcript alongside the final text. An optional cleanup provider
can be injected through `DictationDaemon(cleanup_provider=...)` or
`DeterministicWritingPipeline(...).run_async(...)`; provider-backed jobs use a
frozen `WritingSettings` snapshot.

Remote cleanup is never enabled implicitly. A remote provider must receive both
`cleanup_network_policy="remote_explicit"` and
`cleanup_network_disclosure=True`; otherwise it is rejected before transport
work. Remote configuration retains only a credential environment-variable
reference and reports a coarse endpoint class (`lan`, `http`, or `https`).

If an optional provider fails, times out, is cancelled, or returns blank output,
the exact raw transcript becomes the final text. The in-memory `WritingResult`
records `fallback=True` and a stable code such as `cleanup_timeout` or
`cleanup_empty_output`. Safe diagnostics contain hashes, counts, policy, and
provider metadata only; they omit transcript text, credentials, endpoints, and
local paths.

## Deployment

VoxFlow is a desktop application rather than a hosted service. The normal
deployment is a user-local executable plus the user service and desktop entry;
it does not require sudo:

```bash
make build
uv tool install dist/voxflow-0.1.0-py3-none-any.whl
mkdir -p "$HOME/.config/systemd/user" "$HOME/.local/share/applications"
cp packaging/voxflow.service "$HOME/.config/systemd/user/voxflow.service"
cp packaging/dev.voxflow.VoxFlow.desktop \
  "$HOME/.local/share/applications/dev.voxflow.VoxFlow.desktop"
systemctl --user daemon-reload
systemctl --user enable --now voxflow.service
```

`uv tool install` creates the user-local environment and puts the stable
`voxflow` launcher in `$HOME/.local/bin`; ensure that directory is on `PATH`.
The service uses that launcher and starts `voxflow daemon`. The desktop entry
opens `voxflow settings`; it does not start a second daemon. For a source-only
checkout, `voxflow settings --json` remains available from `.venv/bin` before
the user-local install.

After changing settings that the daemon reads at startup:

```bash
systemctl --user restart voxflow.service
systemctl --user status voxflow.service
```

To stop or uninstall the deployment without deleting local history, models,
settings, or restore state:

```bash
systemctl --user disable --now voxflow.service
rm -f "$HOME/.config/systemd/user/voxflow.service"
rm -f "$HOME/.local/share/applications/dev.voxflow.VoxFlow.desktop"
systemctl --user daemon-reload
uv tool uninstall voxflow
```

The user data directory is intentionally left in place. Remove it separately
only after reviewing the recovery and retention requirements for that machine.

## Host-only acceptance

The pinned build, `make test`, `make check`, and Docker run are non-GUI,
provider-free evidence. They do not prove GTK rendering, a GNOME Wayland
session, portal consent, GlobalShortcuts hold/release behavior, microphone
permission, RemoteDesktop/Clipboard fd passing, EIS keymap readiness, focused
application insertion, or restore-token reuse. Run those checks manually on the
target Ubuntu GNOME session and record the result in the Phase 2.1/Phase 4/Phase
5 acceptance artifacts. Until then, those host behaviors remain unclaimed.
