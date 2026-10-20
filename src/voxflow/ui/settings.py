"""Headless settings controller with a lazily imported GTK surface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from ..core.capabilities import CapabilityRecord
from ..core.diagnostics import build_diagnostics
from ..core.history import HistoryStore
from ..platform.audio_devices import AudioDevice
from ..settings import ApplicationSettingsStore
from .models import SettingsCommandResult, SettingsView


class SettingsErrorCode(StrEnum):
    INVALID = "invalid_settings"
    STORAGE = "settings_storage_failed"
    GTK_UNAVAILABLE = "gtk_unavailable"


class GtkUnavailable(RuntimeError):
    """Raised only when the optional native settings dependency is absent."""


class SettingsController:
    """Typed, provider-free settings seam used by JSON and GTK callers."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        audio_devices: Iterable[AudioDevice] = (),
        capabilities: Iterable[CapabilityRecord | Mapping[str, object]] = (),
    ) -> None:
        self.db_path = db_path
        self.store = ApplicationSettingsStore(db_path)
        self.history = HistoryStore(db_path)
        self.audio_devices = tuple(audio_devices)
        self.capabilities = tuple(capabilities)

    def snapshot(self):
        return self.store.load_application_settings()

    def microphone_options(self) -> tuple[AudioDevice, ...]:
        """Return the existing audio-device contract for a native UI caller."""

        return self.audio_devices

    def view(self) -> SettingsView:
        current = self.snapshot()
        writing = self.store.load_writing_settings()
        diagnostics = build_diagnostics(
            settings_store=self.store,
            history=self.history,
            settings=current,
            capabilities=self.capabilities,
        )
        safe_microphones = tuple(
            device.to_safe_dict() for device in self.audio_devices
        )
        return SettingsView(
            settings=current.to_safe_dict(writing=writing),
            capabilities=tuple(diagnostics["capabilities"]),
            microphones=safe_microphones,
            diagnostics=diagnostics,
        )

    load = view

    def update(self, **changes: object) -> SettingsCommandResult:
        try:
            microphone_id = changes.get("microphone_id")
            if microphone_id is not None and self.audio_devices:
                if microphone_id not in {device.id for device in self.audio_devices}:
                    raise ValueError("microphone_id is not an available device")
            saved = self.store.update_application_settings(**changes)
        except (TypeError, ValueError, KeyError):
            return SettingsCommandResult(
                False,
                SettingsErrorCode.INVALID.value,
                "settings update rejected",
            )
        except Exception:
            return SettingsCommandResult(
                False,
                SettingsErrorCode.STORAGE.value,
                "settings storage is unavailable",
            )
        return SettingsCommandResult(
            True,
            "ok",
            "settings updated",
            {"settings": saved.to_safe_dict(writing=self.store.load_writing_settings())},
        )

    def update_from_mapping(self, values: Mapping[str, object]) -> SettingsCommandResult:
        return self.update(**dict(values))


def _gtk_modules() -> tuple[Any, Any]:
    """Import GTK4/libadwaita only when a GUI action is explicitly requested."""

    try:
        import gi  # type: ignore[import-not-found]

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # type: ignore[import-not-found]
    except (ImportError, ModuleNotFoundError, ValueError) as exc:
        raise GtkUnavailable from exc
    return Gtk, Adw


def gtk_unavailable_result() -> SettingsCommandResult:
    return SettingsCommandResult(
        False,
        SettingsErrorCode.GTK_UNAVAILABLE.value,
        "GTK4/libadwaita is unavailable on this host",
        {
            "capability": {
                "id": "settings.gtk",
                "status": "unavailable",
                "reason": "Install GTK4 and libadwaita to open the native settings window.",
            }
        },
    )


def run_settings_window(controller: SettingsController, argv: Sequence[str] = ()) -> int:
    Gtk, Adw = _gtk_modules()
    application = Adw.Application(application_id="dev.voxflow.VoxFlow")

    def activate(_application: Any) -> None:
        window = Gtk.ApplicationWindow(application=application)
        window.set_title("VoxFlow Settings")
        window.set_default_size(680, 620)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        view = controller.view().to_dict()
        sections = (
            ("Input", "microphones and the configured microphone"),
            ("Writing and providers", "language, style, model, and cleanup policy"),
            ("Privacy and retention", "local-only policy and captured-audio retention"),
            ("Insertion", "paste chord, restore preference, and timing bounds"),
            ("Recovery", "redacted job counts and explicit recovery actions"),
            ("Diagnostics", "capabilities and stable error codes"),
        )
        for title, description in sections:
            label = Gtk.Label(label=f"{title}\n{description}", xalign=0)
            label.set_wrap(True)
            content.append(label)
        policy = Gtk.Label(
            label=(
                "Network policy: "
                f"{view['settings']['asr_network_policy']} / "
                f"cleanup {view['settings']['cleanup_network_policy']}"
            ),
            xalign=0,
        )
        content.append(policy)
        window.set_child(content)
        window.present()

    application.connect("activate", activate)
    return int(application.run(list(argv)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="voxflow settings")
    parser.add_argument("--db", "--db-path", dest="db", type=Path, default=None)
    parser.add_argument("--json", action="store_true", help="use the headless JSON surface")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="validate and persist one JSON-compatible setting",
    )
    return parser


def _updates(values: Sequence[str]) -> dict[str, object]:
    result: dict[str, object] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("settings updates must use FIELD=VALUE")
        name, raw = value.split("=", 1)
        if not name:
            raise ValueError("settings update field must not be blank")
        try:
            result[name] = json.loads(raw)
        except json.JSONDecodeError:
            result[name] = raw
    return result


def main(argv: Sequence[str] = ()) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(list(argv))
        controller = SettingsController(args.db)
        changes = _updates(args.set)
    except SystemExit as exc:
        if exc.code == 0:
            raise
        print(json.dumps(SettingsCommandResult(False, SettingsErrorCode.INVALID.value, "invalid settings arguments").to_dict()))
        return 2
    except ValueError:
        print(json.dumps(SettingsCommandResult(False, SettingsErrorCode.INVALID.value, "invalid settings arguments").to_dict()))
        return 2

    if changes:
        result = controller.update(**changes)
        if not result.ok:
            print(json.dumps(result.to_dict(), sort_keys=True))
            return 2
    if args.json:
        print(json.dumps(controller.view().to_dict(), ensure_ascii=False, sort_keys=True))
        return 0
    try:
        return run_settings_window(controller, argv)
    except GtkUnavailable:
        result = gtk_unavailable_result()
        print(json.dumps(result.to_dict(), sort_keys=True))
        return 4


__all__ = [
    "GtkUnavailable",
    "SettingsController",
    "SettingsErrorCode",
    "gtk_unavailable_result",
    "main",
    "run_settings_window",
]
