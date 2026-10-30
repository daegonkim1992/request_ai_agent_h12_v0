"""제품 분류 — 업무정의서 4.2.

사업부 → Product Line-up → Platform → Chassis 순서로 등록된 조합에서만 고른다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from .errors import ReferenceDataError


class PlatformMode(str, Enum):
    SELECT = "select"            # SAC, Chiller: 목록에서 고른다
    FROM_LINEUP = "from_lineup"  # RAC, Air Care: Product Line-up 으로 정해진다
    NONE = "none"                # AIDC: 해당 없음


@dataclass(frozen=True)
class ProductPath:
    id: str
    division: str
    product_lineup: str
    platform: str | None  # Platform 해당 없음이면 None
    chassis: str | None   # Chassis 가 없는 경로는 None. "NA" 는 실제 값이다

    @property
    def key(self) -> tuple[str, str, str | None, str | None]:
        return self.division, self.product_lineup, self.platform, self.chassis

    @property
    def display_path(self) -> str:
        return " > ".join(p for p in self.key if p)


@dataclass(frozen=True)
class ProductTaxonomy:
    version: str
    platform_modes: Mapping[str, PlatformMode]
    paths: tuple[ProductPath, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ProductTaxonomy:
        try:
            modes = {d: PlatformMode(m) for d, m in (raw.get("platform_mode") or {}).items()}
        except ValueError as e:
            raise ReferenceDataError(f"platform_mode: {e}") from None
        paths = tuple(
            ProductPath(
                id=p["id"], division=p["division"], product_lineup=p["product_lineup"],
                platform=p.get("platform"), chassis=p.get("chassis"),
            )
            for p in raw.get("paths") or []
        )
        taxonomy = cls(version=str(raw.get("version") or ""), platform_modes=modes, paths=paths)
        taxonomy._validate()
        return taxonomy

    def _validate(self) -> None:
        if not self.paths:
            raise ReferenceDataError("제품 분류가 비어 있다")
        ids, keys = set(), set()
        chassis_kinds: dict[tuple, set[bool]] = {}
        for p in self.paths:
            where = f"제품 분류 {p.display_path}"
            mode = self.platform_modes.get(p.division)
            if mode is None:
                raise ReferenceDataError(f"{where}: 사업부 {p.division} 의 Platform 규칙이 없다")
            if not p.product_lineup:
                raise ReferenceDataError(f"{where}: Product Line-up 이 비어 있다")
            if mode is PlatformMode.SELECT and not p.platform:
                raise ReferenceDataError(f"{where}: Platform 이 비어 있다")
            if mode is PlatformMode.FROM_LINEUP and p.platform != p.product_lineup:
                raise ReferenceDataError(f"{where}: Platform 은 Product Line-up 과 같아야 한다")
            if mode is PlatformMode.NONE and p.platform is not None:
                raise ReferenceDataError(f"{where}: Platform 해당 없음인 사업부다")
            if p.chassis == "":
                raise ReferenceDataError(f"{where}: Chassis 가 없으면 빈 문자열이 아니라 null 이다")
            if p.id in ids or p.key in keys:
                raise ReferenceDataError(f"{where}: 중복이다")
            ids.add(p.id)
            keys.add(p.key)
            chassis_kinds.setdefault(p.key[:3], set()).add(p.chassis is None)
        mixed = [k for k, kinds in chassis_kinds.items() if len(kinds) > 1]
        if mixed:
            raise ReferenceDataError(f"Chassis 가 있는 경로와 없는 경로가 섞여 있다: {mixed}")

    def platform_mode(self, division: str) -> PlatformMode | None:
        return self.platform_modes.get(division)

    def divisions(self) -> list[str]:
        return _unique(p.division for p in self.paths)

    def lineups(self, division: str) -> list[str]:
        return _unique(p.product_lineup for p in self.paths if p.division == division)

    def platforms(self, division: str, lineup: str) -> list[str | None]:
        return _unique(p.platform for p in self.paths
                       if (p.division, p.product_lineup) == (division, lineup))

    def chassis_options(self, division: str, lineup: str, platform: str | None) -> list[str | None]:
        return _unique(p.chassis for p in self.paths if p.key[:3] == (division, lineup, platform))

    def find(self, division: str, lineup: str, platform: str | None, chassis: str | None) -> ProductPath | None:
        """등록된 조합이면 그 경로, 아니면 None. 등록되지 않은 분류는 만들 수 없다."""
        key = (division, lineup, platform, chassis)
        return next((p for p in self.paths if p.key == key), None)

    def get(self, path_id: str) -> ProductPath | None:
        return next((p for p in self.paths if p.id == path_id), None)


def _unique(values: Iterable) -> list:
    return list(dict.fromkeys(values))
