"""revision 비교 — 업무정의서 3.4-5.

관리자와 담당자는 이전 revision 과 달라진 부분을 본다. 의뢰서를 경로 단위로 펼쳐 비교한다.
고유 ID 가 있는 목록 항목(조건 패키지, 제품 등)은 ID 로 맞춰 비교해서, 순서가 바뀌거나 앞 항목이 지워져도
뒤 항목이 모두 바뀐 것으로 보이지 않게 한다. 칸({value, status, source})은 값과 상태만 비교한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

_MISSING = object()


@dataclass(frozen=True)
class FormChange:
    path: str
    before: Any   # 없던 항목이면 None
    after: Any    # 지운 항목이면 None
    kind: str     # added | removed | changed


def diff_forms(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[FormChange]:
    old, new = _flatten(before), _flatten(after)
    changes = []
    for path in list(old) + [p for p in new if p not in old]:
        a, b = old.get(path, _MISSING), new.get(path, _MISSING)
        if a == b:
            continue
        kind = "added" if a is _MISSING else "removed" if b is _MISSING else "changed"
        changes.append(FormChange(path, None if a is _MISSING else a, None if b is _MISSING else b, kind))
    return changes


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    if _is_cell(value):
        return {path: value.get("value") if value.get("status") != "none" else "없음"}
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            # Case 재확인 지문은 시스템이 관리한다. revision 비교에는 업무 데이터만 보인다.
            if not path and k == "case_confirmation":
                continue
            out.update(_flatten(v, f"{path}.{k}" if path else str(k)))
        return out
    if isinstance(value, list):
        out = {}
        keyed = all(isinstance(v, Mapping) and v.get("id") for v in value)
        for i, v in enumerate(value):
            key = f"[id={v['id']}]" if keyed else f"[{i}]"
            out.update(_flatten(v, f"{path}{key}"))
        return out or {path: []}
    return {path: value}


def _is_cell(value: Any) -> bool:
    return isinstance(value, Mapping) and "value" in value and set(value) <= {"value", "status", "source"}
