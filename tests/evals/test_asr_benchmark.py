import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from voxflow.audio.artifacts import AudioArtifact
from voxflow.evals.metrics import run_benchmark, select_default, word_error_rate
from voxflow.platform.audio_devices import AudioFormat
from voxflow.providers.asr import (
    ASRCancellationError,
    CancellationToken,
    ProviderCapabilities,
    ProviderConfigSnapshot,
    Segment,
    TranscriptResult,
)


BENCHMARK_TOOL = Path(__file__).parents[2] / "tools" / "asr_benchmark.py"


def benchmark_tool():
    spec = importlib.util.spec_from_file_location("voxflow_asr_benchmark", BENCHMARK_TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


@pytest.mark.parametrize(
    ("reference", "hypothesis", "expected"),
    [
        ("Hello, world!", "hello world", 0.0),
        ("one two three four five six seven eight nine ten", "one two three four five six seven eight nine X", 10.0),
    ],
)
def test_word_error_rate_is_case_insensitive_and_word_based(reference, hypothesis, expected):
    assert word_error_rate(reference, hypothesis) == expected


def test_word_error_rate_rejects_empty_reference():
    with pytest.raises(ValueError):
        word_error_rate("  !!! ", "words")


def test_select_default_uses_accuracy_threshold_then_lowest_p50():
    decision = select_default(
        {
            "medium.en": {"wer": 10.0, "p50_ms": 900.0},
            "small.en": {"wer": 11.0, "p50_ms": 600.0},
            "parakeet": {"wer": 11.5, "p50_ms": 300.0},
            "distil": {"wer": 20.0, "p50_ms": 100.0},
        }
    )
    assert decision["status"] == "ok"
    assert decision["default"] == "parakeet"


def test_select_default_handles_single_candidate_and_target_miss():
    decision = select_default(
        {
            "medium.en": {"wer": 0.0, "p50_ms": 900.0},
            "small.en": {"wer": 1.0, "p50_ms": 701.0},
        }
    )
    assert decision["status"] == "no_default_under_target"
    assert decision["default"] == "small.en"


def test_select_default_never_chooses_medium_and_flags_missing_accuracy():
    no_wer = select_default(
        {
            "medium.en": {"wer": None, "p50_ms": 10.0},
            "small.en": {"wer": None, "p50_ms": 20.0},
        }
    )
    medium_only = select_default(
        {
            "medium.en": {"wer": 0.0, "p50_ms": 10.0},
            "small.en": {"wer": None, "p50_ms": 20.0},
        }
    )
    assert no_wer["status"] == medium_only["status"] == "unvalidated_accuracy"
    assert no_wer["default"] is medium_only["default"] is None
    assert no_wer["fastest"] == medium_only["fastest"] == "small.en"
    assert no_wer["best_wer"] is None
    assert medium_only["best_wer"] == 0.0


class FakeCatalogForBenchmark:
    def __init__(self, providers, installed):
        self.providers = providers
        self.installed = set(installed)

    def load_catalog(self):
        return type(
            "FakeCatalog",
            (),
            {"models": tuple(type("Entry", (), {"id": model_id})() for model_id in self.providers)},
        )()

    def is_installed(self, _root, model_id):
        return model_id in self.installed

    def build_provider(self, entry, _root):
        return self.providers[entry.id]

    def load_results(self, root):
        from voxflow.providers.catalog import load_results

        return load_results(root)

    def save_results(self, root, results):
        from voxflow.providers.catalog import save_results

        save_results(root, results)

    def result_record(self, p50, p95, wer, fixture):
        from voxflow.providers.catalog import result_record

        return result_record(p50, p95, wer, fixture)


class CatalogBenchmarkProvider(FakeBenchmarkProvider):
    def __init__(self, model_id, text):
        super().__init__()
        self.config = ProviderConfigSnapshot(provider_id="fake", model_id=model_id)
        self.text = text

    async def transcribe(self, audio, cancellation):
        await asyncio.sleep(0)
        if cancellation.is_cancelled:
            raise ASRCancellationError()
        return TranscriptResult(
            text=self.text,
            language="en",
            segments=(Segment(start_ms=0, end_ms=10, text=self.text),),
            provider_id="fake",
            model_id=self.config.model_id,
            audio_sha256=audio.audio_sha256,
        )


def test_catalog_mode_iterates_installed_models_and_persists_redacted_rows(tmp_path):
    async def scenario():
        from voxflow.providers.catalog import load_results
        from tools_asr_benchmark_import import run_catalog_benchmark

        providers = {
            "medium.en": CatalogBenchmarkProvider("medium.en", "hello world"),
            "small.en": CatalogBenchmarkProvider("small.en", "hello world"),
            "distil-large-v3": CatalogBenchmarkProvider("distil-large-v3", "different words"),
        }
        fake = FakeCatalogForBenchmark(providers, providers)
        payload = await run_catalog_benchmark(
            FIXTURE,
            tmp_path / "models",
            runs=1,
            reference_text="Hello, world!",
            catalog_module=fake,
        )
        return payload, load_results(tmp_path / "models")

    # Importing the CLI as a file keeps this test independent of packaging the tools directory.
    module = benchmark_tool()
    import sys

    sys.modules["tools_asr_benchmark_import"] = module
    payload, persisted = asyncio.run(scenario())
    assert payload["status"] == "ok"
    assert payload["default"] == "small.en"
    assert payload["fixture_requirement"] == "approximately 6 seconds"
    assert set(persisted) == {"medium.en", "small.en", "distil-large-v3"}
    assert set(persisted["small.en"]) == {"p50_ms", "p95_ms", "wer", "fixture", "ts"}
    assert persisted["small.en"]["wer"] == 0.0
    assert "hello world" not in json.dumps(payload).lower()


def test_catalog_without_reference_requires_explicit_opt_in():
    module = benchmark_tool()
    with pytest.raises(SystemExit) as raised:
        module.main(["--catalog", "--fixture", str(FIXTURE)])
    assert raised.value.code == 2
