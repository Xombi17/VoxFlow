"""Lazy ``sherpa-onnx`` Parakeet-TDT provider behind the ASRProvider contract."""

from __future__ import annotations

import asyncio
import importlib
import threading
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from .asr import (
    ASRCancellationError,
    ASRProviderError,
    AudioInput,
    CancellationToken,
    ProviderCapabilities,
    ProviderConfigSnapshot,
    Segment,
    TranscriptResult,
)

TARGET_RATE = 16_000
_ROLES = ("encoder", "decoder", "joiner", "tokens")


def _load_sherpa_module() -> Any:
    try:
        return importlib.import_module("sherpa_onnx")
    except ImportError as exc:
        raise ASRProviderError(
            "backend_unavailable", "sherpa-onnx is not installed in the project environment."
        ) from exc


def _read_wav_mono16k(path: Path) -> np.ndarray:
    """Read PCM WAV as float32 mono at 16 kHz (linear resample if needed)."""

    with wave.open(str(path), "rb") as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        raw = wav.readframes(wav.getnframes())
    if width == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ASRProviderError("unsupported_audio", "Only 16-bit or 32-bit PCM WAV is supported.")
    if channels > 1:
        samples = samples[: len(samples) // channels * channels].reshape(-1, channels).mean(axis=1)
    if rate != TARGET_RATE and len(samples):
        n_out = max(1, round(len(samples) * TARGET_RATE / rate))
        samples = np.interp(
            np.linspace(0, len(samples) - 1, n_out), np.arange(len(samples)), samples
        ).astype(np.float32)
    return np.ascontiguousarray(samples, dtype=np.float32)


class SherpaParakeetProvider:
    provider_id = "sherpa-parakeet"

    def __init__(
        self,
        entry: Any,
        model_dir: str | Path,
        *,
        config: ProviderConfigSnapshot | None = None,
        module_loader: Callable[[], Any] | None = None,
    ) -> None:
        self.entry = entry
        self.model_dir = Path(model_dir)
        self.model_id = entry.id
        self.config = config or ProviderConfigSnapshot(
            provider_id=self.provider_id, model_id=self.model_id
        )
        if self.config.provider_id != self.provider_id:
            raise ValueError("SherpaParakeetProvider requires the sherpa-parakeet provider ID")
        self._module_loader = module_loader or _load_sherpa_module
        self._recognizer: Any | None = None
        self._lock = threading.Lock()
        self._model_load_count = 0

    @property
    def model_load_count(self) -> int:
        return self._model_load_count

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            model_id=self.model_id,
            offline=True,
            network_required=False,
            supports_cancellation=True,
            supported_languages=("auto", *self.entry.languages),
            supported_devices=("cpu",),
        )

    async def prepare(self) -> None:
        await asyncio.to_thread(self._load)

    async def transcribe(self, audio: AudioInput, cancellation: CancellationToken) -> TranscriptResult:
        if audio.config.network_policy.value != "local_only":
            raise ASRProviderError(
                "network_policy_rejected", "The local provider requires local-only network policy."
            )
        cancellation.raise_if_cancelled()
        if not audio.path.is_file():
            raise ASRProviderError("audio_missing", "The local audio artifact is unavailable.")
        try:
            return await asyncio.to_thread(self._transcribe_sync, audio, cancellation)
        except ASRProviderError:
            raise
        except Exception as exc:
            raise ASRProviderError(
                "inference_failed", "The Parakeet model could not transcribe the artifact."
            ) from exc

    def _paths(self) -> dict[str, str]:
        found: dict[str, str] = {}
        for f in self.entry.files:
            for role in _ROLES:
                if role in Path(f.path).name:
                    found[role] = str(self.model_dir / f.path)
        if set(found) != set(_ROLES) or not all(Path(p).is_file() for p in found.values()):
            raise ASRProviderError("model_incomplete", "The Parakeet model files are not installed.")
        return found

    def _load(self) -> Any:
        with self._lock:
            if self._recognizer is not None:
                return self._recognizer
            paths = self._paths()
            module = self._module_loader()
            try:
                self._recognizer = module.OfflineRecognizer.from_transducer(
                    encoder=paths["encoder"],
                    decoder=paths["decoder"],
                    joiner=paths["joiner"],
                    tokens=paths["tokens"],
                    num_threads=self.config.thread_count,
                    sample_rate=TARGET_RATE,
                    feature_dim=128,
                    decoding_method="greedy_search",
                    model_type="nemo_transducer",
                )
            except Exception as exc:
                raise ASRProviderError(
                    "model_load_failed", "The selected local model could not be loaded."
                ) from exc
            self._model_load_count += 1
            return self._recognizer

    def _transcribe_sync(self, audio: AudioInput, cancellation: CancellationToken) -> TranscriptResult:
        cancellation.raise_if_cancelled()
        recognizer = self._load()
        samples = _read_wav_mono16k(audio.path)
        cancellation.raise_if_cancelled()
        stream = recognizer.create_stream()
        stream.accept_waveform(TARGET_RATE, samples)
        recognizer.decode_stream(stream)
        result = stream.result
        text = str(getattr(result, "text", "")).strip()
        language = str(getattr(result, "lang", "") or "") or audio.config.language_hint
        segments = (Segment(start_ms=0, end_ms=audio.duration_ms, text=text),) if text else ()
        return TranscriptResult(
            text=text,
            language=language,
            segments=segments,
            provider_id=self.provider_id,
            model_id=self.model_id,
            audio_sha256=audio.audio_sha256,
        )


__all__ = ["SherpaParakeetProvider", "ASRCancellationError"]
