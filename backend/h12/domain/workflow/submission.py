"""제출 조건 검사 포트 — 업무정의서 8장.

WorkflowEngine은 이 프로토콜만 알고, form.FormSubmissionChecker가 실제 의뢰서·Case 검사를 제공한다.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Protocol

from .errors import Issue


class SubmissionChecker(Protocol):
    def check(self, form: Mapping[str, Any], *, request_date: date) -> list[Issue]: ...


class AcceptAll:
    def check(self, form: Mapping[str, Any], *, request_date: date) -> list[Issue]:
        return []
