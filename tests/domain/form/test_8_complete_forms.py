"""8장 제출 조건(Case 제외)을 모두 채운 의뢰서는 문제가 없다. 11개 해석유형 모두."""

from __future__ import annotations

import pytest

from h12.domain.form import active_groups, config_of

from .conftest import make_form

TYPES = ["AIRFLOW_RATE", "AIRFLOW_PATTERN", "CONDENSATION", "HX_VELOCITY_PROFILE", "AIRFLOW_REACH", "PDB",
         "REAL_USE", "DUST_BEHAVIOR", "PCB_HEAT", "MULTIPHASE", "REFRIGERANT_LEAK"]


@pytest.mark.parametrize("analysis_type", TYPES)
def test_complete_form_has_no_issues(rules, ref, issuer, check, analysis_type):
    assert check(make_form(rules, ref, issuer, analysis_type)) == []


def test_complete_development_project(rules, ref, issuer, check):
    assert check(make_form(rules, ref, issuer, request_type="DEVELOPMENT_PROJECT")) == []


def test_water_cooled_pcb(rules, ref, issuer, check):
    assert check(make_form(rules, ref, issuer, "PCB_HEAT", cooling_method="수랭식")) == []


def test_unconfirmed_target_blocks(rules, check):
    issues = check({})
    assert issues[0].location == "request_context"


@pytest.mark.parametrize("analysis_type,expected", [
    ("AIRFLOW_PATTERN", ["operating", "space_environment", "supply_air", "heat_exchanger", "installation"]),
    ("DUST_BEHAVIOR", ["operating", "heat_exchanger", "installation", "particles"]),
    ("REFRIGERANT_LEAK", ["operating", "heat_exchanger", "installation", "leakage"]),
])
def test_active_groups(rules, ref, issuer, analysis_type, expected):
    form = make_form(rules, ref, issuer, analysis_type)
    # 필터는 체크하지 않아 쓰지 않는다
    assert active_groups(form["conditions"], config_of(form, ref, rules), rules) == expected
