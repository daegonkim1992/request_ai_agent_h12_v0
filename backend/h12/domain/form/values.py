"""값의 상태와 칸 검사 — 업무정의서 5.4, 5.1.

칸은 {value, status, source} 로 저장한다 (부록 C). 단순 값만 들어 있어도 읽는다.
상태는 저장된 status 를 믿지 않고 값에서 다시 판정한다. 값 없이 "없음"을 명시한 칸만 저장된 상태를 따른다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum, StrEnum
from typing import Any, Mapping

from h12.domain.workflow import Issue


class ValueStatus(StrEnum):
    PROVIDED = "provided"  # 입력됨
    MISSING = "missing"    # 누락
    UNKNOWN = "unknown"    # 모름
    NONE = "none"          # 없음
    SKIPPED = "skipped"    # 생략


class ValueSource(StrEnum):
    USER = "user"
    SYSTEM = "system"


class Need(Enum):
    REQUIRED = "required"            # 값이 있어야 한다. 없음 불가
    VALUE_OR_NONE = "value_or_none"  # 값 또는 "없음"을 명시해야 한다 (○ 조건의 칸)
    OPTIONAL = "optional"            # 비어도 된다. 넣었다면 형식은 맞아야 한다


@dataclass(frozen=True)
class ValueRules:
    keywords: Mapping[ValueStatus, frozenset[str]]
    fills_required: frozenset[ValueStatus]
    max_text_length: int

    def classify(self, value: Any) -> ValueStatus:
        if value is None or (isinstance(value, str) and not value.strip()):
            return ValueStatus.MISSING
        if isinstance(value, str):
            word = value.strip().casefold()
            for status, words in self.keywords.items():
                if word in words:
                    return status
        return ValueStatus.PROVIDED

    def status(self, cell: Any) -> ValueStatus:
        value = value_of(cell)
        status = self.classify(value)
        if status is ValueStatus.MISSING and isinstance(cell, Mapping) and cell.get("status") == ValueStatus.NONE:
            return ValueStatus.NONE
        return status

    def cell(self, value: Any, source: ValueSource = ValueSource.USER) -> dict[str, Any]:
        """입력값으로 저장할 칸을 만든다."""
        return {"value": value, "status": str(self.classify(value)), "source": str(source)}

    @staticmethod
    def none_cell(source: ValueSource = ValueSource.USER) -> dict[str, Any]:
        """컨트롤로 "없음"을 고른 칸."""
        return {"value": None, "status": str(ValueStatus.NONE), "source": str(source)}


def value_of(cell: Any) -> Any:
    return cell.get("value") if isinstance(cell, Mapping) else cell


def as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


@dataclass
class Checker:
    """칸 검사 결과를 모은다. 위치는 의뢰서 안의 경로다 (예: conditions.operating.packages[0].rpm)."""

    values: ValueRules
    issues: list[Issue] = field(default_factory=list)

    def add(self, location: str, message: str) -> None:
        self.issues.append(Issue(location, message))

    def cell(self, location: str, cell: Any, label: str, need: Need, *, kind: str = "text",
             choices: Mapping[str, str] | None = None, allow_custom: bool = False) -> ValueStatus:
        status = self.values.status(cell)
        value = value_of(cell)
        if isinstance(value, str) and len(value) > self.values.max_text_length:
            self.add(location, f"{label}: {self.values.max_text_length}자를 넘을 수 없다")
        if status is ValueStatus.PROVIDED:
            self._format(location, value, label, kind, choices, allow_custom)
        if need is Need.REQUIRED and status not in self.values.fills_required:
            self.add(location, f"{label}: {_MISSING_MESSAGE.get(status, '필수 입력')}")
        elif need is Need.VALUE_OR_NONE and status not in self.values.fills_required | {ValueStatus.NONE}:
            self.add(location, f"{label}: 값을 입력하거나 '없음'을 선택해야 한다")
        return status

    def _format(self, location: str, value: Any, label: str, kind: str,
                choices: Mapping[str, str] | None, allow_custom: bool) -> None:
        if kind == "number" and as_number(value) is None:
            self.add(location, f"{label}: 숫자여야 한다")
        elif kind == "date" and as_date(value) is None:
            self.add(location, f"{label}: 날짜(YYYY-MM-DD)여야 한다")
        elif kind == "choice" and choices is not None and not allow_custom and value not in choices:
            self.add(location, f"{label}: {list(choices.values())} 중에서 골라야 한다")


_MISSING_MESSAGE = {
    ValueStatus.MISSING: "필수 입력",
    ValueStatus.NONE: "필수라 '없음'으로 둘 수 없다",
    ValueStatus.UNKNOWN: "'모름'으로는 채운 것으로 보지 않는다",
    ValueStatus.SKIPPED: "필수라 건너뛸 수 없다",
}
