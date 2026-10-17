"""Immutable source-format WAV artifacts for the audio/provider boundary."""

from __future__ import annotations

import hashlib
import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from ..platform.audio_devices import AudioFormat


PCM_SAMPLE_WIDTH_BYTES = 2
PCM_ENCODING = "PCM_S16LE"


@dataclass(frozen=True, slots=True)
class AudioArtifact:
    """Metadata for one exact WAV byte sequence retained on disk."""

    path: Path
    audio_sha256: str
    source_format: AudioFormat
    frame_count: int
    duration_ms: int
    sample_width_bytes: int = PCM_SAMPLE_WIDTH_BYTES
    encoding: str = PCM_ENCODING
    wav_byte_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if len(self.audio_sha256) != hashlib.sha256().digest_size * 2:
            raise ValueError("audio_sha256 must be a hexadecimal SHA-256 digest")
        try:
            int(self.audio_sha256, 16)
        except ValueError as exc:
            raise ValueError("audio_sha256 must be hexadecimal") from exc
        if self.frame_count < 1:
            raise ValueError("frame_count must be positive")
        if self.duration_ms < 1:
            raise ValueError("duration_ms must be positive")
        if self.sample_width_bytes != PCM_SAMPLE_WIDTH_BYTES:
            raise ValueError("only 16-bit PCM artifacts are supported")
        if self.encoding != PCM_ENCODING:
            raise ValueError("only PCM_S16LE artifacts are supported")
        if self.wav_byte_count < 1:
            raise ValueError("wav_byte_count must be positive")

    @property
    def artifact_id(self) -> str:
        """Return a non-path identity suitable for diagnostics and events."""

        return self.path.name

    def to_dict(self) -> dict[str, object]:
        """Serialize safe metadata without exposing an absolute machine path."""

        return {
            "artifact_id": self.artifact_id,
            "audio_sha256": self.audio_sha256,
            "source_format": self.source_format.to_dict(),
            "encoding": self.encoding,
            "sample_width_bytes": self.sample_width_bytes,
            "frame_count": self.frame_count,
            "duration_ms": self.duration_ms,
            "wav_byte_count": self.wav_byte_count,
        }


def write_wav_artifact(
    directory: str | Path,
    audio_bytes: bytes,
    audio_format: AudioFormat,
    frame_count: int,
    *,
    artifact_name: str | None = None,
) -> AudioArtifact:
    """Write exact interleaved PCM16 frames and return their immutable identity.

    The temporary file is created beside the final artifact and atomically renamed
    after ``wave`` has written the complete header and payload. The checksum is
    computed over the exact bytes that are available to a future ASR provider.
    """

    if not isinstance(audio_bytes, bytes):
        raise TypeError("audio_bytes must be immutable bytes")
    if frame_count < 1:
        raise ValueError("frame_count must be positive")
    expected_bytes = frame_count * audio_format.channels * PCM_SAMPLE_WIDTH_BYTES
    if len(audio_bytes) != expected_bytes:
        raise ValueError(
            "audio_bytes length does not match frame_count, channel count, and PCM16"
        )

    output_dir = Path(directory)
    output_dir.mkdir(parents=True, exist_ok=True)
    name = artifact_name or "capture.wav"
    final_path = output_dir / name
    if final_path.suffix.lower() != ".wav":
        raise ValueError("artifact_name must use the .wav suffix")
    if final_path.name in {".", ".."} or final_path.name != name:
        raise ValueError("artifact_name must be a single safe filename")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_dir,
            prefix=".voxflow-",
            suffix=".wav",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with wave.open(str(temporary_path), "wb") as wav_file:
            wav_file.setnchannels(audio_format.channels)
            wav_file.setsampwidth(PCM_SAMPLE_WIDTH_BYTES)
            wav_file.setframerate(audio_format.sample_rate)
            wav_file.writeframes(audio_bytes)
        os.replace(temporary_path, final_path)
        temporary_path = None
        wav_bytes = final_path.read_bytes()
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    duration_ms = max(1, (frame_count * 1000) // audio_format.sample_rate)
    return AudioArtifact(
        path=final_path,
        audio_sha256=hashlib.sha256(wav_bytes).hexdigest(),
        source_format=audio_format,
        frame_count=frame_count,
        duration_ms=duration_ms,
        wav_byte_count=len(wav_bytes),
    )
