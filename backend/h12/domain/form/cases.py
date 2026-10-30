"""Case 구성 — 업무정의서 6장, 8장.

Case는 형상 하나와 현재 활성인 조건 그룹의 패키지 선택을 묶는다. 조건 원본이 바뀌면
이전에 확인한 Case는 제출할 수 없고, 의뢰자가 다시 확인해야 한다.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
from typing import Any, Mapping

from h12.domain.reference import ReferenceSet
from h12.domain.workflow import Issue

from .conditions import active_groups
from .products import geometry_axis
from .rules import FormRules
from .target import config_of, is_locked

SINGLE = "$single"
MAX_AUTO_CASES = 200


def case_columns(form: Mapping[str, Any], reference: ReferenceSet, rules: FormRules) -> dict[str, tuple[str, ...]]:
    """현재 Case에서 선택할 활성 조건 그룹과 각 그룹의 선택지 ID."""
    config = config_of(form, reference, rules)
    conditions = form.get("conditions") or {}
    columns: dict[str, tuple[str, ...]] = {}
    for key in active_groups(conditions, config, rules):
        group = rules.groups[key]
        if group.single:
            columns[key] = (SINGLE,)
        else:
            columns[key] = tuple(p.get("id") for p in (conditions.get(key) or {}).get("packages") or []
                                if p.get("id"))
    return columns


def case_source_hash(form: Mapping[str, Any], reference: ReferenceSet, rules: FormRules) -> str:
    """Case 재확인이 필요한 원본(의뢰 대상·형상·활성 조건)의 안정적인 지문."""
    columns = case_columns(form, reference, rules)
    conditions = form.get("conditions") or {}
    context = form.get("request_context") or {}
    source = {
        "request_context": {
            key: context.get(key)
            for key in ("taxonomy_id", "analysis_type", "analysis_scope", "cooling_method", "reference_release")
        },
        "geometry": copy.deepcopy(form.get("geometry") or {}),
        "conditions": {key: copy.deepcopy(conditions.get(key) or {}) for key in columns},
    }
    encoded = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def confirm_cases(form: Mapping[str, Any], *, reference: ReferenceSet, rules: FormRules) -> dict[str, Any]:
    """유효한 Case 구성을 의뢰자가 확인했음을 기록한 새 의뢰서를 돌려준다."""
    issues = check_cases(form, reference=reference, rules=rules, require_confirmation=False)
    if issues:
        raise ValueError("Case 구성을 확인할 수 없다: " + "; ".join(issue.message for issue in issues))
    result = copy.deepcopy(dict(form))
    result["case_confirmation"] = {"source_hash": case_source_hash(form, reference, rules)}
    return result


def refresh_cases(form: Mapping[str, Any], *, reference: ReferenceSet, rules: FormRules) -> dict[str, Any]:
    """원본 변경 뒤 더 이상 고를 수 없는 Case 선택을 비우고 재확인을 요구한다.

    6장의 원본 변경 규칙을 적용한다. Case 행 자체는 보존해 의뢰자가 변경 전후를 비교하며 다시 조합한다.
    """
    result = copy.deepcopy(dict(form))
    if not is_locked(result):
        result.pop("case_confirmation", None)
        return result
    columns = case_columns(result, reference, rules)
    geometry_ids = {axis.product_id for axis in geometry_axis(result) if axis.product_id}
    for case in result.get("cases") or []:
        if not isinstance(case, dict):
            continue
        if case.get("geometry_id") not in geometry_ids:
            case["geometry_id"] = None
        selections = case.get("condition_package_ids")
        if not isinstance(selections, dict):
            continue
        for key in set(selections) - set(columns):
            selections.pop(key)
        for key, options in columns.items():
            if selections.get(key) not in options:
                selections[key] = None
    result.pop("case_confirmation", None)
    return result


def default_cases(form: Mapping[str, Any], *, reference: ReferenceSet, rules: FormRules) -> list[dict[str, Any]]:
    """형상마다 빈 기본 Case 한 행을 만든다 (6장)."""
    columns = case_columns(form, reference, rules)
    return [
        {
            "id": f"case-{number}",
            "geometry_id": axis.product_id,
            "condition_package_ids": {key: None for key in columns},
        }
        for number, axis in enumerate(geometry_axis(form), start=1)
        if axis.product_id
    ]


def auto_combine_cases(form: Mapping[str, Any], *, reference: ReferenceSet, rules: FormRules,
                       max_cases: int = MAX_AUTO_CASES) -> list[dict[str, Any]]:
    """형상과 활성 조건 패키지의 곱집합으로 Case를 만든다.

    자동 생성은 최대 200행으로 제한한다. 직접 조합한 Case에는 이 상한을 적용하지 않는다.
    """
    if not 1 <= max_cases <= MAX_AUTO_CASES:
        raise ValueError(f"자동 조합 상한은 1~{MAX_AUTO_CASES} 이다")
    columns = case_columns(form, reference, rules)
    geometry_ids = [axis.product_id for axis in geometry_axis(form) if axis.product_id]
    values = list(columns.values())
    if any(not options for options in values):
        return default_cases(form, reference=reference, rules=rules)
    count = len(geometry_ids)
    for options in values:
        count *= len(options)
    if count > max_cases:
        raise ValueError(f"자동 조합 결과 {count}건은 상한 {max_cases}건을 넘는다")
    cases = []
    for number, (geometry_id, selected) in enumerate(
            itertools.product(geometry_ids, itertools.product(*values)), start=1):
        cases.append({
            "id": f"case-{number}",
            "geometry_id": geometry_id,
            "condition_package_ids": dict(zip(columns, selected, strict=True)),
        })
    return cases


def check_cases(form: Mapping[str, Any], *, reference: ReferenceSet, rules: FormRules,
                require_confirmation: bool = True) -> list[Issue]:
    """8장 Case 제출 조건: 완전성, 중복, 입력값 사용 여부, 재확인을 검사한다."""
    if not is_locked(form):
        return []
    columns = case_columns(form, reference, rules)
    geometry_ids = {axis.product_id for axis in geometry_axis(form) if axis.product_id}
    cases = form.get("cases") or []
    issues: list[Issue] = []
    if not isinstance(cases, list) or not cases:
        return [Issue("cases", "Case: 하나 이상 있어야 한다")]

    seen_case_ids: set[str] = set()
    seen_combinations: dict[tuple[Any, ...], int] = {}
    used_geometry: set[str] = set()
    used_packages = {key: set() for key in columns if columns[key] != (SINGLE,)}
    for index, case in enumerate(cases):
        loc = f"cases[{index}]"
        if not isinstance(case, Mapping):
            issues.append(Issue(loc, "Case: 객체여야 한다"))
            continue
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            issues.append(Issue(f"{loc}.id", "Case: 고유 ID가 필요하다"))
        elif case_id in seen_case_ids:
            issues.append(Issue(f"{loc}.id", "Case: 고유 ID가 겹친다"))
        else:
            seen_case_ids.add(case_id)

        geometry_id = case.get("geometry_id")
        if geometry_id not in geometry_ids:
            issues.append(Issue(f"{loc}.geometry_id", "Case 형상: 입력한 해석 제품에서 골라야 한다"))
        else:
            used_geometry.add(geometry_id)

        selections = case.get("condition_package_ids")
        if not isinstance(selections, Mapping):
            issues.append(Issue(f"{loc}.condition_package_ids", "Case 조건: 활성 조건을 모두 골라야 한다"))
            continue
        extra = set(selections) - set(columns)
        for key in sorted(extra):
            issues.append(Issue(f"{loc}.condition_package_ids.{key}", "Case 조건: 현재 활성 조건이 아니다"))
        selected: list[Any] = []
        complete = geometry_id in geometry_ids
        for key, options in columns.items():
            value = selections.get(key)
            selected.append(value)
            if value not in options:
                issues.append(Issue(f"{loc}.condition_package_ids.{key}",
                                    "Case 조건: 현재 조건 패키지에서 골라야 한다"))
                complete = False
            elif options != (SINGLE,):
                used_packages[key].add(value)
        if complete:
            signature = (geometry_id, *selected)
            if signature in seen_combinations:
                issues.append(Issue(loc, f"Case: {seen_combinations[signature] + 1}번째 Case와 조합이 같다"))
            else:
                seen_combinations[signature] = index

    for geometry_id in sorted(geometry_ids - used_geometry):
        issues.append(Issue("cases", f"Case: 형상 {geometry_id}을(를) 쓰는 Case가 있어야 한다"))
    for key, package_ids in used_packages.items():
        for package_id in sorted(set(columns[key]) - package_ids):
            issues.append(Issue("cases", f"Case: {key} 조건 패키지 {package_id}을(를) 쓰는 Case가 있어야 한다"))

    if require_confirmation and not issues:
        confirmed = (form.get("case_confirmation") or {}).get("source_hash")
        if confirmed != case_source_hash(form, reference, rules):
            issues.append(Issue("cases", "Case: 형상 또는 조건이 바뀌었으므로 구성을 다시 확인해야 한다"))
    return issues
