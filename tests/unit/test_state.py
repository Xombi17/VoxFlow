import pytest

from voxflow import APP_NAME, __version__
from voxflow.core.state import (
    InvalidStateTransitionError,
    SessionState,
    SessionStateMachine,
)


def test_bootstrap_package_metadata_is_available() -> None:
    assert APP_NAME == "voxflow"
    assert __version__ == "0.1.0"


def test_valid_session_transitions_reach_success() -> None:
    session = SessionStateMachine()

    session.transition(SessionState.LISTENING)
    session.transition(SessionState.PROCESSING)
    snapshot = session.transition(SessionState.SUCCESS)

    assert snapshot.state is SessionState.SUCCESS
    assert snapshot.failure_reason is None


def test_listening_session_can_be_cancelled() -> None:
    session = SessionStateMachine()

    session.transition("listening")
    session.transition("cancelled")

    assert session.state is SessionState.CANCELLED


def test_invalid_transition_raises_without_mutating_state() -> None:
    session = SessionStateMachine()

    with pytest.raises(InvalidStateTransitionError, match="idle -> success"):
        session.transition(SessionState.SUCCESS)

    assert session.state is SessionState.IDLE


def test_failed_transition_preserves_user_facing_reason() -> None:
    session = SessionStateMachine()
    session.transition(SessionState.LISTENING)
    session.transition(SessionState.PROCESSING)

    session.transition(SessionState.FAILED, failure_reason="Microphone disconnected")

    assert session.to_dict() == {
        "state": "failed",
        "failure_reason": "Microphone disconnected",
    }


def test_all_six_states_have_stable_serialized_names() -> None:
    assert [state.value for state in SessionState] == [
        "idle",
        "listening",
        "processing",
        "success",
        "cancelled",
        "failed",
    ]
