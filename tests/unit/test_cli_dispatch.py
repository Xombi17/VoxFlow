import json
import sys
import types

import pytest

from voxflow.__main__ import SUBCOMMANDS, main


@pytest.mark.parametrize("name", sorted(SUBCOMMANDS))
def test_subcommands_dispatch_with_remaining_argv(name, monkeypatch) -> None:
    module_name, attr = SUBCOMMANDS[name]
    seen = []
    stub = types.ModuleType(module_name)
    setattr(stub, attr, lambda rest: seen.append(rest) or 0)
    monkeypatch.setitem(sys.modules, module_name, stub)
    assert main([name, "--x", "1"]) == 0
    assert seen == [["--x", "1"]]


def test_missing_target_module_returns_2(monkeypatch, capsys) -> None:
    monkeypatch.setattr("importlib.import_module", _missing)
    assert main(["daemon"]) == 2
    assert "not installed yet" in capsys.readouterr().out


def _missing(name):
    raise ModuleNotFoundError(name=name)


def test_default_diagnostic_unchanged(capsys) -> None:
    assert main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["app"] == "voxflow" and "platform" not in payload
