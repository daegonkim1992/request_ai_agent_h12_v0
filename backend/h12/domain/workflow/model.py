"""업무 흐름 도메인 모델 — 업무정의서 2장, 3장.

상태 이름은 rules/workflow.yaml 이 정하므로 문자열로 다룬다. 역할만 코드가 의미를 안다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    REQUESTER = "REQUESTER"
    MANAGER = "MANAGER"
    ANALYST = "ANALYST"


class PendingKind(StrEnum):
    """3.4-4 대기 요청. 한 의뢰에 하나만 둔다."""

    CHANGE = "change"
    CANCEL = "cancel"


@dataclass(frozen=True)
class User:
    id: str
    role: Role
    department: str


@dataclass(frozen=True)
class PendingRequest:
    kind: PendingKind
    requested_by: str
    comment: str
    requested_at: datetime
    proposed_form: dict[str, Any] | None = None


@dataclass(frozen=True)
class Revision:
    """3.4-5 제출, 재제출, 진행 중 변경 수락 때 남기는 의뢰서 스냅샷."""

    revision_no: int
    form: dict[str, Any]
    created_by: str
    created_at: datetime
    cause_event: str


@dataclass(frozen=True)
class ResultRound:
    """3.4-6 결과 회차. 마지막 회차가 현재 결과다."""

    round_no: int
    summary: str
    registered_by: str
    registered_at: datetime


@dataclass(frozen=True)
class WorkflowEvent:
    """3.4-7 이력. 상태를 유지하는 기능도 남긴다."""

    seq: int
    event_type: str
    action: str
    from_status: str
    to_status: str
    actor_id: str
    at: datetime
    reason_code: str | None = None
    comment: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Request:
    """의뢰 한 건. 변경은 WorkflowEngine 을 거쳐서만 한다."""

    id: str
    requester_id: str
    # 2장 같은 부서 조회의 기준. 의뢰서의 "부서" 칸이 아니라 만든 사람의 소속 부서다
    requester_department: str
    status: str
    created_at: datetime
    form: dict[str, Any] = field(default_factory=dict)
    analyst_id: str | None = None
    held_by: str | None = None
    pending: PendingRequest | None = None
    revisions: list[Revision] = field(default_factory=list)
    results: list[ResultRound] = field(default_factory=list)
    events: list[WorkflowEvent] = field(default_factory=list)

    @property
    def current_revision(self) -> Revision | None:
        return self.revisions[-1] if self.revisions else None

    @property
    def current_result(self) -> ResultRound | None:
        return self.results[-1] if self.results else None
