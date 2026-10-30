"""의뢰서 검사 — 업무정의서 8장 중 Case 를 뺀 영역.

의뢰 대상, 의뢰 내용, 희망 완료일, 해석 제품, 해석조건, 열교환기, 자유 입력 길이를 본다.
Case(6장)와 WorkflowEngine 의 제출 검사 연결은 4단계에서 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping

from h12.domain.reference import ReferenceSet
from h12.domain.workflow import Issue

from .conditions import check_conditions
from .content import check_content
from .products import check_products
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
    issues: list[Issue] = []
    if not is_locked(form):
        issues.append(Issue("request_context", "의뢰 대상: 확정되어 있어야 한다"))
    issues += check_content(form, ctx.rules, ctx.request_date)
    issues += check_products(form, ctx.rules)
    if is_locked(form):
        reference = ctx.reference(pinned_release(form))
        config = config_of(form, reference, ctx.rules)
        issues += check_conditions(form.get("conditions") or {}, config, reference.hx_catalog, ctx.rules)
    return issues
