"""의뢰 유스케이스 — DB 트랜잭션 안에서 도메인 규칙을 조합한다."""

from __future__ import annotations

import copy
import uuid
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol

from h12.domain.form import (
    FormContext, FormError, FormSubmissionChecker, TargetSelection, auto_combine_cases, case_source_hash,
    case_sources_changed, clear_pms_project, confirm_cases, confirm_target, diff_forms, form_shape_issues,
    merge_user_edit, refresh_cases, select_pms_project,
)
from h12.domain.form.errors import FormValidationError
from h12.domain.form.values import value_of
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
    def users_by_role(self, role: Role) -> list[User]: ...
    def request(self, request_id: str) -> Request | None: ...
    def requests(self) -> list[Request]: ...
    def save_request(self, request: Request) -> None: ...
    def issue_number(self, day) -> int: ...
    def attachment(self, attachment_id: str) -> Any | None: ...
    def save_attachment(self, attachment_id: str, request_id: str, filename: str, content_type: str,
                        content: bytes, uploaded_by: str, created_at: datetime) -> None: ...


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
            self._ensure_form_shape(edited)
            form = merge_user_edit(request.form, edited)
            self._preserve_pcb_image(request.form, form)
            form = self._clear_pms_if_not_applicable(form)
            form = self._reconcile_case_state(request.form, form, confirm_case=confirm_case)
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
            form = select_pms_project(request.form, code, self.references.load().pms, rules=self.form_rules)
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

    def auto_combine_case(self, actor: User, request_id: str, *, max_cases: int) -> Request:
        with self.work_provider.work() as work:
            request = self._request(work, request_id)
            if not self.engine.can_edit_form(actor, request):
                raise ActionNotAllowed(f"상태 {request.status} 에서는 Case를 자동 조합할 수 없다")
            release = request.form.get("request_context", {}).get("reference_release")
            if not release:
                raise ActionNotAllowed("의뢰 대상을 확정한 뒤 Case를 구성해야 한다")
            form = copy.deepcopy(request.form)
            form["cases"] = auto_combine_cases(
                form, reference=self.references.load(release), rules=self.form_rules, max_cases=max_cases,
            )
            form.pop("case_confirmation", None)
            self.engine.update_form(actor, request, form)
            work.save_request(request)
            return request

    def search_pms(self, division: str, query: str = ""):
        return self.references.load().pms.search(division, query)

    def analysts(self, actor: User) -> list[User]:
        if actor.role is not Role.MANAGER:
            raise ActionNotAllowed("해석담당자 목록은 해석관리자만 볼 수 있다")
        with self.work_provider.work() as work:
            return work.users_by_role(Role.ANALYST)

    def upload_pcb_image(self, actor: User, request_id: str, *, filename: str, content_type: str,
                         content: bytes) -> tuple[Request, str]:
        with self.work_provider.work() as work:
            request = self._request(work, request_id)
            if not self.engine.can_edit_form(actor, request):
                raise ActionNotAllowed(f"상태 {request.status} 에서는 PCB 이미지를 올릴 수 없다")
            release = request.form.get("request_context", {}).get("reference_release")
            if not release:
                raise FormError("PCB 이미지는 의뢰 대상을 확정한 뒤 올릴 수 있다")
            form = copy.deepcopy(request.form)
            pcb = (form.setdefault("conditions", {}).get("pcb") or {})
            if not pcb:
                raise FormError("PCB발열 의뢰에서만 PCB 이미지를 올릴 수 있다")
            attachment_id = str(uuid.uuid4())
            work.save_attachment(attachment_id, request.id, filename, content_type, content, actor.id, self.now())
            pcb["image"] = attachment_id
            form["conditions"]["pcb"] = pcb
            if case_sources_changed(request.form, form):
                form = refresh_cases(form, reference=self.references.load(release), rules=self.form_rules)
            self.engine.update_form(actor, request, form)
            work.save_request(request)
            return request, attachment_id

    def attachment(self, actor: User, request_id: str, attachment_id: str):
        with self.work_provider.work() as work:
            request = self._request(work, request_id)
            if not self.engine.can_view(actor, request):
                raise ActionNotAllowed("이 첨부파일을 볼 수 없다")
            attachment = work.attachment(attachment_id)
            if attachment is None or attachment.request_id != request.id:
                raise NotFound("첨부파일이 없다")
            return attachment

    def revision_diff(self, actor: User, request_id: str, revision_no: int):
        request = self.get(actor, request_id)
        current = next((item for item in request.revisions if item.revision_no == revision_no), None)
        if current is None:
            raise NotFound("revision이 없다")
        previous = next((item for item in request.revisions if item.revision_no == revision_no - 1), None)
        return diff_forms({} if previous is None else previous.form, current.form)

    def action(self, actor: User, request_id: str, action: str, inputs: Mapping[str, Any] | None) -> Request:
        with self.work_provider.work() as work:
            request = self._request(work, request_id)
            data = copy.deepcopy(dict(inputs or {}))
            if "analyst_id" in data:
                analyst = work.user(data.pop("analyst_id"))
                data["analyst"] = analyst
            if action == "request_change":
                confirm_case = data.pop("confirm_case", False)
                if not isinstance(confirm_case, bool):
                    raise FormError("confirm_case: true 또는 false 이어야 한다")
            else:
                confirm_case = False
            if action == "request_change" and isinstance(data.get("form"), Mapping):
                self._ensure_form_shape(data["form"])
                form = merge_user_edit(request.form, data["form"])
                self._preserve_pcb_image(request.form, form)
                form = self._clear_pms_if_not_applicable(form)
                form = self._reconcile_case_state(request.form, form, confirm_case=confirm_case)
                data["form"] = form
            self.engine.execute(actor, request, action, data, self.now())
            work.save_request(request)
            return request

    def _clear_pms_if_not_applicable(self, form: Mapping[str, Any]) -> dict[str, Any]:
        request_type = value_of((form.get("analysis_overview") or {}).get("request_type"))
        return clear_pms_project(form) if request_type not in self.form_rules.pms_required_for else dict(form)

    @staticmethod
    def _preserve_pcb_image(current: Mapping[str, Any], edited: Mapping[str, Any]) -> None:
        """PCB 파일 식별자는 업로드 유스케이스로만 바꾼다."""
        current_pcb = ((current.get("conditions") or {}).get("pcb") or {})
        edited_pcb = ((edited.get("conditions") or {}).get("pcb") or {})
        if isinstance(current_pcb, Mapping) and isinstance(edited_pcb, dict) and "image" in current_pcb:
            edited_pcb["image"] = copy.deepcopy(current_pcb["image"])

    def _reconcile_case_state(self, current: Mapping[str, Any], edited: dict[str, Any], *, confirm_case: bool) -> dict[str, Any]:
        """활성 Case 열의 실제 원본이 바뀔 때만 재확인을 요구한다."""
        release = (edited.get("request_context") or {}).get("reference_release")
        if not release:
            return edited
        reference = self.references.load(release)
        try:
            changed = case_source_hash(current, reference, self.form_rules) != case_source_hash(
                edited, reference, self.form_rules,
            )
        except (FormError, KeyError, TypeError):
            changed = case_sources_changed(current, edited)
        if changed:
            result = refresh_cases(edited, reference=reference, rules=self.form_rules)
            return confirm_cases(result, reference=reference, rules=self.form_rules) if confirm_case else result
        if current.get("case_confirmation"):
            edited["case_confirmation"] = copy.deepcopy(current["case_confirmation"])
        return edited

    @staticmethod
    def _ensure_form_shape(form: Mapping[str, Any]) -> None:
        issues = form_shape_issues(form)
        if issues:
            raise FormValidationError(issues)

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
