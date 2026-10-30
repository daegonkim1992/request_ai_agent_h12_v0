"""해석유형별 조건 매핑 — 업무정의서 5.2.

기준 데이터라 릴리스에 고정된다 (3.4-10). 열 이름의 의미는 rules/conditions.yaml 이 정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from .errors import ReferenceDataError


class Mark(StrEnum):
    REQUIRED = "●"
    OPTIONAL = "○"
    HIDDEN = "—"


@dataclass(frozen=True)
class ConditionMapping:
    version: str
    columns: tuple[str, ...]
    marks: Mapping[str, Mapping[str, Mark]]       # 해석유형 → 열 → 기호
    measurement: Mapping[str, tuple[str, ...]]    # 해석유형 → 측정·판정 기준 항목

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ConditionMapping:
        columns = tuple(raw.get("columns") or ())
        if not columns or len(set(columns)) != len(columns):
            raise ReferenceDataError("조건 매핑: columns 가 비었거나 중복된다")
        marks = {}
        for analysis_type, row in (raw.get("types") or {}).items():
            row = list(row or [])
            if len(row) != len(columns):
                raise ReferenceDataError(f"조건 매핑 {analysis_type}: 열 {len(columns)}개에 값이 {len(row)}개다")
            try:
                marks[analysis_type] = dict(zip(columns, (Mark(str(m)) for m in row)))
            except ValueError as e:
                raise ReferenceDataError(f"조건 매핑 {analysis_type}: {e}") from None
        if not marks:
            raise ReferenceDataError("조건 매핑: types 가 비어 있다")
        measurement = {t: tuple(items or ()) for t, items in (raw.get("measurement") or {}).items()}
        unknown = set(measurement) - set(marks)
        if unknown:
            raise ReferenceDataError(f"조건 매핑 measurement: 매핑에 없는 해석유형 {sorted(unknown)}")
        return cls(version=str(raw.get("version") or ""), columns=columns, marks=marks, measurement=measurement)

    def marks_for(self, analysis_type: str) -> Mapping[str, Mark]:
        if analysis_type not in self.marks:
            raise ReferenceDataError(f"조건 매핑에 해석유형 {analysis_type} 이 없다")
        return self.marks[analysis_type]

    def measurement_items(self, analysis_type: str) -> tuple[str, ...]:
        return self.measurement.get(analysis_type, ())
