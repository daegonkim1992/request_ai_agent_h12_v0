"""3.4-5 이전 revision 과 달라진 부분."""

from __future__ import annotations

from h12.domain.form import diff_forms

from .conftest import cell, edit, make_form, none


def _changes(before, after):
    return [(c.path, c.before, c.after, c.kind) for c in diff_forms(before, after)]


def test_no_change(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    assert diff_forms(form, form) == []


def test_changed_value(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    after = edit(form, lambda f: f["analysis_overview"].update(model_suffix=cell(rules, "ARNU09")))
    assert _changes(form, after) == [("analysis_overview.model_suffix", "ARNU07GTRB4", "ARNU09", "changed")]


def test_explicit_none_shows_as_none(rules, ref, issuer):
    form = make_form(rules, ref, issuer, "AIRFLOW_PATTERN")
    after = edit(form, lambda f: f["conditions"]["space_environment"]["packages"][0].update(room_temp=none(rules)))
    assert _changes(form, after) == [
        ("conditions.space_environment.packages[id=s1].room_temp", 27, "없음", "changed")]


def test_packages_are_matched_by_id(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    two = edit(form, lambda f: f["conditions"]["operating"]["packages"].insert(
        0, {"id": "o0", "fan_count": 1, "rpm_mode": cell(rules, "common"), "rpm": cell(rules, 700)}))
    changes = _changes(form, two)
    # 앞에 끼워 넣어도 기존 패키지(o1)는 바뀐 것으로 보이지 않는다
    assert {c[0].split("]")[0] for c in changes} == {"conditions.operating.packages[id=o0"}
    assert all(c[3] == "added" for c in changes)


def test_removed_product(rules, ref, issuer):
    form = make_form(rules, ref, issuer)
    after = edit(form, lambda f: f["geometry"].update(comparison_products=[]))
    changes = _changes(form, after)
    assert ("geometry.comparison_products", None, [], "added") in changes
    assert {c[3] for c in changes if c[0].startswith("geometry.comparison_products[id=p2]")} == {"removed"}
