"""5.3.4 열교환기 사양, 9장 열교환기 Catalog.

데이터 기대값은 원본 "압손DB_과제결과" 시트의 행에서 옮겼다.
"""

from __future__ import annotations

import pytest

from h12.domain.reference import (
    HeatExchangerType, HxCatalog, HxSpec, ReferenceDataError, classify, is_flat_fin,
)

MC, FT = HeatExchangerType.MICRO_CHANNEL, HeatExchangerType.FIN_TUBE


@pytest.mark.parametrize("tube,expected", [("W16", MC), ("W10.5", MC), ("w14.5", MC), ("7", FT),
                                           ("9.52", FT), ("5+7", FT)])
def test_tube_diameter_starting_with_w_is_micro_channel(tube, expected):
    assert classify(tube) is expected


def test_types_offered():
    assert {t.value for t in HeatExchangerType} == {"Fin&Tube", "Micro-Channel"}


def test_micro_channel_fin_type_is_fixed_flat(catalog):
    assert catalog.tube_diameters(MC) == ["W10.5", "W14.5", "W16"]
    for tube in catalog.tube_diameters(MC):
        fins = catalog.fin_types(tube)
        assert len(fins) == 1 and is_flat_fin(fins[0])


def test_combination_must_be_in_catalog(catalog):
    assert catalog.contains(HxSpec("7", "Louver", "2", "18"))
    assert catalog.contains(HxSpec("W16", "Flat(MCC)", "1", "75"))
    assert not catalog.contains(HxSpec("7", "Louver", "2", "22"))
    assert not catalog.contains(HxSpec("W16", "Louver", "1", "75"))


def test_standard_mark_is_shown_and_non_standard_is_still_registered(catalog):
    assert catalog.entry(HxSpec("7", "Louver", "2", "18")).standard is True
    non_standard = catalog.entry(HxSpec("5", "Slit(Half)", "1", "22"))
    assert non_standard is not None and non_standard.standard is False


def test_options_narrow_in_order(catalog):
    assert catalog.fin_types("9.52") == ["Louver"]
    assert catalog.row_counts("9.52", "Louver") == ["3", "4"]
    assert catalog.fpis("7", "Louver", "2") == ["14", "17", "18", "19", "20", "21"]


def _raw(*specs):
    return {"version": "t", "entries": [
        {"id": f"H{i}", "tube_diameter": t, "fin_type": f, "row_count": r, "fpi": p, "standard": True}
        for i, (t, f, r, p) in enumerate(specs)]}


@pytest.mark.parametrize("name,raw", [
    ("empty", _raw()),
    ("micro-channel not flat", _raw(("W16", "Louver", "1", "75"))),
    ("duplicate", _raw(("7", "Louver", "2", "18"), ("7", "Louver", "2", "18"))),
    ("number not text", _raw(("7", "Louver", 2, "18"))),
])
def test_invalid_catalog_rejected(name, raw):
    with pytest.raises(ReferenceDataError):
        HxCatalog.from_dict(raw)
