import pytest

from voxflow.providers.asr import Segment, TranscriptResult
from voxflow.text.contracts import (
    CleanupPolicy,
    RawTranscript,
    TextRule,
    TransformationTrace,
    WritingResult,
    WritingSettings,
    WritingStyle,
    text_sha256,
)


def transcript(text="hello world", *, language="en"):
    return TranscriptResult(
        text=text,
        language=language,
        segments=(Segment(start_ms=0, end_ms=100, text=text),),
        provider_id="fake",
        model_id="small.en",
        audio_sha256="a" * 64,
    )


def test_raw_transcript_keeps_validated_result_immutable():
    raw = RawTranscript(transcript())

    assert raw.text == "hello world"
    with pytest.raises(Exception):
        raw.result.text = "changed"


def test_writing_settings_normalize_words_and_are_frozen():
    settings = WritingSettings(
        language="en-US",
        style=WritingStyle.EMAIL,
        cleanup_policy=CleanupPolicy.DETERMINISTIC,
        dictionary_words=(" VoxFlow ", "Alice"),
        corrections=(TextRule(2, "adress", "address"),),
    )

    assert settings.language == "en-US"
    assert settings.dictionary_words == ("alice", "voxflow")
    assert settings.style is WritingStyle.EMAIL
    with pytest.raises(Exception):
        settings.language = "fr"


def test_invalid_settings_and_rules_are_rejected():
    with pytest.raises(ValueError, match="language"):
        WritingSettings(language="not a language")
    with pytest.raises(ValueError, match="trigger"):
        TextRule(1, "   ", "replacement")
    with pytest.raises(ValueError, match="replacement"):
        TextRule(1, "trigger", "   ")


def test_trace_uses_hashes_and_writing_result_safe_dict_redacts_text():
    raw = RawTranscript(transcript("um hello"))
    final = "Hello."
    trace = TransformationTrace(
        stage="filler_cleanup",
        changed=True,
        input_sha256=text_sha256(raw.text),
        output_sha256=text_sha256(final),
    )
    result = WritingResult(raw=raw, final_text=final, settings=WritingSettings(), trace=(trace,))

    safe = result.to_safe_dict()
    assert safe["raw_text_sha256"] == text_sha256("um hello")
    assert safe["final_text_sha256"] == text_sha256(final)
    assert "um hello" not in str(safe)
    assert "Hello." not in str(safe)
    assert safe["trace"][0]["stage"] == "filler_cleanup"


def test_safe_metadata_sanitizes_asr_language_and_validates_trace_fields():
    safe = RawTranscript(transcript(language="/tmp/private-language")).to_safe_dict()

    assert safe["language"] == "redacted"
    with pytest.raises(ValueError, match="trace hashes"):
        TransformationTrace(
            stage="filler_cleanup",
            changed=True,
            input_sha256="g" * 64,
            output_sha256="a" * 64,
        )
    with pytest.raises(ValueError, match="trace stage"):
        TransformationTrace(
            stage="../private",
            changed=False,
            input_sha256="a" * 64,
            output_sha256="a" * 64,
        )


def test_fallback_result_requires_a_stable_code():
    raw = RawTranscript(transcript())
    with pytest.raises(ValueError, match="fallback_code"):
        WritingResult(
            raw=raw,
            final_text=raw.text,
            settings=WritingSettings(),
            fallback=True,
        )


def test_safe_identifiers_reject_local_paths():
    with pytest.raises(ValueError, match="safe identifier"):
        WritingSettings(cleanup_provider_id="/home/alice/private")
