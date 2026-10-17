"""Provider contracts and explicitly selected ASR adapters."""

from .asr import (
    ASRContractError,
    ASRProvider,
    ASRProviderError,
    ASRValidationError,
    AudioInput,
    CancellationToken,
    ProviderCapabilities,
    ProviderConfigSnapshot,
    Segment,
    TranscriptResult,
)

__all__ = [
    "ASRContractError",
    "ASRProvider",
    "ASRProviderError",
    "ASRValidationError",
    "AudioInput",
    "CancellationToken",
    "ProviderCapabilities",
    "ProviderConfigSnapshot",
    "Segment",
    "TranscriptResult",
]
