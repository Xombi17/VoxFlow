import pytest
from pydantic import ValidationError

from voxflow.providers.asr import NetworkPolicy, ProviderKind
from voxflow.providers.config import ProviderSelectionSnapshot, RemoteProviderConfig


def test_default_selection_is_local_only_and_safe() -> None:
    selection = ProviderSelectionSnapshot()

    assert selection.provider_kind is ProviderKind.LOCAL
    assert selection.network_policy is NetworkPolicy.LOCAL_ONLY
    assert selection.provider_id == "local-whisper"
    assert selection.model_id == "local-default"
    assert selection.endpoint is None
    assert selection.to_dict()["endpoint_classification"] is None
    assert "/" not in str(selection.to_safe_diagnostic())


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://asr.example.test/transcribe",
        "http:///missing-host",
        "https://user:password@example.test/asr",
        "https://example.test:99999/asr",
        "https://example.test/asr#fragment",
        "   ",
    ],
)
def test_remote_endpoint_validation_rejects_unsafe_values(endpoint: str) -> None:
    with pytest.raises(ValidationError):
        RemoteProviderConfig(model_id="model", endpoint=endpoint)


def test_remote_config_retains_only_credential_reference_and_safe_identity() -> None:
    config = RemoteProviderConfig(
        model_id="remote-model",
        endpoint="https://asr.example.test/v1/transcribe",
        credential_env_var="VOXFLOW_ASR_TOKEN",
    )

    assert config.credential_env_var == "VOXFLOW_ASR_TOKEN"
    assert config.endpoint_classification == "https"
    safe = config.to_safe_dict()
    assert "endpoint" not in safe
    assert "credential" not in str(safe).lower()
    assert "VOXFLOW_ASR_TOKEN" not in str(safe)


def test_remote_selection_requires_explicit_policy_at_dispatch() -> None:
    config = RemoteProviderConfig(model_id="remote-model", endpoint="http://localhost:8080/asr")
    local_only = config.to_selection(network_policy=NetworkPolicy.LOCAL_ONLY)

    assert local_only.provider_kind is ProviderKind.REMOTE
    assert not local_only.dispatch_allowed
    assert local_only.network_policy is NetworkPolicy.LOCAL_ONLY


def test_remote_selection_is_frozen_and_has_no_credential_value() -> None:
    config = RemoteProviderConfig(
        model_id="remote-model",
        endpoint="http://192.168.1.20:8080/asr",
        credential_env_var="VOXFLOW_ASR_TOKEN",
    )
    selection = config.to_selection()

    with pytest.raises(ValidationError):
        selection.model_id = "changed"
    assert "secret-value" not in str(selection.to_dict())
    assert selection.to_safe_diagnostic()["endpoint_classification"] == "lan"
