import asyncio
import hashlib
import socket
from pathlib import Path

import pytest

from voxflow.audio.artifacts import AudioArtifact
from voxflow.core.jobs import DictationJobRunner
from voxflow.core.state import SessionState
from voxflow.platform.audio_devices import AudioFormat
from voxflow.providers.asr import (
    ASRCancellationError,
    ASRProviderError,
    CancellationToken,
    ProviderCapabilities,
    ProviderConfigSnapshot,
    Segment,
    TranscriptResult,
)
from voxflow.providers.config import NetworkPolicy, RemoteProviderConfig
from voxflow.providers.remote_asr import (
    RemoteASRProvider,
    RemoteASRResponse,
    RemoteTransportError,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "audio" / "short_utterance.wav"
CHECKSUM = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
FORMAT = AudioFormat(48_000, 1)


@pytest.fixture(autouse=True)
def deny_sockets(monkeypatch):
    real_socket = socket.socket

    def fail_socket(*_args, **_kwargs):
        family = _args[0] if _args else _kwargs.get("family", socket.AF_INET)
        if family in {socket.AF_INET, socket.AF_INET6}:
            raise AssertionError("provider contract tests must not open network sockets")
        return real_socket(*_args, **_kwargs)

    monkeypatch.setattr(socket, "socket", fail_socket)


def artifact() -> AudioArtifact:
    return AudioArtifact(
        path=FIXTURE,
        audio_sha256=CHECKSUM,
        source_format=FORMAT,
        frame_count=480,
        duration_ms=10,
        wav_byte_count=FIXTURE.stat().st_size,
    )


def local_config() -> ProviderConfigSnapshot:
    return ProviderConfigSnapshot(
        provider_id="local-fixture",
        model_id="local-model",
    )


def remote_config() -> ProviderConfigSnapshot:
    return RemoteProviderConfig(
        provider_id="remote-fixture",
        model_id="remote-model",
        endpoint="http://127.0.0.1:9000/asr",
    ).to_selection(network_policy=NetworkPolicy.REMOTE_EXPLICIT)


def result_payload(config: ProviderConfigSnapshot, checksum: str = CHECKSUM) -> dict[str, object]:
    return {
        "text": "contract transcript must stay out of diagnostics",
        "language": "en",
        "language_probability": 0.9,
        "confidence": 0.9,
        "segments": [{"start_ms": 0, "end_ms": 10, "text": "contract"}],
        "provider_id": config.provider_id,
        "model_id": config.model_id,
        "audio_sha256": checksum,
    }


class FakeLocalProvider:
    def __init__(self, config, *, response=None, failure=None, blocking=False):
        self.config = config
        self.response = response
        self.failure = failure
        self.blocking = blocking

    @property
    def capabilities(self):
        return ProviderCapabilities(
            provider_id=self.config.provider_id,
            model_id=self.config.model_id,
            offline=True,
            network_required=False,
            supports_cancellation=True,
        )

    async def transcribe(self, _audio, cancellation):
        if self.blocking:
            while not cancellation.is_cancelled:
                await asyncio.sleep(0)
            raise ASRCancellationError()
        if self.failure is not None:
            raise self.failure
        return self.response


class FakeRemoteTransport:
    def __init__(self, response=None, *, failure=None, blocking=False):
        self.response = response
        self.failure = failure
        self.blocking = blocking
        self.calls = 0

    async def request(self, _request, *, timeout_seconds, cancellation):
        self.calls += 1
        if self.blocking:
            while not cancellation.is_cancelled:
                await asyncio.sleep(0)
            raise ASRCancellationError()
        if self.failure is not None:
            raise self.failure
        return self.response


def make_provider(kind: str, scenario: str):
    config = local_config() if kind == "local" else remote_config()
    if scenario == "success":
        response = (
            TranscriptResult(
                text="contract transcript must stay out of diagnostics",
                language="en",
                language_probability=0.9,
                confidence=0.9,
                segments=(Segment(start_ms=0, end_ms=10, text="contract"),),
                provider_id=config.provider_id,
                model_id=config.model_id,
                audio_sha256=CHECKSUM,
            )
            if kind == "local"
            else RemoteASRResponse(200, result_payload(config))
        )
        return config, FakeLocalProvider(config, response=response) if kind == "local" else RemoteASRProvider(
            config,
            transport=FakeRemoteTransport(response=response),
        )
    if scenario == "bad_timestamps":
        response = {
            **result_payload(config),
            "segments": [{"start_ms": 10, "end_ms": 10, "text": "bad"}],
        }
        return config, FakeLocalProvider(config, response=response) if kind == "local" else RemoteASRProvider(
            config,
            transport=FakeRemoteTransport(response=RemoteASRResponse(200, response)),
        )
    if scenario == "bad_checksum":
        response = (
            TranscriptResult(
                text="wrong checksum",
                provider_id=config.provider_id,
                model_id=config.model_id,
                audio_sha256="1" * 64,
            )
            if kind == "local"
            else RemoteASRResponse(200, result_payload(config, "1" * 64))
        )
        return config, FakeLocalProvider(config, response=response) if kind == "local" else RemoteASRProvider(
            config,
            transport=FakeRemoteTransport(response=response),
        )
    if scenario == "failure":
        return config, FakeLocalProvider(
            config,
            failure=ASRProviderError("provider_failure", "private provider detail"),
        ) if kind == "local" else RemoteASRProvider(
            config,
            transport=FakeRemoteTransport(
                failure=RemoteTransportError("remote_transport_failed", "private response body")
            ),
        )
    if scenario == "cancel":
        return config, FakeLocalProvider(config, blocking=True) if kind == "local" else RemoteASRProvider(
            config,
            transport=FakeRemoteTransport(blocking=True),
        )
    raise AssertionError(f"unknown contract scenario: {scenario}")


@pytest.mark.parametrize("kind", ["local", "remote"], ids=["local", "remote"])
def test_contract_success_is_shared_by_local_and_remote(kind: str) -> None:
    config, provider = make_provider(kind, "success")

    snapshot = asyncio.run(DictationJobRunner(provider, artifact(), config=config).run())

    assert snapshot.state is SessionState.SUCCESS
    assert snapshot.result is not None
    assert snapshot.result.audio_sha256 == CHECKSUM


@pytest.mark.parametrize("kind", ["local", "remote"], ids=["local", "remote"])
def test_contract_timestamp_validation_is_shared(kind: str) -> None:
    config, provider = make_provider(kind, "bad_timestamps")

    snapshot = asyncio.run(DictationJobRunner(provider, artifact(), config=config).run())

    assert snapshot.state is SessionState.FAILED
    assert snapshot.error_code == "invalid_result"
    assert snapshot.retryable


@pytest.mark.parametrize("kind", ["local", "remote"], ids=["local", "remote"])
def test_contract_checksum_validation_is_shared(kind: str) -> None:
    config, provider = make_provider(kind, "bad_checksum")

    snapshot = asyncio.run(DictationJobRunner(provider, artifact(), config=config).run())

    assert snapshot.state is SessionState.FAILED
    assert snapshot.error_code == "checksum_mismatch"
    assert snapshot.retry_code == "retry_transcription"


@pytest.mark.parametrize("kind", ["local", "remote"], ids=["local", "remote"])
def test_contract_provider_failure_is_recoverable(kind: str) -> None:
    config, provider = make_provider(kind, "failure")

    snapshot = asyncio.run(DictationJobRunner(provider, artifact(), config=config).run())

    assert snapshot.state is SessionState.FAILED
    assert snapshot.retryable
    assert snapshot.retry_code == "retry_transcription"
    assert snapshot.artifact_reference.audio_sha256 == CHECKSUM
    diagnostics = str(snapshot.to_dict()).lower()
    assert "private provider detail" not in diagnostics
    assert "private response body" not in diagnostics


@pytest.mark.parametrize("kind", ["local", "remote"], ids=["local", "remote"])
def test_contract_cancellation_is_terminal_and_retryable(kind: str) -> None:
    config, provider = make_provider(kind, "cancel")

    async def scenario():
        runner = DictationJobRunner(provider, artifact(), config=config)
        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0)
        snapshot = await runner.cancel()
        return task, snapshot

    task, snapshot = asyncio.run(scenario())

    assert task.done()
    assert snapshot.state is SessionState.CANCELLED
    assert snapshot.retryable
    assert snapshot.retry_code == "retry_transcription"
    assert snapshot.result is None


@pytest.mark.parametrize("kind", ["local", "remote"], ids=["local", "remote"])
def test_contract_diagnostics_are_redacted_and_retry_metadata_is_stable(kind: str) -> None:
    config, provider = make_provider(kind, "success")
    snapshot = asyncio.run(
        DictationJobRunner(provider, artifact(), config=config, retry_count=2).run()
    )

    diagnostics = str(snapshot.to_dict()).lower()
    assert snapshot.retry_count == 2
    assert "contract transcript" not in diagnostics
    assert "text" not in diagnostics
    assert str(FIXTURE) not in diagnostics
    assert "/home/" not in diagnostics
    assert "/tmp/" not in diagnostics
