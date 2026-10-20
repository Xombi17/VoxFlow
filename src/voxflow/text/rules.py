"""Typed personalization records and deterministic rule matching helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .contracts import TextRule


class RuleKind(StrEnum):
    """The persisted kinds of user-authored writing rules."""

    DICTIONARY = "dictionary"
    CORRECTION = "correction"
    SNIPPET = "snippet"


def normalize_trigger(value: str) -> str:
    """Normalize rule spacing without locale-sensitive case conversion."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("rule trigger must not be blank")
    return " ".join(value.split())


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    """A dictionary word as returned by the persistence boundary."""

    rule_id: int
    word: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.rule_id < 1:
            raise ValueError("rule_id must be positive")
        object.__setattr__(self, "word", normalize_trigger(self.word))

    @property
    def normalized_word(self) -> str:
        return self.word.casefold()

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "enabled": self.enabled,
            "word_length": len(self.word),
        }


@dataclass(frozen=True, slots=True)
class StoredRule:
    """A persisted correction or snippet, without exposing values in metadata."""

    rule_id: int
    kind: RuleKind
    trigger: str
    replacement: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.rule_id < 1:
            raise ValueError("rule_id must be positive")
        object.__setattr__(self, "kind", RuleKind(self.kind))
        object.__setattr__(self, "trigger", normalize_trigger(self.trigger))
        if not isinstance(self.replacement, str) or not self.replacement.strip():
            raise ValueError("rule replacement must not be blank")

    @property
    def normalized_trigger(self) -> str:
        return self.trigger.casefold()

    def to_text_rule(self) -> TextRule:
        return TextRule(
            rule_id=self.rule_id,
            trigger=self.trigger,
            replacement=self.replacement,
            enabled=self.enabled,
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "kind": self.kind.value,
            "enabled": self.enabled,
            "trigger_length": len(self.trigger),
            "replacement_length": len(self.replacement),
        }


_PROTECTED_TOKEN = "\ue000{index}\ue001"
_PROTECTED_TOKEN_RE = re.compile(r"\ue000\d+\ue001")
_URL = r"https?://[^\s<>]+"
_EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
_QUOTED = r'"[^"\n]*"|\'[^\'\n]*\''
_WINDOWS_PATH = r"[A-Za-z]:\\[^\s<>]+"
_POSIX_PATH = r"(?<!\w)(?:~|\.{1,2})?/(?:[^\s<>/]+/)*[^\s<>/]+"
_CODE = r"`[^`\n]+`|(?<!\w)(?:--?[A-Za-z0-9][\w-]*|[A-Za-z_][\w]*_[A-Za-z0-9_]+|[A-Za-z_]\w*\(\))(?!\w)"
_PROTECTED_RE = re.compile(
    rf"(?P<quoted>{_QUOTED})|(?P<url>{_URL})|(?P<email>{_EMAIL})|"
    rf"(?P<windows_path>{_WINDOWS_PATH})|(?P<posix_path>{_POSIX_PATH})|(?P<code>{_CODE})"
)


def protect_text(
    value: str,
    *,
    extra_terms: tuple[str, ...] = (),
) -> tuple[str, dict[str, str]]:
    """Replace protected spans with collision-checked deterministic tokens."""

    values: dict[str, str] = {}
    next_index = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal next_index
        while True:
            token = _PROTECTED_TOKEN.format(index=next_index)
            next_index += 1
            if token not in value and token not in values:
                break
        values[token] = match.group(0)
        return token

    protected = _PROTECTED_RE.sub(replace, value)
    for term in sorted((term for term in extra_terms if term.strip()), key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.I)
        protected = pattern.sub(replace, protected)
    return protected, values


def restore_text(value: str, values: dict[str, str]) -> str:
    for token, original in values.items():
        value = value.replace(token, original)
    return value


def ordered_rules(rules: tuple[TextRule, ...]) -> tuple[TextRule, ...]:
    """Return active rules in the shared longest-trigger/lowest-ID order."""

    return tuple(
        sorted(
            (rule for rule in rules if rule.enabled),
            key=lambda rule: (-len(rule.normalized_trigger), rule.rule_id),
        )
    )


def find_matching_rule(
    value: str,
    rules: tuple[TextRule, ...],
    *,
    whole_phrase: bool = True,
) -> TextRule | None:
    """Find the first applicable rule using deterministic precedence."""

    del whole_phrase  # Both supported rule kinds use whole-word boundaries.
    for rule in ordered_rules(rules):
        pattern = re.compile(rf"(?<!\w){re.escape(rule.trigger)}(?!\w)", re.I)
        if pattern.search(value):
            return rule
    return None


def apply_rules(
    value: str,
    rules: tuple[TextRule, ...],
    *,
    whole_phrase: bool = True,
    extra_terms: tuple[str, ...] = (),
) -> tuple[str, tuple[int, ...]]:
    """Apply enabled rules once, protecting URLs, code, quotes, and emails."""

    del whole_phrase  # Both supported rule kinds use whole-word boundaries.
    active = ordered_rules(rules)
    if not active:
        return value, ()

    protected, protected_values = protect_text(value, extra_terms=extra_terms)
    alternatives = "|".join(re.escape(rule.trigger) for rule in active)
    pattern = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.I)
    applied: list[int] = []

    def replace(match: re.Match[str]) -> str:
        matched = match.group(0).casefold()
        rule = next(
            candidate
            for candidate in active
            if candidate.normalized_trigger == matched
        )
        applied.append(rule.rule_id)
        return rule.replacement

    chunks = re.split(rf"({_PROTECTED_TOKEN_RE.pattern})", protected)
    for index in range(0, len(chunks), 2):
        chunks[index] = pattern.sub(replace, chunks[index])
    return restore_text("".join(chunks), protected_values), tuple(applied)


__all__ = [
    "DictionaryEntry",
    "RuleKind",
    "StoredRule",
    "apply_rules",
    "find_matching_rule",
    "normalize_trigger",
    "ordered_rules",
    "protect_text",
    "restore_text",
]
