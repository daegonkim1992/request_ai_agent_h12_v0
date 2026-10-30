"""해석 제품 — 업무정의서 4.5.

Base 제품 정확히 1개, 비교 제품 0개 이상. 제품마다 도면번호가 있고 형식에 맞으며 서로 겹치지 않는다.
제품 순서대로 형상 1..N 을 만들고, 사용자가 고친 표시명은 보존한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .rules import FormRules
from .values import Checker, Need, ValueStatus, value_of


@dataclass(frozen=True)
class GeometryAxis:
    product_id: str
    label: str      # 사용자가 고친 표시명, 없으면 "형상 N"
    is_base: bool


def products(form: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], bool]]:
    geometry = form.get("geometry") or {}
    base = geometry.get("base_product")
    items = [(base, True)] if base else []
    return items + [(p, False) for p in geometry.get("comparison_products") or []]


def geometry_axis(form: Mapping[str, Any]) -> list[GeometryAxis]:
    axis = []
    for n, (product, is_base) in enumerate(products(form), start=1):
        name = value_of(product.get("display_name"))
        label = name.strip() if isinstance(name, str) and name.strip() else f"형상 {n}"
        axis.append(GeometryAxis(product_id=product.get("id"), label=label, is_base=is_base))
    return axis


def check_products(form: Mapping[str, Any], rules: FormRules) -> list:
    c = Checker(rules.values)
    geometry = form.get("geometry") or {}
    if not geometry.get("base_product"):
        c.add("geometry.base_product", "Base 제품: 정확히 1개 있어야 한다")
    seen: dict[str, str] = {}
    ids = []
    for product, is_base in products(form):
        loc = _location(form, product, is_base)
        ids.append(product.get("id"))
        status = c.cell(f"{loc}.drawing_no", product.get("drawing_no"), "도면번호", Need.REQUIRED)
        if status is ValueStatus.PROVIDED:
            drawing_no = str(value_of(product["drawing_no"])).strip()
            if not rules.drawing_no_pattern.fullmatch(drawing_no):
                c.add(f"{loc}.drawing_no", "도면번호: 영문·숫자·하이픈만 쓴다")
            key = drawing_no.upper()  # 대소문자만 다른 도면번호도 같은 것으로 본다 (G-25)
            if key in seen:
                c.add(f"{loc}.drawing_no", f"도면번호: {seen[key]} 와 같다. 제품끼리 겹칠 수 없다")
            else:
                seen[key] = loc
        c.cell(f"{loc}.display_name", product.get("display_name"), "표시명", Need.OPTIONAL)
        if not is_base:
            c.cell(f"{loc}.difference_from_base", product.get("difference_from_base"), "Base 대비 차이",
                   Need.REQUIRED)
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        c.add("geometry", "해석 제품: 제품마다 서로 다른 고유 ID 가 있어야 한다")
    return c.issues


def _location(form: Mapping[str, Any], product: Mapping[str, Any], is_base: bool) -> str:
    if is_base:
        return "geometry.base_product"
    others = (form.get("geometry") or {}).get("comparison_products") or []
    return f"geometry.comparison_products[{next(i for i, p in enumerate(others) if p is product)}]"
