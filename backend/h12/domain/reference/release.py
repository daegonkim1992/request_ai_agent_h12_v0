"""기준 데이터 릴리스 — 업무정의서 3.4-10.

의뢰는 의뢰 대상을 확정한 시점의 릴리스를 따른다. 릴리스는 데이터셋마다 버전 하나를 가리키고,
버전은 한번 만들면 바뀌지 않는다. 그래서 의뢰에 릴리스 ID 를 남기면 확정 당시의 기준 데이터를 다시 얻는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .condition_mapping import ConditionMapping
from .errors import ReferenceDataError
from .hx_catalog import HxCatalog
from .pms import PmsDirectory
from .taxonomy import ProductTaxonomy


@dataclass(frozen=True)
class MeasurementStandards:
    """측정·판정 기준 표준값 (5.3.11). 값이 None 이면 아직 정하지 않았다 [추후 정의]."""

    version: str
    values: Mapping[str, Mapping[str, Any]]  # 해석유형 코드 → 항목 키 → 표준값

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> MeasurementStandards:
        values = raw.get("values") or {}
        if not isinstance(values, dict) or not all(isinstance(v, dict) for v in values.values()):
            raise ReferenceDataError("측정·판정 기준: values 는 {해석유형: {항목: 표준값}} 이다")
        return cls(version=str(raw.get("version") or ""), values=values)

    def for_type(self, analysis_type: str) -> Mapping[str, Any]:
        return self.values.get(analysis_type, {})


@dataclass(frozen=True)
class ReferenceSet:
    release: str
    taxonomy: ProductTaxonomy
    hx_catalog: HxCatalog
    # PMS 는 3.4-10 의 고정 대상이 아니다. 고른 프로젝트의 값은 의뢰에 복사한다 (G-15)
    pms: PmsDirectory
    measurement_standards: MeasurementStandards
    condition_mapping: ConditionMapping
