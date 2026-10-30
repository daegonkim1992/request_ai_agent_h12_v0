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
    return new


def _keep(target: dict[str, Any], source: Mapping[str, Any], key: str) -> None:
    if key in source:
        target[key] = copy.deepcopy(source[key])
    else:
        target.pop(key, None)
