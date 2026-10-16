# Feature Research

**Domain:** Linux desktop voice dictation and voice-to-text writing assistant
**Researched:** 2026-10-16
**Confidence:** HIGH for public behavior; MEDIUM for ecosystem choices

## Feature Landscape

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Push-to-talk dictation | Users need a predictable way to capture a thought into any focused field | HIGH | Wayland shortcut registration is an explicit platform adapter |
| Microphone selection and permission state | Dictation is unusable without clear audio setup | MEDIUM | PipeWire/Pulse compatibility and portal permission errors must be visible |
| Transcription with language selection | Raw speech must become text reliably | HIGH | Local model first; support a small tested language set before claiming broad coverage |
| Cleanup and punctuation | Raw ASR output is not ready to send | HIGH | Separate transcript from transformed output so users can recover the original |
| Paste/insert into focused app | The product value is cross-app writing, not a transcript viewer | HIGH | Clipboard and input injection differ on Wayland; provide explicit status and fallback |
| Cancel, retry, and recent history | Audio/network/model failures must not silently lose work | MEDIUM | Persist job metadata and optionally retained audio under a user-controlled policy |
| Settings for shortcut, mic, language, and provider | Desktop users need control over disruptive global behavior | MEDIUM | Changes apply to future dictations and should be reversible |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Local-first operation | No account, subscription, or mandatory upload | HIGH | Model download/storage and CPU/GPU capability detection are product concerns |
| App-aware writing styles | Email, chat, code, and notes need different formatting | HIGH | Start with explicit user-selected profiles; infer active app only with opt-in integration |
| Dictionary and correction rules | Personal names and jargon become reliable over time | MEDIUM | Whole-word matching, longer-rule precedence, and literal replacement need tests |
| Spoken snippets | Frequent text can be expanded without typing | MEDIUM | Must not conflict with file names, code, URLs, or user dictionary rules |
| Streaming status and latency metrics | Users can tell whether audio, transcription, cleanup, or paste is slow | MEDIUM | Instrument local pipeline without sending telemetry by default |
| Provider adapters | Users can choose local, LAN, or cloud models | HIGH | Stable internal interfaces prevent vendor lock-in |

### Anti-Features

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|------------|
| Silent global key interception | Feels seamless | Wayland security model, accidental capture, and trust concerns | Portal-based shortcut plus explicit permissions and a visible active state |
| Always-on microphone | Hands-free convenience | Privacy risk, battery/CPU use, and difficult consent model | Push-to-talk and hands-free session with a clear stop control |
| Mandatory cloud cleanup | Highest initial quality | Pricing barriers, latency, data exposure, and offline failure | Deterministic local cleanup plus optional configured LLM provider |
| Full meeting assistant in v1 | Expands market surface | Different retention, diarization, and consent requirements | Defer Notetaker until dictation reliability is proven |

## Feature Dependencies

```
Platform permission and shortcut adapter
    └──requires──> audio capture
                       └──requires──> local transcription provider
                                           └──requires──> cleanup pipeline
                                                               └──enhances──> style/dictionary/snippets

Cleanup pipeline ──requires──> focused-text insertion adapter
History/retry ──enhances──> every pipeline stage
Provider adapters ──enhance──> transcription and cleanup
```

### Dependency Notes

- **Audio capture requires platform setup:** PipeWire and portal state must be diagnosed before model latency can be measured.
- **Cleanup requires a stable transcript contract:** The raw transcript must remain available for retry and comparison.
- **Insertion requires an explicit focused-app strategy:** Wayland does not guarantee arbitrary text injection from an unfocused process.
- **Dictionary and styles enhance cleanup:** They should receive structured context rather than mutate audio or provider output invisibly.

## MVP Definition

### Launch With (v1)

- [ ] A tested Ubuntu GNOME Wayland shortcut path for start/stop dictation.
- [ ] Microphone capture through the host audio stack with clear permission/error states.
- [ ] One offline ASR provider and one optional OpenAI-compatible/LAN provider interface.
- [ ] Deterministic cleanup, punctuation, paragraph/list formatting, dictionary rules, and style profiles.
- [ ] Clipboard-first insertion with a documented fallback when the compositor denies synthetic input.
- [ ] Local history, retry, cancellation, and privacy controls.

### Add After Validation (v1.x)

- [ ] Better streaming partial transcripts after end-to-end latency is measured.
- [ ] App-category detection for common GNOME desktop applications.
- [ ] More languages and regional variants backed by recorded fixtures.
- [ ] A local cleanup model adapter with configurable model size and quantization.

### Future Consideration (v2+)

- [ ] Command Mode for editing selected text and launching searches.
- [ ] IDE variable recognition and file tagging.
- [ ] Meeting capture, speaker identification, summaries, and searchable notes.
- [ ] Mobile clients, account sync, team dictionaries, and administrative controls.

## Competitor Compatibility Notes

| Observable behavior | Public Wispr Flow evidence | VoxFlow approach |
|---------------------|----------------------------|------------------|
| Speak naturally and receive polished text | Website and “Why Flow” pages describe filler removal, self-correction, punctuation, and formatting | Build a testable cleanup pipeline with raw/final text separation |
| Works in any text field | Public FAQ and IDE article describe clipboard/paste behavior across apps | Use Wayland-aware insertion adapters with explicit capability reporting |
| Styles by app/category | Public Styles article describes Personal, Work, Email, and Other profiles | Start with explicit profiles and opt-in app hints |
| Dictionary/corrections/snippets | Public Dictionary article describes personal terms, corrections, and snippet behavior | Implement local deterministic rules and versioned migrations |
| Desktop command modes | Public Command Mode article describes a separate hold-to-speak flow | Defer until core dictation has stable focus/insertion contracts |

## Sources

- Wispr Flow public product page: https://wisprflow.ai/
- Wispr Flow comparison page: https://wisprflow.ai/why-flow
- Wispr Flow Help Center: https://docs.wisprflow.ai/
- Wispr Flow Command Mode: https://docs.wisprflow.ai/articles/4816967992-how-to-use-command-mode
- Wispr Flow Styles: https://docs.wisprflow.ai/articles/2368263928-how-to-setup-flow-styles
- Wispr Flow Dictionary: https://docs.wisprflow.ai/articles/4052411709-teach-flow-your-words-with-the-dictionary
- REA evidence ledger: `.planning/research/REA-EVIDENCE.md`

---
*Feature research for: VoxFlow*
*Researched: 2026-10-16*
