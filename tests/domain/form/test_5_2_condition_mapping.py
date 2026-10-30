"""5.2 해석유형별 조건 매핑. 기대값은 정의서 표를 그대로 옮겼다."""

from __future__ import annotations

import pytest

from h12.domain.form import condition_config, group_mark

COLUMNS = ["operating", "room_temp", "room_rh", "room_pressure", "supply_temp", "supply_rh", "heat_exchanger",
           "filter", "installation", "leakage", "particles", "pcb", "pcb_refrigerant", "multiphase"]

# 정의서 5.2 (운전, 공간 온도, 공간 RH, 공간 압력, 취출 온도, 취출 RH, 열교환기, 필터, 설치, 누설, 입자, PCB, 냉매(수랭 PCB), 다상)
TABLE = {
    "기류 패턴":            "● ○ — ○ ○ — ○ ○ ○ — — — — —",
    "풍량":                 "● — — ○ — — ○ ○ ○ — — — — —",
    "이슬맺힘":             "● ● ● — ● ● ● ○ ○ — — — — —",
    "열교환기 유속 프로파일": "● — — ○ — — ● ○ ○ — — — — —",
    "기류 도달 거리":        "● ○ — — ○ — ○ ○ ● — — — — —",
    "PDB":                  "● ● — — ● — ○ ○ ● — — — — —",
    "실사용 해석":           "● ● — — ● — ○ ○ ● — — — — —",
    "집진해석(먼지거동)":     "● — — — — — ○ ○ ● — ● — — —",
    "PCB발열":              "● ● — — ○ — ○ ○ ○ — — ● ● —",
    "다상유동":             "○ — — — — — ○ ○ ○ — — — — ●",
    "냉매누설":             "○ — — — — — ○ ○ ○ ● — — — —",
}

# 정의서 5.2 측정·판정 기준 열, 5.3.11
MEASUREMENT = {
    "기류 도달 거리": {"reach_velocity"},
    "PDB": {"temperature_criterion", "velocity_criterion"},
    "실사용 해석": {"measurement_locations"},
    "PCB발열": {"allowable_temperature"},
}


def _code(rules, label):
    return next(code for code, t in rules.analysis_types.items() if t.label == label)


@pytest.mark.parametrize("label", TABLE)
def test_5_2_marks(rules, ref, label):
    config = condition_config(ref.condition_mapping, _code(rules, label), "수랭식", rules)
    assert [config.marks[c].value for c in COLUMNS] == TABLE[label].split()
    assert set(config.measurement_items) == MEASUREMENT.get(label, set())


def test_mapping_covers_every_analysis_type(rules, ref):
    assert set(ref.condition_mapping.marks) == set(rules.analysis_types)
    assert len(TABLE) == 11


def test_5_2_refrigerant_only_for_water_cooling(rules, ref):
    assert condition_config(ref.condition_mapping, "PCB_HEAT", "수랭식", rules).marks["pcb_refrigerant"].value == "●"
    assert condition_config(ref.condition_mapping, "PCB_HEAT", "공랭식", rules).marks["pcb_refrigerant"].value == "—"


def test_5_2_filter_and_installation_offered_for_every_type(rules, ref):
    # 변경: 필터는 모든 유형에서 선택, 설치는 모든 유형에서 최소 선택
    for code in rules.analysis_types:
        config = condition_config(ref.condition_mapping, code, None, rules)
        assert group_mark(rules.groups["filter"], config).value == "○"
        assert group_mark(rules.groups["installation"], config).value in ("○", "●")


def test_every_mapping_column_is_used(rules, ref):
    used = {f.column for g in rules.groups.values() for f in g.fields.values() if f.column}
    used |= {g.column for g in rules.groups.values() if g.column}
    used.add("pcb_refrigerant")  # PCB 조건 안의 냉매 조건
    assert used == set(ref.condition_mapping.columns)
