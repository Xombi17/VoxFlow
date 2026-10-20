"""Provider-independent dictation job lifecycle and recoverable snapshots."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from enum import StrEnum
from uuid import uuid4

from ..audio.artifacts import AudioArtifact
from ..core.state import SessionState
from ..providers.asr import (
    ASRProvider,
    ASRProviderError,
    ASRValidationError,
    AudioInput,
    CancellationToken,
    NetworkPolicy,
    ProviderKind,
    ProviderConfigSnapshot,
    TranscriptResult,
    validate_provider_result,
)


class JobErrorCode(StrEnum):
    """Stable failure codes that can be retried without raw exceptions."""

    CANCELLED = "cancelled"
    PROVIDER_FAILED = "provider_failed"
    INVALID_RESULT = "invalid_result"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    NETWORK_POLICY_REJECTED = "network_policy_rejected"
    JOB_FAILED = "job_failed"


@dataclass(frozen=True, slots=True)
class DictationJobSnapshot:
    """Immutable in-memory job state with a safe serialization boundary."""

    job_id: str
    state: SessionState
    artifact: AudioArtifact
    config: ProviderConfigSnapshot
    retry_count: int = 0
    retryable: bool = False
    retry_code: str | None = None
    error_code: str | None = None
    result: TranscriptResult | None = None
    failure_reason: str | None = None
    transition_history: tuple[SessionState, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", SessionState(self.state))
        object.__setattr__(
            self,
            "transition_history",
            tuple(SessionState(state) for state in self.transition_history),
        )
        if not self.job_id.strip():
            raise ValueError("job_id must not be blank")
        if self.retry_count < 0:
            raise ValueError("retry_count must not be negative")
        if self.retryable and not self.retry_code:
            raise ValueError("retryable jobs must include retry_code")
        if self.state is SessionState.SUCCESS and self.result is None:
            raise ValueError("successful jobs must include a validated result")
        if self.state is SessionState.FAILED and not self.error_code:
            raise ValueError("failed jobs must include error_code")

    @property
    def artifact_reference(self) -> AudioArtifact:
        return self.artifact

    def to_dict(self) -> dict[str, object]:
        """Serialize diagnostics without path, audio, or transcript content."""

        return {
            "job_id": self.job_id,
            "state": self.state.value,
            "artifact": self.artifact.to_dict(),
            "provider_id": self.config.provider_id,
            "model_id": self.config.model_id,
            "config": self.config.to_dict(),
            "retry_count": self.retry_count,
            "retryable": self.retryable,
            "retry_code": self.retry_code,
            "error_code": self.error_code,
            "failure_reason": self.failure_reason,
            "result": self.result.to_safe_dict() if self.result else None,
            "transition_history": [state.value for state in self.transition_history],
        }


class DictationJobRunner:
    """Run one bounded artifact through any async ``ASRProvider``."""

    def __init__(
        self,
        provider: ASRProvider,
        artifact: AudioArtifact,
        *,
        config: ProviderConfigSnapshot | None = None,
        job_id: str | None = None,
        retry_count: int = 0,
    ) -> None:
        self.provider = provider
        self.artifact = artifact
        self.config = _freeze_config(config or self._config_from_provider(provider))
        self.job_id = job_id or uuid4().hex
        self._token = CancellationToken()
        self._run_task: asyncio.Task[DictationJobSnapshot] | None = None
        self._snapshot = DictationJobSnapshot(
            job_id=self.job_id,
            state=SessionState.PROCESSING,
            artifact=artifact,
            config=self.config,
            retry_count=retry_count,
            transition_history=(SessionState.PROCESSING,),
        )

    @property
    def snapshot(self) -> DictationJobSnapshot:
        return self._snapshot

    @property
    def cancellation(self) -> CancellationToken:
        return self._token

    def request_cancel(self) -> None:
        """Request cancellation without waiting on the owning processing task.

        The daemon owns the task that awaits ``run``.  A shutdown path must
        cancel that outer task directly rather than calling ``cancel`` and
        making it wait on itself.
        """

        self._token.cancel()
        if self._run_task is None or self._run_task is asyncio.current_task():
            self._finish_cancelled()

    async def run(self) -> DictationJobSnapshot:
        """Dispatch, validate, and finish one job exactly once."""

        if self._run_task is not None and self._run_task is not asyncio.current_task():
            return await asyncio.shield(self._run_task)
        if self._run_task is None:
            self._run_task = asyncio.current_task()
        if _is_terminal(self._snapshot.state):
            return self._snapshot

        try:
            self._token.raise_if_cancelled()
            if (
                self.config.provider_kind is ProviderKind.REMOTE
                and self.config.network_policy is not NetworkPolicy.REMOTE_EXPLICIT
            ):
                raise ASRProviderError(
                    JobErrorCode.NETWORK_POLICY_REJECTED.value,
                    "Remote ASR requires explicit remote_explicit network policy.",
                )
            audio = AudioInput.from_artifact(self.artifact, self.config)
            raw_result = await self.provider.transcribe(audio, self._token)
            self._token.raise_if_cancelled()
            result = validate_provider_result(raw_result, self.artifact.audio_sha256)
        except asyncio.CancelledError:
            self._finish_cancelled()
        except ASRValidationError as exc:
            code = (
                JobErrorCode.CHECKSUM_MISMATCH.value
                if "match" in str(exc).lower()
                else JobErrorCode.INVALID_RESULT.value
            )
            self._finish_failed(code, retryable=True, retry_code="retry_transcription")
        except ASRProviderError as exc:
            if exc.code == JobErrorCode.CANCELLED.value or self._token.is_cancelled:
                self._finish_cancelled()
            else:
                self._finish_failed(
                    exc.code or JobErrorCode.PROVIDER_FAILED.value,
                    retryable=True,
                    retry_code="retry_transcription",
                    failure_reason=(
                        "Remote ASR requires explicit remote_explicit network policy."
                        if exc.code == JobErrorCode.NETWORK_POLICY_REJECTED.value
                        else None
                    ),
                )
        except Exception:
            self._finish_failed(
                JobErrorCode.JOB_FAILED.value,
                retryable=True,
                retry_code="retry_transcription",
            )
        else:
            self._snapshot = replace(
                self._snapshot,
                state=SessionState.SUCCESS,
                result=result,
                transition_history=self._snapshot.transition_history + (SessionState.SUCCESS,),
            )
        return self._snapshot

    async def cancel(self) -> DictationJobSnapshot:
        """Request cooperative cancellation and await the provider boundary."""

        self.request_cancel()
        if self._run_task is None:
            self._finish_cancelled()
            return self._snapshot
        if self._run_task is asyncio.current_task():
            self._finish_cancelled()
            return self._snapshot
        try:
            return await asyncio.shield(self._run_task)
        except asyncio.CancelledError:
            self._finish_cancelled()
            return self._snapshot

    def _finish_cancelled(self) -> None:
        if _is_terminal(self._snapshot.state):
            return
        self._snapshot = replace(
            self._snapshot,
            state=SessionState.CANCELLED,
            retryable=True,
            retry_code="retry_transcription",
            error_code=JobErrorCode.CANCELLED.value,
            failure_reason="ASR transcription was cancelled.",
            transition_history=self._snapshot.transition_history + (SessionState.CANCELLED,),
        )

    def _finish_failed(
        self,
        code: str,
        *,
        retryable: bool,
        retry_code: str,
        failure_reason: str | None = None,
    ) -> None:
        if _is_terminal(self._snapshot.state):
            return
        self._snapshot = replace(
            self._snapshot,
            state=SessionState.FAILED,
            retryable=retryable,
            retry_code=retry_code if retryable else None,
            error_code=code,
            failure_reason=(
                failure_reason
                or "ASR provider failed; the captured artifact is available for retry."
            ),
            transition_history=self._snapshot.transition_history + (SessionState.FAILED,),
        )

    @staticmethod
    def _config_from_provider(provider: ASRProvider) -> ProviderConfigSnapshot:
        provider_config = getattr(provider, "config", None)
        if isinstance(provider_config, ProviderConfigSnapshot):
            return provider_config
        capabilities = provider.capabilities
        return ProviderConfigSnapshot(
            provider_id=capabilities.provider_id,
            model_id=capabilities.model_id,
        )


def _freeze_config(config: ProviderConfigSnapshot) -> ProviderConfigSnapshot:
    """Copy validated settings so later caller changes cannot affect a job."""

    return ProviderConfigSnapshot.model_validate(config.model_dump()).model_copy(deep=True)


def _is_terminal(state: SessionState) -> bool:
    return state in {
        SessionState.SUCCESS,
        SessionState.CANCELLED,
        SessionState.FAILED,
    }
