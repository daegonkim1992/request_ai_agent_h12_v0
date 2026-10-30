"""해석조건 — 업무정의서 5.1, 5.2, 5.3.

조건 구성(어떤 그룹·칸이 필수·선택·비표시인지)은 의뢰 대상을 확정한 릴리스의 조건 매핑과 의뢰 대상이 정한다.
그룹 데이터는 conditions.<그룹> 에 두며, 쓰지 않게 된 값도 지우지 않고 보존한다 (비활성 값).
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from h12.domain.reference import (
    ConditionMapping, HeatExchangerType, HxCatalog, HxSpec, Mark, MeasurementStandards, classify, is_flat_fin,
)

from .rules import FormRules, GroupRule, RulesError
from .values import Checker, Need, ValueStatus, value_of

_STRENGTH = {Mark.HIDDEN: 0, Mark.OPTIONAL: 1, Mark.REQUIRED: 2}


@dataclass(frozen=True)
class ConditionConfig:
    """5.2 해석유형과 냉각 방식으로 정해진 조건 구성."""

    analysis_type: str
    marks: Mapping[str, Mark]                # 매핑 열 → 기호
    measurement_items: tuple[str, ...]


def condition_config(mapping: ConditionMapping, analysis_type: str, cooling_method: str | None,
                     rules: FormRules) -> ConditionConfig:
    marks = dict(mapping.marks_for(analysis_type))
    for group in rules.groups.values():
        for column in _columns(group):
            if column not in marks:
                raise RulesError(f"조건 그룹 {group.key}: 매핑 열 {column} 이 조건 매핑에 없다")
    # 냉매 조건은 수랭식일 때만 (5.2, 5.3.9)
    if cooling_method != rules.target.water_cooling:
        marks["pcb_refrigerant"] = Mark.HIDDEN
    return ConditionConfig(analysis_type, marks, mapping.measurement_items(analysis_type))


def group_mark(group: GroupRule, config: ConditionConfig) -> Mark:
    """그룹 기호. 칸마다 열이 다른 그룹은 가장 강한 칸의 기호다."""
    return max((config.marks[c] for c in _columns(group)), key=_STRENGTH.__getitem__)


def field_need(group: GroupRule, key: str, config: ConditionConfig) -> Need | None:
    """칸의 필수 여부. None 이면 표시하지 않는다."""
    rule = group.fields[key]
    if rule.column is None:
        return Need.REQUIRED if rule.required else Need.OPTIONAL
    return {Mark.REQUIRED: Need.REQUIRED, Mark.OPTIONAL: Need.VALUE_OR_NONE}.get(config.marks[rule.column])


def is_active(group: GroupRule, data: Mapping[str, Any] | None, config: ConditionConfig) -> bool:
    """조건을 쓰는가. ● 는 항상 쓰고, ○ 는 사용 여부 체크박스를 따르며, — 는 쓰지 않는다."""
    mark = group_mark(group, config)
    if mark is Mark.HIDDEN:
        return False
    return mark is Mark.REQUIRED or not _toggled_off(group, data)


def active_groups(conditions: Mapping[str, Any], config: ConditionConfig, rules: FormRules) -> list[str]:
    return [k for k, g in rules.groups.items() if is_active(g, conditions.get(k), config)]


def visible_groups(config: ConditionConfig, rules: FormRules) -> list[str]:
    return [k for k, g in rules.groups.items() if group_mark(g, config) is not Mark.HIDDEN]


def _toggled_off(group: GroupRule, data: Mapping[str, Any] | None) -> bool:
    if group.toggle is None:
        return False
    return bool((data or {}).get(group.toggle.key, False)) == group.toggle.off_when


def _columns(group: GroupRule) -> list[str]:
    if group.column is not None:
        return [group.column]
    return list(dict.fromkeys(f.column for f in group.fields.values()))


# ── 기본값 ────────────────────────────────────────────────

def default_pcb(rules: FormRules, water_cooling: bool) -> dict[str, Any]:
    """5.3.9 PCB 조건의 기본값. 의뢰자가 고칠 수 있다."""
    contact = rules.pcb["contact_resistance_default"]
    materials = [
        {k: v for k, v in m.items() if k != "water_cooling_only"}
        for m in rules.pcb["materials_default"]
        if water_cooling or not m.get("water_cooling_only")
    ]
    return {
        "image": None,
        "device_basis": None,
        "devices": [],
        "contact_resistance": {"enabled": False, **contact, "location": None},
        "materials": materials,
        "refrigerant": {k: None for k in rules.pcb["refrigerant_fields"]},
    }


def refresh_measurement(current: Mapping[str, Any] | None, config: ConditionConfig,
                        standards: MeasurementStandards) -> dict[str, Any]:
    """5.3.11 측정·판정 기준에 표준값을 채운다. 의뢰자가 바꾼 값은 그대로 두고, 바꾸지 않은 값은 새 표준값을 따른다.
    지금 해석유형에 없는 항목도 지우지 않는다 (비활성 값)."""
    result = copy.deepcopy(dict(current or {}))
    defaults = standards.for_type(config.analysis_type)
    for key in config.measurement_items:
        standard = defaults.get(key)
        entry = result.get(key)
        if entry is None or not entry.get("modified"):
            result[key] = {"value": standard, "standard_value": standard, "modified": False}
        else:
            result[key] = {**entry, "standard_value": standard, "modified": entry.get("value") != standard}
    return result


# ── 검사 ──────────────────────────────────────────────────

def check_conditions(conditions: Mapping[str, Any], config: ConditionConfig, catalog: HxCatalog,
                     rules: FormRules) -> list:
    c = Checker(rules.values)
    for key, group in rules.groups.items():
        mark = group_mark(group, config)
        if mark is Mark.HIDDEN:
            continue
        data = conditions.get(key) or {}
        loc = f"conditions.{key}"
        if _toggled_off(group, data):
            if mark is Mark.REQUIRED:
                c.add(loc, f"{group.label}: 필수 조건이라 '{group.toggle.label}'로 둘 수 없다")
            else:
                continue
        if not group.single:
            _packages(c, loc, group, data.get("packages") or [], config)
        for name in group.checks:
            _CHECKS[name](c, loc, data, config, catalog, rules)
    _measurement(c, conditions.get("measurement") or {}, config, rules)
    return c.issues


def _packages(c: Checker, loc: str, group: GroupRule, packages: list, config: ConditionConfig) -> None:
    if not packages:
        c.add(f"{loc}.packages", f"{group.label}: 조건 패키지가 하나 이상 있어야 한다")
        return
    _unique_ids(c, f"{loc}.packages", packages, group.label)
    shown = [k for k in group.fields if field_need(group, k, config) is not None]
    for i, package in enumerate(packages):
        for key in shown:
            rule = group.fields[key]
            c.cell(f"{loc}.packages[{i}].{key}", package.get(key), rule.display,
                   field_need(group, key, config), kind=rule.kind)
    # 8장: 같은 내용의 조건 패키지가 중복되지 않는다
    seen: dict[str, int] = {}
    for i, package in enumerate(packages):
        content = {k: v for k, v in package.items() if k not in ("id", "name")}
        if group.fields:
            content = {k: content.get(k) for k in shown}
        signature = json.dumps(_normalize(content, c), sort_keys=True, ensure_ascii=False, default=str)
        if signature in seen:
            c.add(f"{loc}.packages[{i}]", f"{group.label}: {seen[signature] + 1}번째 패키지와 내용이 같다")
        else:
            seen[signature] = i


def _normalize(value: Any, c: Checker) -> Any:
    """내용 비교용. 칸은 (상태, 값)으로, 고유 ID 는 빼고 비교한다."""
    if isinstance(value, Mapping) and "value" in value and set(value) <= {"value", "status", "source"}:
        status = c.values.status(value)
        return [str(status), value_of(value) if status is ValueStatus.PROVIDED else None]
    if isinstance(value, Mapping):
        return {k: _normalize(v, c) for k, v in value.items() if k != "id"}
    if isinstance(value, list):
        return [_normalize(v, c) for v in value]
    return value


def _unique_ids(c: Checker, loc: str, items: list, label: str) -> None:
    ids = [item.get("id") for item in items]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        c.add(loc, f"{label}: 항목마다 서로 다른 고유 ID 가 있어야 한다")


def _operating(c: Checker, loc: str, data: Mapping, config: ConditionConfig, _catalog, rules: FormRules) -> None:
    """5.3.1 운전 조건, RPM과 풍량의 적용 규칙."""
    spec = rules.operating
    required = config.marks["operating"] is Mark.REQUIRED
    for i, p in enumerate(data.get("packages") or []):
        ploc = f"{loc}.packages[{i}]"
        airflow = c.cell(f"{ploc}.airflow", p.get("airflow"), "제품 풍량", Need.OPTIONAL, kind="number")
        has_airflow = airflow is ValueStatus.PROVIDED
        purpose = value_of(p.get("airflow_purpose"))
        if has_airflow:
            c.cell(f"{ploc}.airflow_purpose", p.get("airflow_purpose"), "풍량 활용 목적", Need.REQUIRED,
                   kind="choice", choices=spec["airflow_purposes"])
        mode = value_of(p.get("rpm_mode"))
        fans = p.get("fans") or []
        if mode == "individual":
            has_rpm = any(c.values.status(f.get("rpm")) is ValueStatus.PROVIDED for f in fans)
        else:
            has_rpm = c.values.status(p.get("rpm")) is ValueStatus.PROVIDED

        if not has_rpm and not has_airflow:
            c.add(ploc, "운전 조건: RPM 또는 풍량을 입력해야 한다" if required else
                  "운전 조건: RPM 또는 풍량을 입력하거나 '운전 조건 없음'을 선택해야 한다")
            continue
        if not has_rpm and purpose == "reference":
            c.add(f"{ploc}.rpm", "운전 조건: 풍량이 참고 정보이면 RPM을 입력해야 한다")
            continue
        if not has_rpm:
            continue  # 풍량을 해석에 반영한다. 팬 개수는 무시한다

        fan_count = value_of(p.get("fan_count"))
        if not isinstance(fan_count, int) or isinstance(fan_count, bool) or not 1 <= fan_count <= spec["max_fans"]:
            c.add(f"{ploc}.fan_count", f"팬 개수: 1~{spec['max_fans']} 사이여야 한다")
        c.cell(f"{ploc}.rpm_mode", p.get("rpm_mode"), "팬 회전수 설정 방식", Need.REQUIRED,
               kind="choice", choices=spec["rpm_modes"])
        if mode == "individual":
            if isinstance(fan_count, int) and len(fans) != fan_count:
                c.add(f"{ploc}.fans", "팬별 설정: 팬 개수만큼 팬마다 위치와 RPM을 입력해야 한다")
            for j, fan in enumerate(fans):
                c.cell(f"{ploc}.fans[{j}].location", fan.get("location"), "팬 위치", Need.REQUIRED)
                c.cell(f"{ploc}.fans[{j}].rpm", fan.get("rpm"), "팬 회전수 (rpm)", Need.REQUIRED, kind="number")
        else:
            c.cell(f"{ploc}.rpm", p.get("rpm"), "팬 회전수 (rpm)", Need.REQUIRED, kind="number")


def _heat_exchanger(c: Checker, loc: str, data: Mapping, _config, catalog: HxCatalog, _rules) -> None:
    """5.3.4 열교환기 사양. 네 사양의 조합은 Catalog 에 있어야 한다."""
    types = {t.value: t.value for t in HeatExchangerType}
    for i, p in enumerate(data.get("packages") or []):
        ploc = f"{loc}.packages[{i}]"
        hx_type = c.cell(f"{ploc}.hx_type", p.get("hx_type"), "열교환기 유형", Need.REQUIRED,
                         kind="choice", choices=types)
        spec_keys = {"tube_diameter": "관 직경(Pi) 또는 채널 폭", "fin_type": "Fin type", "row_count": "열 수",
                     "fpi": "FPI (또는 FPDM)"}
        filled = [c.cell(f"{ploc}.{k}", p.get(k), label, Need.REQUIRED) is ValueStatus.PROVIDED
                  for k, label in spec_keys.items()]
        if not all(filled):
            continue
        spec = HxSpec(*(str(value_of(p.get(k))).strip() for k in spec_keys))
        if hx_type is ValueStatus.PROVIDED and value_of(p["hx_type"]) != classify(spec.tube_diameter).value:
            c.add(f"{ploc}.hx_type", "열교환기 유형: 관 직경이 W로 시작하면 Micro-Channel, 아니면 Fin&Tube 다")
        if spec.type is HeatExchangerType.MICRO_CHANNEL and not is_flat_fin(spec.fin_type):
            c.add(f"{ploc}.fin_type", "Fin type: Micro-Channel 이면 Flat 이다")
        if not catalog.contains(spec):
            c.add(ploc, "열교환기 사양: 열교환기 Catalog 에 없는 조합이다")


def _filter(c: Checker, loc: str, data: Mapping, _config, _catalog, _rules) -> None:
    """5.3.5 필터: 패키지 → 물리적 필터 → 측정점(유속, 압력손실) 1개 이상."""
    for i, p in enumerate(data.get("packages") or []):
        ploc = f"{loc}.packages[{i}]"
        filters = p.get("filters") or []
        if not filters:
            c.add(f"{ploc}.filters", "필터: 물리적 필터가 하나 이상 있어야 한다")
            continue
        _unique_ids(c, f"{ploc}.filters", filters, "물리적 필터")
        for j, f in enumerate(filters):
            floc = f"{ploc}.filters[{j}]"
            c.cell(f"{floc}.name", f.get("name"), "필터 이름", Need.REQUIRED)
            points = f.get("points") or []
            if not points:
                c.add(f"{floc}.points", "필터: 측정점(유속, 압력손실)이 하나 이상 있어야 한다")
            for k, point in enumerate(points):
                c.cell(f"{floc}.points[{k}].velocity", point.get("velocity"), "유속 (m/s)", Need.REQUIRED,
                       kind="number")
                c.cell(f"{floc}.points[{k}].pressure_loss", point.get("pressure_loss"), "압력손실 (Pa)",
                       Need.REQUIRED, kind="number")


def _installation(c: Checker, loc: str, data: Mapping, _config, _catalog, _rules) -> None:
    """5.3.6 설치 조건. 세부 항목은 [추후 정의]라 3D 편집으로 저장한 값이 있는지만 본다."""
    if not data.get("data"):
        c.add(f"{loc}.data", "설치 조건: 3D 편집으로 설치 조건을 설정해야 한다")


def _pcb(c: Checker, loc: str, data: Mapping, config: ConditionConfig, _catalog, rules: FormRules) -> None:
    """5.3.9 PCB 조건."""
    spec = rules.pcb
    c.cell(f"{loc}.image", data.get("image"), "PCB 이미지", Need.REQUIRED)
    c.cell(f"{loc}.device_basis", data.get("device_basis"), "소자 기준", Need.REQUIRED,
           kind="choice", choices=spec["device_bases"])
    devices = data.get("devices") or []
    if not devices:
        c.add(f"{loc}.devices", "소자: 하나 이상 있어야 한다")
    for i, d in enumerate(devices):
        c.cell(f"{loc}.devices[{i}].name", d.get("name"), "소자 이름", Need.REQUIRED)
        c.cell(f"{loc}.devices[{i}].value", d.get("value"), "소자 값", Need.REQUIRED, kind="number")
    contact = data.get("contact_resistance") or {}
    if contact.get("enabled"):
        cloc = f"{loc}.contact_resistance"
        c.cell(f"{cloc}.material", contact.get("material"), "접촉재료", Need.REQUIRED)
        c.cell(f"{cloc}.thermal_conductivity", contact.get("thermal_conductivity"), "열전도도 (W/(m·K))",
               Need.REQUIRED, kind="number")
        c.cell(f"{cloc}.thickness", contact.get("thickness"), "두께 (mm)", Need.REQUIRED, kind="number")
        c.cell(f"{cloc}.location", contact.get("location"), "적용 위치", Need.REQUIRED)
    materials = data.get("materials") or []
    if not materials:
        c.add(f"{loc}.materials", "재료물성: 하나 이상 있어야 한다")
    for i, m in enumerate(materials):
        mloc = f"{loc}.materials[{i}]"
        c.cell(f"{mloc}.material_name", m.get("material_name"), "재료 이름", Need.REQUIRED)
        c.cell(f"{mloc}.thermal_conductivity", m.get("thermal_conductivity"), "열전도도 (W/(m·K))",
               Need.REQUIRED, kind="number")
        c.cell(f"{mloc}.applied_part", m.get("applied_part"), "적용 부품", Need.REQUIRED)
    if config.marks["pcb_refrigerant"] is not Mark.HIDDEN:
        refrigerant = data.get("refrigerant") or {}
        need = Need.REQUIRED if config.marks["pcb_refrigerant"] is Mark.REQUIRED else Need.VALUE_OR_NONE
        for key, field in spec["refrigerant_fields"].items():
            c.cell(f"{loc}.refrigerant.{key}", refrigerant.get(key), f"냉매 조건 {field['label']}", need,
                   kind=field.get("kind", "text"))


def _measurement(c: Checker, data: Mapping, config: ConditionConfig, rules: FormRules) -> None:
    """5.3.11 측정·판정 기준. 의뢰 전체에 하나만 둔다."""
    need = Need.REQUIRED if rules.measurement_required else Need.OPTIONAL
    for key in config.measurement_items:
        item = rules.measurement_items.get(key, {})
        label = f"{item.get('label', key)} ({item['unit']})" if item.get("unit") else item.get("label", key)
        c.cell(f"conditions.measurement.{key}", (data.get(key) or {}).get("value"), label, need)


_CHECKS: dict[str, Callable[..., None]] = {
    "operating": _operating,
    "heat_exchanger": _heat_exchanger,
    "filter": _filter,
    "installation": _installation,
    "pcb": _pcb,
}
