import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from voxflow.audio.artifacts import AudioArtifact
from voxflow.platform.audio_devices import AudioFormat
from voxflow.providers.asr import (
    ASRProviderError,
    AudioInput,
    CancellationToken,
    ProviderConfigSnapshot,
)
from voxflow.providers.local_whisper import (
    LocalModelProfile,
    LocalWhisperProvider,
    discover_installed_models,
    discover_local_model,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "audio" / "short_utterance.wav"
CHECKSUM = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
FORMAT = AudioFormat(48_000, 1)


def audio_input(config: ProviderConfigSnapshot) -> AudioInput:
    return AudioInput(
        path=FIXTURE,
        audio_sha256=CHECKSUM,
        source_format=FORMAT,
        duration_ms=10,
        config=config,
    )


def write_model(root: Path) -> None:
    root.mkdir()
    (root / "config.json").write_text('{"model_type":"whisper"}')
    (root / "model.bin").write_bytes(b"fake model weights")


class FakeWhisperModel:
    instances = []
    transcribe_kwargs = []

    def __init__(self, model_path, **kwargs):
        self.model_path = model_path
        self.kwargs = kwargs
        self.instances.append(self)

    def transcribe(self, _audio_path, **kwargs):
        self.transcribe_kwargs.append(kwargs)
        return (
            iter(
                [
                    SimpleNamespace(start=0.0, end=0.004, text=" hello"),
                    SimpleNamespace(start=0.004, end=0.010, text=" world"),
                ]
            ),
            SimpleNamespace(language="en", language_probability=0.96),
        )


class FailingWhisperModel(FakeWhisperModel):
    def transcribe(self, _audio_path, **_kwargs):
        raise RuntimeError("private native error")


def fake_module(model_class=FakeWhisperModel):
    return SimpleNamespace(WhisperModel=model_class)


def test_discovery_is_read_only_and_reports_missing_profile(tmp_path) -> None:
    missing = tmp_path / "missing-profile"

    result = discover_local_model(missing, model_id="tiny")

    assert not result.available
    assert result.error_code == "model_missing"
    assert not missing.exists()
    assert "root" not in result.to_dict()["profile"]
    assert str(tmp_path) not in json.dumps(result.to_dict())


def test_discovery_reports_checksum_and_changes_without_download(tmp_path) -> None:
    root = tmp_path / "tiny"
    write_model(root)

    first = discover_local_model(root, model_id="tiny")
    checksum = first.profile.checksum
    second = discover_local_model(root, model_id="tiny", expected_checksum=checksum)
    (root / "model.bin").write_bytes(b"changed fake model weights")
    changed = discover_local_model(root, model_id="tiny", expected_checksum=checksum)

    assert first.available and second.available
    assert checksum and len(checksum) == 64
    assert changed.error_code == "model_checksum_mismatch"
    assert first.profile.to_dict()["backend"] == "faster-whisper"
    assert not (root / "download.marker").exists()


def test_installed_model_discovery_only_lists_explicit_child_profiles(tmp_path) -> None:
    write_model(tmp_path / "tiny")
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()

    results = discover_installed_models(tmp_path)

    assert [result.profile.model_id for result in results] == ["incomplete", "tiny"]
    assert [result.available for result in results] == [False, True]


def test_provider_is_lazy_reuses_model_and_passes_explicit_settings(tmp_path) -> None:
    root = tmp_path / "tiny"
    write_model(root)
    profile = discover_local_model(root, model_id="tiny").profile
    config = ProviderConfigSnapshot(
        provider_id="local-whisper",
        model_id="tiny",
        language_hint="en",
        vad_filter=True,
        vad_min_silence_duration_ms=500,
        beam_size=7,
        device="cpu",
        thread_count=4,
    )
    provider = LocalWhisperProvider(
        profile,
        config=config,
        module_loader=lambda: fake_module(),
    )
    audio = audio_input(config)

    assert provider.model_load_count == 0
    first = asyncio.run(provider.transcribe(audio, CancellationToken()))
    second = asyncio.run(provider.transcribe(audio, CancellationToken()))

    assert first.text == "hello world"
    assert second.audio_sha256 == CHECKSUM
    assert provider.model_load_count == 1
    assert len(FakeWhisperModel.instances) >= 1
    model = FakeWhisperModel.instances[-1]
    assert model.kwargs == {
        "device": "cpu",
        "compute_type": "int8",
        "cpu_threads": 4,
        "num_workers": 1,
        "local_files_only": True,
    }
    assert FakeWhisperModel.transcribe_kwargs[-1] == {
        "beam_size": 7,
        "vad_filter": True,
        "condition_on_previous_text": False,
        "without_timestamps": False,
        "language": "en",
        "vad_parameters": {"min_silence_duration_ms": 500},
    }
    assert [(segment.start_ms, segment.end_ms) for segment in first.segments] == [
        (0, 4),
        (4, 10),
    ]


def test_provider_cancellation_happens_before_model_dispatch(tmp_path) -> None:
    root = tmp_path / "tiny"
    write_model(root)
    profile = discover_local_model(root, model_id="tiny").profile
    config = ProviderConfigSnapshot(provider_id="local-whisper", model_id="tiny")
    provider = LocalWhisperProvider(profile, config=config, module_loader=lambda: fake_module())
    token = CancellationToken()
    token.cancel()

    with pytest.raises(ASRProviderError) as raised:
        asyncio.run(provider.transcribe(audio_input(config), token))

    assert raised.value.code == "cancelled"
    assert provider.model_load_count == 0


def test_provider_model_failure_is_recoverable_and_does_not_expose_detail(tmp_path) -> None:
    root = tmp_path / "tiny"
    write_model(root)
    profile = discover_local_model(root, model_id="tiny").profile
    config = ProviderConfigSnapshot(provider_id="local-whisper", model_id="tiny")
    provider = LocalWhisperProvider(
        profile,
        config=config,
        module_loader=lambda: fake_module(FailingWhisperModel),
    )

    with pytest.raises(ASRProviderError) as raised:
        asyncio.run(provider.transcribe(audio_input(config), CancellationToken()))

    assert raised.value.code == "inference_failed"
    assert "private native error" not in str(raised.value)


def test_asr_fixture_manifest_has_required_categories_and_no_paths() -> None:
    manifest_path = Path(__file__).parents[1] / "fixtures" / "asr" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    categories = {entry["category"] for entry in manifest["fixtures"]}

    assert {
        "clean",
        "restarts_self_corrections",
        "names_numbers_technical_terms",
        "noisy_silent_boundary",
        "language_hints",
        "cancellation",
        "provider_failure",
    } <= categories
    assert all(entry["non_personal"] for entry in manifest["fixtures"])
    assert "/home/" not in json.dumps(manifest)
    assert "/tmp/" not in json.dumps(manifest)
