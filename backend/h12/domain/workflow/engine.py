"""업무 흐름 엔진 — 업무정의서 3장.

규칙(WorkflowRules)에 적힌 이름을 여기서 동작으로 바꾼다.
execute 는 모든 검사를 마친 뒤에만 의뢰를 바꾼다. 검사에 실패하면 의뢰는 그대로다.
"""

from __future__ import annotations

import copy
import dataclasses
from datetime import datetime
from typing import Any, Callable, Mapping

from .errors import ActionNotAllowed, InvalidInput, SubmissionBlocked
from .model import (
    PendingKind, PendingRequest, Request, ResultRound, Revision, Role, User, WorkflowEvent,
)
from .rules import ActionRule, TodoRule, WorkflowRules
from .submission import AcceptAll, SubmissionChecker

_ACTOR_CHECKS: dict[str, Callable[[User, Request], bool]] = {
    "requester": lambda u, r: u.role is Role.REQUESTER and u.id == r.requester_id,
    "manager": lambda u, r: u.role is Role.MANAGER,
    "assigned_analyst": lambda u, r: u.role is Role.ANALYST and u.id == r.analyst_id,
    "holder": lambda u, r: r.held_by is not None and u.id == r.held_by,
}


class WorkflowEngine:
    def __init__(self, rules: WorkflowRules, submission_checker: SubmissionChecker | None = None):
        self.rules = rules
        self.submission_checker = submission_checker or AcceptAll()

    # ── 조회 ──────────────────────────────────────────────

    def create_request(self, user: User, request_id: str, now: datetime) -> Request:
        """2장 새 의뢰는 의뢰자만 만든다."""
        if user.role is not Role.REQUESTER:
            raise ActionNotAllowed("새 의뢰는 의뢰자만 만들 수 있다")
        return Request(
            id=request_id,
            requester_id=user.id,
            requester_department=user.department,
            status=self.rules.initial_status,
            created_at=now,
        )

    def can_view(self, user: User, request: Request) -> bool:
        """2장 볼 수 있는 의뢰."""
        if user.id == request.requester_id:
            return True
        # 한 번도 제출하지 않은 의뢰는 작성자만 본다. 관리자도 보지 않는다 (2장)
        if not request.revisions:
            return False
        if user.role is Role.MANAGER:
            return True
        if user.role is Role.ANALYST:
            return user.id == request.analyst_id
        return user.department == request.requester_department

    def available_actions(self, user: User, request: Request) -> list[str]:
        """3.2 지금 이 사용자에게 보이는 기능."""
        return [key for key, rule in self.rules.actions.items() if self._allowed(rule, user, request)]

    def can_edit_form(self, user: User, request: Request) -> bool:
        """3.4-1 의뢰서 내용은 정해진 상태에서 의뢰자만 고친다. 3.4-4 취소 요청 대기 중에는 고칠 수 없다."""
        return (
            _ACTOR_CHECKS["requester"](user, request)
            and request.status in self.rules.editable_statuses
            and self._exclusive_kind(request) is None
        )

    def is_todo(self, user: User, request: Request) -> bool:
        """3.5 역할별 할 일 목록."""
        return any(self._todo_matches(t, user, request) for t in self.rules.todo.get(user.role, ()))

    # ── 변경 ──────────────────────────────────────────────

    def update_form(self, user: User, request: Request, form: Mapping[str, Any]) -> None:
        if not self.can_edit_form(user, request):
            raise ActionNotAllowed(f"상태 {request.status} 에서는 의뢰서를 고칠 수 없다")
        request.form = copy.deepcopy(dict(form))

    def execute(
        self,
        user: User,
        request: Request,
        action: str,
        inputs: Mapping[str, Any] | None,
        now: datetime,
    ) -> WorkflowEvent:
        rule = self.rules.actions.get(action)
        if rule is None:
            raise ActionNotAllowed(f"알 수 없는 기능 {action}")
        if not self._allowed(rule, user, request):
            raise ActionNotAllowed(f"{rule.label}: 상태 {request.status} 에서 이 사용자는 수행할 수 없다")
        inputs = dict(inputs or {})
        self._validate_inputs(rule, request, inputs)
        self._run_checks(rule, request, inputs)

        from_status = request.status
        target = rule.transitions[from_status]
        to_status = from_status if target is None else target
        event = WorkflowEvent(
            seq=len(request.events) + 1,
            event_type=rule.event,
            action=rule.key,
            from_status=from_status,
            to_status=to_status,
            actor_id=user.id,
            at=now,
            reason_code=inputs.get("reason_code"),
            comment=inputs.get("comment"),
        )
        payload: dict[str, Any] = {}
        for effect in rule.effects:
            _EFFECTS[effect](request, user, inputs, now, rule, payload)
        request.status = to_status
        event = _with_payload(event, payload)
        request.events.append(event)
        return event

    # ── 내부 ──────────────────────────────────────────────

    def _allowed(self, rule: ActionRule, user: User, request: Request) -> bool:
        if request.status not in rule.transitions:
            return False
        current = request.pending.kind if request.pending else None
        if rule.pending is not None and current not in rule.pending:
            return False
        exclusive = self._exclusive_kind(request)
        if exclusive is not None and (rule.pending is None or exclusive not in rule.pending):
            return False
        return any(_ACTOR_CHECKS[a](user, request) for a in rule.actors)

    def _exclusive_kind(self, request: Request) -> PendingKind | None:
        """3.4-4 다른 기능을 모두 막고 있는 대기 요청."""
        if request.pending and request.pending.kind in self.rules.exclusive_pending:
            return request.pending.kind
        return None

    def _validate_inputs(self, rule: ActionRule, request: Request, inputs: dict[str, Any]) -> None:
        errors: dict[str, str] = {}
        for key in inputs.keys() - rule.requires:
            errors[key] = "이 기능에서 받지 않는 입력"
        for key in rule.requires:
            value = inputs.get(key)
            message = _INPUT_CHECKS[key](value, rule, request, self.rules)
            if message:
                errors[key] = message
        if errors:
            raise InvalidInput(errors)

    def _run_checks(self, rule: ActionRule, request: Request, inputs: Mapping[str, Any]) -> None:
        if "submission" in rule.checks:
            form = inputs["form"] if "form" in rule.requires else request.form
            issues = self.submission_checker.check(form)
            if issues:
                raise SubmissionBlocked(issues)

    def _todo_matches(self, todo: TodoRule, user: User, request: Request) -> bool:
        if todo.relation is not None and not _ACTOR_CHECKS[todo.relation](user, request):
            return False
        if todo.statuses is not None and request.status not in todo.statuses:
            return False
        if todo.pending is not None and not _pending_matches(todo.pending, request):
            return False
        # 막혀 있는 의뢰는 그 대기 요청을 처리할 사람의 할 일에만 들어간다
        exclusive = self._exclusive_kind(request)
        if exclusive is not None and todo.pending is not exclusive:
            return False
        return True


def _pending_matches(expected: PendingKind | None, request: Request) -> bool:
    if expected is None:
        return request.pending is None
    return request.pending is not None and request.pending.kind is expected


def _with_payload(event: WorkflowEvent, payload: dict[str, Any]) -> WorkflowEvent:
    return dataclasses.replace(event, payload=payload) if payload else event


# ── 입력 검사 ─────────────────────────────────────────────

def _text(value: Any, *_: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "필수 입력"
    return None


def _reason_code(value: Any, rule: ActionRule, _request: Request, rules: WorkflowRules) -> str | None:
    codes = rules.reason_codes[rule.reason_codes]
    if value not in codes:
        return f"사유 코드는 {sorted(codes)} 중 하나"
    return None


def _analyst(value: Any, _rule: ActionRule, request: Request, _rules: WorkflowRules) -> str | None:
    if not isinstance(value, User) or value.role is not Role.ANALYST:
        return "해석담당자를 지정해야 한다"
    if value.id == request.analyst_id:
        return "현재 담당자와 같다"
    return None


def _form(value: Any, *_: Any) -> str | None:
    if not isinstance(value, Mapping):
        return "의뢰서가 필요하다"
    return None


_INPUT_CHECKS: dict[str, Callable[[Any, ActionRule, Request, WorkflowRules], str | None]] = {
    "reason_code": _reason_code,
    "comment": _text,
    "analyst": _analyst,
    "form": _form,
    "result_summary": _text,
}


# ── 효과 ──────────────────────────────────────────────────
# (request, user, inputs, now, rule, payload). 검사를 통과한 뒤에만 불리므로 실패하지 않는다.

def _create_revision(request, user, inputs, now, rule, payload):
    revision = Revision(
        revision_no=len(request.revisions) + 1,
        form=copy.deepcopy(request.form),
        created_by=user.id,
        created_at=now,
        cause_event=rule.event,
    )
    request.revisions.append(revision)
    payload["revision_no"] = revision.revision_no


def _assign_analyst(request, user, inputs, now, rule, payload):
    payload["previous_analyst_id"] = request.analyst_id
    payload["analyst_id"] = inputs["analyst"].id
    # 이전 담당자가 보류했다면 보류 책임도 새 담당자에게 넘긴다 (3.4-12)
    if request.held_by is not None and request.held_by == request.analyst_id:
        request.held_by = inputs["analyst"].id
    request.analyst_id = inputs["analyst"].id


def _record_holder(request, user, inputs, now, rule, payload):
    request.held_by = user.id


def _clear_holder(request, user, inputs, now, rule, payload):
    request.held_by = None


def _open_change(request, user, inputs, now, rule, payload):
    request.pending = PendingRequest(
        kind=PendingKind.CHANGE,
        requested_by=user.id,
        comment=inputs["comment"],
        requested_at=now,
        proposed_form=copy.deepcopy(dict(inputs["form"])),
    )
    # 거절되면 대기 요청이 지워지므로 제안 내용은 이력에 남긴다 (3.4-7)
    payload["proposed_form"] = copy.deepcopy(dict(inputs["form"]))


def _apply_change(request, user, inputs, now, rule, payload):
    request.form = copy.deepcopy(request.pending.proposed_form)


def _open_cancel(request, user, inputs, now, rule, payload):
    request.pending = PendingRequest(
        kind=PendingKind.CANCEL,
        requested_by=user.id,
        comment=inputs["comment"],
        requested_at=now,
    )


def _close_pending(request, user, inputs, now, rule, payload):
    request.pending = None


def _add_result(request, user, inputs, now, rule, payload):
    result = ResultRound(
        round_no=len(request.results) + 1,
        summary=inputs["result_summary"],
        registered_by=user.id,
        registered_at=now,
    )
    request.results.append(result)
    payload["round_no"] = result.round_no


_EFFECTS = {
    "create_revision": _create_revision,
    "assign_analyst": _assign_analyst,
    "record_holder": _record_holder,
    "clear_holder": _clear_holder,
    "open_change": _open_change,
    "apply_change": _apply_change,
    "open_cancel": _open_cancel,
    "close_pending": _close_pending,
    "add_result": _add_result,
}
