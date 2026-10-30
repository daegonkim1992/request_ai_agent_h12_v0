"""4.3 프로젝트명(PMS), 4.4 PMS 프로젝트는 제품 사업부에 종속된다.

데이터 기대값은 원본 PMS 파일(Aircare)의 행에서 옮겼다.
"""

from __future__ import annotations

import json

import pytest

from h12.domain.reference import PmsDirectory, ReferenceDataError
from h12.reference import default_store

HYDRO_TOWER = "PJT2026011400000000241097"  # `26년향 하이드로타워 대용량 가습공청기, HY856RNAA.AKOR


def test_search_by_project(pms):
    hits = pms.search("Air Care", "하이드로타워")
    assert HYDRO_TOWER in [p.code for p in hits]
    assert all("하이드로타워" in p.project for p in hits)


def test_search_by_rep_model_ignores_case(pms):
    assert [p.code for p in pms.search("Air Care", "hy856rnaa")] == [HYDRO_TOWER]


def test_search_only_in_product_division(pms):
    assert pms.search("RAC", "HY856RNAA") == []
    assert pms.belongs_to(HYDRO_TOWER, "Air Care")
    assert not pms.belongs_to(HYDRO_TOWER, "RAC")


def test_selecting_project_fills_code_and_region(pms):
    project = pms.get(HYDRO_TOWER)
    assert (project.project, project.rep_model, project.region) == (
        "`26년향 하이드로타워 대용량 가습공청기", "HY856RNAA.AKOR", "Korea")


def test_pms_division_is_product_division(pms):
    # PMS 의 CAC 는 제품 분류의 SAC 다. AIDC 는 PMS 프로젝트가 없다
    assert {p.division for p in pms.projects} == {"SAC", "RAC", "Air Care", "Chiller"}
    assert pms.projects_of("CAC") == []
    assert pms.projects_of("AIDC") == []


def test_no_personal_data_kept():
    store = default_store()
    version = store.versions(store.current_release)["pms"]
    raw = json.loads((store.root / "pms" / f"{version}.json").read_text(encoding="utf-8"))
    keys = set().union(*(p.keys() for p in raw["projects"]))
    assert keys == {"code", "division", "project", "rep_model", "region", "product_group"}


@pytest.mark.parametrize("name,projects", [
    ("missing rep model", [{"code": "A", "division": "RAC", "project": "p", "rep_model": ""}]),
    ("duplicate code", [{"code": "A", "division": "RAC", "project": "p", "rep_model": "m"}] * 2),
])
def test_invalid_pms_rejected(name, projects):
    with pytest.raises(ReferenceDataError):
        PmsDirectory.from_dict({"version": "t", "projects": projects})
