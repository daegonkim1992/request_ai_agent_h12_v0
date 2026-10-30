"""의뢰 유스케이스 — DB 트랜잭션 안에서 도메인 규칙을 조합한다."""

from __future__ import annotations

import copy
import uuid
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol

from h12.domain.form import (
    FormContext, FormSubmissionChecker, TargetSelection, case_sources_changed, confirm_cases, confirm_target, merge_user_edit,
    refresh_cases, select_pms_project,
)
from h12.domain.workflow import ActionNotAllowed, Request, Role, User, WorkflowEngine
from h12.reference.store import ReferenceStore
from h12.rulebook import load_form_rules, load_workflow_rules


class NotFound(Exception):
    pass


class ConcurrentModification(Exception):
    """다른 요청이 먼저 저장해 현재 요청의 기준이 오래되었다."""


class Work(Protocol):
    def user(self, user_id: str) -> User | None: ...
    def save_user(self, user: User) -> None: ...
    def request(self, request_id: str) -> Request | None: ...
    def requests(self) -> list[Request]: ...
    def save_request(self, request: Request) -> None: ...
    def issue_number(self, day) -> int: ...


class WorkProvider(Protocol):
    def work(self) -> AbstractContextManager[Work]: ...


class RequestService:
    def __init__(self, work_provider: WorkProvider, references: ReferenceStore,
                 now: Callable[[], datetime] = datetime.now):
        self.work_provider, self.references, self.now = work_provider, references, now
        self.form_rules = load_form_rules()
        context = FormContext(self.form_rules, references.load, now().date())
        self.engine = WorkflowEngine(load_workflow_rules(), FormSubmissionChecker(context))

    def add_user(self, user: User) -> User:
        with self.work_provider.work() as work:
            work.save_user(user)
        return user

    def user(self, user_id: str) -> User:
        with self.work_provider.work() as work:
            user = work.user(user_id)
            if user is None:
                raise NotFound("사용자가 없다")
            return user

    def create(self, actor: User) -> Request:
        with self.work_provider.work() as work:
            request = self.engine.create_request(actor, str(uuid.uuid4()), self.now())
            work.save_request(request)
            return request

    def get(self, actor: User, request_id: str) -> Request:
        with self.work_provider.work() as work:
            request = self._request(work, request_id)
            if not self.engine.can_view(actor, request):
                raise ActionNotAllowed("이 의뢰를 볼 수 없다")
            return request

    def list(self, actor: User, *, todo_only: bool = False) -> list[Request]:
        return self.list_with_status_counts(actor, todo_only=todo_only)[0]

    def list_with_status_counts(self, actor: User, *, todo_only: bool = False) -> tuple[list[Request], dict[str, int]]:
        with self.work_provider.work() as work:
            items = [r for r in work.requests() if self.engine.can_view(actor, r)]
            if todo_only:
                items = [r for r in items if self.engine.is_todo(actor, r)]
            counts: dict[str, int] = {}
            for request in items:
                counts[request.status] = counts.get(request.status, 0) + 1
            return items, counts

    def status_counts(self, actor: User, *, todo_only: bool = False) -> dict[str, int]:
        return self.list_with_status_counts(actor, todo_only=todo_only)[1]

    def edit_form(self, actor: User, request_id: str, edited: Mapping[str, Any], *, confirm_case: bool = False) -> Request:
        with self.work_provider.work() as work:
            request = self._request(work, request_id)
            form = merge_user_edit(request.form, edited)
            if ((form.get("request_context") or {}).get("locked")
                    and case_sources_changed(request.form, form)):
                form = refresh_cases(form, reference=self.references.load(form["request_context"]["reference_release"]),
                                     rules=self.form_rules)
                if confirm_case:
                    form = confirm_cases(form, reference=self.references.load(form["request_context"]["reference_release"]),
                                         rules=self.form_rules)
            self.engine.update_form(actor, request, form)
            work.save_request(request)
            return request

    def confirm_target(self, actor: User, request_id: str, selection: TargetSelection,
                       *, accept_change: bool = False) -> Request:
        with self.work_provider.work() as work:
            request = self._request(work, request_id)
            if not self.engine.can_edit_form(actor, request):
                raise ActionNotAllowed("상태에서 의뢰 대상을 확정할 수 없다")
            issuer = _NumberIssuer(work, self.form_rules.target.request_no_format)
            form = confirm_target(request.form, selection, reference=self.references.load(), rules=self.form_rules,
                                  issuer=issuer, now=self.now(), accept_change=accept_change)
            self.engine.update_form(actor, request, form)
            work.save_request(request)
            return request

    def select_pms(self, actor: User, request_id: str, code: str) -> Request:
        with self.work_provider.work() as work:
            request = self._request(work, request_id)
            form = select_pms_project(request.form, code, self.references.load().pms)
            self.engine.update_form(actor, request, form)
            work.save_request(request)
            return request

    def confirm_case(self, actor: User, request_id: str) -> Request:
        with self.work_provider.work() as work:
            request = self._request(work, request_id)
            release = request.form.get("request_context", {}).get("reference_release")
            form = confirm_cases(request.form, reference=self.references.load(release), rules=self.form_rules)
            self.engine.update_form(actor, request, form)
            work.save_request(request)
            return request

    def action(self, actor: User, request_id: str, action: str, inputs: Mapping[str, Any] | None) -> Request:
        with self.work_provider.work() as work:
            request = self._request(work, request_id)
            data = copy.deepcopy(dict(inputs or {}))
            if "analyst_id" in data:
                analyst = work.user(data.pop("analyst_id"))
                data["analyst"] = analyst
            if action == "request_change" and isinstance(data.get("form"), Mapping):
                form = merge_user_edit(request.form, data["form"])
                release = form.get("request_context", {}).get("reference_release")
                if release and case_sources_changed(request.form, form):
                    form = refresh_cases(form, reference=self.references.load(release), rules=self.form_rules)
                    if data.pop("confirm_case", False):
                        form = confirm_cases(form, reference=self.references.load(release), rules=self.form_rules)
                data["form"] = form
            self.engine.execute(actor, request, action, data, self.now())
            work.save_request(request)
            return request

    @staticmethod
    def _request(work: Work, request_id: str) -> Request:
        request = work.request(request_id)
        if request is None:
            raise NotFound("의뢰가 없다")
        return request


class _NumberIssuer:
    def __init__(self, work: Work, number_format: str):
        self.work, self.number_format = work, number_format

    def issue(self, day) -> str:
        return self.number_format.format(date=day, seq=self.work.issue_number(day))
