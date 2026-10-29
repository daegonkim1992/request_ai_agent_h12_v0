"""3.4 공통 규칙."""

from __future__ import annotations

import pytest

from h12.domain.workflow import (
    ActionNotAllowed, InvalidInput, Issue, SubmissionBlocked, WorkflowEngine,
)

from .conftest import ANALYST, MANAGER, OWNER, SAME_DEPT

CHANGE = {"form": {"title": "변경안"}, "comment": "RPM 추가"}


# 3.4-1 수정 가능 상태
@pytest.mark.parametrize("status,editable", [
    ("DRAFT", True), ("REVISION_REQUESTED", True), ("ANALYSIS_REVISION_REQUESTED", True),
    ("UNDER_REVIEW", False), ("IN_PROGRESS", False), ("ON_HOLD", False),
    ("RESULT_REVIEW", False), ("COMPLETED", False), ("REJECTED", False), ("CANCELLED", False),
])
def test_3_4_1_editable_statuses(engine, make_request, status, editable):
    request = make_request(status)
    assert engine.can_edit_form(OWNER, request) is editable
    if not editable:
        with pytest.raises(ActionNotAllowed):
            engine.update_form(OWNER, request, {"title": "수정"})


@pytest.mark.parametrize("user", [MANAGER, ANALYST, SAME_DEPT], ids=lambda u: u.id)
def test_3_4_1_only_requester_edits(engine, make_request, user):
    request = make_request("ANALYSIS_REVISION_REQUESTED")
    with pytest.raises(ActionNotAllowed):
        engine.update_form(user, request, {"title": "수정"})


def test_3_4_1_update_form_copies(engine, make_request):
    request = make_request()
    form = {"products": ["A"]}
    engine.update_form(OWNER, request, form)
    form["products"].append("B")
    assert request.form == {"products": ["A"]}


# 3.4-4 대기 요청은 하나만, 대기 중이면 결과 등록 불가
def test_3_4_4_single_pending(engine, make_request, clock):
    request = make_request("IN_PROGRESS", "change")
    with pytest.raises(ActionNotAllowed):
        engine.execute(OWNER, request, "request_cancel", {"comment": "중단"}, clock())
    with pytest.raises(ActionNotAllowed):
        engine.execute(ANALYST, request, "register_result", {"result_summary": "결과"}, clock())


def test_3_4_4_pending_cleared_after_decision(engine, make_request, clock):
    request = make_request("IN_PROGRESS", "cancel")
    engine.execute(MANAGER, request, "decline_cancel", {"comment": "진행 필요"}, clock())
    assert request.pending is None
    assert "register_result" in engine.available_actions(ANALYST, request)


def test_3_4_4_cancel_pending_freezes_form(engine, make_request, clock):
    """취소 요청 대기 중에는 의뢰자가 의뢰서도 고칠 수 없다. 거절되면 다시 고칠 수 있다."""
    request = make_request("ANALYSIS_REVISION_REQUESTED", "cancel")
    assert not engine.can_edit_form(OWNER, request)
    with pytest.raises(ActionNotAllowed):
        engine.update_form(OWNER, request, {"title": "보완본"})
    with pytest.raises(ActionNotAllowed):
        engine.execute(OWNER, request, "resubmit", {}, clock())

    engine.execute(MANAGER, request, "decline_cancel", {"comment": "진행 필요"}, clock())
    assert engine.can_edit_form(OWNER, request)
    assert set(engine.available_actions(OWNER, request)) == {"resubmit", "request_cancel"}


# 3.4-3, 3.4-5 진행 중 변경과 revision
def test_3_4_5_revisions(engine, make_request, clock):
    request = make_request("IN_PROGRESS")  # 제출 1회
    assert [r.cause_event for r in request.revisions] == ["SUBMITTED"]

    engine.execute(OWNER, request, "request_change", CHANGE, clock())
    assert request.form == {"title": "초안"}, "수락 전에는 반영하지 않는다"
    engine.execute(ANALYST, request, "accept_change", {}, clock())

    assert request.form == {"title": "변경안"}
    assert [r.revision_no for r in request.revisions] == [1, 2]
    assert request.current_revision.form == {"title": "변경안"}
    assert request.current_revision.cause_event == "CHANGE_ACCEPTED"
    assert request.revisions[0].form == {"title": "초안"}


def test_3_4_3_declined_change_keeps_original(engine, make_request, clock):
    request = make_request("IN_PROGRESS", "change")
    engine.execute(ANALYST, request, "decline_change", {"comment": "진행 많이 됨"}, clock())
    assert request.form == {"title": "초안"}
    assert len(request.revisions) == 1
    assert request.pending is None
    # 3.4-7 거절된 제안 내용도 이력에 남는다
    requested = next(e for e in request.events if e.event_type == "CHANGE_REQUESTED")
    assert requested.payload["proposed_form"] == {"title": "변경안"}


def test_g2_change_must_be_answered_before_analysis_supplement(engine, make_request, clock):
    request = make_request("IN_PROGRESS", "change")
    for user in (ANALYST, MANAGER):
        with pytest.raises(ActionNotAllowed):
            engine.execute(user, request, "request_analysis_supplement",
                           {"reason_code": "INFO_MISSING", "comment": "x"}, clock())
    engine.execute(ANALYST, request, "decline_change", {"comment": "범위 밖"}, clock())
    engine.execute(ANALYST, request, "request_analysis_supplement",
                   {"reason_code": "INFO_MISSING", "comment": "x"}, clock())
    assert request.status == "ANALYSIS_REVISION_REQUESTED"


def test_g2_change_survives_hold(engine, make_request, clock):
    request = make_request("IN_PROGRESS", "change")
    engine.execute(ANALYST, request, "hold", {"reason_code": "SCHEDULE", "comment": "일정"}, clock())
    assert "accept_change" not in engine.available_actions(ANALYST, request)
    engine.execute(ANALYST, request, "resume", {}, clock())
    assert "accept_change" in engine.available_actions(ANALYST, request)


def test_cancel_approved_during_hold_clears_holder(engine, make_request, clock):
    request = make_request("ON_HOLD", "cancel")
    engine.execute(MANAGER, request, "approve_cancel", {}, clock())
    assert (request.status, request.pending, request.held_by) == ("CANCELLED", None, None)


def test_3_4_5_resubmit_snapshots_edited_form(engine, make_request, clock):
    request = make_request("REVISION_REQUESTED")
    engine.update_form(OWNER, request, {"title": "보완본"})
    engine.execute(OWNER, request, "resubmit", {}, clock())
    assert [(r.revision_no, r.form["title"], r.cause_event) for r in request.revisions] == [
        (1, "초안", "SUBMITTED"), (2, "보완본", "RESUBMITTED")]


def test_3_4_5_revision_is_snapshot(engine, make_request):
    request = make_request("REVISION_REQUESTED")
    engine.update_form(OWNER, request, {"title": "편집 중"})
    assert request.current_revision.form == {"title": "초안"}


# 3.4-6 결과 회차
def test_3_4_6_result_rounds(engine, make_request, clock):
    request = make_request("RESULT_REVIEW")
    engine.execute(OWNER, request, "request_rework", {"comment": "범위 부족"}, clock())
    engine.execute(ANALYST, request, "register_result", {"result_summary": "2차 결과"}, clock())

    assert [(r.round_no, r.summary) for r in request.results] == [(1, "풍량 3% 증가"), (2, "2차 결과")]
    assert request.current_result.summary == "2차 결과"
    assert request.events[-1].payload == {"round_no": 2}


# 3.4-7 이력: 순번이 이어지고 모든 기능이 남는다
def test_3_4_7_history_is_complete(make_request):
    request = make_request("COMPLETED")
    assert [e.seq for e in request.events] == list(range(1, len(request.events) + 1))
    assert [e.event_type for e in request.events] == [
        "SUBMITTED", "ACCEPTED", "RESULT_REGISTERED", "REQUESTER_CONFIRMED"]
    assert all(e.at for e in request.events)


# 3.4-8 종료 상태는 조회만
@pytest.mark.parametrize("status", ["COMPLETED", "REJECTED", "CANCELLED"])
def test_3_4_8_terminal_is_read_only(engine, make_request, status):
    request = make_request(status)
    for user in (OWNER, MANAGER, ANALYST):
        assert engine.available_actions(user, request) == []
        assert not engine.can_edit_form(user, request)


# 3.4-11 결과 확인 필요 상태에서는 취소·취소 요청을 할 수 없다
def test_3_4_11_no_cancel_in_result_review(engine, make_request, clock):
    request = make_request("RESULT_REVIEW")
    for action in ("cancel", "request_cancel"):
        with pytest.raises(ActionNotAllowed):
            engine.execute(OWNER, request, action, {"comment": "x"} if action == "request_cancel" else {}, clock())


# 실패한 기능은 의뢰를 바꾸지 않는다
def test_failed_action_leaves_request_unchanged(engine, make_request, clock):
    request = make_request("UNDER_REVIEW")
    snapshot = (request.status, list(request.events), request.analyst_id)
    with pytest.raises(InvalidInput):
        engine.execute(MANAGER, request, "accept_and_assign", {"analyst": OWNER}, clock())
    assert (request.status, request.events, request.analyst_id) == snapshot


# 8장 제출 조건 검사 자리: 실패하면 위치와 함께 막는다
class _Blocking:
    def __init__(self):
        self.seen = []

    def check(self, form):
        self.seen.append(form)
        return [Issue("conditions.operating[0].fan_rpm", "필수 입력")] if form.get("title") != "완성본" else []


def test_submission_blocked_with_location(rules, clock):
    checker = _Blocking()
    engine = WorkflowEngine(rules, checker)
    request = engine.create_request(OWNER, "r-1", clock())
    engine.update_form(OWNER, request, {"title": "초안"})

    with pytest.raises(SubmissionBlocked) as exc:
        engine.execute(OWNER, request, "submit", {}, clock())
    assert exc.value.issues[0].location == "conditions.operating[0].fan_rpm"
    assert request.status == "DRAFT" and request.revisions == []

    engine.update_form(OWNER, request, {"title": "완성본"})
    engine.execute(OWNER, request, "submit", {}, clock())
    assert request.status == "UNDER_REVIEW"


def test_change_request_checks_proposed_form(rules, clock):
    checker = _Blocking()
    engine = WorkflowEngine(rules, checker)
    request = engine.create_request(OWNER, "r-1", clock())
    engine.update_form(OWNER, request, {"title": "완성본"})
    engine.execute(OWNER, request, "submit", {}, clock())
    engine.execute(MANAGER, request, "accept_and_assign", {"analyst": ANALYST}, clock())

    with pytest.raises(SubmissionBlocked):
        engine.execute(OWNER, request, "request_change", {"form": {"title": "미완성"}, "comment": "변경"}, clock())
    assert checker.seen[-1] == {"title": "미완성"}
    assert request.pending is None
