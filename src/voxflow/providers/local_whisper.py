"""Explicitly installed, lazy ``faster-whisper`` provider adapter."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .asr import (
    ASRProviderError,
    ASRCancellationError,
    ASRProvider,
    AudioInput,
    CancellationToken,
    ProviderCapabilities,
    ProviderConfigSnapshot,
    Segment,
    TranscriptResult,
)


REQUIRED_MODEL_FILES = ("config.json", "model.bin")


@dataclass(frozen=True, slots=True)
class LocalModelProfile:
    """Location-independent metadata for one explicitly installed model."""

    model_id: str
    root: Path = field(repr=False)
    backend: str = "faster-whisper"
    checksum: str | None = None
    supported_languages: tuple[str, ...] = ("auto", "en")
    supported_devices: tuple[str, ...] = ("cpu",)
    compute_type: str = "int8"
    quantization: str = "int8"
    available: bool = True
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        object.__setattr__(self, "supported_languages", tuple(self.supported_languages))
        object.__setattr__(self, "supported_devices", tuple(self.supported_devices))
        if not self.model_id.strip():
            raise ValueError("model_id must not be blank")
        if "/" in self.model_id or "\\" in self.model_id:
            raise ValueError("model_id must be a portable profile ID")
        if not self.backend.strip():
            raise ValueError("backend must not be blank")
        if self.available and not self.checksum:
            raise ValueError("available model profiles require a checksum")

    def to_dict(self) -> dict[str, object]:
        """Serialize only portable metadata; never serialize ``root``."""

        return {
            "model_id": self.model_id,
            "backend": self.backend,
            "checksum": self.checksum,
            "supported_languages": list(self.supported_languages),
            "supported_devices": list(self.supported_devices),
            "compute_type": self.compute_type,
            "quantization": self.quantization,
            "available": self.available,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class LocalModelDiscovery:
    """Read-only discovery result, including typed unavailable profiles."""

    profile: LocalModelProfile
    available: bool
    error_code: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile.to_dict(),
            "available": self.available,
            "error_code": self.error_code,
            "reason": self.reason,
        }


def discover_local_model(
    model_root: str | Path,
    *,
    model_id: str,
    supported_languages: Iterable[str] = ("auto", "en"),
    supported_devices: Iterable[str] = ("cpu",),
    compute_type: str = "int8",
    quantization: str = "int8",
    expected_checksum: str | None = None,
) -> LocalModelDiscovery:
    """Inspect an installed CTranslate2 directory without creating or fetching files."""

    root = Path(model_root)
    languages = tuple(supported_languages)
    devices = tuple(supported_devices)
    unavailable_code: str | None = None
    reason: str | None = None

    if not root.is_dir():
        unavailable_code = "model_missing"
        reason = "The selected local model profile is not installed."
    elif any(not (root / filename).is_file() for filename in REQUIRED_MODEL_FILES):
        unavailable_code = "model_incomplete"
        reason = "The selected local model profile is incomplete."

    checksum: str | None = None
    if unavailable_code is None:
        try:
            checksum = _model_checksum(root)
        except OSError:
            unavailable_code = "model_unreadable"
            reason = "The selected local model profile could not be read."
        if (
            unavailable_code is None
            and expected_checksum is not None
            and checksum != expected_checksum
        ):
            unavailable_code = "model_checksum_mismatch"
            reason = "The selected local model profile checksum changed."

    available = unavailable_code is None
    profile = LocalModelProfile(
        model_id=model_id,
        root=root,
        checksum=checksum,
        supported_languages=languages,
        supported_devices=devices,
        compute_type=compute_type,
        quantization=quantization,
        available=available,
        error_code=unavailable_code,
    )
    return LocalModelDiscovery(
        profile=profile,
        available=available,
        error_code=unavailable_code,
        reason=reason,
    )


def discover_installed_models(
    model_root: str | Path,
    **profile_options: object,
) -> tuple[LocalModelDiscovery, ...]:
    """Discover child profiles below an explicit root without mutating it."""

    root = Path(model_root)
    if not root.is_dir():
        return ()
    results: list[LocalModelDiscovery] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if child.is_dir() and not child.is_symlink():
            results.append(
                discover_local_model(child, model_id=child.name, **profile_options)
            )
    return tuple(results)


# Explicit aliases keep the discovery vocabulary readable at call sites.
discover_local_model_profile = discover_local_model
discover_installed_profiles = discover_installed_models


def _model_checksum(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


class LocalWhisperProvider(ASRProvider):
    """Lazy local provider with one cached model per provider instance."""

    provider_id = "local-whisper"

    def __init__(
        self,
        profile: LocalModelProfile,
        *,
        config: ProviderConfigSnapshot | None = None,
        module_loader: Callable[[], Any] | None = None,
    ) -> None:
        self.profile = profile
        self.config = config or ProviderConfigSnapshot(
            provider_id=self.provider_id,
            model_id=profile.model_id,
            device=profile.supported_devices[0] if profile.supported_devices else "cpu",
        )
        if self.config.provider_id != self.provider_id:
            raise ValueError("LocalWhisperProvider requires the local-whisper provider ID")
        if self.config.model_id != profile.model_id:
            raise ValueError("provider config model_id must match the selected profile")
        self._module_loader = module_loader or _load_faster_whisper_module
        self._model: Any | None = None
        self._model_load_count = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            model_id=self.profile.model_id,
            offline=True,
            network_required=False,
            supports_cancellation=True,
            supported_languages=self.profile.supported_languages,
            supported_devices=self.profile.supported_devices,
        )

    @property
    def model_load_count(self) -> int:
        return self._model_load_count

    async def prepare(self) -> None:
        """Load the selected installed profile once for benchmark cold-start timing."""

        await asyncio.to_thread(self._load_model)

    async def transcribe(
        self,
        audio: AudioInput,
        cancellation: CancellationToken,
    ) -> TranscriptResult:
        if not self.profile.available:
            raise ASRProviderError(
                self.profile.error_code or "model_unavailable",
                "The selected local model profile is unavailable.",
            )
        if audio.config.network_policy.value != "local_only":
            raise ASRProviderError(
                "network_policy_rejected",
                "The local provider requires local-only network policy.",
            )
        cancellation.raise_if_cancelled()
        if not audio.path.is_file():
            raise ASRProviderError("audio_missing", "The local audio artifact is unavailable.")
        try:
            await asyncio.to_thread(self._load_model)
            return await asyncio.to_thread(self._transcribe_sync, audio, cancellation)
        except ASRCancellationError:
            raise
        except ASRProviderError:
            raise
        except Exception as exc:
            raise ASRProviderError(
                "inference_failed",
                "The local Whisper model could not transcribe the artifact.",
            ) from exc

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if not self.profile.available:
            raise ASRProviderError(
                self.profile.error_code or "model_unavailable",
                "The selected local model profile is unavailable.",
            )
        module = self._module_loader()
        model_class = getattr(module, "WhisperModel", None)
        if model_class is None:
            raise ASRProviderError("backend_unavailable", "The local Whisper backend is unavailable.")
        try:
            self._model = model_class(
                str(self.profile.root),
                device=self.config.device,
                compute_type=self.profile.compute_type,
                cpu_threads=self.config.thread_count,
                num_workers=1,
                local_files_only=True,
            )
        except Exception as exc:
            raise ASRProviderError(
                "model_load_failed",
                "The selected local model could not be loaded.",
            ) from exc
        self._model_load_count += 1
        return self._model

    def _transcribe_sync(
        self,
        audio: AudioInput,
        cancellation: CancellationToken,
    ) -> TranscriptResult:
        model = self._model
        if model is None:
            raise ASRProviderError("model_unavailable", "The local Whisper model is not loaded.")
        cancellation.raise_if_cancelled()
        kwargs: dict[str, object] = {
            "beam_size": audio.config.beam_size,
            "vad_filter": audio.config.vad_filter,
            "condition_on_previous_text": False,
            "without_timestamps": False,
        }
        if audio.config.language_hint is not None:
            kwargs["language"] = audio.config.language_hint
        if audio.config.vad_min_silence_duration_ms is not None:
            kwargs["vad_parameters"] = {
                "min_silence_duration_ms": audio.config.vad_min_silence_duration_ms
            }
        segments, info = model.transcribe(str(audio.path), **kwargs)
        mapped_segments: list[Segment] = []
        previous_end = 0
        text_parts: list[str] = []
        for raw_segment in segments:
            cancellation.raise_if_cancelled()
            start_ms, end_ms, text = _raw_segment_values(raw_segment)
            if start_ms >= audio.duration_ms:
                continue
            start_ms = max(previous_end, start_ms)
            end_ms = min(audio.duration_ms, end_ms)
            if end_ms <= start_ms:
                raise ASRProviderError(
                    "invalid_segment",
                    "The local Whisper backend returned invalid timestamps.",
                )
            if not text.strip():
                continue
            segment = Segment(start_ms=start_ms, end_ms=end_ms, text=text)
            mapped_segments.append(segment)
            previous_end = end_ms
            text_parts.append(text)

        language = _read_info_value(info, "language")
        language_probability = _read_info_value(info, "language_probability")
        confidence = _optional_probability(language_probability)
        return TranscriptResult(
            text="".join(text_parts).strip(),
            language=str(language) if language else audio.config.language_hint,
            language_probability=confidence,
            confidence=confidence,
            segments=tuple(mapped_segments),
            provider_id=self.provider_id,
            model_id=self.profile.model_id,
            audio_sha256=audio.audio_sha256,
        )


def _load_faster_whisper_module() -> Any:
    """Import the optional backend only when a selected job actually runs."""

    try:
        return importlib.import_module("faster_whisper")
    except ImportError as exc:
        raise ASRProviderError(
            "backend_unavailable",
            "faster-whisper is not installed in the project environment.",
        ) from exc


def _raw_segment_values(segment: Any) -> tuple[int, int, str]:
    start = _read_segment_value(segment, "start")
    end = _read_segment_value(segment, "end")
    text = _read_segment_value(segment, "text")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        raise ASRProviderError("invalid_segment", "The local Whisper backend returned invalid timestamps.")
    if not isinstance(text, str):
        raise ASRProviderError("invalid_segment", "The local Whisper backend returned invalid text metadata.")
    if not math.isfinite(float(start)) or not math.isfinite(float(end)):
        raise ASRProviderError("invalid_segment", "The local Whisper backend returned invalid timestamps.")
    if start < 0 or end <= start:
        raise ASRProviderError("invalid_segment", "The local Whisper backend returned invalid timestamps.")
    start_ms = max(0, int(round(float(start) * 1000)))
    end_ms = max(start_ms + 1, int(round(float(end) * 1000)))
    return start_ms, end_ms, text


def _read_segment_value(segment: Any, name: str) -> Any:
    if isinstance(segment, Mapping):
        return segment.get(name)
    return getattr(segment, name, None)


def _read_info_value(info: Any, name: str) -> Any:
    if isinstance(info, Mapping):
        return info.get(name)
    return getattr(info, name, None)


def _optional_probability(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not 0 <= number <= 1:
        return None
    return number
