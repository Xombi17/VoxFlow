#!/usr/bin/env python3
"""Run an explicitly selected local ASR benchmark and print redacted JSON."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import wave
from pathlib import Path

from voxflow.audio.artifacts import AudioArtifact
from voxflow.evals.metrics import run_benchmark
from voxflow.platform.audio_devices import AudioFormat
from voxflow.providers.asr import ProviderConfigSnapshot
from voxflow.providers.local_whisper import LocalWhisperProvider, discover_local_model


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark an explicitly installed faster-whisper profile. "
            "No model download is attempted."
        )
    )
    parser.add_argument("--fixture", type=Path, required=True, help="checked-in WAV fixture")
    parser.add_argument("--model-root", type=Path, required=True, help="installed model directory")
    parser.add_argument("--model-id", required=True, help="portable model profile ID")
    parser.add_argument("--runs", type=int, default=3, help="number of warm runs")
    parser.add_argument("--language", default=None, help="optional language hint")
    parser.add_argument("--device", default="cpu", help="explicit inference device")
    parser.add_argument("--threads", type=int, default=1, help="explicit inference thread count")
    parser.add_argument("--json", action="store_true", help="emit the redacted JSON report")
    args = parser.parse_args()

    discovery = discover_local_model(args.model_root, model_id=args.model_id)
    if not discovery.available:
        parser.error(discovery.error_code or "selected model is unavailable")
    artifact = _read_wav_artifact(args.fixture)
    config = ProviderConfigSnapshot(
        provider_id="local-whisper",
        model_id=args.model_id,
        language_hint=args.language,
        device=args.device,
        thread_count=args.threads,
    )
    provider = LocalWhisperProvider(discovery.profile, config=config)
    report = asyncio.run(run_benchmark(provider, artifact, runs=args.runs))
    # The non-JSON form remains a terse local diagnostic without adding fields.
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True))
    else:
        record = report.records[0]
        print(
            f"status={record.status} provider={record.provider_id} model={record.model_id} "
            f"warm_p50_ms={record.warm_p50_ms} warm_p95_ms={record.warm_p95_ms}"
        )
    return 0


def _read_wav_artifact(path: Path) -> AudioArtifact:
    """Read fixture metadata without copying or embedding its bytes in output."""

    if not path.is_file():
        raise SystemExit("fixture WAV is unavailable")
    wav_bytes = path.read_bytes()
    try:
        with wave.open(str(path), "rb") as wav_file:
            audio_format = AudioFormat(wav_file.getframerate(), wav_file.getnchannels())
            frame_count = wav_file.getnframes()
    except (wave.Error, ValueError) as exc:
        raise SystemExit("fixture is not a supported WAV") from exc
    duration_ms = max(1, (frame_count * 1000) // audio_format.sample_rate)
    return AudioArtifact(
        path=path,
        audio_sha256=hashlib.sha256(wav_bytes).hexdigest(),
        source_format=audio_format,
        frame_count=frame_count,
        duration_ms=duration_ms,
        wav_byte_count=len(wav_bytes),
    )


if __name__ == "__main__":
    raise SystemExit(main())
