"""의뢰 대상 — 업무정의서 4.2, 3.4-9, 3.4-10.

확정하면 의뢰 대상이 잠기고, 의뢰번호를 발급하며, 그 시점의 기준 데이터 릴리스를 의뢰에 남긴다.
조건 구성은 남긴 릴리스의 조건 매핑과 의뢰 대상으로 정해진다.
확정한 의뢰 대상을 바꾸려면 영향을 확인받아야 하고, 쓰지 않게 된 조건 값은 지우지 않고 보존한다.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Protocol

from h12.domain.reference import Mark, ProductPath, ReferenceSet
from h12.domain.workflow import Issue

from .conditions import (
    ConditionConfig, condition_config, default_pcb, group_mark, refresh_measurement, visible_groups,
)
from .errors import ConfirmationRequired, FormError
from .rules import FormRules

PRODUCT_KEYS = ("division", "product_lineup", "platform", "chassis")


@dataclass(frozen=True)
class TargetSelection:
    taxonomy_id: str
    analysis_type: str
    analysis_scope: str | None = None   # RAC Window 일 때만
    cooling_method: str | None = None   # PCB발열일 때만


@dataclass(frozen=True)
class TargetChange:
    """확정한 의뢰 대상을 바꿀 때 확인받는 영향 (4.2, 4.6)."""

    product_changed: bool
    analysis_type_changed: bool
    pms_cleared: bool                     # 제품 분류가 바뀌어 PMS 프로젝트를 비운다
    hidden_groups: tuple[str, ...]        # 새 구성에서 보이지 않게 되는 조건 그룹. 값은 보존한다
    added_groups: tuple[str, ...]         # 새로 생기는 조건 그룹


class RequestNumberIssuer(Protocol):
    """3.4-9 의뢰번호 발급. 한번 발급한 번호는 취소되어도 다시 쓰지 않는다."""

    def issue(self, day: date) -> str: ...


class InMemoryNumberIssuer:
    """날짜별 일련번호. 저장소 구현(5단계)이 생기기 전까지 쓴다."""

    def __init__(self, number_format: str):
        self.number_format = number_format
        self._last: dict[date, int] = {}

    def issue(self, day: date) -> str:
        seq = self._last.get(day, 0) + 1
        self._last[day] = seq
        return self.number_format.format(date=day, seq=seq)


# ── 조회 ──────────────────────────────────────────────────

def target_items(path: ProductPath, analysis_type: str, rules: FormRules) -> set[str]:
    """이 제품과 해석유형에서 고르는 의뢰 대상 항목 (analysis_scope, cooling_method)."""
    items = set()
    if any(_matches(path, cond) for cond in rules.target.analysis_scope_products):
        items.add("analysis_scope")
    if analysis_type in rules.target.cooling_method_types:
        items.add("cooling_method")
    return items


def is_locked(form: Mapping[str, Any]) -> bool:
    return bool((form.get("request_context") or {}).get("locked"))


def pinned_release(form: Mapping[str, Any]) -> str | None:
    """3.4-10 의뢰가 따르는 기준 데이터 릴리스."""
    return (form.get("request_context") or {}).get("reference_release")


def config_of(form: Mapping[str, Any], reference: ReferenceSet, rules: FormRules) -> ConditionConfig:
    """확정한 의뢰 대상의 조건 구성. reference 는 의뢰가 남긴 릴리스여야 한다."""
    ctx = form.get("request_context") or {}
    if not ctx.get("locked"):
        raise FormError("의뢰 대상이 확정되지 않았다")
    if reference.release != ctx.get("reference_release"):
        raise FormError(f"의뢰는 기준 데이터 {ctx.get('reference_release')} 를 따른다 ({reference.release} 가 아니다)")
    return condition_config(reference.condition_mapping, ctx["analysis_type"], ctx.get("cooling_method"), rules)


def check_selection(selection: TargetSelection, reference: ReferenceSet, rules: FormRules) -> list[Issue]:
    issues = []
    path = reference.taxonomy.get(selection.taxonomy_id)
    if path is None:
        issues.append(Issue("request_context.taxonomy_id", "제품 분류: 등록된 분류에서 골라야 한다"))
    if selection.analysis_type not in rules.analysis_types:
        issues.append(Issue("request_context.analysis_type", "해석유형: 11종 중에서 골라야 한다"))
    elif selection.analysis_type not in reference.condition_mapping.marks:
        issues.append(Issue("request_context.analysis_type", "해석유형: 조건 매핑에 없다"))
    if issues:
        return issues
    items = target_items(path, selection.analysis_type, rules)
    for key, label, options in (("analysis_scope", "해석 범위", "analysis_scope"),
                                ("cooling_method", "냉각 방식", "cooling_method")):
        value = getattr(selection, key)
        choices = rules.options[options]
        if key not in items:
            if value is not None:
                issues.append(Issue(f"request_context.{key}", f"{label}: 이 의뢰 대상에서는 고르지 않는다"))
        elif value is None and choices.default is None:
            issues.append(Issue(f"request_context.{key}", f"{label}: 골라야 한다"))
        elif value is not None and value not in choices.choices:
            issues.append(Issue(f"request_context.{key}", f"{label}: {list(choices.choices.values())} 중에서 골라야 한다"))
    return issues


def target_change(form: Mapping[str, Any], selection: TargetSelection, reference: ReferenceSet,
                  rules: FormRules) -> TargetChange | None:
    """확정한 의뢰 대상과 달라지는 점. 확정 전이거나 같으면 None.
    다시 확정하면 지금 릴리스를 따르므로 두 구성 모두 지금 릴리스(reference)의 매핑으로 비교한다."""
    ctx = form.get("request_context") or {}
    if not ctx.get("locked"):
        return None
    new_ctx = _context(selection, reference, rules)
    keys = ("taxonomy_id", "analysis_type", "analysis_scope", "cooling_method")
    if all(ctx.get(k) == new_ctx[k] for k in keys):
        return None
    old = condition_config(reference.condition_mapping, ctx["analysis_type"], ctx.get("cooling_method"), rules)
    new = condition_config(reference.condition_mapping, new_ctx["analysis_type"], new_ctx["cooling_method"], rules)
    old_groups, new_groups = set(visible_groups(old, rules)), set(visible_groups(new, rules))
    product_changed = any(ctx.get(k) != new_ctx[k] for k in PRODUCT_KEYS)
    return TargetChange(
        product_changed=product_changed,
        analysis_type_changed=ctx.get("analysis_type") != new_ctx["analysis_type"],
        pms_cleared=product_changed and bool((form.get("analysis_overview") or {}).get("pms_project")),
        hidden_groups=tuple(g for g in rules.groups if g in old_groups - new_groups),
        added_groups=tuple(g for g in rules.groups if g in new_groups - old_groups),
    )


# ── 변경 ──────────────────────────────────────────────────

def confirm_target(form: Mapping[str, Any], selection: TargetSelection, *, reference: ReferenceSet,
                   rules: FormRules, issuer: RequestNumberIssuer, now: datetime,
                   accept_change: bool = False) -> dict[str, Any]:
    """의뢰 대상을 확정한 새 의뢰서를 돌려준다. reference 는 지금(확정 시점)의 릴리스다.

    이미 확정한 의뢰 대상을 바꾸면 accept_change=True 로 영향을 확인받아야 한다 (ConfirmationRequired).
    """
    issues = check_selection(selection, reference, rules)
    if issues:
        raise FormError("; ".join(f"{i.location}: {i.message}" for i in issues))
    change = target_change(form, selection, reference, rules)
    if change is not None and not accept_change:
        raise ConfirmationRequired(change)

    new = copy.deepcopy(dict(form))
    old_ctx = new.get("request_context") or {}
    ctx = _context(selection, reference, rules)
    ctx.update(locked=True, reference_release=reference.release, confirmed_at=now.isoformat())
    new["request_context"] = ctx

    basic = new.setdefault("basic_info", {})
    if not basic.get("request_no"):
        basic["request_no"] = issuer.issue(now.date())  # 다시 확정해도 번호는 그대로다

    # 4.4 PMS 프로젝트는 제품 사업부에 종속된다. 제품 분류가 바뀌면 비운다
    if old_ctx.get("locked") and any(old_ctx.get(k) != ctx[k] for k in PRODUCT_KEYS):
        (new.get("analysis_overview") or {}).pop("pms_project", None)

    config = condition_config(reference.condition_mapping, ctx["analysis_type"], ctx["cooling_method"], rules)
    conditions = new.setdefault("conditions", {})
    conditions["measurement"] = refresh_measurement(conditions.get("measurement"), config,
                                                    reference.measurement_standards)
    if group_mark(rules.groups["pcb"], config) is not Mark.HIDDEN and not conditions.get("pcb"):
        conditions["pcb"] = default_pcb(rules, ctx["cooling_method"] == rules.target.water_cooling)
    return new


def _context(selection: TargetSelection, reference: ReferenceSet, rules: FormRules) -> dict[str, Any]:
    path = reference.taxonomy.get(selection.taxonomy_id)
    items = target_items(path, selection.analysis_type, rules)
    return {
        "taxonomy_id": path.id,
        "division": path.division,
        "product_lineup": path.product_lineup,
        "platform": path.platform,
        "chassis": path.chassis,
        "display_path": path.display_path,
        "analysis_type": selection.analysis_type,
        "analysis_scope": selection.analysis_scope if "analysis_scope" in items else None,
        "cooling_method": selection.cooling_method if "cooling_method" in items else None,
    }


def _matches(path: ProductPath, cond: Mapping[str, str]) -> bool:
    return all(getattr(path, k) == v for k, v in cond.items())
