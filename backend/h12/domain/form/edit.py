"""의뢰자의 의뢰서 수정 — 업무정의서 3.4-1, 4.2, 4.3, 5.3.11.

의뢰자가 보낸 의뢰서를 그대로 쓰지 않는다. 시스템이 정하는 값은 지금 의뢰서의 값을 지킨다.
  - 의뢰 대상(request_context): 확정·변경은 confirm_target 으로만 한다
  - 의뢰번호(basic_info.request_no): 확정할 때 발급한다
  - PMS 프로젝트(analysis_overview.pms_project): select_pms_project 로만 고른다 (Code, Region 은 자동)
  - 측정·판정 기준의 표준값: 기준 데이터가 정한다. 표준값에서 바꿨는지는 값을 보고 다시 정한다
"""

from __future__ import annotations

import copy
from typing import Any, Mapping


def merge_user_edit(current: Mapping[str, Any], edited: Mapping[str, Any]) -> dict[str, Any]:
    new = copy.deepcopy(dict(edited))
    _keep(new, current, "request_context")
    _keep(new, current, "case_confirmation")
    _keep(new.setdefault("basic_info", {}), current.get("basic_info") or {}, "request_no")
    _keep(new.setdefault("analysis_overview", {}), current.get("analysis_overview") or {}, "pms_project")

    conditions = new.setdefault("conditions", {})
    edited_measurement = conditions.get("measurement") or {}
    measurement = {}
    for key, entry in ((current.get("conditions") or {}).get("measurement") or {}).items():
        value = (edited_measurement.get(key) or {}).get("value", entry.get("value"))
        standard = entry.get("standard_value")
        measurement[key] = {"value": value, "standard_value": standard, "modified": value != standard}
    if measurement or "measurement" in conditions:
        conditions["measurement"] = measurement
    if case_sources_changed(current, new):
        _clear_removed_case_choices(new)
        new.pop("case_confirmation", None)
    return new


def _keep(target: dict[str, Any], source: Mapping[str, Any], key: str) -> None:
    if key in source:
        target[key] = copy.deepcopy(source[key])
    else:
        target.pop(key, None)


def case_sources_changed(current: Mapping[str, Any], edited: Mapping[str, Any]) -> bool:
    """형상·조건의 사용자 수정은 Case 재확인을 무효화한다."""
    return ((current.get("geometry") or {}) != (edited.get("geometry") or {})
            or (current.get("conditions") or {}) != (edited.get("conditions") or {}))


def _clear_removed_case_choices(form: dict[str, Any]) -> None:
    """삭제된 형상·조건 패키지를 가리키던 Case 선택만 비운다.

    의뢰 대상 변경으로 열 자체가 달라지는 경우는 confirm_target → refresh_cases가 처리한다.
    """
    geometry = form.get("geometry") or {}
    products = [geometry.get("base_product")] + list(geometry.get("comparison_products") or [])
    geometry_ids = {product.get("id") for product in products if isinstance(product, Mapping) and product.get("id")}
    package_ids = {
        key: {package.get("id") for package in (data or {}).get("packages") or []
              if isinstance(package, Mapping) and package.get("id")}
        for key, data in (form.get("conditions") or {}).items()
        if isinstance(data, Mapping) and "packages" in data
    }
    for case in form.get("cases") or []:
        if not isinstance(case, dict):
            continue
        if case.get("geometry_id") not in geometry_ids:
            case["geometry_id"] = None
        selections = case.get("condition_package_ids")
        if not isinstance(selections, dict):
            continue
        for key, value in selections.items():
            data = (form.get("conditions") or {}).get(key)
            if _is_toggled_off(data) or (key in package_ids and value not in package_ids[key]):
                selections[key] = None


def _is_toggled_off(data: Any) -> bool:
    """현재 조건 사전의 선택 조건 토글로 꺼진 그룹인지 본다.

    해석유형 변경으로 숨겨지는 그룹은 reference가 필요한 refresh_cases가 처리한다.
    """
    if not isinstance(data, Mapping):
        return False
    return bool(data.get("disabled")) or bool(data.get("none")) or data.get("enabled") is False
