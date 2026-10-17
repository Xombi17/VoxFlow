import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from voxflow.audio.artifacts import AudioArtifact
from voxflow.platform.audio_devices import AudioFormat
from voxflow.providers.asr import (
    ASRValidationError,
    AudioInput,
    ProviderCapabilities,
    ProviderConfigSnapshot,
    Segment,
    TranscriptResult,
    validate_provider_result,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "audio" / "short_utterance.wav"
CHECKSUM = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
FORMAT = AudioFormat(48_000, 1)
CONFIG = ProviderConfigSnapshot(provider_id="fake", model_id="fixture")


def test_audio_input_preserves_artifact_identity_without_path_in_safe_metadata() -> None:
    artifact = AudioArtifact(
        path=FIXTURE,
        audio_sha256=CHECKSUM,
        source_format=FORMAT,
        frame_count=480,
        duration_ms=10,
        wav_byte_count=FIXTURE.stat().st_size,
    )

    audio = AudioInput.from_artifact(artifact, CONFIG)

    assert audio.audio_sha256 == CHECKSUM
    assert audio.to_dict()["artifact_id"] == FIXTURE.name
    assert str(FIXTURE) not in str(audio.to_dict())


def test_segments_reject_invalid_bounds_and_confidence() -> None:
    with pytest.raises(ValidationError):
        Segment(start_ms=50, end_ms=50, text="bad")
    with pytest.raises(ValidationError):
        Segment(start_ms=0, end_ms=50, text="bad", confidence=1.1)


def test_transcript_rejects_overlapping_segments_and_blank_identity() -> None:
    with pytest.raises(ValidationError):
        TranscriptResult(
            text="overlap",
            segments=(
                Segment(start_ms=0, end_ms=100, text="one"),
                Segment(start_ms=99, end_ms=200, text="two"),
            ),
            provider_id="fake",
            model_id="fixture",
            audio_sha256=CHECKSUM,
        )
    with pytest.raises(ValidationError):
        TranscriptResult(
            text="bad",
            provider_id="",
            model_id="fixture",
            audio_sha256=CHECKSUM,
        )


def test_result_checksum_mismatch_is_typed_and_safe() -> None:
    result = TranscriptResult(
        text="private transcript",
        provider_id="fake",
        model_id="fixture",
        audio_sha256=CHECKSUM,
    )

    with pytest.raises(ASRValidationError):
        validate_provider_result(result, "0" * 64)
    assert "private transcript" not in str(result.to_safe_dict())


def test_capabilities_reject_contradictory_network_metadata() -> None:
    with pytest.raises(ValidationError):
        ProviderCapabilities(
            provider_id="fake",
            model_id="fixture",
            offline=True,
            network_required=True,
            supports_cancellation=True,
        )
