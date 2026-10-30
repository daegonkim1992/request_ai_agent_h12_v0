"""의뢰서 테스트 공통 준비.

의뢰서는 dict 를 직접 꾸미지 않고 실제 작업을 차례로 해서 만든다:
의뢰 대상 확정(confirm_target) → 의뢰자 수정(merge_user_edit) → PMS 선택(select_pms_project).
"""

from __future__ import annotations

import copy
from datetime import date, datetime

import pytest

from h12.domain.form import (
    FormContext, InMemoryNumberIssuer, TargetSelection, check_form, confirm_target, merge_user_edit,
    select_pms_project,
)
from h12.reference import default_store
from h12.rulebook import load_form_rules

NOW = datetime(2026, 11, 2, 9, 0)
TODAY = NOW.date()
PMS_SAC = "PJT2025092400000000229266"  # CAC(=SAC) 파일 첫 행


@pytest.fixture(scope="session")
def rules():
    return load_form_rules()


@pytest.fixture(scope="session")
def ref():
    return default_store().load()


@pytest.fixture
def issuer(rules):
    return InMemoryNumberIssuer(rules.target.request_no_format)


@pytest.fixture
def ctx(rules):
    return FormContext(rules=rules, reference=default_store().load, request_date=TODAY)


def path_id(ref, division, lineup, platform, chassis):
    path = ref.taxonomy.find(division, lineup, platform, chassis)
    assert path is not None, (division, lineup, platform, chassis)
    return path.id


def sac_ahu(ref):
    return path_id(ref, "SAC", "Multi V", "AHU", "10RT")


def cell(rules, value):
    return rules.values.cell(value)


def none(rules):
    return rules.values.none_cell()


def selection(ref, analysis_type, **kwargs):
    taxonomy_id = kwargs.pop("taxonomy_id", None) or sac_ahu(ref)
    if analysis_type == "PCB_HEAT":
        kwargs.setdefault("cooling_method", "공랭식")
    return TargetSelection(taxonomy_id=taxonomy_id, analysis_type=analysis_type, **kwargs)


def confirmed(rules, ref, issuer, analysis_type="AIRFLOW_PATTERN", form=None, **kwargs):
    return confirm_target(form or {}, selection(ref, analysis_type, **kwargs), reference=ref, rules=rules,
                          issuer=issuer, now=NOW)


def content(rules, request_type="QUALITY_IMPROVEMENT"):
    c = lambda v: cell(rules, v)  # noqa: E731
    return {
        "basic_info": {"division": c("SAC"), "department": c("냉동기설계팀"), "requester_name": c("홍길동"),
                       "requester_role": c("선임연구원")},
        "analysis_overview": {
            "request_type": c(request_type),
            "model_suffix": c("ARNU07GTRB4"),
            "desired_completion_date": c("2026-12-01"),
            "request_description": c("토출 기류가 한쪽으로 쏠린다"),
            "additional_result_request": c("루버 각도별 기류 분포"),
            "development_grade": c("B"),
            "npi_stage": c("DV"),
        },
        "geometry": {
            "base_product": {"id": "p1", "drawing_no": c("MEA12345601")},
            "comparison_products": [{"id": "p2", "drawing_no": c("MEA12345602"),
                                     "difference_from_base": c("루버 형상 변경")}],
        },
    }


def conditions(rules, ref, analysis_type, cooling=None):
    """해석유형에 맞는 최소한의 완성된 조건. 보이지 않는 그룹의 값도 넣어 둔다 (무시되어야 한다)."""
    c = lambda v: cell(rules, v)  # noqa: E731
    pcb = {
        "image": c("pcb-image-1"), "device_basis": c("heat"),
        "devices": [{"id": "d1", "name": c("IGBT"), "value": c(15)}],
        "contact_resistance": {"enabled": False},
        "materials": [{"id": "m1", "material_name": c("알루미늄"), "thermal_conductivity": c(200),
                       "applied_part": c("히트싱크")}],
        "refrigerant": {k: c("R32" if k == "refrigerant" else "1") for k in rules.pcb["refrigerant_fields"]},
    }
    return {
        "operating": {"packages": [{"id": "o1", "name": "운전 1", "fan_count": 1, "rpm_mode": c("common"),
                                    "rpm": c(1000)}]},
        "space_environment": {"packages": [{"id": "s1", "room_temp": c(27), "room_rh": c(60),
                                            "inlet_pressure": none(rules), "outlet_pressure": none(rules)}]},
        "supply_air": {"packages": [{"id": "a1", "supply_temp": c(15), "supply_rh": c(90)}]},
        "heat_exchanger": {"packages": [{"id": "h1", "hx_type": "Fin&Tube", "tube_diameter": "7",
                                         "fin_type": "Louver", "row_count": "2", "fpi": "18"}]},
        "filter": {"enabled": False},
        "installation": {"enabled": True, "data": {"scene": "설치 1"}},
        "leakage": {"packages": [{"id": "l1", **{k: c("값") for k in rules.groups["leakage"].fields}}]},
        "particles": {"packages": [{"id": "q1", **{k: c("값") for k in rules.groups["particles"].fields}}]},
        "multiphase": {"packages": [{"id": "m1", **{k: c("값") for k in rules.groups["multiphase"].fields}}]},
        "pcb": pcb,
    }


def make_form(rules, ref, issuer, analysis_type="AIRFLOW_PATTERN", request_type="QUALITY_IMPROVEMENT",
              **target):
    """제출 조건(Case 제외)을 모두 채운 의뢰서."""
    form = confirmed(rules, ref, issuer, analysis_type, **target)
    edited = {**copy.deepcopy(form), **content(rules, request_type)}
    edited["conditions"] = {**conditions(rules, ref, analysis_type), "measurement": form["conditions"]["measurement"]}
    form = merge_user_edit(form, edited)
    if request_type == "DEVELOPMENT_PROJECT":
        form = select_pms_project(form, PMS_SAC, ref.pms)
    return form


def edit(form, mutate):
    """의뢰자가 의뢰서를 고친다."""
    edited = copy.deepcopy(form)
    mutate(edited)
    return merge_user_edit(form, edited)


def locations(issues):
    return [i.location for i in issues]


@pytest.fixture
def check(ctx):
    return lambda form: check_form(form, ctx)


__all__ = ["date"]
