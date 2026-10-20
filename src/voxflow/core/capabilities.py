"""Capability result contracts shared by platform adapters and diagnostics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class CapabilityStatus(StrEnum):
    """The actionable result of probing one platform capability."""

    AVAILABLE = "available"
    NEEDS_USER_ACTION = "needs_user_action"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


CAPABILITY_STATUS_ORDER: Final[tuple[CapabilityStatus, ...]] = (
    CapabilityStatus.AVAILABLE,
    CapabilityStatus.NEEDS_USER_ACTION,
    CapabilityStatus.UNAVAILABLE,
    CapabilityStatus.UNSUPPORTED,
)


def status_rank(status: CapabilityStatus | str) -> int:
    """Return the stable diagnostic ordering for a capability status."""

    return CAPABILITY_STATUS_ORDER.index(CapabilityStatus(status))


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """A stable capability ID, probe status, and actionable user reason."""

    id: str
    status: CapabilityStatus
    reason: str

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("capability id must not be blank")
        if not self.reason.strip():
            raise ValueError("capability reason must not be blank")
        object.__setattr__(self, "status", CapabilityStatus(self.status))

    def to_dict(self) -> dict[str, str]:
        """Serialize stable field names for CLI and GTK diagnostics."""

        return {
            "id": self.id,
            "status": self.status.value,
            "reason": self.reason,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


Capability = CapabilityRecord
