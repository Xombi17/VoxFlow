import os
import stat

import pytest

from voxflow.platform import restore_token as rt


def test_store_load_roundtrip_modes_and_overwrite(tmp_path) -> None:
    p = tmp_path / "state" / "t"
    rt.store("abc-123", p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    assert rt.load(p) == "abc-123"
    rt.store("new", p)
    assert rt.load(p) == "new"
    assert [x.name for x in p.parent.iterdir()] == ["t"]


def test_wide_permissions_rejected(tmp_path) -> None:
    p = tmp_path / "t"
    rt.store("abc", p)
    os.chmod(p, 0o644)
    assert rt.load(p) is None


def test_symlink_rejected(tmp_path) -> None:
    real = tmp_path / "real"
    rt.store("abc", real)
    link = tmp_path / "link"
    link.symlink_to(real)
    assert rt.load(link) is None


def test_missing_and_invalid(tmp_path) -> None:
    assert rt.load(tmp_path / "none") is None
    with pytest.raises(ValueError):
        rt.store("has space", tmp_path / "t")
    with pytest.raises(ValueError):
        rt.store("", tmp_path / "t")


def test_default_path_uses_xdg_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert rt.token_path() == tmp_path / "voxflow" / "remote_desktop.token"
