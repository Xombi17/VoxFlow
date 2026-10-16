# Pitfalls Research

**Domain:** Linux desktop voice dictation
**Researched:** 2026-10-16
**Confidence:** HIGH for platform/security pitfalls; MEDIUM for model performance

## Critical Pitfalls

### Pitfall 1: Treating Wayland like X11

**What goes wrong:** A global shortcut or paste path works in a local X11 test but fails on the user's Wayland session.

**Why it happens:** X11 exposes global input primitives that Wayland intentionally restricts. Desktop portals and compositor-specific permissions are required for several operations.

**How to avoid:** Make shortcut and insertion capabilities explicit. Test on the actual Ubuntu GNOME session before selecting the default adapter.

**Warning signs:** The app says recording started but no key release arrives; clipboard content is set but the focused app never receives paste.

**Phase to address:** Phase 1, platform feasibility.

---

### Pitfall 2: Assuming GlobalShortcuts supports hold/release everywhere

**What goes wrong:** Push-to-talk is implemented on top of a portal that only provides activation or is missing on the installed portal backend.

**Why it happens:** Portal interfaces and backend support vary by distribution and version. The documented interface has `Activated` and `Deactivated`, but the local environment still needs validation.

**How to avoid:** Probe interface version and signals at startup; support a clear press-to-toggle or GNOME-specific fallback if true hold semantics are unavailable.

**Warning signs:** Only one signal is observed, shortcut binding is empty, or the portal returns “not supported”.

**Phase to address:** Phase 1, platform feasibility.

---

### Pitfall 3: Measuring model quality without measuring latency and hardware

**What goes wrong:** A large model gives attractive transcripts but makes the desktop app feel unusable on CPU-only laptops.

**Why it happens:** ASR quality, model size, quantization, VAD, and startup/warm-cache behavior trade off against one another.

**How to avoid:** Benchmark warm and cold paths on the user's hardware. Ship a small offline model profile first and make larger models explicit choices.

**Warning signs:** First dictation takes minutes, CPU stays saturated after completion, or the UI cannot cancel an inference.

**Phase to address:** Phase 2, audio and ASR.

---

### Pitfall 4: Letting cleanup destroy meaning

**What goes wrong:** Filler removal or self-correction logic changes names, code, URLs, quoted text, or intentional repetition.

**Why it happens:** Cleanup is treated as a single opaque prompt rather than a constrained transformation with context.

**How to avoid:** Preserve raw transcript, make style/rule inputs explicit, use deterministic protections for URLs/code, and test corrections such as “5, actually 6”.

**Warning signs:** Users need to compare final text with audio to discover changes; dictionary rules unexpectedly affect snippets or code.

**Phase to address:** Phase 3, text transformation.

---

### Pitfall 5: Losing audio or duplicating paste during retries

**What goes wrong:** A network/model failure discards a recording, or a retry inserts the same text twice.

**Why it happens:** Job state is kept only in memory and insertion is treated as a side effect without an idempotency record.

**How to avoid:** Persist job stages and an insertion attempt ID before acting. Keep audio only under an explicit retention policy and clean it deterministically.

**Warning signs:** History has a completed entry but no recoverable audio, or repeated clicks paste multiple copies.

**Phase to address:** Phase 4, history/recovery/insertion.

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Hard-code one model path | Faster demo | Breaks on another machine and prevents provider selection | Only in a throwaway spike |
| Put platform calls in UI code | Fewer modules | Impossible to test and replace under Wayland | Never beyond a spike |
| Store all transcripts as JSON blobs | Quick persistence | Weak migrations, concurrent write issues, difficult queries | Export format only |
| Download models in test setup | Realistic demo | Offline tests become flaky and huge | Never for `make test` |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| XDG GlobalShortcuts | Assume portal availability from docs | Probe version/backend and return a capability result |
| RemoteDesktop/EIS | Ask for broad screen/input access without explaining it | Request only keyboard capability needed for paste and explain user consent |
| PipeWire | Assume default sample rate/channel layout | Negotiate and normalize to the ASR contract in the audio adapter |
| Local ASR | Load model on every dictation | Keep a bounded warm worker and expose memory usage |
| Optional cloud provider | Log audio, prompts, or tokens for debugging | Redact by default and make network operations visible in settings/history |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Capture audio when UI says idle | Privacy violation | Single authoritative state machine, visible active indicator, and tests for stop/cancel |
| Store raw audio forever | Sensitive data retention | User-controlled retention, encryption-at-rest only if needed, deletion tests |
| Send clipboard content to a cleanup provider | Secret leakage | Send only when explicitly enabled; redact or disable cloud cleanup for sensitive fields |
| Accept arbitrary provider endpoints | Credential/data exfiltration | Validate schemes, show endpoint, and separate local/LAN/cloud trust levels |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No clear recording indicator | User does not know when audio is captured | Status icon, sound/visual cue, and explicit cancel |
| Silent insertion failure | User thinks text disappeared | Keep transcript in history and show Copy/Retry/Save actions |
| Over-aggressive formatting | Output needs more edits than speech saved | Per-style controls and a “raw transcript” fallback |
| First-run model setup hidden in a spinner | App appears broken | Explain model size, download/storage, and offline status |

## “Looks Done But Isn’t” Checklist

- [ ] Shortcut: verified on Ubuntu GNOME Wayland with both activation and release/cancel behavior.
- [ ] Audio: verified mic selection, permission denial, disconnect, sample-rate conversion, and no-device state.
- [ ] ASR: verified cold start, warm start, cancellation, language selection, and no-network operation.
- [ ] Cleanup: verified self-corrections, filler words, URLs, code, names, dictionaries, and snippets.
- [ ] Paste: verified focused GTK, browser, terminal, and XWayland apps; documented unsupported cases.
- [ ] Recovery: verified failure persistence, retry idempotency, audio retention, and deletion policy.
- [ ] Privacy: verified cloud providers are off by default and sensitive data is not written to logs.

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Wayland assumptions | Phase 1 | Capability probe and host acceptance checks |
| Portal hold/release gaps | Phase 1 | D-Bus contract fixture plus live GNOME smoke test |
| Model latency | Phase 2 | Recorded benchmark on target hardware |
| Cleanup meaning loss | Phase 3 | Golden transcript transformation fixtures |
| Retry/paste loss or duplication | Phase 4 | State-machine and idempotency tests |
| Privacy leakage | Phase 5 | Network-disabled tests and log inspection |

## Sources

- XDG Global Shortcuts portal: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html
- XDG Remote Desktop portal: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html
- PipeWire docs: https://pipewire.pages.freedesktop.org/pipewire/
- Wispr Flow troubleshooting and behavior docs: https://docs.wisprflow.ai/
- REA evidence ledger: `.planning/research/REA-EVIDENCE.md`

---
*Pitfalls research for: VoxFlow*
*Researched: 2026-10-16*
