"""Allow-listed diagnostic projection for local settings and recovery state."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .. import APP_NAME, __version__
from ..settings import (
    ApplicationSettings,
    ApplicationSettingsStore,
    SCHEMA_VERSION,
)
from .capabilities import CapabilityRecord, CapabilityStatus
from .history import HistoryStore


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_REASON = re.compile(r"^[^\x00-\x1f\x7f]+$")


def _safe_reason(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_REASON.fullmatch(value):
        return "redacted"
    lowered = value.casefold()
    if any(marker in lowered for marker in ("/", "\\", "://", "token", "credential", "transcript")):
        return "redacted"
    return value


def _safe_capabilities(values: Iterable[CapabilityRecord | Mapping[str, object]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for value in values:
        if isinstance(value, CapabilityRecord):
            identifier, status, reason = value.id, value.status.value, value.reason
        elif isinstance(value, Mapping):
            identifier = value.get("id")
            status = value.get("status")
            reason = value.get("reason")
        else:
            continue
        safe_id = identifier if isinstance(identifier, str) and _SAFE_ID.fullmatch(identifier) else "redacted"
        try:
            safe_status = CapabilityStatus(status).value
        except (TypeError, ValueError):
            safe_status = CapabilityStatus.UNAVAILABLE.value
        result.append({"id": safe_id, "status": safe_status, "reason": _safe_reason(reason)})
    return result


def _safe_provider(value: object) -> dict[str, object] | None:
    """Project provider-like objects without calling arbitrary serializers."""

    if value is None:
        return None
    fields: dict[str, object] = {}
    for name in (
        "provider_kind", "provider_id", "model_id", "network_policy",
        "network_disclosure", "endpoint_classification",
    ):
        item = getattr(value, name, None)
        if hasattr(item, "value"):
            item = item.value
        if isinstance(item, (str, bool, int, float)) or item is None:
            fields[name] = item
    return fields


def build_diagnostics(
    *,
    db_path: str | None = None,
    settings_store: ApplicationSettingsStore | None = None,
    history: HistoryStore | None = None,
    settings: ApplicationSettings | None = None,
    capabilities: Iterable[CapabilityRecord | Mapping[str, object]] = (),
    state: Mapping[str, object] | Any | None = None,
    provider: object | None = None,
) -> dict[str, object]:
    """Build a stable projection from named fields only.

    A missing database is represented by empty local defaults. The function never
    serializes arbitrary exception, provider, history, or settings objects.
    """

    if settings is None:
        if settings_store is not None:
            settings = settings_store.load_application_settings()
        elif db_path is not None:
            settings = ApplicationSettingsStore(db_path).load_application_settings()
        else:
            settings = ApplicationSettings()
    if history is not None:
        history_counts = history.diagnostic_counts()
    else:
        history_counts = {
            "job_count": 0,
            "attempt_count": 0,
            "statuses": {},
            "retention": {},
            "error_codes": {},
        }
    current_state = state
    if current_state is not None and hasattr(current_state, "to_dict"):
        current_state = current_state.to_dict()
    safe_state = {}
    if isinstance(current_state, Mapping):
        for key in ("state", "failure_reason"):
            if key in current_state:
                safe_state[key] = (
                    current_state[key] if key == "state" else _safe_reason(current_state[key])
                )
    writing = None
    if settings_store is not None:
        writing = settings_store.load_writing_settings()
    elif db_path is not None:
        writing = ApplicationSettingsStore(db_path).load_writing_settings()
    return {
        "app": APP_NAME,
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "settings": settings.to_safe_dict(writing=writing),
        "provider": _safe_provider(provider),
        "capabilities": _safe_capabilities(capabilities),
        "state": safe_state,
        "history": history_counts,
        "policy": {
            "asr": {
                "provider_kind": settings.asr_provider_kind.value,
                "provider_id": settings.asr_provider_id,
                "model_id": settings.selected_model_id,
                "network_policy": settings.asr_network_policy.value,
                "network_disclosure": settings.asr_network_disclosure,
            },
            "cleanup": {
                "policy": settings.cleanup_policy.value,
                "provider_id": settings.cleanup_provider_id,
                "network_policy": settings.cleanup_network_policy.value,
                "network_disclosure": settings.cleanup_network_disclosure,
            },
        },
        "errors": history_counts["error_codes"],
    }


diagnostic_projection = build_diagnostics


__all__ = ["build_diagnostics", "diagnostic_projection"]
