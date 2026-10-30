"""9장 기준 데이터 변환. 원본 → 버전 파일.

변환 규칙은 작은 원본 행으로 확인하고, 저장소의 버전 파일이 원본에서 그대로 다시 만들어지는지도 확인한다
(원본 xlsx 는 h12 밖에 있어서 없으면 건너뛴다).
"""

from __future__ import annotations

import pytest

from h12.reference import default_store
from h12.reference.build import (
    BUILT_DATASETS, REPO_ROOT, BuildError, build_dataset, build_hx_catalog, build_pms, build_taxonomy,
    dumps, load_sources, read_rows,
)
from h12.reference.store import version_path
from h12.rulebook import load_options

RULES = {
    "platform_mode": {"SAC": "select", "RAC": "from_lineup", "AIDC": "none"},
    "na_chassis_platforms": ["Duct(Multi V)"],
    "fix_values": {},
    "exclude": [{"match": {"division": "ESS"}, "reason": "대상 아님"}],
    "add": [{"path": {"division": "AIDC", "product_lineup": "CDU"}, "reason": "추가"}],
}


def _taxonomy(*rows, **overrides):
    return build_taxonomy([(i + 2, r) for i, r in enumerate(rows)], {**RULES, **overrides})


def _paths(result):
    return [(p["division"], p["product_lineup"], p["platform"], p["chassis"]) for p in result["paths"]]


BASE = [("ESS", "PCS", "단상", "RSA")]


def test_taxonomy_column_mapping():
    result = _taxonomy(*BASE, ("SAC", "Multi V", "AHU", "10RT"), ("RAC", "Window", "WN", "LG"),
                       ("RAC", "Window", "WN", "NA"), ("RAC", "Wall Mounted", "Siganture(S7)", "NA"),
                       fix_values={"Siganture(S7)": "Signature(S7)"})
    assert _paths(result) == [
        ("SAC", "Multi V", "AHU", "10RT"),
        ("RAC", "Window", "Window", "WN"),               # LEVEL3 는 버리고 같은 분류로 합친다
        ("RAC", "Wall Mounted", "Wall Mounted", "Signature(S7)"),
        ("AIDC", "CDU", None, None),
    ]
    assert result["paths"][1]["source_rows"] == [4, 5]
    assert result["paths"][3]["note"] == "추가"


def test_taxonomy_na_chassis():
    result = _taxonomy(*BASE,
                       ("SAC", "Multi V", "Duct(Multi V)", "NA"), ("SAC", "Multi V", "Duct(Multi V)", "M1"),
                       ("SAC", "Chiller", "Air Cooled", "NA"),
                       ("SAC", "Multi V", "Water", "NA"), ("SAC", "Multi V", "Water", "UWB"))
    assert _paths(result)[:4] == [
        ("SAC", "Multi V", "Duct(Multi V)", "NA"),       # 실제 값
        ("SAC", "Multi V", "Duct(Multi V)", "M1"),
        ("SAC", "Chiller", "Air Cooled", None),          # Chassis 없음
        ("SAC", "Multi V", "Water", "UWB"),
    ]
    assert [(e["row"], e["reason"]) for e in result["excluded"]] == [
        (2, "대상 아님"), (6, "같은 Platform 에 다른 Chassis 가 있는 NA 행")]


def test_taxonomy_trims_whitespace_and_merges_duplicates():
    result = _taxonomy(*BASE, ("SAC", "Multi", "CST", "TP "), ("SAC", "Multi", "CST", "TP"))
    assert _paths(result)[0] == ("SAC", "Multi", "CST", "TP")
    assert result["paths"][0]["source_rows"] == [3, 4]


def test_taxonomy_ids_are_stable():
    first = _taxonomy(*BASE, ("SAC", "Multi V", "AHU", "10RT"), ("SAC", "Multi V", "AHU", "15RT"))
    second = _taxonomy(*BASE, ("SAC", "Multi V", "AHU", "15RT"))
    assert first["paths"][1]["id"] == second["paths"][0]["id"]


@pytest.mark.parametrize("name,rows,overrides", [
    ("division without rule", [*BASE, ("Chiller", "Screw", "Air Cooled", "NA")], {}),
    ("exclude rule matches nothing", [("SAC", "Multi V", "AHU", "10RT")], {}),
    ("fix rule matches nothing", [*BASE], {"fix_values": {"Typo": "Fixed"}}),
    ("added path already exists", [*BASE, ("SAC", "Multi V", "AHU", "10RT")],
     {"add": [{"path": {"division": "SAC", "product_lineup": "Multi V", "platform": "AHU",
                        "chassis": "10RT"}, "reason": "중복"}]}),
])
def test_taxonomy_build_errors(name, rows, overrides):
    with pytest.raises(BuildError):
        _taxonomy(*rows, **overrides)


HX_RULES = {
    "columns": {"관경": "tube_diameter", "핀타입": "fin_type", "열수": "row_count", "FPI": "fpi",
                "표준 여부": "standard"},
    "standard_marks": {"O": True, "X": False},
}
HX_HEADER = ("관경", "핀타입", "열수", "FPI", "두께", "표준 여부", "측정 방법", "(에코) 압손 [Pa]")


def _hx(*rows):
    return build_hx_catalog(HX_HEADER, [(i + 3, r) for i, r in enumerate(rows)], HX_RULES)


def test_hx_catalog_values_keep_source_notation():
    result = _hx((9.52, "Louver", 3, 18, None, "X", "해석", 1.2), ("5+7", "Slit(Half)", "1+2", "20+22", None, "X"),
                 (7.0, "Louver", 2, 18, None, "O"), ("W16", "Flat(MCC)", 1, 75, None, "O"),
                 ("비표준 포함 DB 보유", None, None, None, None, None), (None, None, None, None, None, None, "DB보유 수"))
    assert [(e["tube_diameter"], e["fin_type"], e["row_count"], e["fpi"], e["standard"]) for e in result["entries"]] == [
        ("9.52", "Louver", "3", "18", False),
        ("5+7", "Slit(Half)", "1+2", "20+22", False),
        ("7", "Louver", "2", "18", True),
        ("W16", "Flat(MCC)", "1", "75", True),
    ]


@pytest.mark.parametrize("rows", [
    [(7, "Louver", 2, 18, None, "?")],
    [(7, "Louver", 2, 18, None, "O"), (7, "Louver", 2, 18, None, "X")],
    [(7, "Louver", None, 18, None, "O")],
])
def test_hx_catalog_build_errors(rows):
    with pytest.raises(BuildError):
        _hx(*rows)


def test_hx_catalog_header_must_match():
    with pytest.raises(BuildError):
        build_hx_catalog(("관경", "핀 타입", "열수", "FPI", "표준 여부"), [], HX_RULES)


PMS_RULES = {"division_column": "Division",
             "columns": {"PMS Project Code": "code", "Project": "project", "Rep Model": "rep_model",
                         "Region": "region"}}
PMS_HEADER = ("No", "Division", "Project", "Rep Model", "P/Leader", "Region", "PMS Project Code")
CAC = {"file": "CAC.xlsx", "pms_division": "CAC", "division": "SAC"}


def _pms(*rows, file_rule=CAC):
    return build_pms([(file_rule, PMS_HEADER, [(i + 2, r) for i, r in enumerate(rows)])], PMS_RULES)


def test_pms_maps_division_and_drops_other_columns():
    result = _pms((1, "CAC", "Multi V Water5", "ARWM080", "홍길동(gildong.hong)", "Europe", "PJT1"),
                  (None, None, None, None, None, None, None))
    assert result["projects"] == [{"code": "PJT1", "division": "SAC", "project": "Multi V Water5",
                                   "rep_model": "ARWM080", "region": "Europe"}]


@pytest.mark.parametrize("rows", [
    [(1, "RAC", "p", "m", "", "Korea", "PJT1")],
    [(1, "CAC", "p", "m", "", "Korea", "PJT1"), (2, "CAC", "q", "n", "", "Korea", "PJT1")],
])
def test_pms_build_errors(rows):
    with pytest.raises(BuildError):
        _pms(*rows)


def test_dumps_writes_one_item_per_line():
    text = dumps({"dataset": "x", "items": [{"a": 1}, {"a": "가"}], "empty": []})
    assert text == '{\n  "dataset": "x",\n  "items": [\n    {"a": 1},\n    {"a": "가"}\n  ],\n  "empty": [\n  ]\n}\n'


def test_pms_grades_are_development_grade_options():
    """PMS 원본의 Grade 는 모두 개발 등급 선택지에 있어야 한다 (G-16). PMS 를 갱신하면 여기서 드러난다."""
    pytest.importorskip("openpyxl")
    src = load_sources(default_store().root)["pms"]["source"]
    if not (REPO_ROOT / src["dir"]).exists():
        pytest.skip("PMS 원본이 없다")
    grades = set()
    for file_rule in src["files"]:
        rows = read_rows(REPO_ROOT / src["dir"] / file_rule["file"])
        i = list(rows[0]).index("Grade")
        grades |= {str(r[i]).strip() for r in rows[1:] if r[i]}
    assert grades <= set(load_options()["development_grade"].choices)


@pytest.mark.parametrize("dataset", BUILT_DATASETS)
def test_committed_version_rebuilds_from_source(dataset):
    """저장소의 현재 버전 파일은 원본과 변환 규칙으로 다시 만들 수 있어야 한다."""
    pytest.importorskip("openpyxl")
    store = default_store()
    rules = load_sources(store.root)[dataset]
    src = rules["source"]
    source = REPO_ROOT / (src.get("file") or src["dir"])
    if not source.exists():
        pytest.skip(f"원본이 없다: {source}")
    version = store.versions(store.current_release)[dataset]
    data = build_dataset(dataset, rules, REPO_ROOT)
    expected = version_path(store.root, dataset, version).read_text(encoding="utf-8")
    assert dumps({"dataset": dataset, "version": version, **data}) == expected
