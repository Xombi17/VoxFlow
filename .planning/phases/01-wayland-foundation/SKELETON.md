# Phase 1 Walking Skeleton

## User-visible slice

A user can launch VoxFlow on Ubuntu GNOME Wayland, see the detected session and microphone/shortcut capability states, and run the same capability/state logic against deterministic fakes in offline tests. The app does not transcribe or paste in this phase.

## Skeleton boundaries

- **Entry point:** `python -m voxflow` launches a diagnostic GTK surface when GTK is available and a structured CLI diagnostic when requested.
- **Core interaction:** the status surface can refresh capabilities and transition a fake session through idle/listening/cancelled/failed states.
- **Real integration boundary:** the platform adapters are real modules with explicit `available`, `needs_user_action`, and `unsupported` results; live D-Bus/audio operations are isolated from tests.
- **Test boundary:** `make test` executes state, capability, and error mapping tests without a live display, audio device, portal, or network.

## Walking skeleton acceptance

- Launching the diagnostic produces structured capability output.
- The GTK surface, when launched in a GNOME session, renders at least one status and a refresh action.
- A fake adapter test proves a listening session can be started and cancelled without leaving the state machine active.
- A host probe records the actual Ubuntu session/portal/audio findings in a local acceptance report without storing audio or transcript content.
