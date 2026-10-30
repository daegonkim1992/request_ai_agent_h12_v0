"""Case 구성 — 업무정의서 6장, 8장."""

from __future__ import annotations

import pytest

from h12.domain.form import (
    TargetSelection, auto_combine_cases, check_cases, confirm_cases, confirm_target, default_cases,
)

from .conftest import NOW, edit, locations, make_form, sac_ahu


def test_6_complete_cases_cover_all_geometry_and_active_packages(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    assert check_cases(form, reference=ref, rules=rules) == []


def test_6_each_active_column_must_be_selected(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    missing = edit(form, lambda f: f["cases"][0]["condition_package_ids"].pop("operating"))
    assert locations(check_cases(missing, reference=ref, rules=rules)) == [
        "cases[0].condition_package_ids.operating",
    ]


def test_6_duplicate_case_combination_is_rejected(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    duplicate = edit(form, lambda f: f["cases"][1].update(geometry_id="p1"))
    assert locations(check_cases(duplicate, reference=ref, rules=rules)) == ["cases[1]", "cases"]


def test_6_every_input_package_must_be_used(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    extra = edit(form, lambda f: f["conditions"]["operating"]["packages"].append({
        "id": "o2", "name": "운전 2", "fan_count": 1, "rpm_mode": rules.values.cell("common"),
        "rpm": rules.values.cell(900),
    }))
    issues = check_cases(extra, reference=ref, rules=rules)
    assert locations(issues) == ["cases"]
    assert "o2" in issues[0].message


def test_6_removing_a_package_clears_its_case_selection(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    changed = edit(form, lambda f: f["conditions"]["operating"]["packages"].pop())
    assert [case["condition_package_ids"]["operating"] for case in changed["cases"]] == [None, None]
    assert "case_confirmation" not in changed


def test_6_disabling_an_optional_condition_clears_its_case_selection(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    enabled = edit(form, lambda f: f["conditions"].update(filter={
        "enabled": True,
        "packages": [{
            "id": "f1",
            "filters": [{
                "id": "filter-1",
                "name": rules.values.cell("프리필터"),
                "points": [{"velocity": rules.values.cell(1), "pressure_loss": rules.values.cell(2)}],
            }],
        }],
    }))
    enabled["cases"] = [
        {**case, "condition_package_ids": {**case["condition_package_ids"], "filter": "f1"}}
        for case in enabled["cases"]
    ]
    disabled = edit(enabled, lambda f: f["conditions"]["filter"].update(enabled=False))
    assert [case["condition_package_ids"]["filter"] for case in disabled["cases"]] == [None, None]


def test_6_source_change_requires_case_reconfirmation(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    changed = edit(form, lambda f: f["conditions"]["operating"]["packages"][0].update(
        rpm=rules.values.cell(900)))
    issues = check_cases(changed, reference=ref, rules=rules)
    assert locations(issues) == ["cases"]
    assert "다시 확인" in issues[0].message
    assert check_cases(confirm_cases(changed, reference=ref, rules=rules), reference=ref, rules=rules) == []


def test_6_target_change_requires_case_reconfirmation_even_when_columns_match(rules, ref, issuer):
    form = make_form(rules, ref, issuer, "AIRFLOW_RATE")
    changed = confirm_target(
        form, TargetSelection(sac_ahu(ref), "HX_VELOCITY_PROFILE"), reference=ref, rules=rules, issuer=issuer,
        now=NOW, accept_change=True,
    )
    issues = check_cases(changed, reference=ref, rules=rules)
    assert locations(issues) == ["cases"]
    assert "다시 확인" in issues[0].message


def test_6_inactive_condition_is_not_a_case_option(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    invalid = edit(form, lambda f: f["cases"][0]["condition_package_ids"].update(filter="f1"))
    assert locations(check_cases(invalid, reference=ref, rules=rules)) == [
        "cases[0].condition_package_ids.filter",
    ]


def test_6_default_cases_add_one_blank_row_per_geometry(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    rows = default_cases(form, reference=ref, rules=rules)
    assert [(row["id"], row["geometry_id"]) for row in rows] == [("case-1", "p1"), ("case-2", "p2")]
    assert all(value is None for value in rows[0]["condition_package_ids"].values())


def test_6_auto_combination_has_a_hard_limit(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    form["conditions"]["operating"]["packages"] = [{"id": f"o{i}"} for i in range(101)]
    with pytest.raises(ValueError, match="상한"):
        auto_combine_cases(form, reference=ref, rules=rules)
