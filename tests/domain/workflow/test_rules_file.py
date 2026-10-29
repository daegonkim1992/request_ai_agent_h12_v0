"""규칙 파일 해석과 검증. 잘못된 규칙은 기동 시점에 막는다."""

from __future__ import annotations

import copy

import pytest

from h12.domain.workflow import RulesError, WorkflowRules
from h12.domain.workflow import engine as engine_module
from h12.domain.workflow import rules as rules_module
from h12.rulebook import load_yaml


@pytest.fixture
def raw():
    return load_yaml("workflow.yaml"), load_yaml("reason_codes.yaml")


def test_engine_implements_every_declared_name():
    assert set(engine_module._EFFECTS) == rules_module.EFFECTS
    assert set(engine_module._INPUT_CHECKS) == rules_module.INPUTS
    assert set(engine_module._ACTOR_CHECKS) == rules_module.ACTORS


def test_3_1_statuses(rules):
    assert set(rules.statuses) == {
        "DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED", "IN_PROGRESS", "ANALYSIS_REVISION_REQUESTED",
        "ON_HOLD", "RESULT_REVIEW", "COMPLETED", "REJECTED", "CANCELLED"}
    assert rules.terminal_statuses == {"COMPLETED", "REJECTED", "CANCELLED"}


def _broken(raw, mutate):
    workflow, reasons = copy.deepcopy(raw)
    mutate(workflow, reasons)
    return workflow, reasons


@pytest.mark.parametrize("name,mutate", [
    ("unknown status", lambda w, r: w["actions"]["submit"]["transitions"].update({"DRAFT": "SENT"})),
    ("unknown actor", lambda w, r: w["actions"]["submit"].update(actors=["admin"])),
    ("unknown effect", lambda w, r: w["actions"]["submit"].update(effects=["send_mail"])),
    ("unknown input", lambda w, r: w["actions"]["submit"].update(requires=["file"])),
    ("unknown pending", lambda w, r: w["actions"]["submit"].update(pending="any")),
    ("unknown pending in list", lambda w, r: w["actions"]["submit"].update(pending=["none", "any"])),
    ("empty pending list", lambda w, r: w["actions"]["submit"].update(pending=[])),
    ("from terminal", lambda w, r: w["actions"]["cancel"]["transitions"].update({"COMPLETED": "CANCELLED"})),
    ("reason set missing", lambda w, r: r.pop("hold")),
    ("reason code without set", lambda w, r: w["actions"]["reject"].pop("reason_codes")),
    ("duplicate event", lambda w, r: w["actions"]["cancel"].update(event="SUBMITTED")),
    ("exclusive none", lambda w, r: w.update(exclusive_pending=["none"])),
    ("unknown todo role", lambda w, r: w["todo"].update(ADMIN=[])),
    ("bad initial", lambda w, r: w.update(initial_status="NEW")),
])
def test_invalid_rules_rejected(raw, name, mutate):
    with pytest.raises(RulesError):
        WorkflowRules.from_dicts(*_broken(raw, mutate))
