"""4.2 의뢰 대상, 3.4-9 의뢰번호, 3.4-10 기준 데이터 고정, 4.6 변경 영향."""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from h12.domain.form import (
    ConfirmationRequired, FormError, TargetSelection, check_selection, confirm_target, is_locked, pinned_release,
    select_pms_project, target_items,
)

from .conftest import NOW, PMS_SAC, confirmed, edit, make_form, path_id, sac_ahu, selection


def _rac_window(ref):
    return path_id(ref, "RAC", "Window", "Window", "WN")


def test_4_2_items_by_product_and_type(rules, ref):
    window = ref.taxonomy.get(_rac_window(ref))
    sac = ref.taxonomy.get(sac_ahu(ref))
    assert target_items(window, "AIRFLOW_PATTERN", rules) == {"analysis_scope"}  # RAC Window 만 해석 범위
    assert target_items(sac, "AIRFLOW_PATTERN", rules) == set()
    assert target_items(sac, "PCB_HEAT", rules) == {"cooling_method"}             # PCB발열만 냉각 방식
    # 실내·실외 구분은 RAC Window 뿐이다. 다른 RAC 제품에는 없다 (G-18)
    portable = ref.taxonomy.get(path_id(ref, "RAC", "Portable", "Portable", "PA"))
    assert target_items(portable, "AIRFLOW_PATTERN", rules) == set()


@pytest.mark.parametrize("scope,label", [("indoor", "실내측"), ("outdoor", "실외측"), ("both", "실내·실외 모두")])
def test_4_2_rac_window_scope(rules, ref, issuer, scope, label):
    form = confirmed(rules, ref, issuer, taxonomy_id=_rac_window(ref), analysis_scope=scope)
    assert form["request_context"]["analysis_scope"] == scope
    assert rules.options["analysis_scope"].label(scope) == label


def test_4_2_selection_rules(rules, ref):
    window = _rac_window(ref)
    assert check_selection(TargetSelection(window, "AIRFLOW_PATTERN", analysis_scope="both"), ref, rules) == []
    missing_scope = check_selection(TargetSelection(window, "AIRFLOW_PATTERN"), ref, rules)
    assert [i.location for i in missing_scope] == ["request_context.analysis_scope"]
    not_offered = check_selection(TargetSelection(sac_ahu(ref), "AIRFLOW_PATTERN", analysis_scope="both"), ref, rules)
    assert [i.location for i in not_offered] == ["request_context.analysis_scope"]
    no_cooling = check_selection(TargetSelection(sac_ahu(ref), "PCB_HEAT"), ref, rules)
    assert [i.location for i in no_cooling] == ["request_context.cooling_method"]
    unregistered = check_selection(TargetSelection("PT-NOPE", "AIRFLOW_PATTERN"), ref, rules)
    assert [i.location for i in unregistered] == ["request_context.taxonomy_id"]
    bad_type = check_selection(TargetSelection(sac_ahu(ref), "구조해석"), ref, rules)
    assert [i.location for i in bad_type] == ["request_context.analysis_type"]


def test_invalid_selection_is_not_confirmed(rules, ref, issuer):
    with pytest.raises(FormError):
        confirm_target({}, TargetSelection(sac_ahu(ref), "PCB_HEAT"), reference=ref, rules=rules,
                       issuer=issuer, now=NOW)


def test_4_2_confirm_locks_target_and_pins_release(rules, ref, issuer):
    form = confirmed(rules, ref, issuer, "AIRFLOW_PATTERN")
    ctx = form["request_context"]
    assert is_locked(form)
    assert ctx["context_locked"] is True
    assert ctx["taxonomy_version"] == ref.taxonomy.version
    assert ctx["condition_fieldset_key"] == "AIRFLOW_PATTERN"
    assert ctx["condition_fieldset_snapshot"]["analysis_type"] == "AIRFLOW_PATTERN"
    assert pinned_release(form) == ref.release  # 3.4-10
    assert (ctx["division"], ctx["product_lineup"], ctx["platform"], ctx["chassis"]) == ("SAC", "Multi V", "AHU", "10RT")
    assert ctx["display_path"] == "SAC > Multi V > AHU > 10RT"


def test_3_4_9_request_number(rules, ref, issuer):
    first = confirmed(rules, ref, issuer)
    second = confirmed(rules, ref, issuer)
    next_day = confirm_target({}, selection(ref, "AIRFLOW_PATTERN"), reference=ref, rules=rules, issuer=issuer,
                              now=datetime(2026, 11, 3, 9, 0))
    assert first["basic_info"]["request_no"] == "CFD-20261102-001"
    assert second["basic_info"]["request_no"] == "CFD-20261102-002"
    assert next_day["basic_info"]["request_no"] == "CFD-20261103-001"
    assert re.fullmatch(r"CFD-\d{8}-\d{3}", first["basic_info"]["request_no"])


def test_3_4_9_reconfirm_keeps_number(rules, ref, issuer):
    form = confirmed(rules, ref, issuer, "AIRFLOW_PATTERN")
    again = confirm_target(form, selection(ref, "AIRFLOW_RATE"), reference=ref, rules=rules, issuer=issuer,
                           now=NOW, accept_change=True)
    assert again["basic_info"]["request_no"] == form["basic_info"]["request_no"]


def test_4_2_change_needs_confirmation(rules, ref, issuer):
    form = confirmed(rules, ref, issuer, "AIRFLOW_PATTERN")
    with pytest.raises(ConfirmationRequired) as raised:
        confirm_target(form, selection(ref, "CONDENSATION"), reference=ref, rules=rules, issuer=issuer, now=NOW)
    change = raised.value.impact
    assert change.analysis_type_changed and not change.product_changed
    assert change.added_groups == () and change.hidden_groups == ()
    with pytest.raises(ConfirmationRequired) as raised:
        confirm_target(form, selection(ref, "DUST_BEHAVIOR"), reference=ref, rules=rules, issuer=issuer, now=NOW)
    assert raised.value.impact.hidden_groups == ("space_environment", "supply_air")
    assert raised.value.impact.added_groups == ("particles",)


def test_4_2_same_target_reconfirms_without_question(rules, ref, issuer):
    form = confirmed(rules, ref, issuer, "AIRFLOW_PATTERN")
    again = confirm_target(form, selection(ref, "AIRFLOW_PATTERN"), reference=ref, rules=rules, issuer=issuer,
                           now=NOW)
    assert again["request_context"]["reference_release"] == ref.release


def test_4_2_values_of_unused_conditions_are_kept(rules, ref, issuer):
    form = make_form(rules, ref, issuer, "AIRFLOW_PATTERN")
    changed = confirm_target(form, selection(ref, "DUST_BEHAVIOR"), reference=ref, rules=rules, issuer=issuer,
                             now=NOW, accept_change=True)
    assert changed["conditions"]["space_environment"] == form["conditions"]["space_environment"]


def test_4_4_product_change_clears_pms(rules, ref, issuer):
    form = make_form(rules, ref, issuer, "AIRFLOW_PATTERN", request_type="DEVELOPMENT_PROJECT")
    assert form["analysis_overview"]["pms_project"]["code"] == PMS_SAC
    other_sac = path_id(ref, "SAC", "Multi V", "AHU", "15RT")
    with pytest.raises(ConfirmationRequired) as raised:
        confirm_target(form, selection(ref, "AIRFLOW_PATTERN", taxonomy_id=other_sac), reference=ref, rules=rules,
                       issuer=issuer, now=NOW)
    assert raised.value.impact.pms_cleared
    changed = confirm_target(form, selection(ref, "AIRFLOW_PATTERN", taxonomy_id=other_sac), reference=ref,
                             rules=rules, issuer=issuer, now=NOW, accept_change=True)
    assert "pms_project" not in changed["analysis_overview"]
    # 해석유형만 바뀌면 PMS 는 그대로
    type_only = confirm_target(form, selection(ref, "AIRFLOW_RATE"), reference=ref, rules=rules, issuer=issuer,
                               now=NOW, accept_change=True)
    assert type_only["analysis_overview"]["pms_project"]["code"] == PMS_SAC


def test_5_3_11_standard_values_are_prefilled(rules, ref, issuer):
    form = confirmed(rules, ref, issuer, "PDB")
    # 표준값은 [추후 정의]라 아직 비어 있다
    assert form["conditions"]["measurement"] == {
        "temperature_criterion": {"value": None, "standard_value": None, "modified": False},
        "velocity_criterion": {"value": None, "standard_value": None, "modified": False},
    }


def test_5_3_9_pcb_defaults(rules, ref, issuer):
    # 정의서 5.3.9 기본값 표
    air = confirmed(rules, ref, issuer, "PCB_HEAT", cooling_method="공랭식")["conditions"]["pcb"]
    water = confirmed(rules, ref, issuer, "PCB_HEAT", cooling_method="수랭식")["conditions"]["pcb"]
    assert [(m["applied_part"], m["material_name"], m["thermal_conductivity"]) for m in air["materials"]] == [
        ("히트싱크", "알루미늄", 200), ("소자", "알루미늄", 200), ("PCB 보드", "PCB 보드 물성", None)]
    assert water["materials"][-1] == {"applied_part": "파이프", "material_name": "구리", "thermal_conductivity": 390}
    assert air["contact_resistance"] == {"enabled": False, "material": "Grease", "thermal_conductivity": 0.8,
                                         "thickness": 0.1, "location": None}


def test_4_4_pms_belongs_to_product_division(rules, ref, issuer):
    with pytest.raises(FormError):
        select_pms_project({}, PMS_SAC, ref.pms, rules=rules)  # 의뢰 대상 확정 전
    rac = confirmed(rules, ref, issuer, taxonomy_id=_rac_window(ref), analysis_scope="indoor")
    with pytest.raises(FormError):
        select_pms_project(rac, PMS_SAC, ref.pms, rules=rules)
    ready = edit(confirmed(rules, ref, issuer), lambda f: f.setdefault("analysis_overview", {}).update(
        request_type=rules.values.cell("DEVELOPMENT_PROJECT")))
    form = select_pms_project(ready, PMS_SAC, ref.pms, rules=rules)
    project = ref.pms.get(PMS_SAC)
    assert form["analysis_overview"]["pms_project"] == {
        "code": PMS_SAC, "project_name": project.project, "rep_model": project.rep_model,
        "region": project.region, "division": "SAC"}


def test_user_cannot_edit_target_number_or_pms(rules, ref, issuer):
    form = make_form(rules, ref, issuer, request_type="DEVELOPMENT_PROJECT")

    def tamper(f):
        f["request_context"]["analysis_type"] = "PDB"
        f["request_context"]["reference_release"] = "R1999-01-01"
        f["basic_info"]["request_no"] = "CFD-19990101-999"
        f["analysis_overview"]["pms_project"]["region"] = "Mars"
        f["basic_info"]["department"] = {"value": "공조설계팀"}

    edited = edit(form, tamper)
    assert edited["request_context"] == form["request_context"]
    assert edited["basic_info"]["request_no"] == form["basic_info"]["request_no"]
    assert edited["analysis_overview"]["pms_project"] == form["analysis_overview"]["pms_project"]
    assert edited["basic_info"]["department"] == {"value": "공조설계팀"}
