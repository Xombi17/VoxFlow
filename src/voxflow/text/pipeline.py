"""Conservative, dependency-free raw transcript normalization."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable

from ..providers.asr import CancellationToken, TranscriptResult
from ..providers.cleanup import (
    CleanupCancellationError,
    CleanupProvider,
    CleanupProviderError,
    CleanupRequest,
)
from ..providers.config import NetworkPolicy
from .contracts import (
    CleanupPolicy,
    RawTranscript,
    TransformationTrace,
    WritingResult,
    WritingSettings,
    WritingStyle,
    text_sha256,
)
from .rules import apply_rules, protect_text, restore_text


_FILLER_RE = re.compile(r"(?<!\w)(?:um|uh|er|hmm|you\s+know)(?!\w)[,;:]?\s*", re.I)
_SELF_CORRECTION_RE = re.compile(
    r"(?P<prefix>.*\s)?(?P<old>[\w']+)\s*,\s*"
    r"(?:no|i\s+mean)\s*,?\s*"
    r"(?P<new>[\w']+)(?=\s*[,.!?;:]|\s*$)",
    re.I,
)
_AMBIGUOUS_PRECEDERS = frozenset(
    {"a", "an", "each", "every", "my", "our", "the", "this", "that", "your"}
)
_COPULAS = frozenset({"am", "are", "is", "means", "mean", "was", "were"})
_SAFE_PROVIDER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")

_PROVIDER_FALLBACK_CODES = {
    "cancelled": "cleanup_cancelled",
    "timeout": "cleanup_timeout",
    "remote_timeout": "cleanup_timeout",
    "empty_output": "cleanup_empty_output",
    "invalid_output": "cleanup_invalid_output",
    "network_policy_rejected": "cleanup_network_policy_rejected",
    "cleanup_policy_rejected": "cleanup_policy_rejected",
    "network_disabled": "cleanup_network_disabled",
    "remote_http_error": "cleanup_provider_http_error",
    "remote_invalid_response": "cleanup_invalid_response",
}


class DeterministicWritingPipeline:
    """Apply the locked Phase 3 deterministic stage order."""

    def __init__(self, cleanup_provider: CleanupProvider | None = None) -> None:
        self.cleanup_provider = cleanup_provider

    def run(
        self,
        transcript: TranscriptResult | RawTranscript,
        settings: WritingSettings | None = None,
    ) -> WritingResult:
        raw = transcript if isinstance(transcript, RawTranscript) else RawTranscript(transcript)
        current = raw.text
        job_settings = settings or WritingSettings()
        if job_settings.cleanup_policy is CleanupPolicy.PROVIDER:
            raise RuntimeError("provider cleanup requires the async run_async entry point")
        trace: list[TransformationTrace] = []

        current = _stage(
            trace,
            current,
            "normalize_whitespace",
            lambda value: _protected_stage(
                value,
                _normalize_whitespace,
                extra_terms=job_settings.dictionary_words,
            ),
        )
        current = _stage(
            trace,
            current,
            "filler_cleanup",
            lambda value: _protected_stage(
                value,
                _remove_fillers,
                extra_terms=job_settings.dictionary_words,
            ),
        )
        current = _stage(
            trace,
            current,
            "self_correction",
            lambda value: _protected_stage(
                value,
                _apply_self_correction,
                extra_terms=job_settings.dictionary_words,
            ),
        )
        current = _stage(
            trace,
            current,
            "snippet_expansion",
            lambda value: apply_rules(value, job_settings.snippets, whole_phrase=True),
        )
        current = _stage(
            trace,
            current,
            "whole_word_corrections",
            lambda value: apply_rules(
                value,
                job_settings.corrections,
                whole_phrase=False,
                extra_terms=job_settings.dictionary_words,
            ),
        )
        current = _stage(
            trace,
            current,
            "formatting",
            lambda value: _format_stage(value, job_settings),
        )

        fallback = False
        fallback_code = None
        if not current.strip():
            previous = current
            current = raw.text.strip()
            fallback = True
            fallback_code = "blank_output"
            trace.append(
                TransformationTrace(
                    stage="blank_output_fallback",
                    changed=True,
                    input_sha256=text_sha256(previous),
                    output_sha256=text_sha256(current),
                )
            )
        if not current.strip():
            raise ValueError("cannot transform a blank transcript")
        return WritingResult(
            raw=raw,
            final_text=current,
            settings=job_settings,
            trace=tuple(trace),
            cleanup_provider_id=job_settings.cleanup_provider_id,
            fallback=fallback,
            fallback_code=fallback_code,
        )

    async def run_async(
        self,
        transcript: TranscriptResult | RawTranscript,
        settings: WritingSettings | None = None,
        *,
        cancellation: CancellationToken | None = None,
    ) -> WritingResult:
        """Run deterministic cleanup or the injected optional provider."""

        raw = transcript if isinstance(transcript, RawTranscript) else RawTranscript(transcript)
        job_settings = settings or WritingSettings()
        if job_settings.cleanup_policy is CleanupPolicy.DETERMINISTIC:
            return self.run(raw, job_settings)

        provider = self.cleanup_provider
        provider_id = _provider_id(provider, job_settings)
        if provider is None:
            return _provider_fallback(
                raw,
                job_settings,
                job_settings.cleanup_provider_id,
                "cleanup_provider_unavailable",
            )
        if getattr(provider, "provider_id", None) != job_settings.cleanup_provider_id:
            return _provider_fallback(
                raw,
                job_settings,
                job_settings.cleanup_provider_id,
                "cleanup_provider_mismatch",
            )
        if getattr(provider, "network_required", False) and (
            job_settings.cleanup_network_policy is not NetworkPolicy.REMOTE_EXPLICIT
            or not job_settings.cleanup_network_disclosure
        ):
            return _provider_fallback(
                raw,
                job_settings,
                provider_id,
                "cleanup_network_policy_rejected",
            )

        token = cancellation or CancellationToken()
        timeout_seconds = job_settings.cleanup_timeout_seconds
        request = CleanupRequest(
            raw_text=raw.text,
            settings=job_settings,
            provider_id=provider_id,
            timeout_seconds=timeout_seconds,
            endpoint=getattr(provider, "endpoint", None),
            credential_env_var=getattr(provider, "credential_env_var", None),
        )
        try:
            output = await asyncio.wait_for(
                provider.cleanup(request, token),
                timeout=timeout_seconds,
            )
        except CleanupCancellationError:
            return _provider_fallback(raw, job_settings, provider_id, "cleanup_cancelled")
        except asyncio.CancelledError:
            return _provider_fallback(raw, job_settings, provider_id, "cleanup_cancelled")
        except asyncio.TimeoutError:
            return _provider_fallback(raw, job_settings, provider_id, "cleanup_timeout")
        except CleanupProviderError as exc:
            return _provider_fallback(
                raw,
                job_settings,
                provider_id,
                _PROVIDER_FALLBACK_CODES.get(exc.code, "cleanup_provider_failed"),
            )
        except Exception as exc:
            if token.is_cancelled or getattr(exc, "code", None) == "cancelled":
                return _provider_fallback(raw, job_settings, provider_id, "cleanup_cancelled")
            return _provider_fallback(raw, job_settings, provider_id, "cleanup_provider_failed")

        if token.is_cancelled:
            return _provider_fallback(raw, job_settings, provider_id, "cleanup_cancelled")
        if not isinstance(output, str):
            return _provider_fallback(raw, job_settings, provider_id, "cleanup_invalid_output")
        if not output.strip():
            return _provider_fallback(raw, job_settings, provider_id, "cleanup_empty_output")
        trace = TransformationTrace(
            stage="cleanup_provider",
            changed=output != raw.text,
            input_sha256=text_sha256(raw.text),
            output_sha256=text_sha256(output),
        )
        return WritingResult(
            raw=raw,
            final_text=output,
            settings=job_settings,
            trace=(trace,),
            cleanup_provider_id=provider_id,
        )


def run_deterministic(
    transcript: TranscriptResult | RawTranscript,
    settings: WritingSettings | None = None,
) -> WritingResult:
    """Convenience function for callers that do not need a pipeline object."""

    return DeterministicWritingPipeline().run(transcript, settings)


def _provider_id(provider: CleanupProvider | None, settings: WritingSettings) -> str:
    value = getattr(provider, "provider_id", settings.cleanup_provider_id)
    return value if isinstance(value, str) and _SAFE_PROVIDER_ID.fullmatch(value) else settings.cleanup_provider_id


def _provider_fallback(
    raw: RawTranscript,
    settings: WritingSettings,
    provider_id: str,
    code: str,
) -> WritingResult:
    trace = TransformationTrace(
        stage="cleanup_provider",
        changed=False,
        input_sha256=text_sha256(raw.text),
        output_sha256=text_sha256(raw.text),
    )
    return WritingResult(
        raw=raw,
        final_text=raw.text,
        settings=settings,
        trace=(trace,),
        cleanup_provider_id=provider_id,
        fallback=True,
        fallback_code=code,
    )


def _stage(
    trace: list[TransformationTrace],
    value: str,
    name: str,
    transform: Callable[[str], str | tuple[str, tuple[int, ...]]],
) -> str:
    result = transform(value)
    if isinstance(result, tuple):
        output, rule_ids = result
    else:
        output, rule_ids = result, ()
    trace.append(
        TransformationTrace(
            stage=name,
            changed=output != value,
            input_sha256=text_sha256(value),
            output_sha256=text_sha256(output),
            rule_ids=rule_ids,
        )
    )
    return output


def _protected_stage(
    value: str,
    transform: Callable[[str], str],
    *,
    extra_terms: tuple[str, ...] = (),
) -> str:
    protected, values = protect_text(value, extra_terms=extra_terms)
    return restore_text(transform(protected), values)


def _normalize_whitespace(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return value.strip()


def _remove_fillers(value: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", _FILLER_RE.sub("", value)).strip()


def _apply_self_correction(value: str) -> str:
    return _SELF_CORRECTION_RE.sub(
        lambda match: f"{match.group('prefix') or ''}{match.group('new')}",
        value,
    )


def _format_stage(value: str, settings: WritingSettings) -> str:
    protected, values = protect_text(value, extra_terms=settings.dictionary_words)
    formatted = _format_text(protected, settings)
    restored = restore_text(formatted, values)
    return _ensure_terminal_punctuation(restored)


def _format_text(value: str, settings: WritingSettings) -> str:
    value = re.sub(r"\bnew\s+paragraph\b", "\n\n", value, flags=re.I)
    value = re.sub(r"\bnew\s+line\b", "\n", value, flags=re.I)
    value = _replace_spoken_punctuation(value)
    value = _format_spoken_list(value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\s+([,.;!?])", r"\1", value)
    value = re.sub(r"([,;:])(?=[^\s\n])", r"\1 ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    if settings.style is not WritingStyle.OTHER:
        value = re.sub(r"(^|[.!?]\s+|\n+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), value)
        value = re.sub(
            r"(^|\n)([-*]\s+)([a-z])",
            lambda m: m.group(1) + m.group(2) + m.group(3).upper(),
            value,
        )
    value = value.strip()
    return value


_TERMINAL_PUNCTUATION = frozenset(".!?;:")
_CLOSING_PUNCTUATION = frozenset('"\'»”’)]}')


def _ensure_terminal_punctuation(value: str) -> str:
    candidate = value.rstrip()
    while candidate and candidate[-1] in _CLOSING_PUNCTUATION:
        candidate = candidate[:-1].rstrip()
    if candidate and candidate[-1] in _TERMINAL_PUNCTUATION:
        return value
    return f"{value}." if value else value


def _replace_spoken_punctuation(value: str) -> str:
    commands = {
        "semi-colon": ";",
        "semi colon": ";",
        "semicolon": ";",
        "comma": ",",
        "full stop": ".",
        "period": ".",
    }
    pattern = re.compile(
        r"\b(?:semi[- ]?colon|comma|full\s+stop|period)\b",
        re.I,
    )

    def replace(match: re.Match[str]) -> str:
        before = value[: match.start()]
        after = value[match.end() :]
        previous = re.search(r"[A-Za-z']+$", before.rstrip())
        following = re.match(r"[A-Za-z']+", after.lstrip())
        previous_word = previous.group(0).casefold() if previous else ""
        following_word = following.group(0).casefold() if following else ""
        if previous_word in _AMBIGUOUS_PRECEDERS or following_word in _COPULAS:
            return match.group(0)
        return commands[re.sub(r"\s+", " ", match.group(0).casefold())]

    return pattern.sub(replace, value)


def _format_spoken_list(value: str) -> str:
    match = re.fullmatch(
        r"\s*first\s+(.+?),\s*second\s+(.+?)\s*([.!?])?\s*",
        value,
        flags=re.I | re.S,
    )
    if match is None:
        return value
    first, second, punctuation = match.groups()
    suffix = punctuation or ""
    return f"- {first.strip()}\n- {second.strip()}{suffix}"


__all__ = ["DeterministicWritingPipeline", "run_deterministic"]
