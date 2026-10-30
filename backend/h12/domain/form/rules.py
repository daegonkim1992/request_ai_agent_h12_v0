"""의뢰서 규칙 — rules/form.yaml, target.yaml, value_states.yaml, conditions.yaml 을 해석한다.

파일은 읽지 않는다 (h12.rulebook 이 읽는다). 엔진이 모르는 이름은 읽는 시점에 막는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from h12.domain.reference import AnalysisType, OptionList

from .errors import FormError
from .values import ValueRules, ValueStatus

FIELD_KINDS = frozenset({"text", "date", "choice", "number"})
GROUP_CHECKS = frozenset({"operating", "heat_exchanger", "filter", "installation", "pcb"})
PATH_KEYS = frozenset({"division", "product_lineup", "platform", "chassis"})


class RulesError(FormError):
    """규칙 파일이 엔진이 아는 이름과 맞지 않는다."""


@dataclass(frozen=True)
class FieldRule:
    key: str
    label: str
    kind: str
    options: str | None = None
    required: bool = False
    # 이 의뢰 유형일 때만 필수 (required 보다 우선). None 이면 따지지 않는다
    required_for_types: frozenset[str] | None = None
    unit: str | None = None
    column: str | None = None  # 조건 칸: 칸마다 따르는 매핑 열

    @property
    def display(self) -> str:
        return f"{self.label} ({self.unit})" if self.unit else self.label


@dataclass(frozen=True)
class Toggle:
    key: str
    label: str
    off_when: bool


@dataclass(frozen=True)
class GroupRule:
    key: str
    label: str
    column: str | None
    package_label: str | None
    toggle: Toggle | None
    single: bool
    fields: Mapping[str, FieldRule]
    checks: tuple[str, ...]


@dataclass(frozen=True)
class TargetRules:
    analysis_scope_products: tuple[Mapping[str, str], ...]
    cooling_method_types: frozenset[str]
    water_cooling: str
    request_no_format: str


@dataclass(frozen=True)
class FormRules:
    values: ValueRules
    target: TargetRules
    sections: Mapping[str, Mapping[str, FieldRule]]  # basic_info, analysis_overview
    pms_required_for: frozenset[str]
    drawing_no_pattern: re.Pattern[str]
    groups: Mapping[str, GroupRule]
    operating: Mapping[str, Any]
    pcb: Mapping[str, Any]
    measurement_items: Mapping[str, Mapping[str, str]]
    measurement_required: bool
    options: Mapping[str, OptionList]
    analysis_types: Mapping[str, AnalysisType]

    @classmethod
    def from_dicts(cls, *, form: Mapping[str, Any], target: Mapping[str, Any], value_states: Mapping[str, Any],
                   conditions: Mapping[str, Any], options: Mapping[str, OptionList],
                   analysis_types: Mapping[str, AnalysisType]) -> FormRules:
        sections = {name: _fields(form.get(name) or {}, f"form.{name}", options) for name in
                    ("basic_info", "analysis_overview")}
        request_types = options["request_type"].choices
        for section in sections.values():
            for f in section.values():
                unknown = (f.required_for_types or frozenset()) - set(request_types)
                if unknown:
                    raise RulesError(f"{f.key}: 의뢰 유형 {sorted(unknown)} 이 없다")
        pms_required_for = frozenset(form.get("pms_required_for") or ())
        if pms_required_for - set(request_types):
            raise RulesError("pms_required_for: 없는 의뢰 유형")

        cooling_types = frozenset(target.get("cooling_method_types") or ())
        if cooling_types - set(analysis_types):
            raise RulesError("cooling_method_types: 없는 해석유형")
        water = target.get("water_cooling")
        if water not in options["cooling_method"].choices:
            raise RulesError(f"water_cooling {water!r} 은 냉각 방식 선택지에 없다")
        target_rules = TargetRules(
            analysis_scope_products=_paths(target.get("analysis_scope_products"), "analysis_scope_products"),
            cooling_method_types=cooling_types,
            water_cooling=water,
            request_no_format=target["request_no_format"],
        )

        return cls(
            values=_value_rules(value_states),
            target=target_rules,
            sections=sections,
            pms_required_for=pms_required_for,
            drawing_no_pattern=re.compile(form["drawing_no_pattern"]),
            groups={k: _group(k, v or {}) for k, v in (conditions.get("groups") or {}).items()},
            operating=conditions["operating"],
            pcb=conditions["pcb"],
            measurement_items=conditions.get("measurement_items") or {},
            measurement_required=bool(conditions.get("measurement_required", False)),
            options=options,
            analysis_types=analysis_types,
        )


def _value_rules(raw: Mapping[str, Any]) -> ValueRules:
    try:
        keywords = {ValueStatus(s): frozenset(w.casefold() for w in words)
                    for s, words in (raw.get("keywords") or {}).items()}
        fills = frozenset(ValueStatus(s) for s in raw.get("fills_required") or ())
    except ValueError as e:
        raise RulesError(f"value_states: {e}") from None
    if ValueStatus.PROVIDED not in fills:
        raise RulesError("value_states.fills_required 에 provided 가 있어야 한다")
    return ValueRules(keywords=keywords, fills_required=fills, max_text_length=int(raw["max_text_length"]))


def _fields(raw: Mapping[str, Any], where: str, options: Mapping[str, OptionList] | None) -> dict[str, FieldRule]:
    fields = {}
    for key, spec in raw.items():
        spec = spec or {}
        kind = spec.get("kind", "text")
        if kind not in FIELD_KINDS:
            raise RulesError(f"{where}.{key}: kind {kind!r} 은 엔진이 모른다")
        option_list = spec.get("options")
        if kind == "choice" and (options is None or option_list not in options):
            raise RulesError(f"{where}.{key}: 선택지 목록 {option_list!r} 이 없다")
        required = spec.get("required", False)
        for_types = None
        if isinstance(required, Mapping):
            if set(required) != {"request_type"}:
                raise RulesError(f"{where}.{key}: required 조건은 request_type 만 쓸 수 있다")
            for_types, required = frozenset(required["request_type"]), True
        fields[key] = FieldRule(
            key=key, label=spec.get("label", key), kind=kind, options=option_list, required=bool(required),
            required_for_types=for_types, unit=spec.get("unit"), column=spec.get("column"),
        )
    return fields


def _group(key: str, spec: Mapping[str, Any]) -> GroupRule:
    toggle = spec.get("toggle")
    checks = tuple(spec.get("checks") or ())
    if set(checks) - GROUP_CHECKS:
        raise RulesError(f"groups.{key}.checks: {sorted(set(checks) - GROUP_CHECKS)} 은 엔진이 모른다")
    fields = _fields(spec.get("fields") or {}, f"groups.{key}.fields", None)
    if spec.get("column") is None and any(f.column is None for f in fields.values()):
        raise RulesError(f"groups.{key}: 그룹 column 이 없으면 칸마다 column 이 있어야 한다")
    return GroupRule(
        key=key,
        label=spec.get("label", key),
        column=spec.get("column"),
        package_label=spec.get("package_label"),
        toggle=Toggle(toggle["key"], toggle["label"], bool(toggle["off_when"])) if toggle else None,
        single=bool(spec.get("single", False)),
        fields=fields,
        checks=checks,
    )


def _paths(raw: Any, where: str) -> tuple[Mapping[str, str], ...]:
    paths = tuple(dict(p) for p in raw or ())
    for p in paths:
        if not p or set(p) - PATH_KEYS:
            raise RulesError(f"{where}: 경로 조건의 키는 {sorted(PATH_KEYS)} 중에서 쓴다")
    return paths
