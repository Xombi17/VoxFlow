import json
from pathlib import Path

import pytest

from voxflow.providers.asr import Segment, TranscriptResult
from voxflow.text.contracts import TextRule, WritingSettings, WritingStyle
from voxflow.text.pipeline import DeterministicWritingPipeline
from voxflow.text.rules import apply_rules


FIXTURES = Path(__file__).parents[1] / "fixtures" / "text" / "writing_cases.json"


def make_transcript(text: str) -> TranscriptResult:
    return TranscriptResult(
        text=text,
        language="en",
        segments=(Segment(start_ms=0, end_ms=100, text=text),),
        provider_id="fake",
        model_id="small.en",
        audio_sha256="b" * 64,
    )


def test_golden_writing_cases_are_exact():
    pipeline = DeterministicWritingPipeline()
    for case in json.loads(FIXTURES.read_text()):
        settings_data = case.get("settings", {})
        settings = WritingSettings(
            snippets=tuple(TextRule(**rule) for rule in settings_data.get("snippets", [])),
            corrections=tuple(TextRule(**rule) for rule in settings_data.get("corrections", [])),
        )
        result = pipeline.run(make_transcript(case["raw"]), settings)
        assert result.final_text == case["final"], case["name"]
        assert result.raw_text == case["raw"]


def test_longest_snippet_and_correction_rules_win_deterministically():
    settings = WritingSettings(
        snippets=(
            TextRule(20, "my email", "alice@example.com"),
            TextRule(10, "email", "short@example.com"),
        ),
        corrections=(
            TextRule(30, "vox flow", "VoxFlow"),
            TextRule(5, "vox", "wrong"),
        ),
    )

    result = DeterministicWritingPipeline().run(
        make_transcript("my email and vox flow"),
        settings,
    )

    assert result.final_text == "alice@example.com and VoxFlow."
    assert result.trace[3].rule_ids == (20,)
    assert result.trace[4].rule_ids == (30,)


def test_dictionary_words_are_preserved_while_uncertain_text_is_left_alone():
    settings = WritingSettings(dictionary_words=("voxflow", "PostgreSQL"))

    result = DeterministicWritingPipeline().run(
        make_transcript("voxflow connects to PostgreSQL via snake_case"),
        settings,
    )

    assert result.final_text == "voxflow connects to PostgreSQL via snake_case."


def test_rule_replacements_are_literal_and_do_not_retrigger_shorter_rules():
    settings = WritingSettings(
        corrections=(
            TextRule(1, "vox flow", r"C:\Users\Alice"),
            TextRule(2, "C", "CORRUPTED"),
        ),
    )
    result = DeterministicWritingPipeline().run(make_transcript("vox flow"), settings)

    assert result.final_text == r"C:\Users\Alice."


def test_protected_spans_cannot_be_rewritten_by_numeric_rules():
    settings = WritingSettings(corrections=(TextRule(1, "0", "ZERO"),))

    result = DeterministicWritingPipeline().run(
        make_transcript("visit https://example.com/0"),
        settings,
    )

    assert result.final_text == "Visit https://example.com/0."


def test_posix_paths_are_protected_from_rule_rewrites():
    settings = WritingSettings(
        corrections=(
            TextRule(1, "home", "CORRUPTED"),
            TextRule(2, "alice", "CORRUPTED"),
        )
    )

    result = DeterministicWritingPipeline().run(
        make_transcript("open /home/alice/notes/today.txt"),
        settings,
    )

    assert result.final_text == "Open /home/alice/notes/today.txt."


def test_ambiguous_words_and_self_corrections_are_left_alone():
    pipeline = DeterministicWritingPipeline()

    ordinary = pipeline.run(make_transcript("the period is short"))
    uncertain = pipeline.run(make_transcript("The old plan, no, the new plan, is ready"))

    assert ordinary.final_text == "The period is short."
    assert uncertain.final_text == "The old plan, no, the new plan, is ready."


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("visit https://example.com.", "Visit https://example.com."),
        ('say "hello."', 'Say "hello."'),
        ("hello world", "Hello world."),
    ],
)
def test_terminal_punctuation_is_not_duplicated_after_protected_spans(raw, expected):
    result = DeterministicWritingPipeline().run(make_transcript(raw))

    assert result.final_text == expected


def test_spoken_semi_colon_is_formatted_without_lookup_failure():
    result = DeterministicWritingPipeline().run(make_transcript("one semi colon two"))

    assert result.final_text == "One; two."


def test_other_style_preserves_sentence_case_while_personal_formats_it():
    pipeline = DeterministicWritingPipeline()

    personal = pipeline.run(make_transcript("hello world"), WritingSettings())
    other = pipeline.run(
        make_transcript("hello world"), WritingSettings(style=WritingStyle.OTHER)
    )

    assert personal.final_text == "Hello world."
    assert other.final_text == "hello world."


def test_blank_cleanup_uses_an_explicit_fallback_trace():
    result = DeterministicWritingPipeline().run(make_transcript("um"))

    assert result.final_text == "um"
    assert result.fallback is True
    assert result.fallback_code == "blank_output"
    assert result.trace[-1].stage == "blank_output_fallback"


def test_pipeline_is_repeatable_and_safe_diagnostics_omit_text():
    pipeline = DeterministicWritingPipeline()
    transcript = make_transcript("um hello comma world")

    first = pipeline.run(transcript)
    second = pipeline.run(transcript)

    assert first.final_text == second.final_text == "Hello, world."
    assert first.to_safe_dict() == second.to_safe_dict()
    assert "hello comma world" not in str(first.to_safe_dict())


def test_shared_rule_helper_uses_id_tie_breaking_and_ignores_disabled_rules():
    rules = (
        TextRule(8, "go now", "later"),
        TextRule(2, "go now", "immediately"),
        TextRule(1, "go", "disabled", enabled=False),
    )

    result, rule_ids = apply_rules("go now", rules)

    assert result == "immediately"
    assert rule_ids == (2,)


def test_snippets_win_before_corrections_and_dictionary_is_not_a_replacement():
    settings = WritingSettings(
        dictionary_words=("VoxFlow",),
        snippets=(TextRule(20, "my address", "VoxFlow HQ"),),
        corrections=(
            TextRule(4, "my address", "the address"),
            TextRule(5, "VoxFlow", "wrong"),
        ),
    )

    result = DeterministicWritingPipeline().run(
        make_transcript("my address is VoxFlow"),
        settings,
    )

    assert result.final_text == "VoxFlow HQ is VoxFlow."
    assert result.trace[3].rule_ids == (20,)
    assert result.trace[4].rule_ids == ()
