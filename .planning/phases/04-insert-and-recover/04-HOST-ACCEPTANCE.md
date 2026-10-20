# Phase 4 host acceptance (04-03)

**Live status: PENDING / NOT RUN. Host approval is a blocking checkpoint.**
This is a user-run checklist for Ubuntu GNOME on Wayland. No live results or
measurements have been collected for this artifact. Offline tests and prior
summaries do not validate INSERT-01/02/03 or REC-01/02/03 on the host.

Use alongside `04-03-PLAN.md`, `04-CONTEXT.md`, and
`../02.1-walking-skeleton-on-gnome-50/02.1-HOST-ACCEPTANCE.md`. Record Phase 4
evidence here; the parent must separately reconcile the upstream acceptance gate.

## Preparation and evidence rules

- Use the existing checkout, Python 3.12 `.venv`, and locked dependencies from
  `README.md`, `.python-version`, and `uv.lock`. Host libraries (`libportaudio2`,
  `libei1`, and the compositor keymap library) and an installed, selected local
  model are manual prerequisites. Record actual missing prerequisites if found.
- Run from the user's GNOME Wayland session with one foreground daemon. Use
  disposable local Text Editor documents, a Firefox textarea, and an empty,
  unexecuted terminal prompt. Keep remote cleanup disabled and disconnect host
  networking for the offline dictation run; `uv --offline` prevents dependency
  fetching, not arbitrary application network access.
- Record only versions, opaque job/attempt IDs, status codes, counts, hashes,
  elapsed times, and redacted observations. Never attach transcripts, audio,
  clipboard bytes, restore tokens, credentials, database dumps, or absolute
  machine paths. Inspect intentional `show`/`save` output privately. Synthetic
  `insert-test` input below is a fixed transport fixture, not a host transcript.
- `install-identity` prints a local path: record only its exit status and the
  desktop-entry basename. Review all other output before copying safe fields.

| Run metadata | Evidence |
|---|---|
| Date, operator alias, revision / implementation under test | PENDING / NOT RUN |
| OS release, GNOME Shell / Mutter version, Wayland session | PENDING / NOT RUN |
| xdg-desktop-portal version, active backend name/version; GlobalShortcuts, RemoteDesktop and Clipboard interface versions | PENDING / NOT RUN |
| PipeWire, PortAudio, libei, libxkbcommon versions; Python runtime version | PENDING / NOT RUN |
| Text Editor, Firefox, terminal and XWayland target names/versions/backends | PENDING / NOT RUN |
| Installed and selected model ID/revision, provider, device, compute profile; language/style/cleanup policy | PENDING / NOT RUN |
| Bound shortcut, hold/release vs toggle behavior; offline run method | PENDING / NOT RUN |
| Initial retention setting; first-consent vs existing-grant setup | PENDING / NOT RUN |

Read versions from GNOME About, local package metadata, app diagnostics and the
probe where exposed. Do not infer the actual GNOME version from a phase title.

## Project-local commands (user runs these)

From the repository root, define this shell helper again after each login:

```bash
vf() {
  NETWORK_DISABLED=1 PYTHONPATH=src uv run --offline --no-sync \
    --python .venv/bin/python python -m voxflow "$@"
}

vf models list --json
vf install-identity
vf --json --probe-portals --probe-audio
vf insert-test --delay-seconds 3 "hello wörld"
vf daemon
```

Run commands individually in matrix order. The probe can open RemoteDesktop /
Clipboard consent and opens/closes the microphone for discovery; it is itself
live work. Inspect consent before continuing. `--probe-portals` reports insertion
capability, `consent_required`, and `restore_token_reused`, but does not negotiate
EIS/keymap readiness. A successful probe alone does not prove paste capability.

The 04-03 recovery CLI is now wired through the fixed top-level dispatch. Before
running host checks, confirm `vf recovery --help` and each action's help against
the checked-out implementation. The supported forms are:

```bash
vf recovery list
vf recovery show JOB_ID
vf recovery save JOB_ID "artifacts/host-acceptance/final.txt"
vf recovery save JOB_ID "artifacts/host-acceptance/raw.txt" --raw
vf recovery copy JOB_ID
vf recovery retry JOB_ID
```

Replace `JOB_ID` with the actual local ID. Choose a private save directory and
fresh filenames; the relative paths above are examples. Keep saved text local.
The commands also accept `--db` or `--db-path` before or after the action,
`copy` accepts `--wait-seconds`, and `retry` accepts `--delay-seconds`. These
delays are bounded by the CLI. There is no force or confirmation option for an
ambiguous post-chord retry. If a command or option differs from this checkout,
record the actual mismatch and have the parent reconcile it before that row
runs.

## Session and focused-app matrix

Each result cell starts unexecuted. Record the observed result and safe evidence
after running, using the disposition rules at the end.

| ID | User action | Required observation / evidence | Result |
|---|---|---|---|
| I1 Identity | Run `vf install-identity`, then the probe. | Entry basename `dev.voxflow.VoxFlow.desktop`; portal identity/name is VoxFlow (`dev.voxflow.VoxFlow`), not an anonymous app. Record registration outcome without its installed path. | PENDING / NOT RUN |
| I2 Capability and first consent | In a manually arranged fresh-grant session, run the probe and approve keyboard/Clipboard access for VoxFlow. | Record dialog count and requested access, GlobalShortcuts and insertion capability status/reason, consent/reuse booleans, and audio capability. Distinguish `available`, `needs_user_action`, `unavailable`, and `unsupported` as actually returned. EIS readiness remains a separate paste check. | PENDING / NOT RUN |
| I3 Unicode transport | Run the delayed `insert-test` separately for Text Editor and a local Firefox textarea. After consent, focus the intended field within the delay. | Record JSON `result` and exit status per app; privately verify the fixed Unicode fixture appears exactly once, intact, at the intended caret, without stuck modifiers. `sent` means bytes transferred, so also record visual success. | PENDING / NOT RUN |
| I4 Hold/speak/release | Start `vf daemon`; use its reported shortcut. Perform 20 attempts in Text Editor, then 20 in Firefox, waiting for idle between attempts. Include at least one known Unicode-producing phrase per app when the selected language/profile supports it. | Each hold starts one capture; release stops/closes it before processing and insertion. Verify final text privately, exactly once, intact, and at the intended caret. Separate ASR/formatting errors from transport corruption; if the profile cannot produce a stable Unicode check, record that bounded limitation or blocked reason. Fill the attempt/timing ledger below. | PENDING / NOT RUN |
| I5 Terminal chords | Use a blank, unexecuted prompt. Test default Ctrl+V insertion, then separately manual Ctrl+Shift+V with a live clipboard-only copy session. | Record terminal name/version, both bindings and actual behavior. Ctrl+V is the current default; manual Ctrl+Shift+V success does not prove an EIS Ctrl+Shift+V chord. Test an automated alternative only if the integrated CLI actually exposes it. Never execute the pasted fixture. | PENDING / NOT RUN |
| I6 XWayland | Select an already installed editable X11 target, or Firefox in a separately confirmed X11 mode; repeat I3 and a dictation cycle. | Record target/version, how XWayland was verified (Firefox: Window Protocol in `about:support`), chord and visual/transport outcomes. If no usable target can be exercised, record the concrete observed reason rather than assuming support or absence. | PENDING / NOT RUN |
| I7 Logout/login restore | After an approved insertion, stop VoxFlow, log out/in, redefine `vf`, and repeat the probe and I3 with the same identity and state locations. | Record token-file presence/permissions only, reuse/consent booleans, actual new-dialog count, insertion outcome and remote-control indicator lifecycle. `restore_token_reused` records submission of a stored token; no-dialog reuse plus a successful paste is the host evidence. | PENDING / NOT RUN |

Fresh consent, grant revocation and a confirmed XWayland target require manual
host setup. Use the desktop's available permission controls and record the
actual method. The current CLI provides no reset-consent command. Do not display
or attach the restore-token file. If the host cannot arrange a scenario, record
why that specific check could not run.

## Recovery, cancellation and retention matrix

Use durable jobs created by the daemon for these rows; `insert-test` alone does
not create recovery history. Stop/restart the daemon when changing its startup
settings. For failure scenarios, record how the condition was created and the
actual safe capability/error code; do not infer the side-effect phase solely
from whether text appeared.

| ID | User action | Required observation / evidence | Result |
|---|---|---|---|
| R1 Denied insertion | Arrange fresh consent manually, deny/cancel RemoteDesktop access, then dictate with shortcut/audio access still available. | Daemon continues capture/ASR; completed raw/final text survives in history and after daemon restart. List stays redacted, show/save remain usable; status says retained/unavailable rather than claiming a copy. Record denial code, job ID and insertion state. | PENDING / NOT RUN |
| R2 Unavailable insertion | With a separately arranged insertion-only unavailability, dictate again. | Preserve text and recovery actions despite unavailable Clipboard/EIS. Record the actual unavailable component/code and how shortcut/capture remained usable. A failure of the whole desktop session does not establish this case. | PENDING / NOT RUN |
| R3 Safe pre-chord retry | Select a job whose latest attempt is `failed_before_side_effect`, retryable, with no chord sent. Restore usable insertion, focus a disposable target using the implementation's supported focus/delay mechanism, and run `recovery retry`. | Reuse stored final text without ASR or retained audio. Record old/new attempt IDs, retry linkage, chord/transfer flags, terminal outcome and one visible insertion. Repeating retry for a completed job must not emit another chord; record refusal or idempotent no-op. | PENDING / NOT RUN |
| R4 Unknown post-chord | Use a target that does not request clipboard text (a noneditable target or the terminal case may provide this). Require actual `unknown_after_side_effect` metadata before running plain `recovery retry`. | Record chord-sent/phase, timeout or failure code, attempt count before/after and nonzero refusal. No automatic or plain-command retry, including after restart. Inspect target privately for a possible prior paste; retain show/save access. Do not use a confirmation override to turn this into a safe retry. | PENDING / NOT RUN |
| R5 Explicit text recovery | Run `recovery list`; intentionally `show JOB_ID`, save final text, and save `--raw` to separate private files. Restart and repeat the lookup. | List/normal daemon output contains no text. Privately verify UTF-8 saves match the chosen raw/final values; record only hash/length match flags, exit codes and durability. Raw and final may legitimately differ. Never attach show output or saved files. | PENDING / NOT RUN |
| R6 Truthful clipboard-only copy | With usable clipboard access, run `recovery copy`; manually paste into a disposable field while its owner/session is still alive. Repeat without usable clipboard access. | Copy itself emits no paste chord or target insertion. Success requires actual clipboard ownership and usable matching content on manual paste; a stored final string alone is insufficient. Record owner lifetime, transfer outcome and zero chord count. Unavailable/expired ownership returns a truthful failure, not "copied". | PENDING / NOT RUN |
| R7 Cancel and prevent duplicates | Stop the foreground daemon with Ctrl+C during capture and, separately, during processing before insertion. Restart and exercise rapid/repeated trigger events and repeated retry of a completed job. | Record cancellation phase/status, capture closure, no late pre-chord-cancel paste, and job/attempt/chord counts. If cancellation crosses the chord boundary, apply R4 instead of claiming no side effect. Completed jobs and duplicate requests must not paste twice. | PENDING / NOT RUN |
| R8 Default audio deletion | With `retain_audio=false`, exercise successful, failed-insertion and cancelled jobs, then restart. | Check history retention metadata and actual artifact absence privately, including transient/orphan cleanup. Record terminal case, retained/deleted/not-available state and file-exists boolean only. Text already produced remains recoverable even when audio is deleted. | PENDING / NOT RUN |
| R9 Opt-in retention | Explicitly enable retention before a new daemon run; complete a job, restart and inspect it. Restore the previous setting afterward. | Record opt-in policy, retained state and actual file-exists/resolvable booleans. If exercising retained-audio retry, use only an implemented action and record its outcome. Job deletion/expiry cleanup needs its actual supported manual mechanism; never claim it ran merely because retention is enabled. | PENDING / NOT RUN |

Manual setup and inspection boundaries:

- R1/R2 require an insertion-only denial/unavailability while shortcut/audio
  remain usable. R4 requires a real post-chord outcome. There are no documented
  CLI fault-injection switches; record a reproducible manual method or a concrete
  blocked reason. Do not manufacture evidence by editing job/attempt rows.
- If the recovery CLI omits attempt details, inspect only safe metadata using
  the existing `HistoryStore.list_insertion_attempts(job_id)` API and each
  record's `to_safe_dict()`. Keep intentional text views private.
- Retention currently uses the settings API rather than a daemon flag. With
  the daemon stopped, read and note the previous value, then explicitly opt in
  only for R9 using these default-database calls:

  ```bash
  NETWORK_DISABLED=1 PYTHONPATH=src uv run --offline --no-sync \
    --python .venv/bin/python python -c \
    'from voxflow.settings import get_audio_retention; print(get_audio_retention())'
  NETWORK_DISABLED=1 PYTHONPATH=src uv run --offline --no-sync \
    --python .venv/bin/python python -c \
    'from voxflow.settings import set_audio_retention; set_audio_retention(True)'
  ```

  For R8 use `set_audio_retention(False)` in the second call. Restore the noted
  previous value afterward and restart the daemon. Inspect artifact existence
  locally under `settings.data_dir() / "captures"` using the opaque artifact ID;
  record booleans, never the resolved path. Custom databases require matching
  settings, daemon and recovery configuration before testing.

## Repeated-attempt and latency evidence

For I4, keep separate Text Editor and Firefox sets, targeting **20/20 successful,
exactly-once attempts per app**. Do not replace failures with new successes or
silently count toggle-mode runs as hold/release passes. Separate warm-up/cold
start and any alternate model/profile into labeled sets.

Measure shortcut release to final text visibly complete in the focused app,
not just ASR completion or clipboard transfer. Record the timing method and its
resolution. Inserter `elapsed_ms` starts at insertion, so its trace alone cannot
supply release-to-text latency. Catalogue benchmark p50 is also a different
measurement.

| Set / app / backend | Attempts and exactly-once successes (target 20/20) | Timed sample count | Release-to-text p50 ms | Release-to-text p95 ms | Misses / duplicates / wrong-target count | Result |
|---|---|---|---|---|---|---|
| Text Editor | PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN |
| Firefox textarea | PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN |

Timing method/resolution and cold/warm classification: PENDING / NOT RUN.
Use median for p50 and nearest-rank p95 (rank 19 of 20 sorted samples). Record
the actual sample count; leave unmeasurable times unmeasured, never zero. Failed
attempts remain in the success denominator; label any successful-only latency
sample subset and record failures separately.

Expand this redacted ledger row for attempts 01-20 in each app and for recovery
cases as needed. Use actual IDs after execution, not text or screen captures:

| Case / sequence / app-backend | Job / attempt IDs | Result / side-effect phase / retryable | Chord / transfer / visible-once | Release-to-text ms | Safe reason / metadata reference |
|---|---|---|---|---|---|
| PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN | PENDING / NOT RUN |

## Dispositions and blocking approval

After execution, replace each result with one of the following and attach only
redacted evidence. Keep an unattempted item `PENDING / NOT RUN`.

- **PASS:** record the action, actual outcome, IDs/codes/counts and required
  timing or visual observations. A transport `sent` alone is insufficient.
- **BOUNDED LIMITATION:** describe exactly what worked, what failed, affected
  app/backend/version/chord, a demonstrated recovery/workaround, and the scope
  the user accepts. Do not turn terminal manual paste into automatic-paste proof.
- **BLOCKED:** record the attempted step, actual capability/error or missing
  prerequisite, impact, and concrete next step/owner. If no safe manual scenario
  can be arranged, say what was attempted and why. No blocker is presumed here.

Parent reconciliation before approval:

- Check final recovery help/dispatch, supported focus delay, clipboard-owner
  lifetime, metadata fields and exit codes. Keep alternate chord configuration,
  fault setup and retention/deletion controls manual unless actually exposed.
- Recheck the integrated revision with `NETWORK_DISABLED=1 make test` and
  `git diff --check`; offline results do not fill live matrix cells.
- Reconcile relevant Phase 02.1 acceptance evidence separately. Do not mark the
  insertion/recovery requirements validated from this prepared checklist.

Host operator decision, accepted limitations and date: **PENDING / NOT RUN**.
Plan 04-03's human-verification checkpoint remains open until the user supplies
recorded outcomes and applicable p50/p95, then explicitly approves the supported
scope or reports failures. Preparing this file does not complete that gate.
