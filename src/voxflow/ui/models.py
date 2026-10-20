"""Provider- and storage-neutral models consumed by settings views."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class SettingsView:
    settings: Mapping[str, object]
    capabilities: tuple[Mapping[str, object], ...] = ()
    microphones: tuple[Mapping[str, object], ...] = ()
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "settings": dict(self.settings),
            "capabilities": [dict(item) for item in self.capabilities],
            "microphones": [dict(item) for item in self.microphones],
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class SettingsCommandResult:
    ok: bool
    code: str
    message: str
    data: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "code": self.code,
            "message": self.message,
            "data": dict(self.data),
        }
