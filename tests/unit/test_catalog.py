import json

import pytest

from voxflow import settings
from voxflow.providers import catalog


def test_manifest_valid():
    cat = catalog.load_catalog()
    ids = {m.id for m in cat.models}
    assert {"small.en", "distil-large-v3", "parakeet-tdt-0.6b-v3", "medium.en"} <= ids
    assert all(f.sha256 and f.url.startswith("https://") for m in cat.models for f in m.files)


def install(root, mid):
    d = root / mid
    d.mkdir(parents=True)
    (d / catalog.VERIFIED_MARKER).write_text("{}")


def test_list_select_remove(tmp_path):
    root, db = tmp_path / "models", tmp_path / "v.db"
    install(root, "small.en")
    with pytest.raises(catalog.CatalogError):
        catalog.select("medium.en", root, db_path=db)
    catalog.select("small.en", root, db_path=db)
    assert catalog.get_selected(db_path=db) == "small.en"
    rows = {r["id"]: r for r in catalog.list_models(root, db_path=db)}
    assert rows["small.en"]["installed"] and rows["small.en"]["selected"]
    assert not rows["medium.en"]["installed"]
    catalog.remove("small.en", root, db_path=db)
    assert not (root / "small.en").exists() and catalog.get_selected(db_path=db) is None


@pytest.mark.parametrize("bad", ["../x", "a/b", "..", "", "/abs", ".hidden"])
def test_traversal_ids_rejected(tmp_path, bad):
    with pytest.raises(catalog.CatalogError):
        catalog.remove(bad, tmp_path)


def test_results_roundtrip_and_malformed(tmp_path):
    assert catalog.load_results(tmp_path) == {}
    catalog.results_path(tmp_path).write_text("{not json")
    assert catalog.load_results(tmp_path) == {}
    rec = catalog.result_record(120.0, 200.0, None, "/x/y/fixture.wav")
    assert set(rec) == {"p50_ms", "p95_ms", "wer", "fixture", "ts"} and rec["fixture"] == "fixture.wav"
    catalog.save_results(tmp_path, {"small.en": rec})
    assert catalog.load_results(tmp_path) == {"small.en": rec}
    install(tmp_path, "small.en")
    row = next(r for r in catalog.list_models(tmp_path, db_path=tmp_path / "d.db") if r["id"] == "small.en")
    assert row["p50_ms"] == 120.0 and row["wer"] is None


def test_settings_roundtrip(tmp_path):
    db = tmp_path / "s.db"
    assert settings.get("k", "d", db_path=db) == "d"
    settings.set("k", "v", db_path=db)
    settings.set("k", "w", db_path=db)
    assert settings.get("k", db_path=db) == "w"
