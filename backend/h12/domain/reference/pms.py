"""PMS 프로젝트 — 업무정의서 4.3, 4.4.

PMS 프로젝트는 제품 사업부에 종속된다. Project 또는 Rep Model 로 검색한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ReferenceDataError


@dataclass(frozen=True)
class PmsProject:
    code: str          # PMS Project Code
    division: str      # 제품 분류의 사업부
    project: str
    rep_model: str
    region: str
    product_group: str


@dataclass(frozen=True)
class PmsDirectory:
    version: str
    projects: tuple[PmsProject, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PmsDirectory:
        projects = tuple(
            PmsProject(
                code=p["code"], division=p["division"], project=p["project"],
                rep_model=p["rep_model"], region=p.get("region") or "",
                product_group=p.get("product_group") or "",
            )
            for p in raw.get("projects") or []
        )
        directory = cls(version=str(raw.get("version") or ""), projects=projects)
        directory._validate()
        return directory

    def _validate(self) -> None:
        codes = set()
        for p in self.projects:
            if not (p.code and p.division and p.project and p.rep_model):
                raise ReferenceDataError(f"PMS {p.code or p.project}: 코드, 사업부, Project, Rep Model 은 필수다")
            if p.code in codes:
                raise ReferenceDataError(f"PMS {p.code}: 중복이다")
            codes.add(p.code)

    def get(self, code: str) -> PmsProject | None:
        return next((p for p in self.projects if p.code == code), None)

    def projects_of(self, division: str) -> list[PmsProject]:
        return [p for p in self.projects if p.division == division]

    def search(self, division: str, query: str = "") -> list[PmsProject]:
        """사업부의 프로젝트 중 Project 또는 Rep Model 에 검색어가 들어 있는 것. 대소문자는 가리지 않는다."""
        q = query.strip().casefold()
        return [p for p in self.projects_of(division)
                if q in p.project.casefold() or q in p.rep_model.casefold()]

    def belongs_to(self, code: str, division: str) -> bool:
        project = self.get(code)
        return project is not None and project.division == division
