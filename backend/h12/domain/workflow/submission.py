"""제출 조건 검사 자리 — 업무정의서 8장.

실제 검사는 4단계(Case, 제출 검증)에서 만든다. 엔진은 이 프로토콜만 안다.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .errors import Issue


class SubmissionChecker(Protocol):
    def check(self, form: Mapping[str, Any]) -> list[Issue]: ...


class AcceptAll:
    def check(self, form: Mapping[str, Any]) -> list[Issue]:
        return []
