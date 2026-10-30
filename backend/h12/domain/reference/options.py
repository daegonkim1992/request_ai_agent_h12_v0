"""해석유형 목록(부록 A)과 의뢰서 선택지(4.2, 4.3).

rules/analysis_types.yaml, rules/options.yaml 을 읽은 dict 를 해석한다. 파일은 h12.rulebook 이 읽는다.
이 둘은 의뢰에 값이 복사되므로 기준 데이터 버전(3.4-10)에 넣지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ReferenceDataError


@dataclass(frozen=True)
class AnalysisType:
    code: str
    label: str
    description: str
    suitable_for: tuple[str, ...]


@dataclass(frozen=True)
class OptionList:
    key: str
    choices: Mapping[str, str]  # 코드 → 표시 이름
    allow_custom: bool = False
    default: str | None = None

    def label(self, code: str) -> str | None:
        return self.choices.get(code)


def parse_analysis_types(raw: Mapping[str, Any]) -> dict[str, AnalysisType]:
    types = {}
    for code, spec in (raw or {}).items():
        spec = spec or {}
        if not spec.get("label") or not spec.get("description"):
            raise ReferenceDataError(f"해석유형 {code}: label, description 은 필수다")
        types[code] = AnalysisType(
            code=code, label=spec["label"], description=spec["description"],
            suitable_for=tuple(spec.get("suitable_for") or ()),
        )
    labels = [t.label for t in types.values()]
    if len(set(labels)) != len(labels):
        raise ReferenceDataError("해석유형 이름이 중복된다")
    return types


def parse_options(raw: Mapping[str, Any]) -> dict[str, OptionList]:
    options = {}
    for key, spec in (raw or {}).items():
        spec = spec or {}
        choices = spec.get("choices")
        if isinstance(choices, list):
            choices = {str(c): str(c) for c in choices}
        if not isinstance(choices, dict) or not choices:
            raise ReferenceDataError(f"선택지 {key}: choices 가 비어 있다")
        default = spec.get("default")
        if default is not None and default not in choices:
            raise ReferenceDataError(f"선택지 {key}: 기본값 {default} 가 choices 에 없다")
        options[key] = OptionList(
            key=key, choices={str(k): str(v) for k, v in choices.items()},
            allow_custom=bool(spec.get("allow_custom", False)), default=default,
        )
    return options
