import asyncio

import pytest

from voxflow.providers.asr import CancellationToken
from voxflow.providers.cleanup import (
    CleanupCancellationError,
    CleanupProviderError,
    CleanupRequest,
    CleanupResponse,
    RemoteCleanupProvider,
    UrllibCleanupTransport,
)
from voxflow.providers.config import CleanupProviderConfig, NetworkPolicy
from voxflow.text.contracts import CleanupPolicy, WritingSettings


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


def settings(
    *, policy=NetworkPolicy.REMOTE_EXPLICIT, disclosure=True, timeout=30.0
) -> WritingSettings:
    return WritingSettings(
        cleanup_policy=CleanupPolicy.PROVIDER,
        cleanup_provider_id="remote-cleanup",
        cleanup_network_policy=policy,
        cleanup_network_disclosure=disclosure,
        cleanup_timeout_seconds=timeout,
    )


def request(job_settings: WritingSettings | None = None) -> CleanupRequest:
    job_settings = job_settings or settings()
    return CleanupRequest(
        raw_text="private transcript token=do-not-leak",
        settings=job_settings,
        provider_id="remote-cleanup",
        timeout_seconds=job_settings.cleanup_timeout_seconds,
        endpoint="https://cleanup.example.test/v1/clean",
        credential_env_var="VOXFLOW_CLEANUP_TOKEN",
    )


def provider(transport=None) -> RemoteCleanupProvider:
    return RemoteCleanupProvider(
        CleanupProviderConfig(
            provider_id="remote-cleanup",
            endpoint="https://cleanup.example.test/v1/clean",
            credential_env_var="VOXFLOW_CLEANUP_TOKEN",
        ),
        transport=transport or FakeTransport(CleanupResponse(200, {"text": "cleaned"})),
    )


def test_cleanup_request_safe_metadata_omits_text_endpoint_and_credentials():
    safe = request().to_safe_dict()

    assert "private transcript" not in str(safe)
    assert "cleanup.example.test" not in str(safe)
    assert "VOXFLOW_CLEANUP_TOKEN" not in str(safe)
    assert safe["endpoint_classification"] == "https"
    assert safe["settings"]["cleanup_network_policy"] == "remote_explicit"


def test_remote_cleanup_success_uses_one_injected_transport_call():
    transport = FakeTransport(CleanupResponse(200, {"text": "cleaned"}))

    result = asyncio.run(provider(transport).cleanup(request(), CancellationToken()))

    assert result == "cleaned"
    assert len(transport.calls) == 1
    safe = transport.calls[0][0].to_safe_dict()
    assert "private transcript" not in str(safe)


def test_remote_cleanup_transport_timeout_is_bounded_by_job_timeout():
    transport = FakeTransport(CleanupResponse(200, {"text": "cleaned"}))
    remote = RemoteCleanupProvider(
        CleanupProviderConfig(
            provider_id="remote-cleanup",
            endpoint="https://cleanup.example.test/v1/clean",
            transport_timeout_seconds=9.0,
        ),
        transport=transport,
    )
    job_settings = settings(timeout=2.0)

    asyncio.run(remote.cleanup(request(job_settings), CancellationToken()))

    transport_request, timeout_seconds, _cancellation = transport.calls[0]
    assert timeout_seconds == 2.0
    assert transport_request.timeout_seconds == 2.0


def test_remote_cleanup_rejects_local_only_policy_before_transport():
    transport = FakeTransport(CleanupResponse(200, {"text": "must not run"}))

    with pytest.raises(CleanupProviderError) as raised:
        asyncio.run(
            provider(transport).cleanup(
                request(settings(policy=NetworkPolicy.LOCAL_ONLY, disclosure=False)),
                CancellationToken(),
            )
        )

    assert raised.value.code == "network_policy_rejected"
    assert transport.calls == []


def test_remote_cleanup_requires_network_disclosure():
    transport = FakeTransport(CleanupResponse(200, {"text": "must not run"}))

    with pytest.raises(CleanupProviderError) as raised:
        asyncio.run(
            provider(transport).cleanup(
                request(settings(disclosure=False)),
                CancellationToken(),
            )
        )

    assert raised.value.code == "network_policy_rejected"
    assert transport.calls == []


def test_pre_cancelled_cleanup_never_reaches_transport():
    transport = FakeTransport(CleanupResponse(200, {"text": "must not run"}))
    cancellation = CancellationToken()
    cancellation.cancel()

    with pytest.raises(CleanupCancellationError):
        asyncio.run(provider(transport).cleanup(request(), cancellation))

    assert transport.calls == []


def test_transport_failure_is_typed_and_redacted():
    transport = FakeTransport(
        failure=CleanupProviderError("secret-upstream-code", "Bearer secret response body")
    )

    with pytest.raises(CleanupProviderError) as raised:
        asyncio.run(provider(transport).cleanup(request(), CancellationToken()))

    assert raised.value.code == "remote_transport_failed"
    assert "secret" not in str(raised.value).lower()
    assert "response body" not in str(raised.value).lower()


def test_network_disabled_transport_fails_before_socket_work(monkeypatch):
    monkeypatch.setenv("NETWORK_DISABLED", "1")
    remote = RemoteCleanupProvider(
        CleanupProviderConfig(
            provider_id="remote-cleanup",
            endpoint="https://cleanup.example.test/v1/clean",
        ),
        transport=UrllibCleanupTransport(),
    )

    with pytest.raises(CleanupProviderError) as raised:
        asyncio.run(remote.cleanup(request(), CancellationToken()))

    assert raised.value.code == "network_disabled"


def test_cleanup_config_safe_metadata_has_only_coarse_endpoint_classification():
    config = CleanupProviderConfig(
        endpoint="http://192.168.1.20:8080/v1/clean",
        credential_env_var="VOXFLOW_CLEANUP_TOKEN",
    )

    safe = config.to_safe_dict()
    assert safe["endpoint_classification"] == "lan"
    assert "192.168.1.20" not in str(safe)
    assert "VOXFLOW_CLEANUP_TOKEN" not in str(safe)
