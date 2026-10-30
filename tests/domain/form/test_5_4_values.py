"""5.4 값의 상태."""

from __future__ import annotations

import pytest

from h12.domain.form import ValueStatus
from h12.domain.form.values import Checker, Need

# 정의서 5.4 판정하는 입력의 예
EXAMPLES = [
    ("모름", ValueStatus.UNKNOWN), ("확인 필요", ValueStatus.UNKNOWN), ("unknown", ValueStatus.UNKNOWN),
    ("TBD", ValueStatus.UNKNOWN),
    ("없음", ValueStatus.NONE), ("해당 없음", ValueStatus.NONE), ("none", ValueStatus.NONE), ("N/A", ValueStatus.NONE),
    ("건너뜀", ValueStatus.SKIPPED), ("생략", ValueStatus.SKIPPED), ("skip", ValueStatus.SKIPPED),
    ("", ValueStatus.MISSING), ("  ", ValueStatus.MISSING), (None, ValueStatus.MISSING),
    ("25", ValueStatus.PROVIDED), (0, ValueStatus.PROVIDED), ("없음이 아님", ValueStatus.PROVIDED),
]


@pytest.mark.parametrize("value,status", EXAMPLES)
def test_status_from_input(rules, value, status):
    assert rules.values.classify(value) is status
    assert rules.values.cell(value)["status"] == status


def test_explicit_none_and_source(rules):
    assert rules.values.status(rules.values.none_cell()) is ValueStatus.NONE
    assert rules.values.cell(3)["source"] == "user"
    assert rules.values.cell(3, "system")["source"] == "system"


def test_stored_status_is_not_trusted(rules):
    assert rules.values.status({"value": "", "status": "provided"}) is ValueStatus.MISSING
    assert rules.values.status({"value": "모름", "status": "provided"}) is ValueStatus.UNKNOWN


@pytest.mark.parametrize("value,need,ok", [
    # "모름"은 채운 것으로 본다 (5.4, G-21)
    ("25", Need.REQUIRED, True), ("모름", Need.REQUIRED, True), ("생략", Need.REQUIRED, False),
    ("없음", Need.REQUIRED, False), ("", Need.REQUIRED, False),
    ("없음", Need.VALUE_OR_NONE, True), ("", Need.VALUE_OR_NONE, False), ("모름", Need.VALUE_OR_NONE, True),
    ("", Need.OPTIONAL, True), ("모름", Need.OPTIONAL, True),
])
def test_needs(rules, value, need, ok):
    c = Checker(rules.values)
    c.cell("x", rules.values.cell(value), "칸", need)
    assert (c.issues == []) is ok


def test_number_format(rules):
    c = Checker(rules.values)
    c.cell("a", rules.values.cell("25.5"), "온도", Need.REQUIRED, kind="number")
    c.cell("b", rules.values.cell("스물다섯"), "온도", Need.REQUIRED, kind="number")
    c.cell("c", rules.values.cell("모름"), "온도", Need.OPTIONAL, kind="number")  # 모름은 숫자 검사를 하지 않는다
    assert [i.location for i in c.issues] == ["b"]
