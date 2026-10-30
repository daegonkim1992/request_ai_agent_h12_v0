"""열교환기 Catalog — 업무정의서 5.3.4.

관 직경, Fin type, 열 수, FPI 네 사양의 조합은 Catalog 에 등록된 실제 조합이어야 한다.
값은 원본 표기를 그대로 쓰는 문자열이다 ("7", "9.52", "W16", "5+7").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from .errors import ReferenceDataError

MICRO_CHANNEL_PREFIX = "W"  # 관 직경이 W로 시작하면 Micro-Channel
FLAT_FIN_PREFIX = "Flat"    # Micro-Channel 의 Fin type. Catalog 에는 Flat(MCE), Flat(MCC) 로 있다 (G-13)


class HeatExchangerType(str, Enum):
    FIN_TUBE = "Fin&Tube"
    MICRO_CHANNEL = "Micro-Channel"


def classify(tube_diameter: str) -> HeatExchangerType:
    if tube_diameter.strip().upper().startswith(MICRO_CHANNEL_PREFIX):
        return HeatExchangerType.MICRO_CHANNEL
    return HeatExchangerType.FIN_TUBE


def is_flat_fin(fin_type: str) -> bool:
    return fin_type.startswith(FLAT_FIN_PREFIX)


@dataclass(frozen=True)
class HxSpec:
    tube_diameter: str
    fin_type: str
    row_count: str
    fpi: str

    @property
    def type(self) -> HeatExchangerType:
        return classify(self.tube_diameter)


@dataclass(frozen=True)
class HxEntry:
    id: str
    spec: HxSpec
    standard: bool  # 표준 사양 표시. 비표준도 Catalog 에 있는 실제 조합이다 (G-13)


@dataclass(frozen=True)
class HxCatalog:
    version: str
    entries: tuple[HxEntry, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> HxCatalog:
        entries = tuple(
            HxEntry(
                id=e["id"],
                spec=HxSpec(e["tube_diameter"], e["fin_type"], e["row_count"], e["fpi"]),
                standard=e["standard"],
            )
            for e in raw.get("entries") or []
        )
        catalog = cls(version=str(raw.get("version") or ""), entries=entries)
        catalog._validate()
        return catalog

    def _validate(self) -> None:
        if not self.entries:
            raise ReferenceDataError("열교환기 Catalog 가 비어 있다")
        ids, specs = set(), set()
        for e in self.entries:
            values = (e.spec.tube_diameter, e.spec.fin_type, e.spec.row_count, e.spec.fpi)
            if not all(isinstance(v, str) and v for v in values):
                raise ReferenceDataError(f"열교환기 {values}: 사양 값은 빈 값이 아닌 문자열이다")
            if not isinstance(e.standard, bool):
                raise ReferenceDataError(f"열교환기 {values}: 표준 여부는 참·거짓이다")
            if e.spec.type is HeatExchangerType.MICRO_CHANNEL and not is_flat_fin(e.spec.fin_type):
                raise ReferenceDataError(f"열교환기 {values}: Micro-Channel 의 Fin type 은 Flat 이다")
            if e.id in ids or e.spec in specs:
                raise ReferenceDataError(f"열교환기 {values}: 중복이다")
            ids.add(e.id)
            specs.add(e.spec)

    def entry(self, spec: HxSpec) -> HxEntry | None:
        return next((e for e in self.entries if e.spec == spec), None)

    def contains(self, spec: HxSpec) -> bool:
        return self.entry(spec) is not None

    # 선택지는 앞 사양으로 좁힌다: 관 직경 → Fin type → 열 수 → FPI
    def tube_diameters(self, hx_type: HeatExchangerType | None = None) -> list[str]:
        return _unique(e.spec.tube_diameter for e in self.entries
                       if hx_type is None or e.spec.type is hx_type)

    def fin_types(self, tube_diameter: str) -> list[str]:
        return _unique(e.spec.fin_type for e in self._match(tube_diameter))

    def row_counts(self, tube_diameter: str, fin_type: str) -> list[str]:
        return _unique(e.spec.row_count for e in self._match(tube_diameter, fin_type))

    def fpis(self, tube_diameter: str, fin_type: str, row_count: str) -> list[str]:
        return _unique(e.spec.fpi for e in self._match(tube_diameter, fin_type, row_count))

    def _match(self, *prefix: str) -> list[HxEntry]:
        return [e for e in self.entries
                if (e.spec.tube_diameter, e.spec.fin_type, e.spec.row_count)[:len(prefix)] == prefix]


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
