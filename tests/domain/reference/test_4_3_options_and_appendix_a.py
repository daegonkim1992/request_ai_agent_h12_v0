"""부록 A 해석유형, 4.2·4.3 선택지, 5.3.11 측정·판정 기준 표준값 자리."""

from __future__ import annotations

import pytest

from h12.domain.reference import ReferenceDataError, parse_options
from h12.rulebook import load_analysis_types, load_options

APPENDIX_A = [
    "풍량", "기류 패턴", "이슬맺힘", "열교환기 유속 프로파일", "기류 도달 거리", "PDB", "실사용 해석",
    "집진해석(먼지거동)", "PCB발열", "다상유동", "냉매누설",
]


def test_appendix_a_eleven_analysis_types():
    types = load_analysis_types()
    assert [t.label for t in types.values()] == APPENDIX_A
    assert all(t.description and len(t.suitable_for) == 3 for t in types.values())


def _labels(key):
    return list(load_options()[key].choices.values())


def test_4_3_requester_info():
    assert _labels("requester_division") == ["SAC", "RAC", "Aircare", "Chiller", "연구소"]
    assert _labels("requester_role") == ["책임연구원", "선임연구원", "연구원"]
    assert load_options()["requester_division"].allow_custom
    assert load_options()["requester_role"].allow_custom


def test_4_3_overview():
    options = load_options()
    assert _labels("request_type") == ["개발 프로젝트", "품질 개선", "필드 이슈", "선행 검토", "기타"]
    assert _labels("npi_stage") == ["CP", "DV", "PV", "MQ", "MP", "Pre MP", "미정"]
    # 정의서 예시 + PMS 원본의 Grade 값 (G-16)
    assert set(_labels("development_grade")) == {
        "A", "B", "Ca", "Cb", "D", "JDM", "ODM",
        "B_Mi", "Ca_Mi", "Ca_SW", "Cc", "Csw", "HW", "ND_Cb", "ND_D", "JDM_Ca", "JDM_Cb", "JDM_D",
        "JDM_파급", "ODM_CSKD", "ODM_ND", "ODM_OTS", "ODM_파급", "OTS_파생", "ECM_A", "ECM_Cb",
        "T1", "T2", "T3"}
    assert options["npi_stage"].allow_custom and options["development_grade"].allow_custom
    assert options["decision_use"].choices == {
        "problem_analysis": "문제 분석", "design_review": "설계 검토",
        "performance_validation": "성능 검증", "other": "기타", "undecided": "미정"}


def test_4_2_context_options():
    options = load_options()
    assert options["analysis_scope"].choices == {"indoor": "실내측", "outdoor": "실외측", "both": "실내·실외 모두"}
    assert _labels("operation_mode") == ["실내", "실외", "동시운전"]
    assert options["operation_mode"].default == "실내"
    assert _labels("cooling_method") == ["공랭식", "수랭식"]


def test_5_3_11_measurement_standard_slots(ref):
    standards = ref.measurement_standards
    assert {k: set(v) for k, v in standards.values.items()} == {
        "AIRFLOW_REACH": {"reach_velocity"},
        "REAL_USE": {"measurement_locations"},
        "PDB": {"temperature_criterion", "velocity_criterion"},
        "PCB_HEAT": {"allowable_temperature"},
    }
    assert set(standards.values) <= set(load_analysis_types())
    # 표준값은 [추후 정의]
    assert all(v is None for items in standards.values.values() for v in items.values())


@pytest.mark.parametrize("raw", [
    {"x": {"choices": []}},
    {"x": {"choices": ["a"], "default": "b"}},
])
def test_invalid_options_rejected(raw):
    with pytest.raises(ReferenceDataError):
        parse_options(raw)
