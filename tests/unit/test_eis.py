import ctypes.util
import os

import pytest

from voxflow.platform import eis
from voxflow.platform.eis import (
    EisError,
    EisKeyboard,
    KeymapTooLarge,
    Unavailable,
    read_keymap,
    resolve_keycodes,
)


class FakeXkb:
    """Keymap text is 'name=code' lines (xkb keycode, i.e. evdev + 8)."""

    def find_keycodes(self, text, names):
        table = dict(line.split("=") for line in text.split())
        return {n: int(table[n]) - 8 for n in names if n in table}


def test_keycodes_follow_keymap_not_constants() -> None:
    assert resolve_keycodes("Control_L=37 v=55", FakeXkb()) == (29, 47)
    assert resolve_keycodes("Control_L=37 v=60", FakeXkb()) == (29, 52)  # non-QWERTY v
    with pytest.raises(EisError):
        resolve_keycodes("Control_L=37", FakeXkb())


@pytest.mark.skipif(not ctypes.util.find_library("xkbcommon"), reason="no libxkbcommon")
def test_real_xkbcommon_resolves_from_generated_keymap() -> None:
    import ctypes

    lib = ctypes.CDLL("libxkbcommon.so.0")
    lib.xkb_context_new.restype = ctypes.c_void_p
    lib.xkb_keymap_new_from_names.restype = ctypes.c_void_p
    lib.xkb_keymap_new_from_names.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    lib.xkb_keymap_get_as_string.restype = ctypes.c_void_p
    lib.xkb_keymap_get_as_string.argtypes = [ctypes.c_void_p, ctypes.c_int]
    ctx = lib.xkb_context_new(0)
    km = lib.xkb_keymap_new_from_names(ctx, None, 0)
    if not km:
        pytest.skip("no xkb data on this host")
    text = ctypes.string_at(lib.xkb_keymap_get_as_string(km, 1)).decode()
    ctrl, v = resolve_keycodes(text)
    assert (ctrl, v) == (29, 47)  # default us layout


def test_keymap_read_is_bounded(tmp_path) -> None:
    p = tmp_path / "k"
    p.write_bytes(b"x" * 10 + b"\0")
    fd = os.open(p, os.O_RDONLY)
    assert read_keymap(fd, 11) == "x" * 10
    with pytest.raises(KeymapTooLarge):
        read_keymap(fd, eis.MAX_KEYMAP_BYTES + 1)
    os.close(fd)
    # lying size: file bigger than the cap is still refused after a capped read
    big = tmp_path / "big"
    big.write_bytes(b"y" * (eis.MAX_KEYMAP_BYTES + 5000))
    fd = os.open(big, os.O_RDONLY)
    reads = []
    real = os.pread
    os.pread = lambda f, n, o: reads.append(o + n) or real(f, n, o)
    try:
        with pytest.raises(KeymapTooLarge):
            read_keymap(fd, 10)
    finally:
        os.pread = real
        os.close(fd)
    assert max(reads) <= eis.MAX_KEYMAP_BYTES + 1


class FakeLib:
    def __init__(self, keymap_path, events=None, has_kb=True):
        self.log = []
        self.queue = list(events if events is not None else [
            ("seat", 1), ("added", 2), ("resumed", 2)])
        self.keymap_path = keymap_path
        self.fd = None
        self.has_kb = has_kb

    def ei_new_sender(self, _): return 100
    def ei_configure_name(self, ei, name): pass
    def ei_setup_backend_fd(self, ei, fd): return 0
    def ei_get_fd(self, ei): return -1
    def ei_dispatch(self, ei): self.log.append("dispatch")
    def ei_get_event(self, ei): return self.queue.pop(0) if self.queue else None
    def ei_event_get_type(self, ev):
        return {"seat": eis.EI_EVENT_SEAT_ADDED, "added": eis.EI_EVENT_DEVICE_ADDED,
                "resumed": eis.EI_EVENT_DEVICE_RESUMED, "bye": eis.EI_EVENT_DISCONNECT}[ev[0]]
    def ei_event_get_seat(self, ev): return ev[1]
    def ei_event_get_device(self, ev): return ev[1]
    def ei_event_unref(self, ev): pass
    def ei_seat_bind_capabilities(self, seat, cap, end): self.log.append("bind")
    def ei_device_has_capability(self, dev, cap): return self.has_kb
    def ei_device_ref(self, dev): return dev
    def ei_device_keyboard_get_keymap(self, dev): return 55
    def ei_keymap_get_fd(self, km):
        self.fd = os.open(self.keymap_path, os.O_RDONLY)
        return self.fd
    def ei_keymap_get_size(self, km): return os.path.getsize(self.keymap_path)
    def ei_device_start_emulating(self, dev, seq): self.log.append("start")
    def ei_device_stop_emulating(self, dev): self.log.append("stop")
    def ei_device_keyboard_key(self, dev, code, press): self.log.append(("key", code, press))
    def ei_device_frame(self, dev, t): self.log.append("frame")
    def ei_now(self, ei): return 1
    def ei_unref(self, ei): self.log.append("unref")


@pytest.fixture
def keymap(tmp_path):
    p = tmp_path / "km"
    p.write_text("Control_L=37 v=55")
    return p


def test_chord_event_order(keymap) -> None:
    lib = FakeLib(keymap)
    kb = EisKeyboard(lib, poll=lambda fd, t: None)
    kb.connect(3)
    assert kb.keymap_text() == "Control_L=37 v=55"
    ctrl, v = resolve_keycodes(kb.keymap_text(), FakeXkb())
    kb.send_paste_chord((ctrl, v))
    chord = [e for e in lib.log if e != "dispatch"]
    assert chord == [
        "bind", "start", ("key", 29, True), ("key", 47, True), "frame",
        ("key", 47, False), ("key", 29, False), "frame", "stop",
    ]
    kb.close()
    assert lib.log[-1] == "unref"


def test_no_keyboard_times_out_and_disconnect_errors(keymap) -> None:
    t = [0.0]

    def poll(fd, timeout):
        t[0] += 1.0

    lib = FakeLib(keymap, events=[("seat", 1)])
    with pytest.raises(EisError):
        EisKeyboard(lib, poll=poll, clock=lambda: t[0]).connect(3)
    lib = FakeLib(keymap, events=[("bye", 0)])
    with pytest.raises(EisError):
        EisKeyboard(lib, poll=poll, clock=lambda: t[0]).connect(3)


def test_chord_before_connect_is_error() -> None:
    with pytest.raises(EisError):
        EisKeyboard(object()).send_paste_chord((1, 2))


def test_load_failures_are_typed(monkeypatch) -> None:
    def boom(name):
        raise OSError(name)

    monkeypatch.setattr(eis.ctypes, "CDLL", boom)
    with pytest.raises(Unavailable):
        eis.load_libei()
    with pytest.raises(Unavailable):
        eis.LibXkbcommon()
    with pytest.raises(Unavailable):
        EisKeyboard().connect(3)
