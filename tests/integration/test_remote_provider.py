import asyncio
import hashlib
from pathlib import Path

import pytest

from voxflow.audio.artifacts import AudioArtifact
from voxflow.core.jobs import DictationJobRunner
from voxflow.core.state import SessionState
from voxflow.platform.audio_devices import AudioFormat
from voxflow.providers.asr import (
    ASRCancellationError,
    ASRProviderError,
    AudioInput,
    CancellationToken,
    ProviderConfigSnapshot,
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


def artifact() -> AudioArtifact:
    return AudioArtifact(
        path=FIXTURE,
        audio_sha256=CHECKSUM,
        source_format=FORMAT,
        frame_count=480,
        duration_ms=10,
        wav_byte_count=FIXTURE.stat().st_size,
    )


def config(policy: NetworkPolicy = NetworkPolicy.REMOTE_EXPLICIT) -> ProviderConfigSnapshot:
    return RemoteProviderConfig(
        provider_id="remote-fixture",
        model_id="remote-model",
        endpoint="http://127.0.0.1:9000/asr",
        credential_env_var="VOXFLOW_TEST_TOKEN",
    ).to_selection(network_policy=policy, language_hint="en")


def payload(checksum: str = CHECKSUM) -> dict[str, object]:
    return {
        "text": "fixture remote transcript",
        "language": "en",
        "language_probability": 0.98,
        "confidence": 0.97,
        "segments": [{"start_ms": 0, "end_ms": 10, "text": "fixture remote transcript"}],
        "provider_id": "remote-fixture",
        "model_id": "remote-model",
        "audio_sha256": checksum,
    }


class FakeTransport:
    def __init__(self, response=None, *, failure=None):
        self.response = response
        self.failure = failure
        self.calls = []

    async def request(self, request, *, timeout_seconds, cancellation):
        self.calls.append((request, timeout_seconds, cancellation))
        if self.failure is not None:
            raise self.failure
        return self.response


class BlockingTransport:
    def __init__(self):
        self.calls = 0

    async def request(self, _request, *, timeout_seconds, cancellation):
        self.calls += 1
        while not cancellation.is_cancelled:
            await asyncio.sleep(0)
        raise ASRCancellationError()


def test_valid_response_uses_one_safe_structured_request() -> None:
    transport = FakeTransport(RemoteASRResponse(200, payload()))
    provider = RemoteASRProvider(config(), transport=transport)

    snapshot = asyncio.run(DictationJobRunner(provider, artifact(), config=config()).run())

    assert snapshot.state is SessionState.SUCCESS
    assert snapshot.result is not None
    assert snapshot.result.audio_sha256 == CHECKSUM
    assert len(transport.calls) == 1
    request, timeout_seconds, _token = transport.calls[0]
    assert timeout_seconds == 30.0
    safe = request.to_safe_dict()
    assert safe["audio_sha256"] == CHECKSUM
    assert safe["model_id"] == "remote-model"
    assert safe["language_hint"] == "en"
    assert str(FIXTURE) not in str(safe)
    assert "transcript" not in str(safe).lower()


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (RemoteASRResponse(503, {"body": "token=do-not-leak"}), "remote_http_error"),
        (RemoteASRResponse(200, {"text": "raw response should not leak"}), "invalid_result"),
        (RemoteASRResponse(200, payload("1" * 64)), "checksum_mismatch"),
    ],
)
def test_invalid_remote_responses_are_failed_and_redacted(response, error_code: str) -> None:
    provider = RemoteASRProvider(config(), transport=FakeTransport(response))

    snapshot = asyncio.run(DictationJobRunner(provider, artifact(), config=config()).run())

    assert snapshot.state is SessionState.FAILED
    assert snapshot.error_code == error_code
    assert snapshot.retryable
    diagnostics = str(snapshot.to_dict())
    assert "raw response should not leak" not in diagnostics
    assert "do-not-leak" not in diagnostics
    assert "token" not in diagnostics.lower()
    assert str(FIXTURE) not in diagnostics


def test_transport_failure_is_typed_and_does_not_expose_exception_detail() -> None:
    transport = FakeTransport(
        failure=RemoteTransportError("upstream_secret_code", "Bearer secret response body")
    )
    provider = RemoteASRProvider(config(), transport=transport)

    snapshot = asyncio.run(DictationJobRunner(provider, artifact(), config=config()).run())

    assert snapshot.state is SessionState.FAILED
    assert snapshot.error_code == "remote_transport_failed"
    assert "secret" not in str(snapshot.to_dict()).lower()
    assert "response body" not in str(snapshot.to_dict()).lower()


def test_local_only_policy_rejects_before_transport_invocation() -> None:
    transport = FakeTransport(RemoteASRResponse(200, payload()))
    selected = config(NetworkPolicy.LOCAL_ONLY)
    provider = RemoteASRProvider(selected, transport=transport)

    snapshot = asyncio.run(DictationJobRunner(provider, artifact(), config=selected).run())

    assert snapshot.state is SessionState.FAILED
    assert snapshot.error_code == "network_policy_rejected"
    assert snapshot.retryable
    assert "remote_explicit" in snapshot.failure_reason
    assert transport.calls == []


def test_pre_cancelled_request_never_reaches_transport() -> None:
    transport = FakeTransport(RemoteASRResponse(200, payload()))
    provider = RemoteASRProvider(config(), transport=transport)
    token = CancellationToken()
    token.cancel()

    with pytest.raises(ASRProviderError) as raised:
        asyncio.run(
            provider.transcribe(
                # The runner normally builds this immutable input for us.
                AudioInput(
                    path=FIXTURE,
                    audio_sha256=CHECKSUM,
                    source_format=FORMAT,
                    duration_ms=10,
                    config=config(),
                ),
                token,
            )
        )

    assert raised.value.code == "cancelled"
    assert transport.calls == []


def test_in_flight_cancellation_is_cancelled_and_not_success() -> None:
    transport = BlockingTransport()
    provider = RemoteASRProvider(config(), transport=transport)

    async def scenario():
        runner = DictationJobRunner(provider, artifact(), config=config(), job_id="remote-cancel")
        task = asyncio.create_task(runner.run())
        for _ in range(100):
            if transport.calls:
                break
            await asyncio.sleep(0)
        snapshot = await runner.cancel()
        return task, snapshot

    task, snapshot = asyncio.run(scenario())

    assert task.done()
    assert transport.calls == 1
    assert snapshot.state is SessionState.CANCELLED
    assert snapshot.retryable
    assert snapshot.result is None
