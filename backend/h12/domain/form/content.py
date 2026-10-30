"""의뢰 내용 — 업무정의서 4.3, 4.4.

PMS 프로젝트는 제품 사업부에 종속된다. 고르면 Project Code, Region 이 채워지고, 고른 값은 의뢰에 복사한다
(PMS 는 기준 데이터 릴리스에 고정하지 않는다).
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any, Mapping

from h12.domain.reference import PmsDirectory

from .errors import FormError
from .rules import FieldRule, FormRules
from .values import Checker, Need, ValueStatus, as_date, value_of


def check_content(form: Mapping[str, Any], rules: FormRules, request_date: date) -> list:
    c = Checker(rules.values)
    overview = form.get("analysis_overview") or {}
    request_type = value_of(overview.get("request_type"))
    for section, fields in rules.sections.items():
        data = form.get(section) or {}
        for key, rule in fields.items():
            if rule.required_for_types is not None and request_type not in rule.required_for_types:
                continue  # 이 의뢰 유형에서는 받지 않는다 (값은 보존)
            options = rules.options[rule.options] if rule.options else None
            c.cell(f"{section}.{key}", data.get(key), rule.label, _need(rule), kind=rule.kind,
                   choices=options.choices if options else None,
                   allow_custom=options.allow_custom if options else False)

    desired = as_date(value_of(overview.get("desired_completion_date")))
    if desired is not None and desired < request_date:
        c.add("analysis_overview.desired_completion_date", "희망 완료일: 의뢰 요청일보다 앞설 수 없다")

    if request_type in rules.pms_required_for:
        _check_pms(c, form)
    return c.issues


def _need(rule: FieldRule) -> Need:
    return Need.REQUIRED if rule.required else Need.OPTIONAL


def _check_pms(c: Checker, form: Mapping[str, Any]) -> None:
    pms = (form.get("analysis_overview") or {}).get("pms_project")
    division = (form.get("request_context") or {}).get("division")
    if not pms:
        c.add("analysis_overview.pms_project", "프로젝트명(PMS): 개발 프로젝트는 PMS 프로젝트를 골라야 한다")
    elif pms.get("division") != division:
        c.add("analysis_overview.pms_project", f"프로젝트명(PMS): 제품 사업부({division})의 프로젝트가 아니다")


def select_pms_project(form: Mapping[str, Any], code: str, pms: PmsDirectory) -> dict[str, Any]:
    """4.4 PMS 프로젝트를 고른다. 의뢰 대상의 제품 사업부 프로젝트만 고를 수 있다."""
    division = (form.get("request_context") or {}).get("division")
    if not (form.get("request_context") or {}).get("locked"):
        raise FormError("PMS 프로젝트는 의뢰 대상(제품 사업부)을 확정한 뒤 고른다")
    project = pms.get(code)
    if project is None or project.division != division:
        raise FormError(f"PMS 프로젝트 {code} 는 제품 사업부 {division} 의 프로젝트가 아니다")
    new = copy.deepcopy(dict(form))
    new.setdefault("analysis_overview", {})["pms_project"] = {
        "code": project.code,
        "project_name": project.project,
        "rep_model": project.rep_model,
        "region": project.region,
        "division": project.division,
    }
    return new


def clear_pms_project(form: Mapping[str, Any]) -> dict[str, Any]:
    new = copy.deepcopy(dict(form))
    (new.get("analysis_overview") or {}).pop("pms_project", None)
    return new


def request_title(form: Mapping[str, Any], rules: FormRules) -> str:
    """의뢰 제목 (자동). 형식은 정의서에 없어 정했다 [확인 필요] (G-20): [해석유형] 모델명"""
    analysis_type = (form.get("request_context") or {}).get("analysis_type")
    label = rules.analysis_types[analysis_type].label if analysis_type in rules.analysis_types else "해석유형 미정"
    model = value_of((form.get("analysis_overview") or {}).get("model_suffix"))
    if rules.values.classify(model) is not ValueStatus.PROVIDED:
        model = "모델명 미정"
    return f"[{label}] {model}"
