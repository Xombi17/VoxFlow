"""Immutable contracts shared by writing stages and future recovery surfaces."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum

from ..providers.asr import TranscriptResult
from ..providers.config import NetworkPolicy


class WritingStyle(StrEnum):
    """Built-in formatting profiles for the first writing pipeline."""

    PERSONAL = "personal"
    WORK = "work"
    EMAIL = "email"
    OTHER = "other"


class CleanupPolicy(StrEnum):
    """How a job obtains its final text."""

    DETERMINISTIC = "deterministic"
    PROVIDER = "provider"


_LANGUAGE_TAG = re.compile(r"^(?:auto|[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)$")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def text_sha256(text: str) -> str:
    """Return the stable digest used in traces and safe diagnostics."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field_name} must be a safe identifier")
    return value


def _safe_metadata_identifier(value: str) -> str:
    return value if isinstance(value, str) and _SAFE_IDENTIFIER.fullmatch(value) else "redacted"


def _safe_language(value: str | None) -> str | None:
    if value is None:
        return None
    language = value.strip()
    return language if _LANGUAGE_TAG.fullmatch(language) else "redacted"


@dataclass(frozen=True, slots=True)
class TextRule:
    """One user rule captured in a per-job immutable settings snapshot."""

    rule_id: int
    trigger: str
    replacement: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.rule_id < 0:
            raise ValueError("rule_id must not be negative")
        if not self.trigger.strip():
            raise ValueError("rule trigger must not be blank")
        if not self.replacement.strip():
            raise ValueError("rule replacement must not be blank")
        object.__setattr__(self, "trigger", " ".join(self.trigger.split()))

    @property
    def normalized_trigger(self) -> str:
        return self.trigger.casefold()

    def to_safe_dict(self) -> dict[str, object]:
        """Expose rule identity without leaking user dictionary content."""

        return {
            "rule_id": self.rule_id,
            "enabled": self.enabled,
            "trigger_length": len(self.trigger),
            "replacement_length": len(self.replacement),
        }


@dataclass(frozen=True, slots=True)
class WritingSettings:
    """Frozen settings used by exactly one writing job."""

    language: str = "auto"
    style: WritingStyle = WritingStyle.PERSONAL
    cleanup_policy: CleanupPolicy = CleanupPolicy.DETERMINISTIC
    cleanup_provider_id: str = "deterministic"
    cleanup_network_policy: NetworkPolicy = NetworkPolicy.LOCAL_ONLY
    cleanup_network_disclosure: bool = False
    cleanup_timeout_seconds: float = 30.0
    dictionary_words: tuple[str, ...] = ()
    dictionary_rule_ids: tuple[int, ...] = ()
    corrections: tuple[TextRule, ...] = ()
    snippets: tuple[TextRule, ...] = ()

    def __post_init__(self) -> None:
        language = self.language.strip()
        if not _LANGUAGE_TAG.fullmatch(language):
            raise ValueError("language must be 'auto' or a BCP-47-like tag")
        if not self.cleanup_provider_id.strip():
            raise ValueError("cleanup_provider_id must not be blank")
        _safe_identifier(self.cleanup_provider_id, "cleanup_provider_id")
        object.__setattr__(self, "language", language)
        try:
            style = WritingStyle(self.style)
        except ValueError as exc:
            raise ValueError("style must be one of personal, work, email, or other") from exc
        object.__setattr__(self, "style", style)
        object.__setattr__(self, "cleanup_policy", CleanupPolicy(self.cleanup_policy))
        try:
            network_policy = NetworkPolicy(self.cleanup_network_policy)
        except ValueError as exc:
            raise ValueError("cleanup_network_policy must be local_only or remote_explicit") from exc
        if not isinstance(self.cleanup_network_disclosure, bool):
            raise ValueError("cleanup_network_disclosure must be a boolean")
        if (
            not isinstance(self.cleanup_timeout_seconds, (int, float))
            or isinstance(self.cleanup_timeout_seconds, bool)
            or not math.isfinite(float(self.cleanup_timeout_seconds))
            or not 0 < float(self.cleanup_timeout_seconds) <= 300
        ):
            raise ValueError("cleanup_timeout_seconds must be greater than 0 and at most 300")
        if network_policy is NetworkPolicy.LOCAL_ONLY and self.cleanup_network_disclosure:
            raise ValueError("local cleanup settings must not disclose network use")
        object.__setattr__(self, "cleanup_network_policy", network_policy)
        object.__setattr__(self, "cleanup_timeout_seconds", float(self.cleanup_timeout_seconds))
        object.__setattr__(self, "dictionary_words", _freeze_words(self.dictionary_words))
        object.__setattr__(self, "dictionary_rule_ids", _freeze_ids(self.dictionary_rule_ids))
        object.__setattr__(self, "corrections", tuple(self.corrections))
        object.__setattr__(self, "snippets", tuple(self.snippets))

    def to_safe_dict(self) -> dict[str, object]:
        """Return policy, counts, and IDs without user-authored text."""

        return {
            "language": self.language,
            "style": self.style.value,
            "cleanup_policy": self.cleanup_policy.value,
            "cleanup_provider_id": _safe_metadata_identifier(self.cleanup_provider_id),
            "cleanup_network_policy": self.cleanup_network_policy.value,
            "cleanup_network_disclosure": self.cleanup_network_disclosure,
            "cleanup_timeout_seconds": self.cleanup_timeout_seconds,
            "dictionary_count": len(self.dictionary_words),
            "dictionary_rule_ids": list(self.dictionary_rule_ids),
            "correction_rule_ids": [rule.rule_id for rule in self.corrections],
            "snippet_rule_ids": [rule.rule_id for rule in self.snippets],
        }


@dataclass(frozen=True, slots=True)
class RawTranscript:
    """The validated ASR result as an immutable writing input."""

    result: TranscriptResult

    @property
    def text(self) -> str:
        return self.result.text

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "provider_id": _safe_metadata_identifier(self.result.provider_id),
            "model_id": _safe_metadata_identifier(self.result.model_id),
            "audio_sha256": self.result.audio_sha256,
            "language": _safe_language(self.result.language),
            "language_probability": self.result.language_probability,
            "confidence": self.result.confidence,
            "segment_count": len(self.result.segments),
        }


@dataclass(frozen=True, slots=True)
class TransformationTrace:
    """Safe evidence for one deterministic transformation stage."""

    stage: str
    changed: bool
    input_sha256: str
    output_sha256: str
    rule_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _safe_identifier(self.stage, "trace stage")
        if (
            not isinstance(self.input_sha256, str)
            or not isinstance(self.output_sha256, str)
            or not _SHA256.fullmatch(self.input_sha256)
            or not _SHA256.fullmatch(self.output_sha256)
        ):
            raise ValueError("trace hashes must be SHA-256 values")
        object.__setattr__(self, "rule_ids", tuple(self.rule_ids))

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "changed": self.changed,
            "input_sha256": self.input_sha256,
            "output_sha256": self.output_sha256,
            "rule_ids": list(self.rule_ids),
        }


@dataclass(frozen=True, slots=True)
class WritingResult:
    """Raw transcript plus the exact text selected for insertion."""

    raw: RawTranscript
    final_text: str
    settings: WritingSettings
    trace: tuple[TransformationTrace, ...] = field(default_factory=tuple)
    cleanup_provider_id: str = "deterministic"
    fallback: bool = False
    fallback_code: str | None = None

    def __post_init__(self) -> None:
        if not self.final_text.strip():
            raise ValueError("final_text must not be blank")
        if self.fallback and not self.fallback_code:
            raise ValueError("fallback results must include fallback_code")
        if not self.fallback and self.fallback_code is not None:
            raise ValueError("non-fallback results must not include fallback_code")
        if not self.cleanup_provider_id.strip():
            raise ValueError("cleanup_provider_id must not be blank")
        _safe_identifier(self.cleanup_provider_id, "cleanup_provider_id")
        if self.fallback_code is not None:
            _safe_identifier(self.fallback_code, "fallback_code")
        object.__setattr__(self, "trace", tuple(self.trace))

    @property
    def raw_text(self) -> str:
        return self.raw.text

    @property
    def final_sha256(self) -> str:
        return text_sha256(self.final_text)

    def to_safe_dict(self) -> dict[str, object]:
        """Serialize recovery metadata without transcript or filesystem data."""

        return {
            "raw_text_sha256": text_sha256(self.raw_text),
            "final_text_sha256": self.final_sha256,
            "raw_text_length": len(self.raw_text),
            "final_text_length": len(self.final_text),
            "provider_id": _safe_metadata_identifier(self.raw.result.provider_id),
            "model_id": _safe_metadata_identifier(self.raw.result.model_id),
            "cleanup_provider_id": _safe_metadata_identifier(self.cleanup_provider_id),
            "settings": self.settings.to_safe_dict(),
            "trace": [stage.to_safe_dict() for stage in self.trace],
            "fallback": self.fallback,
            "fallback_code": self.fallback_code,
        }


def _freeze_words(words: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = {" ".join(word.split()).casefold() for word in words if word.strip()}
    return tuple(sorted(normalized))


def _freeze_ids(rule_ids: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    normalized = tuple(rule_ids)
    if any(not isinstance(rule_id, int) or rule_id < 1 for rule_id in normalized):
        raise ValueError("dictionary rule IDs must be positive integers")
    return normalized


__all__ = [
    "CleanupPolicy",
    "RawTranscript",
    "TextRule",
    "TransformationTrace",
    "WritingResult",
    "WritingSettings",
    "WritingStyle",
    "text_sha256",
]
