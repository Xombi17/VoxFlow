"""The local hold-to-dictate daemon.

The daemon deliberately composes the existing seams instead of teaching the
portal, audio session, job runner, or inserter about one another.  It owns the
ordering rule: release first, close the microphone, then transcribe and paste.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import signal
import sys
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from .audio.session import AudioSession, AudioSessionConfig, AudioSessionOutcomeType
from .core.capabilities import CapabilityRecord, CapabilityStatus
from .core.history import (
    AudioRetentionState,
    HistoryRecord,
    HistoryStore,
    InsertionAttemptRecord,
    utc_now,
)
from .core.jobs import DictationJobRunner
from .platform.insert import (
    FALLBACK_HINT,
    Inserter,
    InsertOutcome,
    InsertResult,
    InsertSideEffect,
)
from .platform.portals import (
    GlobalShortcutsPortal,
    RemoteDesktopPortal,
    insertion_capability_for_error,
)
from .platform.sd_capture import SoundDeviceCapture
from .platform.shortcuts import (
    GlobalShortcutsAdapter,
    ShortcutEvent,
    ShortcutEventType,
)
from .providers import catalog
from .settings import data_dir, load_application_settings, load_writing_settings
from .text.contracts import RawTranscript, WritingResult, WritingSettings
from .text.pipeline import DeterministicWritingPipeline


class DaemonConfigurationError(RuntimeError):
    """A selected local model or desktop capability is not ready."""


class RecoveryError(RuntimeError):
    """A requested recovery operation is unavailable or needs confirmation."""


class RecoveryNotAllowedError(RecoveryError):
    """Raised when a retry could duplicate an already-emitted paste chord."""


class Notifier(Protocol):
    def notify(self, message: str) -> object: ...


class BestEffortNotifier:
    """Print safe status messages and attempt a desktop notification."""

    def notify(self, message: str) -> None:
        print(message, flush=True)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._notify_desktop(message))

    async def _notify_desktop(self, message: str) -> None:
        bus = None
        try:
            from dbus_next import Message  # type: ignore[import-not-found]
            from dbus_next.aio import MessageBus  # type: ignore[import-not-found]

            bus = await MessageBus().connect()
            await bus.call(
                Message(
                    destination="org.freedesktop.Notifications",
                    path="/org/freedesktop/Notifications",
                    interface="org.freedesktop.Notifications",
                    member="Notify",
                    signature="susssasa{sv}i",
                    body=["VoxFlow", 0, "", "VoxFlow", message, [], {}, 3000],
                )
            )
        except Exception:
            # Notifications are an optional hint; stdout remains the reliable path.
            pass
        finally:
            if bus is not None:
                try:
                    bus.disconnect()
                except Exception:
                    pass


CaptureFactory = Callable[[], Any]
ProviderFactory = Callable[[Any, Path], Any]
AudioSessionFactory = Callable[..., AudioSession]
WritingSettingsFactory = Callable[[], WritingSettings]


class RecoveryController:
    """Small API-first recovery seam for a future CLI or GTK surface."""

    def __init__(self, daemon: "DictationDaemon") -> None:
        self.daemon = daemon

    def list(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        return tuple(record.to_safe_dict() for record in self.daemon.history.list_jobs(limit=limit))

    def show(self, job_id: str) -> HistoryRecord:
        return self.daemon.history.show_job(job_id)

    async def retry(self, job_id: str, *, confirm_ambiguous: bool = False) -> InsertOutcome:
        return await self.daemon.retry_insertion(job_id, confirm_ambiguous=confirm_ambiguous)

    async def retry_transcription(self, job_id: str) -> HistoryRecord:
        return await self.daemon.retry_transcription(job_id)

    def save(self, job_id: str, path: str | Path) -> Path:
        record = self.show(job_id)
        if record.final_text is None:
            raise RecoveryError("job has no final text to save")
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(record.final_text, encoding="utf-8")
        return target


class DictationDaemon:
    """Wire a shortcut, one capture session, the selected provider, and insertion."""

    def __init__(
        self,
        shortcut_adapter: Any | None = None,
        *,
        capture_factory: CaptureFactory | None = None,
        provider_factory: ProviderFactory | None = None,
        catalog_module: Any = catalog,
        models_root: str | Path | None = None,
        db_path: str | Path | None = None,
        inserter: Any | None = None,
        remote_portal: Any | None = None,
        notifier: Notifier | None = None,
        artifact_dir: str | Path | None = None,
        audio_session_factory: AudioSessionFactory = AudioSession,
        audio_config: AudioSessionConfig | None = None,
        cleanup_provider: Any | None = None,
        writing_pipeline: Any | None = None,
        writing_settings_factory: WritingSettingsFactory | None = None,
    ) -> None:
        self.catalog = catalog_module
        self.models_root = Path(models_root) if models_root is not None else Path(
            self.catalog.default_models_root()
        )
        self.db_path = Path(db_path) if db_path is not None else None
        self.shortcut = shortcut_adapter or GlobalShortcutsAdapter(GlobalShortcutsPortal())
        self.application_settings = load_application_settings(db_path=self.db_path)
        self.capture_factory = capture_factory or (
            lambda: SoundDeviceCapture(device=self.application_settings.microphone_id)
        )
        self.provider_factory = provider_factory
        self.remote_portal = remote_portal
        self.inserter = inserter
        self.notifier = notifier or BestEffortNotifier()
        self.audio_session_factory = audio_session_factory
        self.audio_config = audio_config or AudioSessionConfig(
            retain_audio=self.application_settings.retain_audio,
            max_duration_ms=self.application_settings.max_duration_ms,
        )
        self.cleanup_provider = cleanup_provider
        self.writing_pipeline = writing_pipeline or DeterministicWritingPipeline(cleanup_provider)
        self.writing_settings_factory = (
            writing_settings_factory
            if writing_settings_factory is not None
            else lambda: load_writing_settings(db_path=self.db_path)
        )
        self.last_writing_result: WritingResult | None = None
        self.provider: Any | None = None
        self.history = HistoryStore(self.db_path)
        self.recovery = RecoveryController(self)
        self._recovery_lock = asyncio.Lock()
        self._active_job_id: str | None = None
        self._active_runner: DictationJobRunner | None = None
        self._remove_shortcut_listener: Callable[[], object] | None = None
        self._capture_session: AudioSession | None = None
        self._capture_task: asyncio.Task[Any] | None = None
        self._finish_task: asyncio.Task[Any] | None = None
        self._processing_task: asyncio.Task[Any] | None = None
        self._running = False
        self._closed = asyncio.Event()
        self._owns_remote_session = False
        self.insertion_capability = CapabilityRecord(
            id="insertion.portal",
            status=CapabilityStatus.UNAVAILABLE,
            reason="RemoteDesktop and Clipboard insertion is not ready.",
        )
        self.last_insert_outcome: InsertOutcome | None = None
        self.artifact_dir = Path(artifact_dir) if artifact_dir is not None else data_dir() / "captures"
        self.artifact_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def processing(self) -> bool:
        return self._processing_task is not None

    @property
    def active_job_id(self) -> str | None:
        return self._active_job_id

    @property
    def active_runner(self) -> DictationJobRunner | None:
        return self._active_runner

    def reload_provider(self) -> Any:
        """Build the currently selected installed catalogue entry, without I/O."""

        selected = self._selected_model_id()
        if not selected:
            raise DaemonConfigurationError(
                "run: voxflow models download <id> && voxflow models use <id>"
            )
        entry = self.catalog.get_entry(selected)
        if not self.catalog.is_installed(self.models_root, selected):
            raise DaemonConfigurationError(
                f"run: voxflow models download {selected} && voxflow models use {selected}"
            )
        builder = self.provider_factory or self.catalog.build_provider
        self.provider = builder(entry, self.models_root)
        return self.provider

    async def reload_provider_async(self) -> Any:
        """Reload the selected model and warm it before the next dictation."""

        provider = self.reload_provider()
        prepare = getattr(provider, "prepare", None)
        if callable(prepare):
            await prepare()
        return provider

    async def start(self) -> None:
        if self._running:
            return
        self._cleanup_orphans()
        await self.reload_provider_async()

        if self.inserter is None:
            self.remote_portal = self.remote_portal or RemoteDesktopPortal()
            try:
                await self.remote_portal.open_session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                capability = getattr(self.remote_portal, "capability", None)
                if not isinstance(capability, CapabilityRecord):
                    capability = insertion_capability_for_error(exc)
                self.insertion_capability = capability
                self._notify(
                    "insertion unavailable — text will be retained; "
                    "save or retry after desktop portal access is restored"
                )
                close_portal = getattr(self.remote_portal, "close", None)
                if callable(close_portal):
                    try:
                        result = close_portal()
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        pass
            else:
                self._owns_remote_session = True
                self.inserter = Inserter(
                    self.remote_portal,
                    owner_settle_ms=self.application_settings.owner_settle_ms,
                    release_settle_ms=self.application_settings.release_settle_ms,
                    transfer_timeout_ms=self.application_settings.transfer_timeout_ms,
                    chord=self.application_settings.paste_chord,
                )
                capability = getattr(self.inserter, "capability", None)
                if isinstance(capability, CapabilityRecord):
                    self.insertion_capability = capability
                else:
                    self.insertion_capability = CapabilityRecord(
                        id="insertion.portal",
                        status=CapabilityStatus.UNAVAILABLE,
                        reason="EIS keyboard and compositor keymap readiness is pending.",
                    )
        elif self.inserter is not None:
            capability = getattr(self.inserter, "capability", None)
            self.insertion_capability = (
                capability
                if isinstance(capability, CapabilityRecord)
                else CapabilityRecord(
                    id="insertion.portal",
                    status=CapabilityStatus.UNAVAILABLE,
                    reason="Insertion adapter readiness has not been verified.",
                )
            )

        self._remove_shortcut_listener = self.shortcut.add_listener(
            self._on_shortcut_event
        )
        setup = await self.shortcut.configure()
        if not setup.configured:
            if self._remove_shortcut_listener is not None:
                self._remove_shortcut_listener()
                self._remove_shortcut_listener = None
            await self.stop()
            raise DaemonConfigurationError(
                setup.failure.reason if setup.failure else "global shortcut setup failed"
            )
        self._running = True
        self._closed.clear()
        binding = getattr(setup, "binding", None)
        trigger_description = getattr(binding, "trigger_description", "configured shortcut")
        self._status(
            f"ready — hold {trigger_description} to dictate; "
            "release to transcribe"
        )

    async def run_forever(self) -> None:
        await self.start()
        await self._closed.wait()

    async def wait_idle(self) -> None:
        """Yield until a fake or host event has completed its current dictation."""

        while (
            self._capture_task is not None
            or self._finish_task is not None
            or self._processing_task is not None
        ):
            await asyncio.sleep(0)

    async def stop(self) -> None:
        """Stop capture before releasing the platform sessions."""

        self._running = False
        current_task = asyncio.current_task()
        processing_task = self._processing_task
        if self._active_runner is not None:
            self._active_runner.request_cancel()
        if processing_task is not None and processing_task is not current_task:
            processing_task.cancel()
            await asyncio.gather(processing_task, return_exceptions=True)

        finish_task, self._finish_task = self._finish_task, None
        if (
            finish_task is not None
            and finish_task is not current_task
            and finish_task is not processing_task
        ):
            finish_task.cancel()
            await asyncio.gather(finish_task, return_exceptions=True)
        capture_session = self._capture_session
        capture_outcome = None
        if capture_session is not None:
            try:
                capture_outcome = await capture_session.cancel()
            except Exception:
                pass
            if capture_outcome is not None and self._active_runner is None:
                self._persist_capture_terminal(capture_outcome)
        capture_task, self._capture_task = self._capture_task, None
        if capture_task is not None and capture_task is not current_task:
            await asyncio.gather(capture_task, return_exceptions=True)

        self._persist_unfinished_job_cancelled()

        if self._remove_shortcut_listener is not None:
            self._remove_shortcut_listener()
            self._remove_shortcut_listener = None
        close_shortcut = getattr(self.shortcut, "close", None)
        if callable(close_shortcut):
            try:
                await close_shortcut()
            except Exception:
                pass
        if self.inserter is not None:
            close = getattr(self.inserter, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
        if self._owns_remote_session and self.remote_portal is not None:
            try:
                await self.remote_portal.close()
            except Exception:
                pass
            self._owns_remote_session = False
        self._capture_session = None
        self._active_runner = None
        self._active_job_id = None
        self._running = False
        self._closed.set()

    def _on_shortcut_event(self, event: ShortcutEvent) -> None:
        if not self._running:
            return
        if event.type is ShortcutEventType.LISTENING_STARTED:
            if self._capture_session is not None:
                if not self.shortcut.hold_supported:
                    self._status("stopping capture — processing locally")
                    self._schedule_finish_capture()
                return
            self._status(
                "listening — release the shortcut to transcribe; "
                "if it stays active, press the shortcut again to stop"
            )
            if self._processing_task is None:
                self._begin_capture()
            return
        if event.type is ShortcutEventType.LISTENING_STOPPED:
            self._status("processing locally — please wait")
            if self._capture_session is not None:
                self._schedule_finish_capture()

    def _schedule_finish_capture(self) -> None:
        if self._finish_task is None:
            self._finish_task = asyncio.create_task(self._finish_capture())

    def _begin_capture(self) -> None:
        job_id = uuid.uuid4().hex
        self._active_job_id = job_id
        self.history.create_job(
            HistoryRecord(
                job_id=job_id,
                status="listening",
                retain_audio=self.audio_config.retain_audio,
                audio_retention_state=AudioRetentionState.NOT_AVAILABLE,
            )
        )
        capture = self.capture_factory()
        factory_kwargs: dict[str, object] = {"config": self.audio_config}
        try:
            parameters = inspect.signature(self.audio_session_factory).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "artifact_name" in parameters:
            factory_kwargs["artifact_name"] = f"{job_id}.wav"
        self._capture_session = self.audio_session_factory(
            capture, self.artifact_dir, **factory_kwargs
        )
        self._capture_task = asyncio.create_task(self._capture_session.run())
        self._capture_task.add_done_callback(self._capture_task_done)

    def _cleanup_orphans(self) -> None:
        """Discard disabled-retention work left behind by an abnormal exit."""

        for summary in self.history.list_orphaned_jobs():
            artifact_id = summary.artifact_id
            if artifact_id:
                self._discard_artifact(artifact_id)
            self.history.mark_orphaned_job(summary.job_id)

        # A crash during atomic WAV materialization can leave only the hidden
        # temporary file. It is never a retained artifact and contains no
        # durable job identity, so it is safe to remove at startup.
        for path in self.artifact_dir.glob(".voxflow-*.wav"):
            if path.is_file():
                self._unlink_artifact(path)

    def _persist_unfinished_job_cancelled(self) -> None:
        """Close any active durable job not finalized by its task callback."""

        job_id = self._active_job_id
        if job_id is None:
            return
        try:
            record = self.history.get_job(job_id)
        except KeyError:
            return
        if record.status.value not in {"listening", "processing"}:
            return
        self._persist_terminal(
            job_id,
            None,
            self._capture_session,
            status="cancelled",
            error_code="cancelled",
            failure_reason="Dictation was cancelled before insertion.",
            retryable=record.retain_audio,
            retry_code="retry_transcription" if record.retain_audio else None,
        )

    def _capture_task_done(self, task: asyncio.Task[Any]) -> None:
        """Return failed/max-duration sessions to idle without waiting for release."""

        if task is not self._capture_task:
            return
        try:
            outcome = task.result()
        except BaseException:
            outcome = None
        if outcome is None or outcome.kind is not AudioSessionOutcomeType.COMPLETED:
            self._capture_task = None
            self._capture_session = None
            if outcome is not None and outcome.failure is not None:
                self._notify(f"capture failed: {outcome.failure.code}")
            self._persist_capture_terminal(outcome)

    async def _finish_capture(self) -> None:
        try:
            await self._finish_capture_impl()
        finally:
            if self._finish_task is asyncio.current_task():
                self._finish_task = None

    async def _finish_capture_impl(self) -> None:
        session = self._capture_session
        job_id = self._active_job_id
        if session is None:
            return
        outcome = await session.stop()
        capture_task, self._capture_task = self._capture_task, None
        if capture_task is not None and capture_task is not asyncio.current_task():
            await asyncio.gather(capture_task, return_exceptions=True)
        self._capture_session = None

        if outcome is None or outcome.kind is not AudioSessionOutcomeType.COMPLETED:
            if outcome is not None and outcome.failure is not None:
                self._notify(f"capture failed: {outcome.failure.code}")
            self._persist_capture_terminal(outcome)
            return
        if outcome.artifact is None or self.provider is None:
            self._notify("dictation failed: captured audio was unavailable")
            self._persist_terminal(
                job_id,
                outcome.artifact,
                session,
                status="failed",
                error_code="artifact_unavailable",
                failure_reason="Captured audio was unavailable for transcription.",
            )
            return

        self._processing_task = asyncio.current_task()
        snapshot = None
        writing_result: WritingResult | None = None
        try:
            runner = DictationJobRunner(
                self.provider,
                outcome.artifact,
                job_id=job_id,
            )
            self._active_runner = runner
            if job_id is not None:
                self.history.update_job(
                    job_id,
                    status="processing",
                    artifact_id=outcome.artifact.artifact_id,
                    audio_sha256=outcome.artifact.audio_sha256,
                    artifact_metadata=outcome.artifact.to_dict(),
                    retain_audio=self.audio_config.retain_audio,
                    audio_retention_state=AudioRetentionState.TRANSIENT,
                    provider_id=runner.config.provider_id,
                    model_id=runner.config.model_id,
                    provider_metadata=runner.config.to_safe_diagnostic(),
                )
            snapshot = await runner.run()
            if job_id is not None:
                self.history.update_job(
                    job_id,
                    # A successful transcript is still being transformed. A
                    # durable success is only legal after WritingResult has
                    # stored both raw and final text.
                    status=("processing" if snapshot.result is not None else snapshot.state),
                    provider_id=snapshot.config.provider_id,
                    model_id=snapshot.config.model_id,
                    provider_metadata=snapshot.config.to_safe_diagnostic(),
                    error_code=snapshot.error_code,
                    failure_reason=snapshot.failure_reason,
                    retryable=snapshot.retryable,
                    retry_code=snapshot.retry_code,
                    retry_count=snapshot.retry_count,
                )
            if snapshot.result is None or snapshot.state.value != "success":
                self._notify(
                    f"dictation failed: {snapshot.error_code or 'transcription_unavailable'}"
                )
                self._persist_terminal(
                    job_id,
                    outcome.artifact,
                    session,
                    status=snapshot.state,
                    error_code=snapshot.error_code or "transcription_unavailable",
                    failure_reason=snapshot.failure_reason,
                    retryable=snapshot.retryable and self.audio_config.retain_audio,
                    retry_code=snapshot.retry_code if self.audio_config.retain_audio else None,
                )
                self._active_runner = None
                self._active_job_id = None
                return
            if not snapshot.result.text.strip():
                self.last_writing_result = None
                self._notify("dictation failed: empty_transcript")
                self._persist_terminal(
                    job_id,
                    outcome.artifact,
                    session,
                    status="failed",
                    error_code="empty_transcript",
                    failure_reason="The transcription provider returned empty text.",
                )
                self._active_runner = None
                self._active_job_id = None
                return
            try:
                writing_result = await self._run_writing_pipeline(snapshot.result)
            except Exception:
                try:
                    fallback_settings = self.writing_settings_factory()
                except Exception:
                    fallback_settings = WritingSettings()
                self.last_writing_result = WritingResult(
                    raw=RawTranscript(snapshot.result),
                    final_text=snapshot.result.text,
                    settings=fallback_settings,
                    cleanup_provider_id="deterministic",
                    fallback=True,
                    fallback_code="writing_pipeline_failed",
                )
                self._persist_writing_result(
                    job_id,
                    self.last_writing_result,
                    snapshot,
                    outcome.artifact,
                    status="failed",
                )
                self._persist_terminal(
                    job_id,
                    outcome.artifact,
                    session,
                    status="failed",
                    error_code="writing_pipeline_failed",
                    failure_reason="The writing pipeline failed; raw text was retained.",
                )
                self._active_runner = None
                self._active_job_id = None
                self._notify("writing failed: writing_pipeline_failed")
                return
            self.last_writing_result = writing_result
            self._persist_writing_result(
                job_id,
                writing_result,
                snapshot,
                outcome.artifact,
                status="processing",
            )
            if not self._running:
                self._persist_terminal(
                    job_id,
                    outcome.artifact,
                    session,
                    status="cancelled",
                    error_code="cancelled",
                    failure_reason="Dictation was cancelled before insertion.",
                )
                self._active_runner = None
                self._active_job_id = None
                return
            if writing_result.fallback:
                self._status(f"writing fallback: {writing_result.fallback_code}")
            self.last_insert_outcome = await self._insert_for_job(
                job_id,
                writing_result.final_text,
                artifact=outcome.artifact,
                session=session,
            )
            if self.inserter is None:
                self._notify(
                    "insertion unavailable — text retained; save or retry insertion"
                )
            capability = getattr(self.inserter, "capability", None)
            if self.inserter is not None and isinstance(capability, CapabilityRecord):
                self.insertion_capability = capability
            if self.last_insert_outcome.result is not InsertResult.sent:
                self._notify(self.last_insert_outcome.fallback_hint or FALLBACK_HINT)
            else:
                self._status("inserted transcript")
            self._active_runner = None
            self._active_job_id = None
        except asyncio.CancelledError:
            # Cancellation can arrive while optional cleanup or insertion is
            # awaiting. Preserve the transcript if ASR completed, then make
            # the durable job terminal instead of leaving it in processing.
            if (
                job_id is not None
                and snapshot is not None
                and snapshot.result is not None
                and snapshot.result.text.strip()
            ):
                if writing_result is None:
                    try:
                        fallback_settings = self.writing_settings_factory()
                    except Exception:
                        fallback_settings = WritingSettings()
                    writing_result = WritingResult(
                        raw=RawTranscript(snapshot.result),
                        final_text=snapshot.result.text,
                        settings=fallback_settings,
                        cleanup_provider_id="deterministic",
                        fallback=True,
                        fallback_code="writing_cancelled",
                    )
                self.last_writing_result = writing_result
                self._persist_writing_result(
                    job_id,
                    writing_result,
                    snapshot,
                    outcome.artifact,
                    status="cancelled",
                )
            self._persist_terminal(
                job_id,
                outcome.artifact,
                session,
                status="cancelled",
                error_code="cancelled",
                failure_reason="Dictation was cancelled before insertion.",
                retryable=self.audio_config.retain_audio,
                retry_code=("retry_transcription" if self.audio_config.retain_audio else None),
            )
            self._active_runner = None
            self._active_job_id = None
            return
        finally:
            self._processing_task = None

    def _persist_capture_terminal(self, outcome: Any | None) -> None:
        job_id = self._active_job_id
        if job_id is None:
            return
        if outcome is None:
            self._persist_terminal(
                job_id,
                None,
                self._capture_session,
                status="failed",
                error_code="capture_failed",
                failure_reason="Audio capture ended without a structured outcome.",
            )
            return
        status = "cancelled" if outcome.kind is AudioSessionOutcomeType.CANCELLED else "failed"
        failure = outcome.failure
        self._persist_terminal(
            job_id,
            outcome.artifact,
            self._capture_session,
            status=status,
            error_code=failure.code if failure else outcome.kind.value,
            failure_reason=failure.reason if failure else None,
            retryable=bool(outcome.retryable and self.audio_config.retain_audio),
            retry_code=outcome.retry_code if self.audio_config.retain_audio else None,
        )

    def _persist_writing_result(
        self,
        job_id: str | None,
        writing_result: WritingResult,
        snapshot: Any,
        artifact: Any,
        *,
        status: str,
    ) -> None:
        if job_id is None:
            return
        current = self.history.get_job(job_id)
        provider_metadata = dict(snapshot.config.to_safe_diagnostic())
        provider_metadata.update(writing_result.raw.to_safe_dict())
        record = HistoryRecord.from_writing_result(
            job_id,
            writing_result,
            status=status,
            created_at=current.created_at,
            updated_at=utc_now(),
            provider_metadata=provider_metadata,
            artifact=artifact,
            retain_audio=current.retain_audio,
            audio_retention_state=AudioRetentionState.TRANSIENT,
            retry_count=current.retry_count,
            insertion_attempt_id=current.insertion_attempt_id,
            insertion_result=current.insertion_result,
            insertion_side_effect=current.insertion_side_effect,
            insertion_retryable=current.insertion_retryable,
            insertion_detail=current.insertion_detail,
        )
        self.history.upsert_job(record)

    def _persist_terminal(
        self,
        job_id: str | None,
        artifact: Any,
        session: AudioSession | None,
        *,
        status: str,
        error_code: str | None = None,
        failure_reason: str | None = None,
        retryable: bool = False,
        retry_code: str | None = None,
    ) -> None:
        if job_id is None:
            return
        current = self.history.get_job(job_id)
        target = artifact
        retention = AudioRetentionState.NOT_AVAILABLE
        artifact_id = current.artifact_id
        audio_sha256 = current.audio_sha256
        artifact_metadata = current.artifact_metadata
        if artifact is not None and hasattr(artifact, "artifact_id"):
            artifact_id = artifact.artifact_id
            audio_sha256 = artifact.audio_sha256
            artifact_metadata = artifact.to_dict()
        has_artifact = target is not None or artifact_id is not None
        if current.retain_audio:
            retention = AudioRetentionState.RETAINED if has_artifact else AudioRetentionState.NOT_AVAILABLE
        elif has_artifact:
            del session
            deleted = self._discard_artifact(artifact_id)
            retention = AudioRetentionState.DELETED if deleted else AudioRetentionState.TRANSIENT
        self.history.update_job(
            job_id,
            status=status,
            updated_at=utc_now(),
            error_code=error_code,
            failure_reason=failure_reason,
            retryable=retryable,
            retry_code=retry_code,
            retain_audio=current.retain_audio,
            artifact_id=artifact_id,
            audio_sha256=audio_sha256,
            artifact_metadata=artifact_metadata,
            audio_retention_state=retention,
        )

    def _discard_artifact(self, artifact_id: object) -> bool:
        if not isinstance(artifact_id, str) or Path(artifact_id).name != artifact_id:
            return False
        root = self.artifact_dir.resolve()
        raw_path = root / artifact_id
        if raw_path.is_symlink():
            return False
        path = raw_path.resolve()
        if path.parent != root:
            return False
        return self._unlink_artifact(path)

    @staticmethod
    def _unlink_artifact(path: Any) -> bool:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            return False
        return True

    async def _insert_for_job(
        self,
        job_id: str | None,
        text: str,
        *,
        artifact: Any | None = None,
        session: AudioSession | None = None,
        retry_of_attempt_id: str | None = None,
    ) -> InsertOutcome:
        if job_id is None:
            raise RecoveryError("insertion requires a durable job ID")
        current = self.history.get_job(job_id)
        if current.raw_text is None or current.final_text is None:
            raise RecoveryError("insertion requires a stored writing result")
        attempt_id = uuid.uuid4().hex
        self.history.create_insertion_attempt(
            InsertionAttemptRecord(
                attempt_id=attempt_id,
                job_id=job_id,
                phase="prepared",
                side_effect=InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT.value,
                retryable=True,
                retry_of_attempt_id=retry_of_attempt_id,
            )
        )
        # The process can disappear immediately after this write and before
        # the inserter emits its chord. Treat the whole call window as
        # ambiguous until the inserter reports a known pre-side-effect result.
        self.history.update_insertion_attempt(
            attempt_id,
            expected_phase="prepared",
            phase="ambiguous",
            side_effect=InsertSideEffect.UNKNOWN_AFTER_SIDE_EFFECT.value,
            retryable=False,
            detail="insertion side-effect window opened",
        )
        if self.inserter is None:
            insertion = self._unavailable_insert_outcome(text, attempt_id=attempt_id)
        else:
            try:
                insertion = await self._call_inserter(text, attempt_id)
            except asyncio.CancelledError:
                # Leave the durable ambiguous guard in place. A later process
                # must never interpret this attempt as a safe prepared retry.
                raise
            except Exception:
                insertion = InsertOutcome(
                    result=InsertResult.failed,
                    text=text,
                    fallback_hint=FALLBACK_HINT,
                    detail="insertion failed after the side-effect guard",
                    attempt_id=attempt_id,
                    side_effect=InsertSideEffect.UNKNOWN_AFTER_SIDE_EFFECT,
                    retryable=False,
                )
        events = {str(event.get("event")): event for event in insertion.trace}
        chord_sent = "chord_sent" in events
        ownership_confirmed = bool(events.get("ownership_confirmed", {}).get("confirmed", False))
        transfer_completed = bool(events.get("selection_write_done", {}).get("ok", False))
        side_effect = InsertSideEffect(insertion.side_effect)
        phase = (
            "completed"
            if side_effect is InsertSideEffect.COMPLETED
            else "ambiguous"
            if side_effect is InsertSideEffect.UNKNOWN_AFTER_SIDE_EFFECT
            else "failed"
        )
        self.history.update_insertion_attempt(
            attempt_id,
            expected_phase="ambiguous",
            phase=phase,
            chord_sent=chord_sent,
            ownership_confirmed=ownership_confirmed,
            transfer_completed=transfer_completed,
            outcome=insertion.result.value,
            side_effect=side_effect.value,
            retryable=insertion.retryable,
            detail=insertion.detail,
            trace=insertion.trace,
        )
        current = self.history.get_job(job_id)
        retention = current.audio_retention_state
        if artifact is not None or current.artifact_id:
            if current.retain_audio:
                retention = AudioRetentionState.RETAINED
            else:
                del session
                deleted = self._discard_artifact(
                    artifact.artifact_id if artifact is not None else current.artifact_id
                )
                retention = AudioRetentionState.DELETED if deleted else AudioRetentionState.TRANSIENT
        terminal_status = "success" if insertion.result is InsertResult.sent else "failed"
        self.history.update_job(
            job_id,
            status=terminal_status,
            updated_at=utc_now(),
            retryable=insertion.retryable,
            retry_code="retry_insertion" if insertion.retryable else None,
            error_code=None if insertion.result is InsertResult.sent else f"insertion_{insertion.result.value}",
            failure_reason=None if insertion.result is InsertResult.sent else insertion.detail,
            audio_retention_state=retention,
            insertion_attempt_id=attempt_id,
            insertion_result=insertion.result.value,
            insertion_side_effect=side_effect.value,
            insertion_retryable=insertion.retryable,
            insertion_detail=insertion.detail,
        )
        return insertion

    async def _call_inserter(self, text: str, attempt_id: str) -> InsertOutcome:
        assert self.inserter is not None
        insert = self.inserter.insert
        try:
            parameters = inspect.signature(insert).parameters
            accepts_attempt_id = "attempt_id" in parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
        except (TypeError, ValueError):
            accepts_attempt_id = False
        result = insert(text, attempt_id=attempt_id) if accepts_attempt_id else insert(text)
        result = await result if inspect.isawaitable(result) else result
        if not isinstance(result, InsertOutcome):
            raise TypeError("inserter returned an invalid outcome")
        return result

    async def retry_insertion(
        self,
        job_id: str,
        *,
        confirm_ambiguous: bool = False,
    ) -> InsertOutcome:
        """Retry only a known pre-chord failure; serialize duplicate requests."""

        async with self._recovery_lock:
            record = self.history.show_job(job_id)
            attempts = self.history.list_insertion_attempts(job_id)
            latest = attempts[-1] if attempts else None
            if latest is not None and (
                latest.side_effect == InsertSideEffect.COMPLETED.value
                or latest.outcome == InsertResult.sent.value
            ):
                return InsertOutcome(
                    result=InsertResult.sent,
                    text=record.final_text or "",
                    attempt_id=latest.attempt_id,
                    side_effect=InsertSideEffect.COMPLETED,
                    retryable=False,
                )
            if latest is not None and latest.side_effect == InsertSideEffect.UNKNOWN_AFTER_SIDE_EFFECT.value:
                if not confirm_ambiguous:
                    raise RecoveryNotAllowedError(
                        "paste result is unknown after the chord; explicit confirmation is required"
                    )
            elif latest is not None and not latest.retryable:
                raise RecoveryNotAllowedError("the latest insertion attempt is not retry-safe")
            if record.final_text is None:
                raise RecoveryError("job has no final text to insert")
            return await self._insert_for_job(
                job_id,
                record.final_text,
                retry_of_attempt_id=latest.attempt_id if latest else None,
            )

    async def retry(
        self,
        job_id: str,
        *,
        confirm_ambiguous: bool = False,
    ) -> InsertOutcome:
        """Stable recovery-controller spelling for insertion retry."""

        return await self.retry_insertion(job_id, confirm_ambiguous=confirm_ambiguous)

    async def retry_transcription(self, job_id: str) -> HistoryRecord:
        """Retry ASR from a retained artifact, then complete writing/insertion."""

        async with self._recovery_lock:
            record = self.history.show_job(job_id)
            if not record.retain_audio or record.audio_retention_state is not AudioRetentionState.RETAINED:
                raise RecoveryError("transcription retry requires retained audio")
            if not record.retryable or record.retry_code != "retry_transcription":
                raise RecoveryError("the job is not retryable as transcription")

            artifact = self.history.resolve_artifact(job_id, self.artifact_dir)
            if artifact is None:
                self.history.update_job(
                    job_id,
                    status="failed",
                    error_code="audio_unavailable",
                    failure_reason="Captured audio was unavailable for transcription.",
                    retryable=False,
                    retry_code=None,
                    audio_retention_state=AudioRetentionState.NOT_AVAILABLE,
                )
                raise RecoveryError("retained audio is no longer available")

            if self.provider is None:
                try:
                    await self.reload_provider_async()
                except Exception as exc:
                    raise RecoveryError("the selected transcription provider is unavailable") from exc
            if self.provider is None:
                raise RecoveryError("the selected transcription provider is unavailable")

            self.history.update_job(
                job_id,
                status="processing",
                error_code=None,
                failure_reason=None,
                retryable=False,
                retry_code=None,
                retry_count=record.retry_count + 1,
                audio_retention_state=AudioRetentionState.RETAINED,
            )
            runner = DictationJobRunner(
                self.provider,
                artifact,
                job_id=job_id,
                retry_count=record.retry_count + 1,
            )
            self._active_job_id = job_id
            self._active_runner = runner
            self._processing_task = asyncio.current_task()
            snapshot = None
            writing_result: WritingResult | None = None
            try:
                snapshot = await runner.run()
                self.history.update_job(
                    job_id,
                    status=("processing" if snapshot.result is not None else snapshot.state),
                    provider_id=snapshot.config.provider_id,
                    model_id=snapshot.config.model_id,
                    provider_metadata=snapshot.config.to_safe_diagnostic(),
                    error_code=snapshot.error_code,
                    failure_reason=snapshot.failure_reason,
                    retryable=snapshot.retryable,
                    retry_code=snapshot.retry_code,
                    retry_count=snapshot.retry_count,
                )
                if snapshot.result is None or snapshot.state.value != "success":
                    self._persist_terminal(
                        job_id,
                        artifact,
                        None,
                        status=snapshot.state,
                        error_code=snapshot.error_code or "transcription_unavailable",
                        failure_reason=snapshot.failure_reason,
                        retryable=snapshot.retryable,
                        retry_code=snapshot.retry_code,
                    )
                    return self.history.show_job(job_id)
                if not snapshot.result.text.strip():
                    self._persist_terminal(
                        job_id,
                        artifact,
                        None,
                        status="failed",
                        error_code="empty_transcript",
                        failure_reason="The transcription provider returned empty text.",
                    )
                    return self.history.show_job(job_id)

                try:
                    writing_result = await self._run_writing_pipeline(snapshot.result)
                except Exception:
                    try:
                        fallback_settings = self.writing_settings_factory()
                    except Exception:
                        fallback_settings = WritingSettings()
                    writing_result = WritingResult(
                        raw=RawTranscript(snapshot.result),
                        final_text=snapshot.result.text,
                        settings=fallback_settings,
                        cleanup_provider_id="deterministic",
                        fallback=True,
                        fallback_code="writing_pipeline_failed",
                    )
                    self.last_writing_result = writing_result
                    self._persist_writing_result(
                        job_id,
                        writing_result,
                        snapshot,
                        artifact,
                        status="failed",
                    )
                    self._persist_terminal(
                        job_id,
                        artifact,
                        None,
                        status="failed",
                        error_code="writing_pipeline_failed",
                        failure_reason="The writing pipeline failed; raw text was retained.",
                    )
                    return self.history.show_job(job_id)

                self.last_writing_result = writing_result
                self._persist_writing_result(
                    job_id,
                    writing_result,
                    snapshot,
                    artifact,
                    status="processing",
                )
                if not self._running:
                    self._persist_terminal(
                        job_id,
                        artifact,
                        None,
                        status="cancelled",
                        error_code="cancelled",
                        failure_reason="Dictation was cancelled before insertion.",
                        retryable=True,
                        retry_code="retry_transcription",
                    )
                    return self.history.show_job(job_id)
                self.last_insert_outcome = await self._insert_for_job(
                    job_id,
                    writing_result.final_text,
                    artifact=artifact,
                )
                return self.history.show_job(job_id)
            except asyncio.CancelledError:
                if (
                    snapshot is not None
                    and snapshot.result is not None
                    and snapshot.result.text.strip()
                ):
                    if writing_result is None:
                        try:
                            fallback_settings = self.writing_settings_factory()
                        except Exception:
                            fallback_settings = WritingSettings()
                        writing_result = WritingResult(
                            raw=RawTranscript(snapshot.result),
                            final_text=snapshot.result.text,
                            settings=fallback_settings,
                            cleanup_provider_id="deterministic",
                            fallback=True,
                            fallback_code="writing_cancelled",
                        )
                    self.last_writing_result = writing_result
                    self._persist_writing_result(
                        job_id,
                        writing_result,
                        snapshot,
                        artifact,
                        status="cancelled",
                    )
                self._persist_terminal(
                    job_id,
                    artifact,
                    None,
                    status="cancelled",
                    error_code="cancelled",
                    failure_reason="Dictation was cancelled before insertion.",
                    retryable=True,
                    retry_code="retry_transcription",
                )
                return self.history.show_job(job_id)
            finally:
                if self._processing_task is asyncio.current_task():
                    self._processing_task = None
                if self._active_runner is runner:
                    self._active_runner = None
                if self._active_job_id == job_id:
                    self._active_job_id = None

    async def _run_writing_pipeline(self, transcript: Any) -> WritingResult:
        settings = self.writing_settings_factory()
        run_async = getattr(self.writing_pipeline, "run_async", None)
        result = (
            run_async(transcript, settings)
            if callable(run_async)
            else self.writing_pipeline.run(transcript, settings)
        )
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, WritingResult):
            raise TypeError("writing pipeline returned an invalid result")
        return result

    @staticmethod
    def _status(message: str) -> None:
        """Print non-sensitive lifecycle status without exposing transcript text."""

        print(f"VoxFlow: {message}", flush=True)

    def _notify(self, message: str) -> None:
        try:
            self.notifier.notify(message)
        except Exception:
            print(message, file=sys.stderr, flush=True)

    def _selected_model_id(self) -> str | None:
        getter = self.catalog.get_selected
        try:
            return getter(db_path=self.db_path)
        except TypeError:
            return getter()

    @staticmethod
    def _unavailable_insert_outcome(
        text: str,
        *,
        attempt_id: str | None = None,
    ) -> InsertOutcome:
        """Build a retry-safe, metadata-only outcome when no adapter exists."""

        attempt_id = attempt_id or uuid.uuid4().hex
        trace = (
            {"attempt_id": attempt_id, "event": "attempt_started", "elapsed_ms": 0},
            {
                "attempt_id": attempt_id,
                "event": "outcome_recorded",
                "elapsed_ms": 0,
                "result": InsertResult.unavailable.value,
                "side_effect": InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT.value,
                "retryable": True,
            },
        )
        return InsertOutcome(
            result=InsertResult.unavailable,
            text=text,
            fallback_hint=FALLBACK_HINT,
            detail="insertion capability unavailable",
            attempt_id=attempt_id,
            trace=trace,
            side_effect=InsertSideEffect.FAILED_BEFORE_SIDE_EFFECT,
            retryable=True,
        )


async def _run_main(args: argparse.Namespace) -> int:
    daemon = DictationDaemon(models_root=args.model_root, db_path=args.db_path)
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        asyncio.create_task(daemon.stop())

    async def reload_selected() -> None:
        try:
            await daemon.reload_provider_async()
        except DaemonConfigurationError as exc:
            daemon._notify(str(exc))

    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is not None:
            try:
                loop.add_signal_handler(signum, request_stop)
            except (NotImplementedError, RuntimeError):
                pass
    sighup = getattr(signal, "SIGHUP", None)
    if sighup is not None:
        try:
            loop.add_signal_handler(sighup, lambda: asyncio.create_task(reload_selected()))
        except (NotImplementedError, RuntimeError):
            pass
    try:
        await daemon.run_forever()
    finally:
        await daemon.stop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local VoxFlow dictation daemon")
    parser.add_argument("--model-root", type=Path, default=None)
    parser.add_argument("--db-path", type=Path, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return asyncio.run(_run_main(args))
    except DaemonConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2


__all__ = [
    "BestEffortNotifier",
    "DaemonConfigurationError",
    "DictationDaemon",
    "RecoveryController",
    "RecoveryError",
    "RecoveryNotAllowedError",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
