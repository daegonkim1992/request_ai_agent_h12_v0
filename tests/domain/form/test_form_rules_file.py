"""의뢰서 규칙 파일 해석. 엔진이 모르는 이름은 읽는 시점에 막는다."""

from __future__ import annotations

import copy

import pytest

from h12.domain.form import FormRules, RulesError
from h12.domain.form import conditions as conditions_module
from h12.domain.form import rules as rules_module
from h12.rulebook import load_analysis_types, load_options, load_yaml


@pytest.fixture
def raw():
    return {name: load_yaml(f"{name}.yaml") for name in ("form", "target", "value_states", "conditions")}


def _build(raw):
    return FormRules.from_dicts(
        form=raw["form"], target=raw["target"], value_states=raw["value_states"], conditions=raw["conditions"],
        options=load_options(), analysis_types=load_analysis_types())


def test_engine_implements_every_declared_check():
    assert set(conditions_module._CHECKS) == rules_module.GROUP_CHECKS


def test_loads(raw):
    assert _build(raw).groups


@pytest.mark.parametrize("name,mutate", [
    ("unknown kind", lambda r: r["form"]["basic_info"]["department"].update(kind="file")),
    ("unknown options", lambda r: r["form"]["basic_info"]["division"].update(options="nope")),
    ("unknown request type", lambda r: r["form"]["analysis_overview"]["request_type_other"].update(
        required={"request_type": ["NOPE"]})),
    ("unknown required condition", lambda r: r["form"]["analysis_overview"]["request_type_other"].update(
        required={"pms": True})),
    ("unknown check", lambda r: r["conditions"]["groups"]["pcb"].update(checks=["thermal"])),
    ("field without column", lambda r: r["conditions"]["groups"]["supply_air"]["fields"]["supply_temp"].pop("column")),
    ("unknown cooling type", lambda r: r["target"].update(cooling_method_types=["NOPE"])),
    ("water cooling not an option", lambda r: r["target"].update(water_cooling="유랭식")),
    ("unknown path key", lambda r: r["target"].update(analysis_scope_products=[{"line": "Window"}])),
    ("unknown value status", lambda r: r["value_states"].update(fills_required=["provided", "maybe"])),
    ("provided must fill", lambda r: r["value_states"].update(fills_required=["unknown"])),
])
def test_invalid_rules_rejected(raw, name, mutate):
    broken = copy.deepcopy(raw)
    mutate(broken)
    with pytest.raises(RulesError):
        _build(broken)
