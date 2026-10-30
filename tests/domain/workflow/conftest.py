"""업무 흐름 테스트 공통 준비.

의뢰를 원하는 상태로 만들 때는 상태를 직접 넣지 않고 실제 기능을 차례로 수행한다.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest

from h12.domain.form import FormContext, FormSubmissionChecker, InMemoryNumberIssuer, confirm_cases
from h12.domain.workflow import Request, Role, User, WorkflowEngine
from h12.reference import default_store
from h12.rulebook import load_form_rules, load_workflow_rules

from tests.domain.form.conftest import make_form

OWNER = User("req-1", Role.REQUESTER, "냉동기설계팀")
SAME_DEPT = User("req-2", Role.REQUESTER, "냉동기설계팀")
OTHER_DEPT = User("req-3", Role.REQUESTER, "RAC설계팀")
MANAGER = User("mgr-1", Role.MANAGER, "CAE팀")
ANALYST = User("an-1", Role.ANALYST, "CAE팀")
OTHER_ANALYST = User("an-2", Role.ANALYST, "CAE팀")

SUPPLEMENT = {"reason_code": "INFO_MISSING", "comment": "공간 온도가 비어 있습니다"}


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 2, 9, 0)

    def __call__(self) -> datetime:
        self.t += timedelta(minutes=1)
        return self.t


@pytest.fixture
def rules():
    return load_workflow_rules()


@pytest.fixture
def form_rules():
    return load_form_rules()


@pytest.fixture
def ref():
    return default_store().load()


@pytest.fixture
def issuer(form_rules):
    return InMemoryNumberIssuer(form_rules.target.request_no_format)


@pytest.fixture
def engine(rules, form_rules):
    context = FormContext(rules=form_rules, reference=default_store().load, request_date=datetime(2026, 11, 2).date())
    return WorkflowEngine(rules, FormSubmissionChecker(context))


@pytest.fixture
def clock():
    return Clock()


# 상태 이름 → 그 상태까지 가는 (사용자, 기능, 입력) 순서
_PATHS = {
    "DRAFT": [],
    "UNDER_REVIEW": [(OWNER, "submit", {})],
    "REVISION_REQUESTED": [(OWNER, "submit", {}), (MANAGER, "request_review_supplement", SUPPLEMENT)],
    "IN_PROGRESS": [(OWNER, "submit", {}), (MANAGER, "accept_and_assign", {"analyst": ANALYST})],
    "REJECTED": [(OWNER, "submit", {}),
                 (MANAGER, "reject", {"reason_code": "OUT_OF_SCOPE", "comment": "구조해석"})],
    "CANCELLED": [(OWNER, "cancel", {})],
}
_PATHS["ANALYSIS_REVISION_REQUESTED"] = _PATHS["IN_PROGRESS"] + [
    (ANALYST, "request_analysis_supplement", SUPPLEMENT)]
_PATHS["ON_HOLD"] = _PATHS["IN_PROGRESS"] + [
    (ANALYST, "hold", {"reason_code": "SCHEDULE", "comment": "일정"})]
_PATHS["RESULT_REVIEW"] = _PATHS["IN_PROGRESS"] + [
    (ANALYST, "register_result", {"result_summary": "풍량 3% 증가"})]
_PATHS["COMPLETED"] = _PATHS["RESULT_REVIEW"] + [(OWNER, "confirm_result", {})]

_PENDING = {
    "cancel": (OWNER, "request_cancel", {"comment": "과제 중단"}),
}


@pytest.fixture
def changed_form(form_rules, ref):
    """8장 검사를 통과하면서 실제 내용이 바뀐 진행 중 변경안."""
    def change(form):
        result = copy.deepcopy(form)
        result["conditions"]["operating"]["packages"][0]["rpm"] = form_rules.values.cell(900)
        return confirm_cases(result, reference=ref, rules=form_rules)
    return change


@pytest.fixture
def make_request(engine, clock, form_rules, ref, issuer, changed_form):
    counter = iter(range(1, 10_000))

    def make(status: str = "DRAFT", pending: str | None = None) -> Request:
        request = engine.create_request(OWNER, f"r-{next(counter)}", clock())
        engine.update_form(OWNER, request, make_form(form_rules, ref, issuer))
        steps = list(_PATHS[status])
        if pending:
            if pending == "change":
                steps.append((OWNER, "request_change", {"form": changed_form(request.form), "comment": "RPM 추가"}))
            else:
                steps.append(_PENDING[pending])
        for user, action, inputs in steps:
            engine.execute(user, request, action, inputs, clock())
        assert request.status == status
        return request

    return make
