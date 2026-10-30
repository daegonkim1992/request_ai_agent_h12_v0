"""8장 전체 제출 검사와 WorkflowEngine 연결."""

from __future__ import annotations

from h12.domain.form import FormContext, FormSubmissionChecker, InMemoryNumberIssuer
from h12.domain.workflow import SubmissionBlocked, WorkflowEngine
from h12.reference import default_store
from h12.rulebook import load_form_rules

from tests.domain.form.conftest import edit, make_form

from .conftest import ANALYST, MANAGER, OWNER, Clock


def _engine(rules):
    context = FormContext(rules=load_form_rules(),
                          reference=default_store().load, request_date=Clock().t.date())
    return WorkflowEngine(rules, FormSubmissionChecker(context))


def test_submit_uses_full_form_and_case_checker(rules):
    form_rules = load_form_rules()
    reference = default_store().load()
    form = make_form(form_rules, reference, InMemoryNumberIssuer(form_rules.target.request_no_format))
    clock = Clock()
    engine = _engine(rules)
    request = engine.create_request(OWNER, "r-1", clock())
    engine.update_form(OWNER, request, form)

    engine.execute(OWNER, request, "submit", {}, clock())
    assert request.status == "UNDER_REVIEW"
    assert request.revisions[0].form == form


def test_change_request_uses_first_submission_date_and_current_case(rules):
    form_rules = load_form_rules()
    reference = default_store().load()
    issuer = InMemoryNumberIssuer(form_rules.target.request_no_format)
    form = make_form(form_rules, reference, issuer)
    clock = Clock()
    engine = _engine(rules)
    request = engine.create_request(OWNER, "r-1", clock())
    engine.update_form(OWNER, request, form)
    engine.execute(OWNER, request, "submit", {}, clock())
    engine.execute(MANAGER, request, "accept_and_assign", {"analyst": ANALYST}, clock())

    changed = edit(form, lambda f: f["conditions"]["operating"]["packages"][0].update(
        rpm=form_rules.values.cell(900)))
    try:
        engine.execute(OWNER, request, "request_change", {"form": changed, "comment": "RPM 변경"}, clock())
    except SubmissionBlocked as exc:
        assert exc.issues[0].location == "cases"
    else:
        raise AssertionError("Case 재확인 전 변경 요청은 제출될 수 없다")
