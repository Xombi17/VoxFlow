import asyncio

import pytest

from voxflow.core.capabilities import CapabilityStatus
from voxflow.core.events import AudioEventType
from voxflow.platform.audio import (
    AudioBackendError,
    AudioCapture,
    AudioCaptureConfig,
    AudioCaptureError,
    AudioCaptureState,
    AudioDeviceDiscovery,
    AudioErrorCode,
)
from voxflow.platform.audio_devices import (
    AudioDevice,
    AudioFormat,
    OpenedAudioStream,
)


FORMAT = AudioFormat(sample_rate=48_000, channels=1)


class FakeStream:
    def __init__(self, *, start_error=None, stop_error=None, close_error=None):
        self.start_error = start_error
        self.stop_error = stop_error
        self.close_error = close_error
        self.calls = []
        self.active = False
        self.closed = False

    async def start(self):
        self.calls.append("start")
        if self.start_error:
            raise self.start_error
        self.active = True

    async def stop(self):
        self.calls.append("stop")
        if self.stop_error:
            raise self.stop_error
        self.active = False

    async def close(self):
        self.calls.append("close")
        if self.close_error:
            raise self.close_error
        self.active = False
        self.closed = True


class FakeAudioBackend:
    def __init__(self, *, devices=None, enumerate_error=None, open_error=None):
        self.devices = devices if devices is not None else (
            AudioDevice(
                id="mic-1",
                name="Desk microphone",
                is_default=True,
                supported_formats=(FORMAT,),
            ),
        )
        self.enumerate_error = enumerate_error
        self.open_error = open_error
        self.stream = FakeStream()
        self.opened_ids = []

    async def enumerate_devices(self):
        if self.enumerate_error:
            raise self.enumerate_error
        return self.devices

    async def open(self, device_id, requested_format=None):
        self.opened_ids.append((device_id, requested_format))
        if self.open_error:
            raise self.open_error
        device = next(device for device in self.devices if device.id == device_id)
        return OpenedAudioStream(
            device=device,
            format=requested_format or device.supported_formats[0],
            stream=self.stream,
        )


def test_discovery_selects_default_or_requested_device_and_exposes_formats() -> None:
    async def scenario():
        backend = FakeAudioBackend(
            devices=(
                AudioDevice(
                    id="default-mic",
                    name="Default microphone",
                    is_default=True,
                    supported_formats=(FORMAT,),
                ),
                AudioDevice(
                    id="usb-mic",
                    name="USB microphone",
                    supported_formats=(AudioFormat(16_000, 2),),
                ),
            )
        )
        return (
            await AudioDeviceDiscovery(backend).discover(),
            await AudioDeviceDiscovery(backend).discover("usb-mic"),
        )

    default_result, selected_result = asyncio.run(scenario())

    assert default_result.capability.status is CapabilityStatus.AVAILABLE
    assert default_result.default_device_id == "default-mic"
    assert default_result.selected_device_id == "default-mic"
    assert selected_result.selected_device_id == "usb-mic"
    assert selected_result.devices[1].supported_formats[0].channels == 2


def test_no_device_is_a_stable_unsupported_capability() -> None:
    async def scenario():
        return await AudioDeviceDiscovery(FakeAudioBackend(devices=())).discover()

    result = asyncio.run(scenario())

    assert result.failure is not None
    assert result.failure.code is AudioErrorCode.NO_DEVICE
    assert result.capability.status is CapabilityStatus.UNSUPPORTED
    assert "microphone" in result.capability.reason.lower()


def test_permission_denial_is_actionable_and_typed() -> None:
    async def scenario():
        return await AudioDeviceDiscovery(
            FakeAudioBackend(
                enumerate_error=AudioBackendError(
                    AudioErrorCode.PERMISSION_DENIED,
                    "desktop denied microphone access",
                )
            )
        ).discover()

    result = asyncio.run(scenario())

    assert result.failure is not None
    assert result.failure.code is AudioErrorCode.PERMISSION_DENIED
    assert result.capability.status is CapabilityStatus.NEEDS_USER_ACTION
    assert "allow" in result.failure.reason.lower()


def test_muted_device_is_needs_user_action_before_open() -> None:
    async def scenario():
        backend = FakeAudioBackend(
            devices=(
                AudioDevice(
                    id="muted-mic",
                    name="Muted microphone",
                    is_default=True,
                    is_muted=True,
                    supported_formats=(FORMAT,),
                ),
            )
        )
        return await AudioDeviceDiscovery(backend).discover()

    result = asyncio.run(scenario())

    assert result.failure is not None
    assert result.failure.code is AudioErrorCode.MUTED
    assert result.capability.status is CapabilityStatus.NEEDS_USER_ACTION
    assert "unmute" in result.failure.reason.lower()


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        (AudioErrorCode.DISCONNECTED, CapabilityStatus.NEEDS_USER_ACTION),
        (AudioErrorCode.UNSUPPORTED_FORMAT, CapabilityStatus.UNSUPPORTED),
    ],
)
def test_open_failures_keep_stable_codes_and_reasons(code, expected_status) -> None:
    async def scenario():
        backend = FakeAudioBackend(
            open_error=AudioBackendError(code, f"fake {code.value} failure")
        )
        capture = AudioCapture(backend)
        with pytest.raises(AudioCaptureError) as raised:
            await capture.open()
        return capture, raised.value

    capture, error = asyncio.run(scenario())

    assert error.failure.code is code
    assert error.failure.status is expected_status
    assert capture.last_failure is error.failure
    assert capture.state is AudioCaptureState.FAILED
    assert error.failure.reason


def test_capture_lifecycle_emits_events_and_closes_fake_handle() -> None:
    async def scenario():
        backend = FakeAudioBackend()
        events = []
        capture = AudioCapture(
            backend,
            config=AudioCaptureConfig(
                requested_format=FORMAT,
                max_buffer_frames=4,
            ),
            listener=events.append,
        )
        opened = await capture.open()
        await capture.start()
        await capture.stop()
        close_failure = await capture.close()
        return backend, capture, opened, events, close_failure

    backend, capture, opened, events, close_failure = asyncio.run(scenario())

    assert close_failure is None
    assert opened.format == FORMAT
    assert backend.opened_ids == [("mic-1", FORMAT)]
    assert backend.stream.calls == ["start", "stop", "close"]
    assert backend.stream.closed
    assert not capture.has_active_stream
    assert capture.state is AudioCaptureState.CLOSED
    assert [event.type for event in events] == [
        AudioEventType.CAPTURE_OPENED,
        AudioEventType.CAPTURE_STARTED,
        AudioEventType.CAPTURE_STOPPED,
        AudioEventType.CAPTURE_CLOSED,
    ]
    assert events[0].sample_rate == 48_000
    assert events[0].channels == 1
    assert "samples" not in events[0].to_dict()


def test_close_attempts_cleanup_after_disconnect_during_stop() -> None:
    async def scenario():
        backend = FakeAudioBackend()
        backend.stream = FakeStream(
            stop_error=AudioBackendError(
                AudioErrorCode.DISCONNECTED,
                "fake microphone disconnected",
            )
        )
        events = []
        capture = AudioCapture(backend, listener=events.append)
        await capture.open()
        await capture.start()
        failure = await capture.close()
        return backend, capture, events, failure

    backend, capture, events, failure = asyncio.run(scenario())

    assert failure is not None
    assert failure.code is AudioErrorCode.DISCONNECTED
    assert backend.stream.calls == ["start", "stop", "close"]
    assert backend.stream.closed
    assert capture.state is AudioCaptureState.CLOSED
    assert not capture.has_active_stream
    assert events[-2].type is AudioEventType.CAPTURE_FAILED
    assert events[-1].type is AudioEventType.CAPTURE_CLOSED
