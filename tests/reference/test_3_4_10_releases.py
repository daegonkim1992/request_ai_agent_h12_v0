"""3.4-10 기준 데이터 변경: 확정한 의뢰는 확정 시점의 기준 데이터를 따른다.

의뢰는 릴리스 ID 를 남긴다. 새 릴리스가 나와도 이전 릴리스의 데이터는 그대로 읽힌다.
"""

from __future__ import annotations

import json
import shutil

import pytest
import yaml

from h12.domain.reference import ReferenceDataError
from h12.reference import DATASETS, ReferenceStore, default_store
from h12.reference.build import BuildError, write_version

OLD, NEW = "R2026-10-30", "R2026-11-01"
CHILLER = ("Chiller", "Screw", "Air Cooled", None)


@pytest.fixture
def root(tmp_path):
    target = tmp_path / "refdata"
    shutil.copytree(default_store().root, target)
    return target


def _manifest(root):
    return yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8"))


def _save_manifest(root, manifest):
    (root / "manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")


def _release_without_chiller_air_cooled(root):
    """기준 데이터 담당자가 분류 하나를 뺀 새 릴리스를 낸다."""
    old_version = _manifest(root)["releases"][OLD]["taxonomy"]
    raw = json.loads((root / "taxonomy" / f"{old_version}.json").read_text(encoding="utf-8"))
    raw["paths"] = [p for p in raw["paths"] if (p["division"], p["platform"]) != ("Chiller", "Air Cooled")]
    data = {k: v for k, v in raw.items() if k not in ("dataset", "version")}
    write_version(root, "taxonomy", "2026-11-01", data)

    manifest = _manifest(root)
    manifest["releases"][NEW] = {**manifest["releases"][OLD], "taxonomy": "2026-11-01"}
    manifest["current"] = NEW
    _save_manifest(root, manifest)


def test_every_release_in_repository_loads():
    store = ReferenceStore(default_store().root)
    for release in store.releases():
        assert store.load(release).release == release
    assert store.load().release == store.current_release


def test_confirmed_request_keeps_its_release(root):
    pinned = ReferenceStore(root).current_release  # 의뢰 대상 확정 시점에 남긴 릴리스
    assert pinned == OLD

    _release_without_chiller_air_cooled(root)
    store = ReferenceStore(root)

    assert store.current_release == NEW
    assert store.load().taxonomy.find(*CHILLER) is None
    assert store.load(pinned).taxonomy.find(*CHILLER) is not None
    assert len(store.load(pinned).taxonomy.paths) == 252
    # 바뀌지 않은 데이터셋은 같은 버전을 가리킨다
    assert store.versions(NEW)["hx_catalog"] == store.versions(OLD)["hx_catalog"]


def test_version_file_cannot_be_rewritten(root):
    version = _manifest(root)["releases"][OLD]["taxonomy"]
    raw = json.loads((root / "taxonomy" / f"{version}.json").read_text(encoding="utf-8"))
    data = {k: v for k, v in raw.items() if k not in ("dataset", "version")}

    path, written = write_version(root, "taxonomy", version, data)  # 같은 내용이면 그대로 둔다
    assert not written

    data["paths"] = data["paths"][1:]
    with pytest.raises(BuildError):
        write_version(root, "taxonomy", version, data)


def test_invalid_data_is_not_written(root):
    with pytest.raises(BuildError):
        write_version(root, "taxonomy", "2026-11-02", {"platform_mode": {}, "paths": []})
    assert not (root / "taxonomy" / "2026-11-02.json").exists()


def test_unknown_release_rejected(root):
    with pytest.raises(ReferenceDataError):
        ReferenceStore(root).load("R1999-01-01")


@pytest.mark.parametrize("name,mutate", [
    ("current missing", lambda m: m.update(current="R1999-01-01")),
    ("dataset missing", lambda m: m["releases"][OLD].pop("pms")),
    ("unknown dataset", lambda m: m["releases"][OLD].update(extra="2026-10-30")),
])
def test_invalid_manifest_rejected(root, name, mutate):
    manifest = _manifest(root)
    mutate(manifest)
    _save_manifest(root, manifest)
    with pytest.raises(ReferenceDataError):
        ReferenceStore(root).load()


def test_file_must_match_its_version(root):
    manifest = _manifest(root)
    manifest["releases"][OLD]["hx_catalog"] = "2026-11-03"
    _save_manifest(root, manifest)
    shutil.copy(root / "hx_catalog" / "2026-10-30.json", root / "hx_catalog" / "2026-11-03.json")
    with pytest.raises(ReferenceDataError):
        ReferenceStore(root).load()


def test_all_datasets_are_released():
    assert set(DATASETS) == {"taxonomy", "hx_catalog", "pms", "measurement_standards"}
