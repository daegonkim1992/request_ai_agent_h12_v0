"""의뢰서 검사 — 업무정의서 8장.

의뢰 대상, 의뢰 내용, 희망 완료일, 해석 제품, 해석조건, 열교환기, 자유 입력 길이를 본다.
Case(6장)를 포함하며, FormSubmissionChecker로 WorkflowEngine에 연결한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping

from h12.domain.reference import ReferenceDataError, ReferenceSet
from h12.domain.workflow import Issue

from .cases import check_cases
from .conditions import check_conditions
from .content import check_content
from .products import check_products
from .errors import FormError
from .rules import FormRules
from .target import config_of, is_locked, pinned_release


@dataclass(frozen=True)
class FormContext:
    rules: FormRules
    # 릴리스 ID → 기준 데이터. 의뢰가 남긴 릴리스로 검사한다 (3.4-10)
    reference: Callable[[str], ReferenceSet]
    # 의뢰 요청일. 희망 완료일은 이보다 앞설 수 없다
    request_date: date


def check_form(form: Mapping[str, Any], ctx: FormContext) -> list[Issue]:
    shape = form_shape_issues(form)
    if shape:
        return shape
    issues: list[Issue] = []
    if not is_locked(form):
        issues.append(Issue("request_context", "의뢰 대상: 확정되어 있어야 한다"))
    issues += check_content(form, ctx.rules, ctx.request_date)
    issues += check_products(form, ctx.rules)
    if is_locked(form):
        release = pinned_release(form)
        if not isinstance(release, str) or not release:
            issues.append(Issue("request_context.reference_release", "의뢰 대상: 기준 데이터 릴리스가 필요하다"))
        else:
            try:
                reference = ctx.reference(release)
                config = config_of(form, reference, ctx.rules)
            except (FormError, ReferenceDataError, KeyError, TypeError):
                issues.append(Issue("request_context", "의뢰 대상: 고정한 기준 데이터와 일치해야 한다"))
            else:
                issues += check_conditions(form.get("conditions") or {}, config, reference.hx_catalog, ctx.rules)
                issues += check_cases(form, reference=reference, rules=ctx.rules)
    return issues


def form_shape_issues(form: Mapping[str, Any]) -> list[Issue]:
    """JSON 컨테이너를 먼저 검사해 잘못된 입력이 AttributeError가 되지 않게 한다."""
    if not isinstance(form, Mapping):
        return [Issue("form", "의뢰서: 객체여야 한다")]
    issues: list[Issue] = []

    def mapping(value: Any, location: str) -> Mapping[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            issues.append(Issue(location, "객체여야 한다"))
            return {}
        return value

    def sequence(value: Any, location: str) -> list[Any]:
        if value is None:
            return []
        if not isinstance(value, list):
            issues.append(Issue(location, "배열이어야 한다"))
            return []
        return value

    for key in ("request_context", "basic_info", "analysis_overview", "geometry", "conditions"):
        mapping(form.get(key), key)

    overview = mapping(form.get("analysis_overview"), "analysis_overview")
    if overview.get("pms_project") is not None:
        mapping(overview.get("pms_project"), "analysis_overview.pms_project")

    geometry = mapping(form.get("geometry"), "geometry")
    if geometry.get("base_product") is not None:
        mapping(geometry.get("base_product"), "geometry.base_product")
    for index, product in enumerate(sequence(geometry.get("comparison_products"), "geometry.comparison_products")):
        mapping(product, f"geometry.comparison_products[{index}]")

    conditions = mapping(form.get("conditions"), "conditions")
    for key, data in conditions.items():
        if key == "measurement":
            measurement = mapping(data, f"conditions.{key}")
            for item_key, item in measurement.items():
                mapping(item, f"conditions.{key}.{item_key}")
            continue
        group = mapping(data, f"conditions.{key}")
        if "packages" in group:
            packages = sequence(group.get("packages"), f"conditions.{key}.packages")
            for index, package in enumerate(packages):
                package_map = mapping(package, f"conditions.{key}.packages[{index}]")
                if key == "operating" and "fans" in package_map:
                    fans = sequence(package_map.get("fans"), f"conditions.{key}.packages[{index}].fans")
                    for fan_index, fan in enumerate(fans):
                        mapping(fan, f"conditions.{key}.packages[{index}].fans[{fan_index}]")
                if key == "filter" and "filters" in package_map:
                    filters = sequence(package_map.get("filters"), f"conditions.{key}.packages[{index}].filters")
                    for filter_index, item in enumerate(filters):
                        filter_map = mapping(item, f"conditions.{key}.packages[{index}].filters[{filter_index}]")
                        if "points" in filter_map:
                            points = sequence(filter_map.get("points"),
                                              f"conditions.{key}.packages[{index}].filters[{filter_index}].points")
                            for point_index, point in enumerate(points):
                                mapping(point, f"conditions.{key}.packages[{index}].filters[{filter_index}].points[{point_index}]")
        if key == "pcb":
            for child in ("contact_resistance", "refrigerant"):
                if child in group:
                    mapping(group.get(child), f"conditions.pcb.{child}")
            for child in ("devices", "materials"):
                if child in group:
                    for index, item in enumerate(sequence(group.get(child), f"conditions.pcb.{child}")):
                        mapping(item, f"conditions.pcb.{child}[{index}]")

    for index, case in enumerate(sequence(form.get("cases"), "cases")):
        case_map = mapping(case, f"cases[{index}]")
        if "condition_package_ids" in case_map:
            mapping(case_map.get("condition_package_ids"), f"cases[{index}].condition_package_ids")
    return issues
