import json

from voxflow.__main__ import diagnostic


def test_bootstrap_diagnostic_is_json_serializable() -> None:
    payload = diagnostic()

    assert json.loads(json.dumps(payload)) == {
        "app": "voxflow",
        "capabilities": [],
        "version": "0.1.0",
    }
