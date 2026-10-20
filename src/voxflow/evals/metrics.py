"""Allowlisted local ASR performance records.

These records intentionally contain no transcript, audio payload, credentials,
or machine-specific paths.  They are diagnostics for selecting a model profile,
not telemetry.
"""

from __future__ import annotations

import asyncio
import math
import resource
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..audio.artifacts import AudioArtifact
from ..core.jobs import DictationJobRunner
from ..providers.asr import ASRProvider, ASRProviderError, AudioInput, CancellationToken


@dataclass(frozen=True, slots=True)
class BenchmarkRecord:
    """One local benchmark run with an explicit allowlist of fields."""

    job_id: str
    provider_id: str
    model_id: str
    format_summary: dict[str, int]
    cold_start_ms: float | None
    warm_inference_ms: float | None
    end_to_end_ms: float | None
    warm_p50_ms: float | None
    warm_p95_ms: float | None
    cancellation_latency_ms: float | None
    realtime_factor: float | None
    peak_resource_mb: float | None
    status: str
    error_code: str | None = None
    warm_samples_ms: tuple[float, ...] = field(default_factory=tuple, repr=False)

    def __post_init__(self) -> None:
        if not self.job_id.strip() or not self.provider_id.strip() or not self.model_id.strip():
            raise ValueError("benchmark identity fields must not be blank")
        if self.status not in {"success", "cancelled", "failed"}:
            raise ValueError("benchmark status is not supported")
        if set(self.format_summary) != {"sample_rate", "channels"}:
            raise ValueError("format_summary must contain only negotiated format fields")
        for value in (
            self.cold_start_ms,
            self.warm_inference_ms,
            self.end_to_end_ms,
            self.warm_p50_ms,
            self.warm_p95_ms,
            self.cancellation_latency_ms,
            self.realtime_factor,
            self.peak_resource_mb,
            *self.warm_samples_ms,
        ):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("benchmark metrics must be finite and non-negative")

    def to_dict(self) -> dict[str, object]:
        """Serialize exactly the local diagnostic schema."""

        return {
            "job_id": self.job_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "format": dict(self.format_summary),
            "timings_ms": {
                "cold_start": self.cold_start_ms,
                "warm_inference": self.warm_inference_ms,
                "end_to_end": self.end_to_end_ms,
                "cancellation": self.cancellation_latency_ms,
            },
            "warm_distribution_ms": {
                "p50": self.warm_p50_ms,
                "p95": self.warm_p95_ms,
            },
            "realtime_factor": self.realtime_factor,
            "peak_resource_mb": self.peak_resource_mb,
            "status": self.status,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """A local benchmark report containing per-job allowlisted records."""

    records: tuple[BenchmarkRecord, ...]
    warm_p50_ms: float | None
    warm_p95_ms: float | None
    cold_start_ms: tuple[float, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "records": [record.to_dict() for record in self.records],
            "distributions_ms": {
                "warm_inference": {
                    "p50": self.warm_p50_ms,
                    "p95": self.warm_p95_ms,
                },
                "cold_start": list(self.cold_start_ms),
            },
        }


async def run_benchmark(
    provider: ASRProvider,
    artifact: AudioArtifact,
    *,
    runs: int = 3,
    job_id: str = "benchmark-job",
) -> BenchmarkReport:
    """Measure cold load, warm inference, end-to-end, cancel, and resources."""

    if runs < 1:
        raise ValueError("runs must be positive")
    audio = AudioInput.from_artifact(
        artifact,
        getattr(provider, "config", None)
        or _config_from_capabilities(provider),
    )
    cold_start_ms: float | None = None
    prepare = getattr(provider, "prepare", None)
    if callable(prepare):
        started = time.perf_counter()
        await prepare()
        cold_start_ms = _elapsed_ms(started)

    warm_samples: list[float] = []
    end_to_end_samples: list[float] = []
    status = "success"
    error_code: str | None = None
    for _ in range(runs):
        token = CancellationToken()
        started = time.perf_counter()
        try:
            await provider.transcribe(audio, token)
        except ASRProviderError as exc:
            status = "failed"
            error_code = exc.code
            break
        warm_samples.append(_elapsed_ms(started))

        e2e_started = time.perf_counter()
        runner = DictationJobRunner(provider, artifact, config=audio.config)
        snapshot = await runner.run()
        end_to_end_samples.append(_elapsed_ms(e2e_started))
        if snapshot.state.value != "success":
            status = "cancelled" if snapshot.state.value == "cancelled" else "failed"
            error_code = snapshot.error_code
            break

    cancellation_latency = await _measure_cancellation(provider, audio)
    peak_resource_mb = _peak_resource_mb()
    warm_p50 = _percentile(warm_samples, 0.50)
    warm_p95 = _percentile(warm_samples, 0.95)
    representative = warm_p50
    realtime_factor = (
        (representative / 1000) / (artifact.duration_ms / 1000)
        if representative is not None and artifact.duration_ms > 0
        else None
    )
    record = BenchmarkRecord(
        job_id=job_id,
        provider_id=audio.config.provider_id,
        model_id=audio.config.model_id,
        format_summary=artifact.source_format.to_dict(),
        cold_start_ms=cold_start_ms,
        warm_inference_ms=representative,
        end_to_end_ms=_percentile(end_to_end_samples, 0.50),
        warm_p50_ms=warm_p50,
        warm_p95_ms=warm_p95,
        cancellation_latency_ms=cancellation_latency,
        realtime_factor=realtime_factor,
        peak_resource_mb=peak_resource_mb,
        status=status,
        error_code=error_code,
        warm_samples_ms=tuple(warm_samples),
    )
    return BenchmarkReport(
        records=(record,),
        warm_p50_ms=warm_p50,
        warm_p95_ms=warm_p95,
        cold_start_ms=(cold_start_ms,) if cold_start_ms is not None else (),
    )


async def _measure_cancellation(provider: ASRProvider, audio: AudioInput) -> float | None:
    token = CancellationToken()
    task = asyncio.create_task(provider.transcribe(audio, token))
    await asyncio.sleep(0)
    started = time.perf_counter()
    token.cancel()
    try:
        await task
    except Exception:
        pass
    return _elapsed_ms(started)


def _config_from_capabilities(provider: ASRProvider) -> Any:
    from ..providers.asr import ProviderConfigSnapshot

    capabilities = provider.capabilities
    return ProviderConfigSnapshot(
        provider_id=capabilities.provider_id,
        model_id=capabilities.model_id,
    )


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.perf_counter() - started) * 1000)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _peak_resource_mb() -> float | None:
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except (AttributeError, OSError):
        return None
    # Linux reports KiB; keep the field portable and explicitly approximate.
    return round(float(usage.ru_maxrss) / 1024, 3)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Return word-level Levenshtein error as a percentage.

    Punctuation is treated as a separator and comparison is case-insensitive.
    The reference is the denominator by definition; an empty reference is not
    a meaningful accuracy measurement.
    """

    reference_words = _normalized_words(reference)
    hypothesis_words = _normalized_words(hypothesis)
    if not reference_words:
        raise ValueError("reference text must contain at least one word")
    previous = list(range(len(hypothesis_words) + 1))
    for reference_word in reference_words:
        current = [previous[0] + 1]
        for index, hypothesis_word in enumerate(hypothesis_words, start=1):
            substitution = previous[index - 1] + (reference_word != hypothesis_word)
            insertion = current[index - 1] + 1
            deletion = previous[index] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return (previous[-1] / len(reference_words)) * 100.0


def select_default(
    results: Mapping[str, Mapping[str, object]],
    *,
    target_ms: float = 700,
    reference_model_id: str = "medium.en",
) -> dict[str, object]:
    """Choose the fastest accurate non-reference candidate from result rows."""

    if target_ms <= 0:
        raise ValueError("target_ms must be positive")

    def number(row: Mapping[str, object], key: str) -> float | None:
        value = row.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if math.isfinite(float(value)) else None

    candidates = {
        model_id: row
        for model_id, row in results.items()
        if isinstance(model_id, str) and isinstance(row, Mapping)
    }
    non_reference = {
        model_id: row for model_id, row in candidates.items() if model_id != reference_model_id
    }
    non_reference_with_wer = {
        model_id: row
        for model_id, row in non_reference.items()
        if number(row, "wer") is not None
    }
    fastest_non_reference = min(
        (
            (number(row, "p50_ms"), model_id)
            for model_id, row in non_reference.items()
            if number(row, "p50_ms") is not None
        ),
        default=(None, None),
    )[1]
    measured_wers = [
        number(row, "wer")
        for row in candidates.values()
        if number(row, "wer") is not None
    ]
    best_wer = min(measured_wers) if measured_wers else None

    if not non_reference_with_wer:
        return {
            "status": "unvalidated_accuracy",
            "default": None,
            "fastest": fastest_non_reference,
            "best_wer": best_wer,
            "message": (
                "Accuracy is unvalidated; confirm the flagged fastest model with "
                "`voxflow models use <id>` or rerun with a reference sentence."
            ),
        }

    assert best_wer is not None
    eligible = {
        model_id: row
        for model_id, row in non_reference_with_wer.items()
        if number(row, "wer") is not None
        and number(row, "wer") <= best_wer + 2.0
        and number(row, "p50_ms") is not None
    }
    fastest_eligible = min(
        (
            (number(row, "p50_ms"), model_id)
            for model_id, row in eligible.items()
        ),
        default=(None, None),
    )[1]
    if fastest_eligible is None:
        return {
            "status": "no_default_under_target",
            "default": None,
            "fastest": None,
            "best_wer": best_wer,
            "message": "No candidate passed the measured accuracy rule.",
        }

    under_target = {
        model_id: row
        for model_id, row in eligible.items()
        if number(row, "p50_ms") is not None and number(row, "p50_ms") < target_ms
    }
    selected = min(
        (
            (number(row, "p50_ms"), model_id)
            for model_id, row in under_target.items()
        ),
        default=(None, None),
    )[1]
    if selected is not None:
        return {
            "status": "ok",
            "default": selected,
            "fastest": None,
            "best_wer": best_wer,
            "message": "Selected the fastest non-reference candidate within the WER threshold.",
        }
    return {
        "status": "no_default_under_target",
        "default": fastest_eligible,
        "fastest": None,
        "best_wer": best_wer,
        "message": (
            f"The fastest accurate candidate misses the {target_ms:g} ms target; "
            "the target is flagged for the user."
        ),
    }


def _normalized_words(value: str) -> list[str]:
    if not isinstance(value, str):
        raise TypeError("transcript values must be strings")
    chars = [" " if unicodedata.category(char).startswith("P") else char.lower() for char in value]
    return "".join(chars).split()
