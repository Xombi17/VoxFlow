import asyncio
import json

import pytest

from voxflow.core.capabilities import CapabilityStatus
from voxflow.core.events import AudioEventType
from voxflow.core.events import AudioEvent
from voxflow.platform.audio import (
    AudioBackendError,
    AudioCapture,
    AudioCaptureConfig,
    AudioCaptureError,
    AudioCaptureState,
    AudioDeviceDiscovery,
    AudioErrorCode,
    SoundDeviceBackend,
)
from voxflow.platform.audio_devices import (
    AudioDevice,
    AudioFormat,
    OpenedAudioStream,
)


FORMAT = AudioFormat(sample_rate=48_000, channels=1)


class FakeStream:
    def __init__(
        self,
        *,
        start_error=None,
        stop_error=None,
        close_error=None,
        close_errors=None,
    ):
        self.start_error = start_error
        self.stop_error = stop_error
        self.close_error = close_error
        self.close_errors = list(close_errors or ())
        self.calls = []
        self.active = False
        self.closed = False
        self.frame_callback = None

    def register_frame_callback(self, callback):
        self.frame_callback = callback

    def emit(self, data, frame_count):
        assert self.frame_callback is not None
        self.frame_callback(bytes(data), frame_count)

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
        if self.close_errors:
            raise self.close_errors.pop(0)
        if self.close_error:
            raise self.close_error
        self.active = False
        self.closed = True


class FakeAudioBackend:
    def __init__(
        self,
        *,
        devices=None,
        enumerate_error=None,
        open_error=None,
        opened_format=None,
    ):
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
        self.opened_format = opened_format
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
            format=self.opened_format or requested_format or device.supported_formats[0],
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


def test_close_failure_retains_handle_until_a_retry_succeeds() -> None:
    async def scenario():
        backend = FakeAudioBackend()
        backend.stream = FakeStream(
            close_errors=[
                AudioBackendError(
                    AudioErrorCode.BACKEND_UNAVAILABLE,
                    "fake close failure",
                )
            ]
        )
        events = []
        capture = AudioCapture(backend, listener=events.append)
        await capture.open()
        first_failure = await capture.close()
        second_failure = await capture.close()
        return backend, capture, events, first_failure, second_failure

    backend, capture, events, first_failure, second_failure = asyncio.run(scenario())

    assert first_failure is not None
    assert first_failure.code is AudioErrorCode.BACKEND_UNAVAILABLE
    assert second_failure is None
    assert backend.stream.calls == ["close", "close"]
    assert backend.stream.closed
    assert capture.state is AudioCaptureState.CLOSED
    assert not capture.has_active_stream
    assert [event.type for event in events] == [
        AudioEventType.CAPTURE_OPENED,
        AudioEventType.CAPTURE_FAILED,
        AudioEventType.CAPTURE_CLOSED,
    ]


def test_open_validation_failure_closes_the_opened_stream() -> None:
    async def scenario():
        backend = FakeAudioBackend(opened_format=AudioFormat(16_000, 1))
        capture = AudioCapture(backend, requested_format=FORMAT)
        with pytest.raises(AudioCaptureError) as raised:
            await capture.open()
        return backend, capture, raised.value

    backend, capture, error = asyncio.run(scenario())

    assert error.failure.code is AudioErrorCode.UNSUPPORTED_FORMAT
    assert backend.stream.closed
    assert not capture.has_active_stream
    assert capture.state is AudioCaptureState.FAILED


def test_open_cleanup_failure_retains_handle_for_retry() -> None:
    async def scenario():
        backend = FakeAudioBackend(opened_format=AudioFormat(16_000, 1))
        backend.stream = FakeStream(
            close_errors=[
                AudioBackendError(
                    AudioErrorCode.BACKEND_UNAVAILABLE,
                    "validation cleanup failed",
                )
            ]
        )
        capture = AudioCapture(backend, requested_format=FORMAT)
        with pytest.raises(AudioCaptureError) as raised:
            await capture.open()
        retry_failure = await capture.close()
        return capture, backend.stream, raised.value, retry_failure

    capture, stream, error, retry_failure = asyncio.run(scenario())

    assert error.failure.code is AudioErrorCode.BACKEND_UNAVAILABLE
    assert retry_failure is None
    assert stream.calls == ["close", "close"]
    assert stream.closed
    assert capture.state is AudioCaptureState.CLOSED
    assert not capture.has_active_stream


def test_start_failure_closes_handle_and_reopen_does_not_retain_it() -> None:
    async def scenario():
        backend = FakeAudioBackend()
        failed_stream = FakeStream(
            start_error=AudioBackendError(
                AudioErrorCode.BACKEND_UNAVAILABLE,
                "start failed",
            )
        )
        backend.stream = failed_stream
        capture = AudioCapture(backend)
        await capture.open()
        with pytest.raises(AudioCaptureError):
            await capture.start()
        replacement_stream = FakeStream()
        backend.stream = replacement_stream
        await capture.open()
        return capture, failed_stream, replacement_stream

    capture, failed_stream, replacement_stream = asyncio.run(scenario())

    assert failed_stream.closed
    assert capture.has_active_stream
    assert capture.state is AudioCaptureState.OPEN
    assert capture._stream is replacement_stream


def test_start_cleanup_failure_retains_handle_for_retry() -> None:
    async def scenario():
        backend = FakeAudioBackend()
        failed_stream = FakeStream(
            start_error=AudioBackendError(
                AudioErrorCode.BACKEND_UNAVAILABLE,
                "start failed",
            ),
            close_errors=[
                AudioBackendError(
                    AudioErrorCode.BACKEND_UNAVAILABLE,
                    "start cleanup failed",
                )
            ],
        )
        backend.stream = failed_stream
        capture = AudioCapture(backend)
        await capture.open()
        with pytest.raises(AudioCaptureError) as raised:
            await capture.start()
        retry_failure = await capture.close()
        return capture, failed_stream, raised.value, retry_failure

    capture, stream, error, retry_failure = asyncio.run(scenario())

    assert error.failure.code is AudioErrorCode.BACKEND_UNAVAILABLE
    assert retry_failure is None
    assert stream.calls == ["start", "close", "close"]
    assert stream.closed
    assert capture.state is AudioCaptureState.CLOSED
    assert not capture.has_active_stream


class FakeSoundDeviceStream:
    def __init__(self, callback=None):
        self.callback = callback

    def start(self):
        return None

    def stop(self):
        return None

    def close(self):
        return None


class FakeSoundDeviceModule:
    class default:
        device = (0, -1)

    def __init__(self):
        self.input_stream_arguments = []

    def query_devices(self):
        return [
            {
                "name": "Stereo desk microphone",
                "max_input_channels": 2,
                "default_samplerate": 48_000,
            }
        ]

    def InputStream(self, **arguments):
        self.input_stream_arguments.append(arguments)
        return FakeSoundDeviceStream(arguments["callback"])


def test_sounddevice_backend_uses_max_input_channels_and_requested_format() -> None:
    async def scenario():
        sounddevice = FakeSoundDeviceModule()
        backend = SoundDeviceBackend()
        backend._sounddevice = sounddevice
        devices = await backend.enumerate_devices()
        opened_default = await backend.open("0")
        opened_requested = await backend.open("0", AudioFormat(16_000, 1))
        return devices, opened_default, opened_requested, sounddevice

    devices, opened_default, opened_requested, sounddevice = asyncio.run(scenario())

    assert devices[0].supported_formats == (AudioFormat(48_000, 2),)
    assert opened_default.format == AudioFormat(48_000, 2)
    assert opened_requested.format == AudioFormat(16_000, 1)
    assert [arguments["channels"] for arguments in sounddevice.input_stream_arguments] == [
        2,
        1,
    ]
    assert all("callback" in arguments for arguments in sounddevice.input_stream_arguments)


def test_frame_callback_handoff_copies_backend_memory_and_keeps_format() -> None:
    async def scenario():
        sounddevice = FakeSoundDeviceModule()
        backend = SoundDeviceBackend()
        backend._sounddevice = sounddevice
        opened = await backend.open("0", FORMAT)
        received = []
        opened.stream.register_frame_callback(
            lambda data, frame_count: received.append((data, frame_count))
        )
        source = bytearray(b"\x01\x00\x02\x00")
        sounddevice.input_stream_arguments[-1]["callback"](source, 2, None, None)
        source[:] = b"\x09\x09\x09\x09"
        second_source = bytearray(b"\x03\x00\x04\x00")
        sounddevice.input_stream_arguments[-1]["callback"](second_source, 2, None, None)
        second_source[:] = b"\x08\x08\x08\x08"
        return opened, received

    opened, received = asyncio.run(scenario())

    assert opened.format == FORMAT
    assert received == [
        (b"\x01\x00\x02\x00", 2),
        (b"\x03\x00\x04\x00", 2),
    ]


def test_audio_event_serialization_redacts_absolute_device_paths() -> None:
    serialized = json.dumps(
        AudioEvent(
            type=AudioEventType.CAPTURE_FAILED,
            sequence=1,
            device_id="/home/example/private-microphone",
            error_code="backend_unavailable",
            error_reason="safe reason",
        ).to_dict()
    )

    assert "/home/" not in serialized
    assert "private-microphone" not in serialized
    assert "samples" not in serialized
