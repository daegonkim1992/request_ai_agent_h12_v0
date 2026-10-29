from __future__ import annotations

from dataclasses import dataclass


class RulesError(ValueError):
    """규칙 파일이 엔진이 아는 이름과 맞지 않는다."""


class WorkflowError(Exception):
    """기능을 수행할 수 없다. 이 예외가 나면 의뢰는 바뀌지 않는다."""


class ActionNotAllowed(WorkflowError):
    """수행자, 상태, 대기 요청 조건이 맞지 않는다 (3.2 보이는 상태)."""


class InvalidInput(WorkflowError):
    def __init__(self, errors: dict[str, str]):
        super().__init__(", ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


@dataclass(frozen=True)
class Issue:
    """제출을 막는 문제와 그 위치 (8장)."""

    location: str
    message: str


class SubmissionBlocked(WorkflowError):
    def __init__(self, issues: list[Issue]):
        super().__init__(f"제출 조건 미충족 {len(issues)}건")
        self.issues = issues
