"""libei keyboard sender over ctypes, plus keymap-driven keycode lookup.

The RemoteDesktop portal hands us an EIS socket (ConnectToEIS); we are an
``ei`` *sender* that emits one Ctrl+V chord.  Keycodes are resolved from the
compositor-supplied keymap via libxkbcommon, never hardcoded.  Libraries are
injectable so tests never touch the live ones.
"""

from __future__ import annotations

import ctypes
import os
import select
import time
from collections.abc import Callable
from typing import Any

MAX_KEYMAP_BYTES = 1 << 20  # T-02.1-08: hard cap on the keymap read
CONNECT_TIMEOUT_S = 2.0

# libei enum values (libeis/libei.h)
EI_EVENT_CONNECT = 1
EI_EVENT_DISCONNECT = 2
EI_EVENT_SEAT_ADDED = 3
EI_EVENT_DEVICE_ADDED = 5
EI_EVENT_DEVICE_REMOVED = 6
EI_EVENT_DEVICE_RESUMED = 8
EI_DEVICE_CAP_KEYBOARD = 1 << 2

XKB_KEYSYM_NO_FLAGS = 0
XKB_KEYMAP_FORMAT_TEXT_V1 = 1
_EVDEV_OFFSET = 8  # xkb keycode = evdev code + 8


class EisError(RuntimeError):
    """The EIS/keymap path failed (maps to a `failed` insert result)."""


class Unavailable(EisError):
    """libei or libxkbcommon could not be loaded (maps to `unavailable`)."""


class KeymapTooLarge(EisError):
    """The compositor keymap exceeded MAX_KEYMAP_BYTES."""


def load_libei() -> Any:
    try:
        lib = ctypes.CDLL("libei.so.1")
    except OSError as exc:
        raise Unavailable("libei.so.1 is not installed (apt install libei1)") from exc
    vp, c_int, c_u32, c_u64 = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_uint64
    sig = {
        "ei_new_sender": (vp, [vp]),
        "ei_configure_name": (None, [vp, ctypes.c_char_p]),
        "ei_setup_backend_fd": (c_int, [vp, c_int]),
        "ei_get_fd": (c_int, [vp]),
        "ei_dispatch": (None, [vp]),
        "ei_get_event": (vp, [vp]),
        "ei_event_get_type": (c_int, [vp]),
        "ei_event_get_seat": (vp, [vp]),
        "ei_event_get_device": (vp, [vp]),
        "ei_event_unref": (vp, [vp]),
        "ei_device_ref": (vp, [vp]),
        "ei_device_has_capability": (ctypes.c_bool, [vp, c_int]),
        "ei_device_keyboard_get_keymap": (vp, [vp]),
        "ei_keymap_get_fd": (c_int, [vp]),
        "ei_keymap_get_size": (ctypes.c_size_t, [vp]),
        "ei_device_start_emulating": (None, [vp, c_u32]),
        "ei_device_stop_emulating": (None, [vp]),
        "ei_device_keyboard_key": (None, [vp, c_u32, ctypes.c_bool]),
        "ei_device_frame": (None, [vp, c_u64]),
        "ei_now": (c_u64, [vp]),
        "ei_unref": (vp, [vp]),
    }
    try:
        for name, (res, args) in sig.items():
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = res, args
    except AttributeError as exc:
        raise Unavailable(f"libei is missing {exc}") from exc
    return lib  # ei_seat_bind_capabilities is variadic: deliberately untyped


def read_keymap(fd: int, size: int) -> str:
    """Read the keymap fd, never more than MAX_KEYMAP_BYTES."""

    if size > MAX_KEYMAP_BYTES:
        raise KeymapTooLarge(f"keymap is {size} bytes (cap {MAX_KEYMAP_BYTES})")
    chunks, total = [], 0
    while total <= MAX_KEYMAP_BYTES:
        chunk = os.pread(fd, min(65536, MAX_KEYMAP_BYTES + 1 - total), total)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total > MAX_KEYMAP_BYTES:
        raise KeymapTooLarge(f"keymap exceeds {MAX_KEYMAP_BYTES} bytes")
    return b"".join(chunks).rstrip(b"\0").decode("utf-8", "replace")


class LibXkbcommon:
    """ctypes libxkbcommon: find the keycode that yields a keysym."""

    def __init__(self, lib: Any | None = None) -> None:
        if lib is None:
            try:
                lib = ctypes.CDLL("libxkbcommon.so.0")
            except OSError as exc:
                raise Unavailable("libxkbcommon.so.0 is not installed") from exc
        vp, u32, c_int = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int
        for name, res, args in (
            ("xkb_context_new", vp, [c_int]),
            ("xkb_context_unref", None, [vp]),
            ("xkb_keymap_new_from_string", vp, [vp, ctypes.c_char_p, c_int, c_int]),
            ("xkb_keymap_unref", None, [vp]),
            ("xkb_keymap_min_keycode", u32, [vp]),
            ("xkb_keymap_max_keycode", u32, [vp]),
            ("xkb_keymap_num_layouts_for_key", u32, [vp, u32]),
            ("xkb_keymap_key_get_syms_by_level", c_int,
             [vp, u32, u32, u32, ctypes.POINTER(ctypes.POINTER(u32))]),
            ("xkb_keysym_from_name", u32, [ctypes.c_char_p, c_int]),
        ):
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = res, args
        self._lib = lib

    def find_keycodes(self, keymap_text: str, names: tuple[str, ...]) -> dict[str, int]:
        """Map each keysym name to an evdev keycode (xkb keycode - 8)."""

        lib = self._lib
        ctx = lib.xkb_context_new(0)
        if not ctx:
            raise EisError("xkb_context_new failed")
        try:
            km = lib.xkb_keymap_new_from_string(
                ctx, keymap_text.encode(), XKB_KEYMAP_FORMAT_TEXT_V1, 0
            )
            if not km:
                raise EisError("compositor keymap could not be compiled")
            try:
                wanted = {lib.xkb_keysym_from_name(n.encode(), 0): n for n in names}
                found: dict[str, int] = {}
                out = ctypes.POINTER(ctypes.c_uint32)()
                # ponytail: first layout containing the keysym wins; add group
                # state handling if users report a non-Latin primary layout.
                for key in range(lib.xkb_keymap_min_keycode(km), lib.xkb_keymap_max_keycode(km) + 1):
                    for layout in range(lib.xkb_keymap_num_layouts_for_key(km, key)):
                        n = lib.xkb_keymap_key_get_syms_by_level(km, key, layout, 0, ctypes.byref(out))
                        for i in range(n if n > 0 else 0):
                            name = wanted.get(out[i])
                            if name and name not in found and key >= _EVDEV_OFFSET:
                                found[name] = key - _EVDEV_OFFSET
                return found
            finally:
                lib.xkb_keymap_unref(km)
        finally:
            lib.xkb_context_unref(ctx)


def resolve_keycodes(keymap_text: str, xkb: Any | None = None) -> tuple[int, int]:
    """Return evdev (ctrl, v) keycodes from the compositor keymap."""

    xkb = xkb or LibXkbcommon()
    found = xkb.find_keycodes(keymap_text, ("Control_L", "v"))
    try:
        return found["Control_L"], found["v"]
    except KeyError as exc:
        raise EisError(f"keymap has no key for {exc}") from exc


def _poll(fd: int, timeout_s: float) -> None:
    select.select([fd], [], [], timeout_s)


class EisKeyboard:
    """Connect to an EIS fd, find the keyboard, emit chords."""

    def __init__(
        self,
        lib: Any | None = None,
        *,
        poll: Callable[[int, float], object] = _poll,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lib = lib
        self._poll = poll
        self._clock = clock
        self._ei: Any = None
        self._fd = -1
        self._device: Any = None
        self._ready = False
        self._keymap: str | None = None
        self._sequence = 0

    def connect(self, fd: int) -> None:
        lib = self._lib = self._lib or load_libei()
        ei = lib.ei_new_sender(None)
        if not ei:
            raise EisError("ei_new_sender failed")
        self._ei = ei
        lib.ei_configure_name(ei, b"voxflow")
        if lib.ei_setup_backend_fd(ei, fd) != 0:
            raise EisError("ei_setup_backend_fd failed")
        self._fd = lib.ei_get_fd(ei)
        deadline = self._clock() + CONNECT_TIMEOUT_S
        while not (self._ready and self._keymap is not None):
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise EisError("no keyboard device from the compositor")
            self._pump(remaining)

    def _pump(self, timeout_s: float) -> None:
        lib = self._lib
        self._poll(self._fd, timeout_s)
        lib.ei_dispatch(self._ei)
        while (event := lib.ei_get_event(self._ei)):
            try:
                self._handle(event)
            finally:
                lib.ei_event_unref(event)

    def _handle(self, event: Any) -> None:
        lib = self._lib
        kind = lib.ei_event_get_type(event)
        if kind == EI_EVENT_DISCONNECT:
            raise EisError("EIS connection closed by the compositor")
        if kind == EI_EVENT_SEAT_ADDED:
            # variadic, NULL-terminated: explicit ctypes types, no argtypes
            lib.ei_seat_bind_capabilities(
                ctypes.c_void_p(lib.ei_event_get_seat(event)),
                ctypes.c_uint(EI_DEVICE_CAP_KEYBOARD),
                ctypes.c_void_p(None),
            )
        elif kind == EI_EVENT_DEVICE_ADDED:
            device = lib.ei_event_get_device(event)
            if self._device is None and lib.ei_device_has_capability(device, EI_DEVICE_CAP_KEYBOARD):
                self._device = lib.ei_device_ref(device)
                km = lib.ei_device_keyboard_get_keymap(device)
                if km:
                    self._keymap = read_keymap(lib.ei_keymap_get_fd(km), lib.ei_keymap_get_size(km))
        elif kind == EI_EVENT_DEVICE_RESUMED:
            if lib.ei_event_get_device(event) == self._device:
                self._ready = True
        elif kind == EI_EVENT_DEVICE_REMOVED:
            if lib.ei_event_get_device(event) == self._device:
                self._device, self._ready = None, False

    def keymap_text(self) -> str:
        if self._keymap is None:
            raise EisError("not connected")
        return self._keymap

    def send_paste_chord(self, keycodes: tuple[int, int]) -> None:
        if self._device is None or not self._ready:
            raise EisError("keyboard device is not ready")
        lib, dev = self._lib, self._device
        ctrl, v = keycodes
        self._sequence += 1
        lib.ei_device_start_emulating(dev, self._sequence)
        lib.ei_device_keyboard_key(dev, ctrl, True)
        lib.ei_device_keyboard_key(dev, v, True)
        lib.ei_device_frame(dev, lib.ei_now(self._ei))
        lib.ei_device_keyboard_key(dev, v, False)
        lib.ei_device_keyboard_key(dev, ctrl, False)
        lib.ei_device_frame(dev, lib.ei_now(self._ei))
        lib.ei_device_stop_emulating(dev)
        lib.ei_dispatch(self._ei)  # flush

    def close(self) -> None:
        if self._ei is not None and self._lib is not None:
            self._lib.ei_unref(self._ei)
        self._ei, self._device, self._ready = None, None, False
