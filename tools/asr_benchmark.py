#!/usr/bin/env python3
"""Run explicit local ASR benchmarks without downloading or echoing transcripts."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import wave
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from voxflow.audio.artifacts import AudioArtifact
from voxflow.evals.metrics import run_benchmark, select_default, word_error_rate
from voxflow.platform.audio_devices import AudioFormat
from voxflow.providers import catalog
from voxflow.providers.asr import (
    AudioInput,
    CancellationToken,
    ProviderConfigSnapshot,
    validate_provider_result,
)
from voxflow.providers.local_whisper import LocalWhisperProvider, discover_local_model


REFERENCE_SENTENCE = (
    "Please send the report to Alice by Friday afternoon, and remind her about the "
    "budget meeting."
)
HELP_EPILOG = (
    "For --catalog, provide a user-recorded WAV of about 6 seconds. Read this "
    f"fixed sentence at a natural pace: {REFERENCE_SENTENCE!r}"
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark explicitly installed local ASR profiles. No model download "
            "is attempted."
        ),
        epilog=HELP_EPILOG,
    )
    parser.add_argument("--fixture", type=Path, required=True, help="user-recorded WAV fixture")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--catalog",
        action="store_true",
        help="benchmark every installed catalogue entry under the default models root",
    )
    mode.add_argument("--model-root", type=Path, help="one installed model directory")
    parser.add_argument("--model-id", help="portable model profile ID for single-model mode")
    reference = parser.add_mutually_exclusive_group()
    reference.add_argument("--reference-text", help="reference sentence used to compute WER")
    reference.add_argument("--reference-file", type=Path, help="UTF-8 file containing the reference sentence")
    parser.add_argument(
        "--allow-no-reference",
        action="store_true",
        help="allow catalog mode with null WER and an unvalidated selection",
    )
    parser.add_argument("--runs", type=int, default=3, help="number of warm runs")
    parser.add_argument("--language", default=None, help="optional language hint")
    parser.add_argument("--device", default="cpu", help="explicit inference device")
    parser.add_argument("--threads", type=int, default=1, help="explicit inference thread count")
    parser.add_argument("--json", action="store_true", help="emit the redacted JSON report")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.catalog:
        reference_text = _reference_text(args, parser)
        payload = asyncio.run(
            run_catalog_benchmark(
                args.fixture,
                catalog.default_models_root(),
                runs=args.runs,
                reference_text=reference_text,
                language=args.language,
                device=args.device,
                threads=args.threads,
            )
        )
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                f"status={payload['status']} default={payload['default']} "
                f"models={len(payload['results'])} results={catalog.results_path(catalog.default_models_root())}"
            )
        return 0

    if args.model_root is None or not args.model_id:
        parser.error("single-model mode requires --model-root and --model-id")
    if args.reference_text is not None or args.reference_file is not None or args.allow_no_reference:
        parser.error("reference arguments are only valid with --catalog")

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
    if args.json:
        print(json.dumps(report.to_dict(), sort_keys=True))
    else:
        record = report.records[0]
        print(
            f"status={record.status} provider={record.provider_id} model={record.model_id} "
            f"warm_p50_ms={record.warm_p50_ms} warm_p95_ms={record.warm_p95_ms}"
        )
    return 0


async def run_catalog_benchmark(
    fixture: Path,
    model_root: Path,
    *,
    runs: int = 3,
    reference_text: str | None = None,
    language: str | None = None,
    device: str = "cpu",
    threads: int = 1,
    catalog_module: Any = catalog,
) -> dict[str, object]:
    """Benchmark installed entries and merge the redacted rows into the catalogue."""

    if runs < 1:
        raise ValueError("runs must be positive")
    artifact = _read_wav_artifact(fixture)
    rows = catalog_module.load_results(model_root)
    measured: dict[str, dict[str, object]] = {}
    for entry in catalog_module.load_catalog().models:
        if not catalog_module.is_installed(model_root, entry.id):
            print(f"skip {entry.id}: not installed", file=sys.stderr)
            continue
        provider = catalog_module.build_provider(entry, model_root)
        report = await run_benchmark(provider, artifact, runs=runs)
        hypothesis = await _transcribe_once(provider, artifact, language, device, threads)
        wer = word_error_rate(reference_text, hypothesis) if reference_text is not None else None
        measured[entry.id] = catalog_module.result_record(
            report.warm_p50_ms if report.warm_p50_ms is not None else 0.0,
            report.warm_p95_ms if report.warm_p95_ms is not None else 0.0,
            wer,
            str(fixture),
        )
    rows.update(measured)
    catalog_module.save_results(model_root, rows)
    selection = select_default(measured)
    payload: dict[str, object] = {
        "schema_version": 1,
        "fixture": fixture.name,
        "fixture_duration_ms": artifact.duration_ms,
        "fixture_requirement": "approximately 6 seconds",
        "reference_sha256": (
            hashlib.sha256(reference_text.encode("utf-8")).hexdigest()
            if reference_text is not None
            else None
        ),
        "results": measured,
        "status": selection["status"],
        "default": selection["default"],
        "message": selection["message"],
    }
    if selection["status"] == "unvalidated_accuracy":
        payload["fastest"] = selection["fastest"]
    return payload


async def _transcribe_once(
    provider: Any,
    artifact: AudioArtifact,
    language: str | None,
    device: str,
    threads: int,
) -> str:
    config = getattr(provider, "config", None)
    if config is None:
        capabilities = provider.capabilities
        config = ProviderConfigSnapshot(
            provider_id=capabilities.provider_id,
            model_id=capabilities.model_id,
            language_hint=language,
            device=device,
            thread_count=threads,
        )
    audio = AudioInput.from_artifact(artifact, config)
    result = await provider.transcribe(audio, CancellationToken())
    return validate_provider_result(result, artifact.audio_sha256).text


def _reference_text(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str | None:
    if args.reference_text is not None:
        reference = args.reference_text.strip()
    elif args.reference_file is not None:
        try:
            reference = args.reference_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            parser.error(f"could not read --reference-file: {exc}")
    elif args.allow_no_reference:
        return None
    else:
        parser.error(
            "--catalog requires exactly one of --reference-text or --reference-file "
            "unless --allow-no-reference is passed"
        )
    if not reference:
        parser.error("the reference text must contain at least one word")
    return reference


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
