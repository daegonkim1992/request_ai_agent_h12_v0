"""5.1 공통 규칙, 5.3 조건 사전."""

from __future__ import annotations

import pytest

from h12.domain.form import check_form

from .conftest import cell, edit, locations, make_form, none


@pytest.fixture
def issues(ctx):
    return lambda form: [i for i in check_form(form, ctx) if i.location.startswith("conditions")]


def _op(form, **package):
    """운전 조건 패키지 하나를 바꾼다."""
    return edit(form, lambda f: f["conditions"]["operating"].update(packages=[{"id": "o1", **package}]))


# ── 5.3.1 운전 조건: RPM과 풍량의 적용 규칙 (정의서 표의 행 순서) ───────────

RPM = {"fan_count": 2, "rpm_mode": "common", "rpm": 1000}


@pytest.mark.parametrize("row,package,expected", [
    ("RPM만", RPM, []),
    ("풍량만 + 해석에 반영 (팬 개수 무시)", {"airflow": 10, "airflow_purpose": "reflect"}, []),
    ("둘 다 + 해석에 반영", {**RPM, "airflow": 10, "airflow_purpose": "reflect"}, []),
    ("둘 다 + 참고 정보", {**RPM, "airflow": 10, "airflow_purpose": "reference"}, []),
    ("풍량만 + 참고 정보", {"airflow": 10, "airflow_purpose": "reference"},
     ["conditions.operating.packages[0].rpm"]),
    ("둘 다 없음 (●)", {}, ["conditions.operating.packages[0]"]),
])
def test_5_3_1_rpm_and_airflow(rules, ref, issuer, issues, row, package, expected):
    form = make_form(rules, ref, issuer, "AIRFLOW_PATTERN")
    cells = {k: (cell(rules, v) if k != "fan_count" else v) for k, v in package.items()}
    assert locations(issues(_op(form, **cells))) == expected


def test_5_3_1_airflow_needs_purpose(rules, ref, issuer, issues):
    form = _op(make_form(rules, ref, issuer), fan_count=1, rpm_mode=cell(rules, "common"), rpm=cell(rules, 900),
               airflow=cell(rules, 10))
    assert locations(issues(form)) == ["conditions.operating.packages[0].airflow_purpose"]


def test_5_3_1_rpm_and_airflow_may_differ(rules, ref, issuer, issues):
    form = _op(make_form(rules, ref, issuer), fan_count=1, rpm_mode=cell(rules, "common"), rpm=cell(rules, 900),
               airflow=cell(rules, 99999), airflow_purpose=cell(rules, "reflect"))
    assert issues(form) == []


@pytest.mark.parametrize("fan_count,ok", [(0, False), (1, True), (10, True), (11, False), ("2", False)])
def test_5_3_1_fan_count(rules, ref, issuer, issues, fan_count, ok):
    form = _op(make_form(rules, ref, issuer), fan_count=fan_count, rpm_mode=cell(rules, "common"),
               rpm=cell(rules, 900))
    assert (issues(form) == []) is ok


def test_5_3_1_individual_fans(rules, ref, issuer, issues):
    fans = [{"location": cell(rules, "좌측"), "rpm": cell(rules, 900)},
            {"location": cell(rules, "우측"), "rpm": cell(rules, 950)}]
    form = make_form(rules, ref, issuer)
    assert issues(_op(form, fan_count=2, rpm_mode=cell(rules, "individual"), fans=fans)) == []
    no_location = [{"rpm": cell(rules, 900)}, fans[1]]
    assert locations(issues(_op(form, fan_count=2, rpm_mode=cell(rules, "individual"), fans=no_location))) == [
        "conditions.operating.packages[0].fans[0].location"]
    assert locations(issues(_op(form, fan_count=3, rpm_mode=cell(rules, "individual"), fans=fans))) == [
        "conditions.operating.packages[0].fans"]


def test_5_3_1_no_operating_only_when_optional(rules, ref, issuer, issues):
    # 다상유동·냉매누설은 운전이 ○: "운전 조건 없음"을 체크할 수 있다
    leak = make_form(rules, ref, issuer, "REFRIGERANT_LEAK")
    empty = _op(leak)
    assert locations(issues(empty)) == ["conditions.operating.packages[0]"]
    assert "운전 조건 없음" in issues(empty)[0].message
    off = edit(empty, lambda f: f["conditions"]["operating"].update(disabled=True))
    assert issues(off) == []
    # ● 인 유형에서는 쓸 수 없다
    pattern = edit(make_form(rules, ref, issuer), lambda f: f["conditions"]["operating"].update(disabled=True))
    assert locations(issues(pattern)) == ["conditions.operating"]


def test_5_3_1_operating_alternatives_are_packages(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer)
    two = edit(form, lambda f: f["conditions"]["operating"]["packages"].append(
        {"id": "o2", "fan_count": 1, "rpm_mode": cell(rules, "common"), "rpm": cell(rules, 1200)}))
    assert issues(two) == []


# ── 5.3.2 공간 환경, 5.3.3 취출 공기 ───────────────────────────────

def _space(form, **fields):
    return edit(form, lambda f: f["conditions"]["space_environment"]["packages"][0].update(fields))


def test_5_3_2_optional_field_needs_value_or_none(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "AIRFLOW_PATTERN")  # 공간 온도 ○, 공간 압력 ○
    assert issues(_space(form, room_temp=none(rules))) == []
    assert issues(_space(form, room_temp=cell(rules, "없음"))) == []
    assert locations(issues(_space(form, room_temp=cell(rules, "")))) == [
        "conditions.space_environment.packages[0].room_temp"]
    assert locations(issues(_space(form, inlet_pressure=cell(rules, "")))) == [
        "conditions.space_environment.packages[0].inlet_pressure"]


def test_5_3_2_required_field_cannot_be_none(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "CONDENSATION")  # 공간 온도·RH ●
    assert locations(issues(_space(form, room_rh=none(rules)))) == ["conditions.space_environment.packages[0].room_rh"]


def test_5_3_2_hidden_fields_are_ignored(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "AIRFLOW_PATTERN")  # 기류 패턴의 RH 는 표시하지 않는다
    assert issues(_space(form, room_rh=cell(rules, "아무 값"))) == []


def test_5_3_3_supply_rh_has_no_none(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "CONDENSATION")
    no_rh = edit(form, lambda f: f["conditions"]["supply_air"]["packages"][0].update(supply_rh=none(rules)))
    assert locations(issues(no_rh)) == ["conditions.supply_air.packages[0].supply_rh"]


def test_5_3_numbers(rules, ref, issuer, issues):
    form = _space(make_form(rules, ref, issuer, "PDB"), room_temp=cell(rules, "상온"))
    assert locations(issues(form)) == ["conditions.space_environment.packages[0].room_temp"]


# ── 5.3.4 열교환기 ──────────────────────────────────────────

def _hx(form, **spec):
    return edit(form, lambda f: f["conditions"]["heat_exchanger"]["packages"][0].update(spec))


def test_5_3_4_catalog_combination(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "CONDENSATION")
    assert locations(issues(_hx(form, fpi="22"))) == ["conditions.heat_exchanger.packages[0]"]
    mc = _hx(form, hx_type="Micro-Channel", tube_diameter="W16", fin_type="Flat(MCC)", row_count="1", fpi="75")
    assert issues(mc) == []


def test_5_3_4_type_follows_tube_diameter(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "CONDENSATION")
    wrong = _hx(form, hx_type="Fin&Tube", tube_diameter="W16", fin_type="Flat(MCC)", row_count="1", fpi="75")
    assert locations(issues(wrong)) == ["conditions.heat_exchanger.packages[0].hx_type"]


def test_5_3_4_micro_channel_is_flat(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "CONDENSATION")
    louver = _hx(form, hx_type="Micro-Channel", tube_diameter="W16", fin_type="Louver", row_count="1", fpi="75")
    assert "conditions.heat_exchanger.packages[0].fin_type" in locations(issues(louver))


def test_5_3_4_no_heat_exchanger_only_when_optional(rules, ref, issuer, issues):
    optional = edit(make_form(rules, ref, issuer, "AIRFLOW_PATTERN"),
                    lambda f: f["conditions"]["heat_exchanger"].update(none=True, packages=[]))
    assert issues(optional) == []
    required = edit(make_form(rules, ref, issuer, "CONDENSATION"),
                    lambda f: f["conditions"]["heat_exchanger"].update(none=True))
    assert locations(issues(required)) == ["conditions.heat_exchanger"]


def test_5_3_4_type_has_no_none(rules, ref, issuer, issues):
    form = _hx(make_form(rules, ref, issuer, "CONDENSATION"), hx_type="없음")
    assert "conditions.heat_exchanger.packages[0].hx_type" in locations(issues(form))


# ── 5.3.5 필터 ──────────────────────────────────────────────

FILTER = {"id": "f1", "name": "필터 1", "filters": [
    {"id": "A", "name": "프리필터", "points": [{"velocity": 1.0, "pressure_loss": 20}]},
    {"id": "B", "name": "메인필터", "points": [{"velocity": 1.0, "pressure_loss": 50},
                                              {"velocity": 2.0, "pressure_loss": 110}]},
]}


def _filter(form, **data):
    return edit(form, lambda f: f["conditions"].update(filter=data))


def test_5_3_5_filter_unchecked_means_none(rules, ref, issuer, issues):
    assert issues(_filter(make_form(rules, ref, issuer), enabled=False, packages=[FILTER])) == []


def test_5_3_5_filter_structure(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer)
    assert issues(_filter(form, enabled=True, packages=[FILTER])) == []
    assert locations(issues(_filter(form, enabled=True, packages=[]))) == ["conditions.filter.packages"]
    no_points = {**FILTER, "filters": [{"id": "A", "name": "프리필터", "points": []}]}
    assert locations(issues(_filter(form, enabled=True, packages=[no_points]))) == [
        "conditions.filter.packages[0].filters[0].points"]
    half_point = {**FILTER, "filters": [{"id": "A", "name": "프리필터", "points": [{"velocity": 1.0}]}]}
    assert locations(issues(_filter(form, enabled=True, packages=[half_point]))) == [
        "conditions.filter.packages[0].filters[0].points[0].pressure_loss"]


def test_5_3_5_packages_may_differ_in_filter_count(rules, ref, issuer, issues):
    one = {"id": "f2", "name": "필터 2", "filters": [FILTER["filters"][0]]}
    assert issues(_filter(make_form(rules, ref, issuer), enabled=True, packages=[FILTER, one])) == []


# ── 5.3.6 설치 ──────────────────────────────────────────────

def test_5_3_6_installation(rules, ref, issuer, issues):
    reach = make_form(rules, ref, issuer, "AIRFLOW_REACH")  # 설치 ● (변경)
    off = edit(reach, lambda f: f["conditions"].update(installation={"enabled": False}))
    assert locations(issues(off)) == ["conditions.installation", "conditions.installation.data"]
    pattern = make_form(rules, ref, issuer, "AIRFLOW_PATTERN")  # 설치 ○
    assert issues(edit(pattern, lambda f: f["conditions"].update(installation={"enabled": False}))) == []
    assert locations(issues(edit(pattern, lambda f: f["conditions"].update(installation={"enabled": True})))) == [
        "conditions.installation.data"]


# ── 5.3.7 누설, 5.3.8 입자, 5.3.10 다상 ─────────────────────

@pytest.mark.parametrize("analysis_type,group,required,optional", [
    ("REFRIGERANT_LEAK", "leakage",
     ["refrigerant", "location", "amount", "size", "pressure", "temperature", "duration"], ["notes"]),
    ("DUST_BEHAVIOR", "particles", ["density", "diameter", "duration", "total_amount"], []),
    ("MULTIPHASE", "multiphase", ["fluid", "initial_state", "mass_flow", "inlet_quality"],
     ["gas_velocity_or_flow", "liquid_velocity_or_flow", "notes"]),
])
def test_free_text_condition_fields(rules, ref, issuer, issues, analysis_type, group, required, optional):
    form = make_form(rules, ref, issuer, analysis_type)
    blank = edit(form, lambda f: f["conditions"][group]["packages"][0].update(
        {k: cell(rules, "") for k in required + optional}))
    assert locations(issues(blank)) == [f"conditions.{group}.packages[0].{k}" for k in required]


# ── 5.3.9 PCB ───────────────────────────────────────────────

def _pcb(form, mutate):
    return edit(form, lambda f: mutate(f["conditions"]["pcb"]))


def test_5_3_9_pcb_required_parts(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "PCB_HEAT")
    assert locations(issues(_pcb(form, lambda p: p.update(image=None, devices=[], materials=[])))) == [
        "conditions.pcb.image", "conditions.pcb.devices", "conditions.pcb.materials"]
    assert locations(issues(_pcb(form, lambda p: p.update(device_basis=cell(rules, "전류"))))) == [
        "conditions.pcb.device_basis"]


def test_5_3_9_default_board_conductivity_must_be_filled(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "PCB_HEAT")
    defaults = _pcb(form, lambda p: p.update(materials=[
        {"material_name": "PCB 보드 물성", "thermal_conductivity": None, "applied_part": "PCB 보드"}]))
    assert locations(issues(defaults)) == ["conditions.pcb.materials[0].thermal_conductivity"]


def test_5_3_9_contact_resistance_when_checked(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "PCB_HEAT")
    checked = _pcb(form, lambda p: p.update(contact_resistance={
        "enabled": True, "material": "Grease", "thermal_conductivity": 0.8, "thickness": 0.1, "location": None}))
    assert locations(issues(checked)) == ["conditions.pcb.contact_resistance.location"]


def test_5_3_9_refrigerant_only_for_water_cooling(rules, ref, issuer, issues):
    air = make_form(rules, ref, issuer, "PCB_HEAT", cooling_method="공랭식")
    water = make_form(rules, ref, issuer, "PCB_HEAT", cooling_method="수랭식")
    blank = lambda p: p.update(refrigerant={})  # noqa: E731
    assert issues(_pcb(air, blank)) == []
    assert len(issues(_pcb(water, blank))) == 5


# ── 5.3.11 측정·판정 기준 ───────────────────────────────────

def test_5_3_11_requester_may_change_standard_value(rules, ref, issuer):
    form = make_form(rules, ref, issuer, "AIRFLOW_REACH")
    changed = edit(form, lambda f: f["conditions"]["measurement"]["reach_velocity"].update(value=0.25))
    assert changed["conditions"]["measurement"]["reach_velocity"] == {
        "value": 0.25, "standard_value": None, "modified": True}
    tampered = edit(changed, lambda f: f["conditions"]["measurement"]["reach_velocity"].update(standard_value=0.25))
    assert tampered["conditions"]["measurement"]["reach_velocity"]["standard_value"] is None


def test_5_3_11_one_per_request_not_a_package(rules, ref, issuer):
    form = make_form(rules, ref, issuer, "PDB")
    assert set(form["conditions"]["measurement"]) == {"temperature_criterion", "velocity_criterion"}
    assert "packages" not in form["conditions"]["measurement"]


# ── 5.1 공통 ────────────────────────────────────────────────

def test_5_1_duplicate_packages(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "PDB")
    dup = edit(form, lambda f: f["conditions"]["space_environment"]["packages"].append(
        {**f["conditions"]["space_environment"]["packages"][0], "id": "s2", "name": "공간 2"}))
    assert locations(issues(dup)) == ["conditions.space_environment.packages[1]"]


def test_5_1_duplicate_ignores_hidden_fields(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "PDB")  # 공간 RH 는 PDB 에서 표시하지 않는다
    dup = edit(form, lambda f: f["conditions"]["space_environment"]["packages"].append(
        {**f["conditions"]["space_environment"]["packages"][0], "id": "s2", "room_rh": cell(rules, 10)}))
    assert locations(issues(dup)) == ["conditions.space_environment.packages[1]"]


def test_5_1_required_group_needs_a_package(rules, ref, issuer, issues):
    form = edit(make_form(rules, ref, issuer, "PDB"),
                lambda f: f["conditions"]["supply_air"].update(packages=[]))
    assert locations(issues(form)) == ["conditions.supply_air.packages"]


def test_5_1_package_ids_unique(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer)
    dup_id = edit(form, lambda f: f["conditions"]["operating"]["packages"].append(
        {"id": "o1", "fan_count": 1, "rpm_mode": cell(rules, "common"), "rpm": cell(rules, 1500)}))
    assert locations(issues(dup_id)) == ["conditions.operating.packages"]


def test_5_1_free_text_200_in_conditions(rules, ref, issuer, issues):
    form = make_form(rules, ref, issuer, "REFRIGERANT_LEAK")
    long = edit(form, lambda f: f["conditions"]["leakage"]["packages"][0].update(notes=cell(rules, "가" * 201)))
    assert locations(issues(long)) == ["conditions.leakage.packages[0].notes"]
