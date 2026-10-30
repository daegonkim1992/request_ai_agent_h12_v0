"""4.3 의뢰 내용, 4.4 의뢰 유형별 변경, 5.1 자유 입력 200자."""

from __future__ import annotations

from datetime import date

import pytest

from h12.domain.form import check_content, clear_pms_project, request_title

from .conftest import cell, confirmed, edit, locations, make_form


@pytest.fixture
def form(rules, ref, issuer):
    return make_form(rules, ref, issuer)


def _issues(rules, form, today=date(2026, 11, 2)):
    return check_content(form, rules, today)


# 4.3 필수 항목
REQUIRED = [
    ("basic_info", "division"), ("basic_info", "department"), ("basic_info", "requester_name"),
    ("basic_info", "requester_role"), ("analysis_overview", "request_type"), ("analysis_overview", "model_suffix"),
    ("analysis_overview", "desired_completion_date"), ("analysis_overview", "request_description"),
    ("analysis_overview", "additional_result_request"),
]


@pytest.mark.parametrize("section,key", REQUIRED)
def test_4_3_required(rules, form, section, key):
    blank = edit(form, lambda f: f[section].pop(key))
    assert locations(_issues(rules, blank)) == [f"{section}.{key}"]


def test_5_4_unknown_fills_required(rules, form):
    unknown = edit(form, lambda f: f["analysis_overview"].update(model_suffix=cell(rules, "확인 필요")))
    assert _issues(rules, unknown) == []


def test_4_3_result_use_is_optional(rules, form):
    assert _issues(rules, form) == []
    with_use = edit(form, lambda f: f["analysis_overview"].update(decision_use=cell(rules, "design_review")))
    assert _issues(rules, with_use) == []


@pytest.mark.parametrize("section,key,value", [
    ("basic_info", "division", "공조연구소"),        # 직접 입력
    ("basic_info", "requester_role", "수석연구원"),
    ("analysis_overview", "development_grade", "B+"),
    ("analysis_overview", "npi_stage", "EVT"),
])
def test_4_3_custom_input_allowed(rules, ref, issuer, section, key, value):
    form = make_form(rules, ref, issuer, request_type="DEVELOPMENT_PROJECT")
    assert _issues(rules, edit(form, lambda f: f[section].update({key: cell(rules, value)}))) == []


def test_4_3_request_type_must_be_listed(rules, form):
    bad = edit(form, lambda f: f["analysis_overview"].update(request_type=cell(rules, "긴급")))
    assert locations(_issues(rules, bad)) == ["analysis_overview.request_type"]


def test_4_4_other_needs_free_text(rules, form):
    other = edit(form, lambda f: f["analysis_overview"].update(request_type=cell(rules, "OTHER")))
    assert locations(_issues(rules, other)) == ["analysis_overview.request_type_other"]
    filled = edit(other, lambda f: f["analysis_overview"].update(request_type_other=cell(rules, "교육용")))
    assert _issues(rules, filled) == []


def test_4_4_development_project_needs_pms_grade_npi(rules, form):
    dev = edit(form, lambda f: [f["analysis_overview"].update(request_type=cell(rules, "DEVELOPMENT_PROJECT")),
                                f["analysis_overview"].pop("development_grade"),
                                f["analysis_overview"].pop("npi_stage")])
    assert locations(_issues(rules, dev)) == [
        "analysis_overview.development_grade", "analysis_overview.npi_stage", "analysis_overview.pms_project"]


@pytest.mark.parametrize("request_type", ["QUALITY_IMPROVEMENT", "FIELD_ISSUE", "PRE_STUDY"])
def test_4_4_other_types_need_nothing_more(rules, ref, issuer, request_type):
    form = make_form(rules, ref, issuer, request_type=request_type)
    no_extra = edit(form, lambda f: [f["analysis_overview"].pop("development_grade"),
                                     f["analysis_overview"].pop("npi_stage")])
    assert _issues(rules, no_extra) == []


def test_4_4_pms_cleared_blocks_development_project(rules, ref, issuer):
    form = clear_pms_project(make_form(rules, ref, issuer, request_type="DEVELOPMENT_PROJECT"))
    assert locations(_issues(rules, form)) == ["analysis_overview.pms_project"]


def test_4_4_aidc_cannot_be_development_project(rules, ref, issuer):
    # G-12: AIDC 는 PMS 프로젝트가 없어 고를 수 없다
    aidc = ref.taxonomy.find("AIDC", "CDU", None, None).id
    form = make_form(rules, ref, issuer, taxonomy_id=aidc)
    dev = edit(form, lambda f: f["analysis_overview"].update(request_type=cell(rules, "DEVELOPMENT_PROJECT")))
    assert ref.pms.projects_of("AIDC") == []
    assert locations(_issues(rules, dev)) == ["analysis_overview.pms_project"]


@pytest.mark.parametrize("desired,ok", [("2026-11-01", False), ("2026-11-02", True), ("2026-11-03", True)])
def test_4_3_desired_date_not_before_request_date(rules, form, desired, ok):
    changed = edit(form, lambda f: f["analysis_overview"].update(desired_completion_date=cell(rules, desired)))
    assert (_issues(rules, changed) == []) is ok


def test_4_3_date_format(rules, form):
    bad = edit(form, lambda f: f["analysis_overview"].update(desired_completion_date=cell(rules, "다음 달")))
    assert locations(_issues(rules, bad)) == ["analysis_overview.desired_completion_date"]


@pytest.mark.parametrize("length,ok", [(200, True), (201, False)])
def test_5_1_free_text_200(rules, form, length, ok):
    changed = edit(form, lambda f: f["analysis_overview"].update(request_description=cell(rules, "가" * length)))
    assert (_issues(rules, changed) == []) is ok


def test_title(rules, ref, issuer):
    assert request_title(make_form(rules, ref, issuer, "PDB"), rules) == "[PDB] ARNU07GTRB4"
    assert request_title(confirmed(rules, ref, issuer, "PDB"), rules) == "[PDB] 모델명 미정"
