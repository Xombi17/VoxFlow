import hashlib
import json
import wave
from pathlib import Path

from voxflow.audio.artifacts import AudioArtifact, write_wav_artifact
from voxflow.platform.audio_devices import AudioFormat


FORMAT = AudioFormat(sample_rate=48_000, channels=1)


def test_write_wav_artifact_preserves_source_format_and_checksum(tmp_path) -> None:
    pcm = b"\x01\x00\x02\x00" * 480

    artifact = write_wav_artifact(tmp_path, pcm, FORMAT, 960, artifact_name="utterance.wav")

    assert isinstance(artifact, AudioArtifact)
    assert artifact.path == tmp_path / "utterance.wav"
    assert artifact.source_format == FORMAT
    assert artifact.frame_count == 960
    assert artifact.duration_ms == 20
    assert artifact.audio_sha256 == hashlib.sha256(artifact.path.read_bytes()).hexdigest()
    with wave.open(str(artifact.path), "rb") as wav_file:
        assert wav_file.getframerate() == 48_000
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getnframes() == 960

    serialized = json.dumps(artifact.to_dict())
    assert str(tmp_path) not in serialized
    assert "\x01" not in serialized


def test_write_wav_artifact_rejects_non_pcm16_frame_length(tmp_path) -> None:
    try:
        write_wav_artifact(tmp_path, b"\x00", FORMAT, 1)
    except ValueError as exc:
        assert "PCM16" in str(exc)
    else:
        raise AssertionError("invalid PCM16 frame length was accepted")


def test_checked_in_fixture_manifest_has_stable_non_personal_checksum() -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "audio"
    manifest = json.loads((fixture_dir / "manifest.json").read_text())
    fixture = manifest["fixtures"][0]
    fixture_path = fixture_dir / fixture["file"]

    assert fixture["id"] == "short-utterance-generated-001"
    assert fixture["non_personal"] is True
    assert fixture["permitted_for_repository_tests"] is True
    assert fixture["sha256"] == hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert "/home/" not in json.dumps(manifest)
    assert "/tmp/" not in json.dumps(manifest)
