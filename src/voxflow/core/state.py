"""Pure dictation session state contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class SessionState(StrEnum):
    """Observable states for one dictation session."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SUCCESS = "success"
    CANCELLED = "cancelled"
    FAILED = "failed"


STATE_TRANSITIONS: Final[dict[SessionState, frozenset[SessionState]]] = {
    SessionState.IDLE: frozenset({SessionState.LISTENING}),
    SessionState.LISTENING: frozenset(
        {
            SessionState.PROCESSING,
            SessionState.CANCELLED,
            SessionState.FAILED,
        }
    ),
    SessionState.PROCESSING: frozenset(
        {
            SessionState.SUCCESS,
            SessionState.CANCELLED,
            SessionState.FAILED,
        }
    ),
    SessionState.SUCCESS: frozenset({SessionState.IDLE}),
    SessionState.CANCELLED: frozenset({SessionState.IDLE}),
    SessionState.FAILED: frozenset({SessionState.IDLE}),
}


class InvalidStateTransitionError(ValueError):
    """Raised when a session attempts an unsupported state transition."""

    def __init__(self, from_state: SessionState, to_state: SessionState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid dictation transition: {from_state.value} -> {to_state.value}"
        )


InvalidTransitionError = InvalidStateTransitionError


def _coerce_state(state: SessionState | str) -> SessionState:
    try:
        return SessionState(state)
    except ValueError as exc:
        raise ValueError(f"Unknown dictation state: {state!r}") from exc


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Immutable state plus optional failure context for diagnostics."""

    state: SessionState = SessionState.IDLE
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", _coerce_state(self.state))
        if self.failure_reason is not None and not self.failure_reason.strip():
            raise ValueError("failure_reason must not be blank")

    def transition(
        self,
        to_state: SessionState | str,
        *,
        failure_reason: str | None = None,
    ) -> SessionSnapshot:
        """Return a new snapshot after validating the requested transition."""

        return transition_session(self, to_state, failure_reason=failure_reason)

    def to_dict(self) -> dict[str, str | None]:
        """Serialize stable state field names for CLI/UI diagnostics."""

        return {
            "state": self.state.value,
            "failure_reason": self.failure_reason,
        }


def transition_session(
    session: SessionSnapshot,
    to_state: SessionState | str,
    *,
    failure_reason: str | None = None,
) -> SessionSnapshot:
    """Validate and return the next immutable session snapshot."""

    target = _coerce_state(to_state)
    if target not in STATE_TRANSITIONS[session.state]:
        raise InvalidStateTransitionError(session.state, target)

    reason = failure_reason if target is SessionState.FAILED else None
    if target is SessionState.FAILED and reason is None:
        reason = "Dictation session failed."
    return SessionSnapshot(state=target, failure_reason=reason)


class SessionStateMachine:
    """Validated mutable facade around immutable session snapshots."""

    def __init__(self, initial: SessionState | str = SessionState.IDLE) -> None:
        self._snapshot = SessionSnapshot(state=_coerce_state(initial))

    @property
    def state(self) -> SessionState:
        return self._snapshot.state

    @property
    def failure_reason(self) -> str | None:
        return self._snapshot.failure_reason

    @property
    def snapshot(self) -> SessionSnapshot:
        return self._snapshot

    def transition(
        self,
        to_state: SessionState | str,
        *,
        failure_reason: str | None = None,
    ) -> SessionSnapshot:
        """Apply a valid transition and return the resulting snapshot."""

        next_snapshot = transition_session(
            self._snapshot,
            to_state,
            failure_reason=failure_reason,
        )
        self._snapshot = next_snapshot
        return next_snapshot

    def to_dict(self) -> dict[str, str | None]:
        return self._snapshot.to_dict()


DictationState = SessionState
DictationSession = SessionStateMachine
