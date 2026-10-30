"""refdata/ 의 기준 데이터를 릴리스 단위로 읽는다 — 업무정의서 3.4-10, 9장.

refdata/manifest.yaml 의 릴리스가 데이터셋마다 버전 파일 하나를 가리킨다.
버전 파일(refdata/<데이터셋>/<버전>.json|yaml)은 한번 만들면 고치지 않는다. 바꿀 때는 새 버전 파일과
새 릴리스를 추가하고 current 를 옮긴다. 기본 위치는 저장소 루트의 refdata/ 이고 H12_REFDATA_DIR 로 바꿀 수 있다.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from h12.domain.reference import (
    ConditionMapping, HxCatalog, MeasurementStandards, PmsDirectory, ProductTaxonomy, ReferenceDataError,
    ReferenceSet,
)

DEFAULT_REFDATA_DIR = Path(__file__).resolve().parents[3] / "refdata"

# 데이터셋 이름 → (파일 확장자, 해석 함수)
DATASETS: dict[str, tuple[str, Callable[[Mapping[str, Any]], Any]]] = {
    "taxonomy": ("json", ProductTaxonomy.from_dict),
    "hx_catalog": ("json", HxCatalog.from_dict),
    "pms": ("json", PmsDirectory.from_dict),
    "measurement_standards": ("yaml", MeasurementStandards.from_dict),
    "condition_mapping": ("yaml", ConditionMapping.from_dict),
}


def refdata_dir() -> Path:
    return Path(os.environ.get("H12_REFDATA_DIR", DEFAULT_REFDATA_DIR))


def version_path(root: Path, dataset: str, version: str) -> Path:
    return root / dataset / f"{version}.{DATASETS[dataset][0]}"


class ReferenceStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or refdata_dir())
        self._manifest: dict[str, Any] | None = None
        self._loaded: dict[str, ReferenceSet] = {}

    @property
    def current_release(self) -> str:
        return self._read_manifest()["current"]

    def releases(self) -> list[str]:
        return list(self._read_manifest()["releases"])

    def versions(self, release: str) -> Mapping[str, str]:
        releases = self._read_manifest()["releases"]
        if release not in releases:
            raise ReferenceDataError(f"기준 데이터 릴리스 {release} 가 없다")
        return releases[release]

    def load(self, release: str | None = None) -> ReferenceSet:
        """릴리스의 기준 데이터. 생략하면 현재 릴리스다."""
        release = release or self.current_release
        if release not in self._loaded:
            versions = self.versions(release)
            data = {name: self._load_dataset(name, versions[name]) for name in DATASETS}
            self._loaded[release] = ReferenceSet(release=release, **data)
        return self._loaded[release]

    def _load_dataset(self, dataset: str, version: str) -> Any:
        path = version_path(self.root, dataset, version)
        if not path.exists():
            raise ReferenceDataError(f"{path} 가 없다")
        with path.open(encoding="utf-8") as f:
            raw = json.load(f) if path.suffix == ".json" else yaml.safe_load(f)
        if raw.get("dataset") != dataset or str(raw.get("version")) != version:
            raise ReferenceDataError(f"{path}: 파일의 dataset·version 이 경로와 다르다")
        return DATASETS[dataset][1](raw)

    def _read_manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            with (self.root / "manifest.yaml").open(encoding="utf-8") as f:
                self._manifest = _parse_manifest(yaml.safe_load(f) or {})
        return self._manifest


def _parse_manifest(raw: Mapping[str, Any]) -> dict[str, Any]:
    releases = {}
    for release, versions in (raw.get("releases") or {}).items():
        versions = {k: str(v) for k, v in (versions or {}).items()}
        if set(versions) != set(DATASETS):
            raise ReferenceDataError(f"manifest {release}: 데이터셋은 {sorted(DATASETS)} 이어야 한다")
        releases[str(release)] = versions
    current = raw.get("current")
    if current not in releases:
        raise ReferenceDataError(f"manifest: current {current!r} 가 releases 에 없다")
    return {"current": current, "releases": releases}


@lru_cache(maxsize=None)
def default_store() -> ReferenceStore:
    return ReferenceStore()
