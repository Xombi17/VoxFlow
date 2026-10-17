import asyncio
import hashlib
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from voxflow.platform.audio_devices import AudioFormat
from voxflow.providers import catalog
from voxflow.providers.asr import (
    ASRCancellationError,
    ASRProviderError,
    AudioInput,
    CancellationToken,
    ProviderConfigSnapshot,
    validate_provider_result,
)
from voxflow.providers.local_whisper import LocalWhisperProvider
from voxflow.providers.sherpa_parakeet import SherpaParakeetProvider

ENTRY = catalog.get_entry("parakeet-tdt-0.6b-v3")


def make_wav(path: Path, rate=48_000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"\x00\x01" * (rate // 10))
    return path


def audio_for(path, provider_id="sherpa-parakeet", rate=48_000):
    return AudioInput(
        path=path,
        audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_format=AudioFormat(rate, 1),
        duration_ms=100,
        config=ProviderConfigSnapshot(provider_id=provider_id, model_id=ENTRY.id),
    )


class FakeSherpa:
    loads = 0

    class Stream:
        result = SimpleNamespace(text="  hello there ", lang="en")

        def accept_waveform(self, rate, samples):
            assert rate == 16_000 and samples.dtype.name == "float32"

    class OfflineRecognizer:
        @classmethod
        def from_transducer(cls, **kw):
            FakeSherpa.loads += 1
            return cls()

        def create_stream(self):
            return FakeSherpa.Stream()

        def decode_stream(self, s):
            pass


def installed(tmp_path):
    d = tmp_path / ENTRY.id
    d.mkdir()
    for f in ENTRY.files:
        (d / f.path).write_bytes(b"x")
    return tmp_path


def test_transcribe_single_load_and_checksum(tmp_path):
    FakeSherpa.loads = 0
    p = SherpaParakeetProvider(ENTRY, installed(tmp_path) / ENTRY.id, module_loader=lambda: FakeSherpa)
    a = audio_for(make_wav(tmp_path / "a.wav"))
    for _ in range(2):
        r = asyncio.run(p.transcribe(a, CancellationToken()))
    validate_provider_result(r, a.audio_sha256)
    assert r.text == "hello there" and r.language == "en" and FakeSherpa.loads == 1
    assert p.capabilities.offline and not p.capabilities.network_required


def test_cancel_before_decode(tmp_path):
    p = SherpaParakeetProvider(ENTRY, installed(tmp_path) / ENTRY.id, module_loader=lambda: FakeSherpa)
    tok = CancellationToken()
    tok.cancel()
    with pytest.raises(ASRCancellationError):
        asyncio.run(p.transcribe(audio_for(make_wav(tmp_path / "a.wav")), tok))


def test_missing_module_and_model(tmp_path):
    def no_mod():
        raise ASRProviderError("backend_unavailable", "x")

    a = audio_for(make_wav(tmp_path / "a.wav"))
    p = SherpaParakeetProvider(ENTRY, installed(tmp_path) / ENTRY.id, module_loader=no_mod)
    with pytest.raises(ASRProviderError) as e:
        asyncio.run(p.transcribe(a, CancellationToken()))
    assert e.value.code == "backend_unavailable"
    p2 = SherpaParakeetProvider(ENTRY, tmp_path / "nowhere", module_loader=lambda: FakeSherpa)
    with pytest.raises(ASRProviderError) as e:
        asyncio.run(p2.transcribe(a, CancellationToken()))
    assert e.value.code == "model_incomplete"


def test_build_provider_factory(tmp_path):
    assert isinstance(catalog.build_provider(ENTRY, tmp_path), SherpaParakeetProvider)
    assert isinstance(catalog.build_provider(catalog.get_entry("small.en"), tmp_path), LocalWhisperProvider)
    bad = ENTRY.model_copy(update={"engine": "nope"})
    with pytest.raises(catalog.CatalogError):
        catalog.build_provider(bad, tmp_path)
