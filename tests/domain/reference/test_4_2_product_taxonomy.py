"""4.2 의뢰 대상의 제품 분류, 9장 제품 분류 기준 데이터."""

from __future__ import annotations

import pytest

from h12.domain.reference import PlatformMode, ProductTaxonomy, ReferenceDataError

# 9장: 252행, 사업부 5개
DIVISIONS = {"SAC", "RAC", "Air Care", "Chiller", "AIDC"}


def test_9_registered_paths(taxonomy):
    assert len(taxonomy.paths) == 252
    assert set(taxonomy.divisions()) == DIVISIONS


def test_4_2_platform_selection_by_division(taxonomy):
    assert taxonomy.platform_mode("SAC") is PlatformMode.SELECT
    assert taxonomy.platform_mode("Chiller") is PlatformMode.SELECT
    assert taxonomy.platform_mode("RAC") is PlatformMode.FROM_LINEUP
    assert taxonomy.platform_mode("Air Care") is PlatformMode.FROM_LINEUP
    assert taxonomy.platform_mode("AIDC") is PlatformMode.NONE


@pytest.mark.parametrize("division", ["RAC", "Air Care"])
def test_4_2_platform_follows_lineup(taxonomy, division):
    for lineup in taxonomy.lineups(division):
        assert taxonomy.platforms(division, lineup) == [lineup]


def test_4_2_sac_and_chiller_choose_platform_from_list(taxonomy):
    assert len(taxonomy.platforms("SAC", "Multi V")) > 1
    assert taxonomy.platforms("Chiller", "Screw") == ["Air Cooled", "Water Cooled"]


def test_4_2_aidc_has_no_platform(taxonomy):
    assert taxonomy.lineups("AIDC") == ["CDU"]
    assert taxonomy.platforms("AIDC", "CDU") == [None]


def test_4_2_rac_window_product(taxonomy):
    # 해석 범위를 고르는 RAC Window 제품: 사업부 RAC, Line-up Window, Platform Window
    assert taxonomy.platforms("RAC", "Window") == ["Window"]
    assert "WN" in taxonomy.chassis_options("RAC", "Window", "Window")


def test_4_2_na_is_a_real_chassis_only_for_duct(taxonomy):
    assert {p.platform for p in taxonomy.paths if p.chassis == "NA"} == {"Duct(Multi V)", "Duct(Single CAC)"}


def test_4_2_path_without_chassis_is_empty(taxonomy):
    assert taxonomy.chassis_options("Chiller", "Screw", "Air Cooled") == [None]
    assert taxonomy.find("Chiller", "Screw", "Air Cooled", None) is not None
    assert taxonomy.find("Chiller", "Screw", "Air Cooled", "NA") is None


def test_4_2_only_registered_combinations(taxonomy):
    assert taxonomy.find("SAC", "Multi V", "Duct(Multi V)", "NA") is not None
    assert taxonomy.find("SAC", "Multi V", "Duct(Multi V)", "ZZ") is None
    assert taxonomy.find("RAC", "Window", "WN", None) is None  # RAC 의 Platform 은 Line-up 이다


def test_4_2_classification_ends_at_chassis(taxonomy):
    # 원본 LEVEL3(LG, Friedrich 등)은 정의서에 없는 단계라 Chassis 선택지에 섞이지 않는다
    options = taxonomy.chassis_options("RAC", "Window", "Window")
    assert "LG" not in options and "Friedrich" not in options
    assert taxonomy.find("RAC", "Window", "Window", "WN") is not None


def test_path_lookup_by_id(taxonomy):
    path = taxonomy.find("SAC", "Multi V", "Duct(Multi V)", "NA")
    assert taxonomy.get(path.id) == path
    assert path.display_path == "SAC > Multi V > Duct(Multi V) > NA"


def _raw(*paths, modes=None):
    return {
        "version": "t",
        "platform_mode": modes or {"SAC": "select", "RAC": "from_lineup", "AIDC": "none"},
        "paths": [{"id": f"P{i}", **p} for i, p in enumerate(paths)],
    }


SAC = {"division": "SAC", "product_lineup": "Multi V", "platform": "AHU", "chassis": "10RT"}


@pytest.mark.parametrize("name,raw", [
    ("empty", _raw()),
    ("unknown division", _raw({**SAC, "division": "ESS"})),
    ("unknown mode", _raw(SAC, modes={"SAC": "auto"})),
    ("select without platform", _raw({**SAC, "platform": None})),
    ("from_lineup platform differs", _raw({"division": "RAC", "product_lineup": "Window",
                                          "platform": "WN", "chassis": None})),
    ("none with platform", _raw({"division": "AIDC", "product_lineup": "CDU", "platform": "CDU",
                                 "chassis": None})),
    ("empty string chassis", _raw({**SAC, "chassis": ""})),
    ("duplicate", _raw(SAC, SAC)),
    ("chassis and no chassis mixed", _raw(SAC, {**SAC, "chassis": None})),
])
def test_invalid_taxonomy_rejected(name, raw):
    with pytest.raises(ReferenceDataError):
        ProductTaxonomy.from_dict(raw)
