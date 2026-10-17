import asyncio
import hashlib
import json
from pathlib import Path

from voxflow.audio.artifacts import AudioArtifact
from voxflow.evals.metrics import run_benchmark
from voxflow.platform.audio_devices import AudioFormat
from voxflow.providers.asr import (
    ASRCancellationError,
    CancellationToken,
    ProviderCapabilities,
    ProviderConfigSnapshot,
    Segment,
    TranscriptResult,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "audio" / "short_utterance.wav"
CHECKSUM = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


def audio_artifact() -> AudioArtifact:
    return AudioArtifact(
        path=FIXTURE,
        audio_sha256=CHECKSUM,
        source_format=AudioFormat(48_000, 1),
        frame_count=480,
        duration_ms=10,
        wav_byte_count=FIXTURE.stat().st_size,
    )


class FakeBenchmarkProvider:
    config = ProviderConfigSnapshot(provider_id="fake", model_id="fixture")

    def __init__(self):
        self.prepared = 0

    @property
    def capabilities(self):
        return ProviderCapabilities(
            provider_id="fake",
            model_id="fixture",
            offline=True,
            network_required=False,
            supports_cancellation=True,
        )

    async def prepare(self):
        self.prepared += 1
        await asyncio.sleep(0.001)

    async def transcribe(self, audio, cancellation: CancellationToken):
        await asyncio.sleep(0.001)
        if cancellation.is_cancelled:
            raise ASRCancellationError()
        return TranscriptResult(
            text="fixture transcript must not be serialized",
            language="en",
            segments=(Segment(start_ms=0, end_ms=10, text="fixture"),),
            provider_id="fake",
            model_id="fixture",
            audio_sha256=audio.audio_sha256,
        )


def test_fake_benchmark_separates_cold_warm_end_to_end_and_cancel_metrics() -> None:
    provider = FakeBenchmarkProvider()

    report = asyncio.run(run_benchmark(provider, audio_artifact(), runs=3, job_id="bench-1"))
    serialized = report.to_dict()
    record = serialized["records"][0]

    assert provider.prepared == 1
    assert record["timings_ms"]["cold_start"] is not None
    assert record["timings_ms"]["warm_inference"] is not None
    assert record["timings_ms"]["end_to_end"] is not None
    assert record["timings_ms"]["cancellation"] is not None
    assert record["warm_distribution_ms"]["p50"] is not None
    assert record["warm_distribution_ms"]["p95"] is not None
    assert record["realtime_factor"] is not None
    assert record["peak_resource_mb"] is not None
    assert report.warm_p95_ms >= report.warm_p50_ms


def test_benchmark_serialization_is_allowlisted_and_local_only() -> None:
    provider = FakeBenchmarkProvider()
    report = asyncio.run(run_benchmark(provider, audio_artifact(), runs=1, job_id="bench-2"))
    serialized = json.dumps(report.to_dict(), sort_keys=True).lower()

    for forbidden in ("audio", "transcript", "text", "token", "credential", "secret"):
        assert forbidden not in serialized
    assert "/home/" not in serialized
    assert "/tmp/" not in serialized
    assert "fixture" in serialized


def test_asr_manifest_is_available_without_personal_reference_text() -> None:
    manifest = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "asr" / "manifest.json").read_text()
    )

    assert len(manifest["fixtures"]) >= 7
    assert all("sha256" in item for item in manifest["fixtures"])
    assert all("transcript" not in item for item in manifest["fixtures"])
