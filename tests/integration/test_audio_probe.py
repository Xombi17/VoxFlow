import asyncio
import json

from voxflow.__main__ import main
from voxflow.platform.audio import AudioBackendError, AudioErrorCode, probe_audio
from voxflow.platform.audio_devices import AudioDevice, AudioFormat, OpenedAudioStream


FORMAT = AudioFormat(sample_rate=48_000, channels=1)


class FakeProbeStream:
    def __init__(self, *, close_error=None):
        self.closed = False
        self.started = False
        self.close_error = close_error

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    async def close(self):
        if self.close_error:
            raise self.close_error
        self.closed = True


class FakeProbeBackend:
    def __init__(self, *, unavailable=False, close_error=None):
        self.device = AudioDevice(
            id="fake-mic",
            name="Fake microphone",
            is_default=True,
            supported_formats=(FORMAT,),
        )
        self.stream = FakeProbeStream(close_error=close_error)
        self.unavailable = unavailable

    async def enumerate_devices(self):
        if self.unavailable:
            raise AudioBackendError(
                AudioErrorCode.BACKEND_UNAVAILABLE,
                "fake backend unavailable",
            )
        return (self.device,)

    async def open(self, device_id, requested_format=None):
        assert device_id == self.device.id
        return OpenedAudioStream(
            device=self.device,
            format=requested_format or FORMAT,
            stream=self.stream,
        )


def test_probe_opens_and_closes_without_starting_or_emitting_samples() -> None:
    backend = FakeProbeBackend()

    report = asyncio.run(probe_audio(backend))

    assert report["capability"]["status"] == "available"
    assert report["negotiated_format"] == {"channels": 1, "sample_rate": 48_000}
    assert report["capture"] == {"active": False, "closed": True, "started": False}
    assert not backend.stream.started
    assert backend.stream.closed
    assert "Fake microphone" not in json.dumps(report)
    assert "fake-mic" not in json.dumps(report)
    assert report["devices"][0]["id"] == "<device-0>"
    assert report["devices"][0]["name"] == "<redacted-device-name>"
    assert "samples" not in json.dumps(report)


def test_probe_reports_unavailable_backend_as_safe_json() -> None:
    backend = FakeProbeBackend(unavailable=True)

    report = asyncio.run(probe_audio(backend))

    assert report["capability"]["id"] == "audio.input"
    assert report["capability"]["status"] == "unsupported"
    assert report["failure"]["code"] == "backend_unavailable"
    assert report["capture"]["closed"] is True


def test_probe_reports_failed_cleanup_as_unavailable_and_active() -> None:
    backend = FakeProbeBackend(
        close_error=AudioBackendError(
            AudioErrorCode.BACKEND_UNAVAILABLE,
            "fake stream close failed",
        )
    )

    report = asyncio.run(probe_audio(backend))

    assert report["capability"]["status"] == "unsupported"
    assert report["failure"]["code"] == "backend_unavailable"
    assert report["capture"] == {"active": True, "closed": False, "started": False}
    assert not backend.stream.closed


def test_main_includes_audio_only_when_explicitly_requested(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "voxflow.__main__.audio_platform_diagnostic",
        lambda: {
            "probe": "audio",
            "capability": {
                "id": "audio.input",
                "status": "available",
                "reason": "fake input is ready",
            },
            "devices": [],
            "default_device_id": None,
            "selected_device_id": None,
            "negotiated_format": None,
            "failure": None,
            "capture": {"started": False, "closed": True, "active": False},
        },
    )

    assert main(["--json"]) == 0
    default_output = json.loads(capsys.readouterr().out)
    assert "platform" not in default_output

    assert main(["--json", "--probe-audio"]) == 0
    probed_output = json.loads(capsys.readouterr().out)
    assert probed_output["platform"]["audio"]["probe"] == "audio"
    assert probed_output["capabilities"] == [
        {
            "id": "audio.input",
            "reason": "fake input is ready",
            "status": "available",
        }
    ]
