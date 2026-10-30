"""4.5 해석 제품."""

from __future__ import annotations

import pytest

from h12.domain.form import check_products, geometry_axis

from .conftest import cell, edit, locations, make_form


@pytest.fixture
def form(rules, ref, issuer):
    return make_form(rules, ref, issuer)


def test_base_product_exactly_one(rules, form):
    assert check_products(form, rules) == []
    no_base = edit(form, lambda f: f["geometry"].pop("base_product"))
    assert locations(check_products(no_base, rules)) == ["geometry.base_product"]


def test_comparison_products_zero_or_more(rules, form):
    only_base = edit(form, lambda f: f["geometry"].update(comparison_products=[]))
    assert check_products(only_base, rules) == []


def test_comparison_needs_difference(rules, form):
    no_diff = edit(form, lambda f: f["geometry"]["comparison_products"][0].pop("difference_from_base"))
    assert locations(check_products(no_diff, rules)) == ["geometry.comparison_products[0].difference_from_base"]


@pytest.mark.parametrize("drawing_no,ok", [("MEA-123", True), ("abc123", True), ("MEA 123", False),
                                           ("MEA_123", False), ("도면1", False), ("", False)])
def test_drawing_number_format(rules, form, drawing_no, ok):
    changed = edit(form, lambda f: f["geometry"]["base_product"].update(drawing_no=cell(rules, drawing_no)))
    assert (check_products(changed, rules) == []) is ok


def test_drawing_numbers_do_not_repeat(rules, form):
    same = edit(form, lambda f: f["geometry"]["comparison_products"][0].update(drawing_no=cell(rules, "mea12345601")))
    assert locations(check_products(same, rules)) == ["geometry.comparison_products[0].drawing_no"]


def test_geometry_axis_keeps_user_names(rules, form):
    named = edit(form, lambda f: f["geometry"]["comparison_products"][0].update(display_name=cell(rules, "개선안")))
    assert [(a.product_id, a.label, a.is_base) for a in geometry_axis(named)] == [
        ("p1", "형상 1", True), ("p2", "개선안", False)]
