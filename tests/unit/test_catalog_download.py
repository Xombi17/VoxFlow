import hashlib
import socket

import pytest

from voxflow.providers import catalog, catalog_cli
from voxflow.providers.catalog import CatalogError, FetchResponse, ModelEntry, ModelFile

DATA = b"hello model bytes" * 100
SHA = hashlib.sha256(DATA).hexdigest()
URL = "https://huggingface.co/x/y/resolve/rev/model.bin"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(socket, "socket", boom)


def entry(path="model.bin", sha=SHA, mid="m1"):
    return ModelEntry(
        id=mid, name="m", engine="faster-whisper", languages=("en",), size_bytes=len(DATA),
        tier="speed", source_url="https://huggingface.co/x/y", license="MIT",
        files=(ModelFile(path=path, url=URL, sha256=sha),),
    )


class Fake:
    def __init__(self, data=DATA, url=URL):
        self.data, self.url, self.calls = data, url, []

    def __call__(self, url, start, suffixes):
        self.calls.append(start)
        status = 206 if start else 200
        return FetchResponse(self.url, status, [self.data[start:]])


yes = lambda _n: True


def test_download_ok(tmp_path):
    f = Fake()
    d = catalog.download_model(entry(), tmp_path, f, yes)
    assert (d / "model.bin").read_bytes() == DATA and (d / ".verified").is_file()
    assert not (d / "model.bin.part").exists()
    assert catalog.is_installed(tmp_path, "m1")


def test_hash_mismatch(tmp_path):
    with pytest.raises(CatalogError, match="mismatch"):
        catalog.download_model(entry(sha="0" * 64), tmp_path, Fake(), yes)
    assert not catalog.is_installed(tmp_path, "m1")
    assert not (tmp_path / "m1" / "model.bin.part").exists()
    assert not (tmp_path / "m1" / "model.bin").exists()


def test_resume(tmp_path):
    (tmp_path / "m1").mkdir()
    (tmp_path / "m1" / "model.bin.part").write_bytes(DATA[:50])
    f = Fake()
    catalog.download_model(entry(), tmp_path, f, yes)
    assert f.calls == [50]
    assert (tmp_path / "m1" / "model.bin").read_bytes() == DATA


def test_no_consent_no_fetch(tmp_path):
    f = Fake()
    with pytest.raises(catalog.ConsentRequired):
        catalog.download_model(entry(), tmp_path, f)
    assert f.calls == []
    assert "huggingface.co" in catalog.network_notice(entry())


def test_cross_host_redirect_refused(tmp_path):
    with pytest.raises(CatalogError, match="refusing"):
        catalog.download_model(entry(), tmp_path, Fake(url="https://evil.example/model.bin"), yes)
    assert not catalog.is_installed(tmp_path, "m1")
    with pytest.raises(CatalogError):
        catalog.download_model(entry(), tmp_path, Fake(url="http://huggingface.co/model.bin"), yes)


def test_cdn_suffix_redirect_allowed(tmp_path):
    catalog.download_model(entry(), tmp_path, Fake(url="https://us.aws.cdn.hf.co/blob"), yes)
    assert catalog.is_installed(tmp_path, "m1")


@pytest.mark.parametrize("rel", ["../escape.bin", "/abs.bin", "a/../../b.bin"])
def test_path_traversal_refused_before_fetch(tmp_path, rel):
    f = Fake()
    with pytest.raises(CatalogError):
        catalog.download_model(entry(path=rel), tmp_path, f, yes)
    assert f.calls == []


def test_symlinked_parent_refused(tmp_path):
    root, outside = tmp_path / "models", tmp_path / "outside"
    root.mkdir(), outside.mkdir()
    (root / "m1").symlink_to(outside)
    f = Fake()
    with pytest.raises(CatalogError, match="outside"):
        catalog.download_model(entry(), root, f, yes)
    assert f.calls == [] and list(outside.iterdir()) == []


def test_symlinked_subdir_refused(tmp_path):
    root, outside = tmp_path / "models", tmp_path / "outside"
    (root / "m1").mkdir(parents=True), outside.mkdir()
    (root / "m1" / "sub").symlink_to(outside)
    with pytest.raises(CatalogError, match="outside"):
        catalog.download_model(entry(path="sub/model.bin"), root, Fake(), yes)
    assert list(outside.iterdir()) == []


def test_remove_symlink_refused(tmp_path):
    root, outside = tmp_path / "models", tmp_path / "outside"
    root.mkdir(), outside.mkdir()
    (root / "m1").symlink_to(outside)
    with pytest.raises(CatalogError):
        catalog.remove("m1", root, db_path=tmp_path / "d.db")
    assert outside.exists()


def test_cli_download_accepts_multiple_model_ids(monkeypatch, tmp_path, capsys):
    entries = {model_id: entry(mid=model_id) for model_id in ("m1", "m2")}
    calls = []

    monkeypatch.setattr(catalog_cli.catalog, "get_entry", entries.__getitem__)

    def fake_download(model, root, *, confirm):
        calls.append((model.id, root, confirm("network")))

    monkeypatch.setattr(catalog_cli.catalog, "download_model", fake_download)

    assert catalog_cli.main(["--root", str(tmp_path), "download", "m1", "m2", "--yes"]) == 0
    assert [model_id for model_id, _root, confirmed in calls if confirmed] == ["m1", "m2"]
    output = capsys.readouterr().out
    assert "Installed m1" in output
    assert "Installed m2" in output
