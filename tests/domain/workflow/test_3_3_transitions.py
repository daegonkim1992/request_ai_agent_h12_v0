"""3.2 결과 상태, 3.3 상태 흐름, 3.4-7 이력."""

from __future__ import annotations

import pytest

from h12.domain.workflow import ActionNotAllowed

from .conftest import ANALYST, MANAGER, OTHER_ANALYST, OWNER, SUPPLEMENT

CHANGE = {"form": {"title": "변경안"}, "comment": "RPM 추가"}

# (시작 상태, 대기 요청, 수행자, 기능, 입력, 결과 상태)
CASES = [
    ("DRAFT", None, OWNER, "submit", {}, "UNDER_REVIEW"),
    ("UNDER_REVIEW", None, MANAGER, "request_review_supplement", SUPPLEMENT, "REVISION_REQUESTED"),
    ("UNDER_REVIEW", None, MANAGER, "reject", {"reason_code": "DUPLICATE", "comment": "중복"}, "REJECTED"),
    ("UNDER_REVIEW", None, MANAGER, "accept_and_assign", {"analyst": ANALYST}, "IN_PROGRESS"),
    ("REVISION_REQUESTED", None, OWNER, "resubmit", {}, "UNDER_REVIEW"),
    ("ANALYSIS_REVISION_REQUESTED", None, OWNER, "resubmit", {}, "IN_PROGRESS"),
    ("IN_PROGRESS", None, ANALYST, "request_analysis_supplement", SUPPLEMENT, "ANALYSIS_REVISION_REQUESTED"),
    ("IN_PROGRESS", None, MANAGER, "request_analysis_supplement", SUPPLEMENT, "ANALYSIS_REVISION_REQUESTED"),
    ("IN_PROGRESS", None, ANALYST, "hold", {"reason_code": "SCHEDULE", "comment": "일정"}, "ON_HOLD"),
    ("IN_PROGRESS", None, MANAGER, "hold", {"reason_code": "OTHER", "comment": "장비"}, "ON_HOLD"),
    ("ON_HOLD", None, ANALYST, "resume", {}, "IN_PROGRESS"),
    ("ON_HOLD", None, MANAGER, "resume", {}, "IN_PROGRESS"),
    ("IN_PROGRESS", None, MANAGER, "reassign", {"analyst": OTHER_ANALYST, "comment": "부하"}, "IN_PROGRESS"),
    ("ANALYSIS_REVISION_REQUESTED", None, MANAGER, "reassign",
     {"analyst": OTHER_ANALYST, "comment": "부하"}, "ANALYSIS_REVISION_REQUESTED"),
    ("ON_HOLD", None, MANAGER, "reassign", {"analyst": OTHER_ANALYST, "comment": "부하"}, "ON_HOLD"),
    ("IN_PROGRESS", None, OWNER, "request_change", CHANGE, "IN_PROGRESS"),
    ("IN_PROGRESS", "change", ANALYST, "accept_change", {}, "IN_PROGRESS"),
    ("IN_PROGRESS", "change", ANALYST, "decline_change", {"comment": "진행 많이 됨"}, "IN_PROGRESS"),
    ("DRAFT", None, OWNER, "cancel", {}, "CANCELLED"),
    ("UNDER_REVIEW", None, OWNER, "cancel", {}, "CANCELLED"),
    ("REVISION_REQUESTED", None, OWNER, "cancel", {}, "CANCELLED"),
    ("IN_PROGRESS", None, OWNER, "request_cancel", {"comment": "중단"}, "IN_PROGRESS"),
    ("ANALYSIS_REVISION_REQUESTED", None, OWNER, "request_cancel", {"comment": "중단"}, "ANALYSIS_REVISION_REQUESTED"),
    ("ON_HOLD", None, OWNER, "request_cancel", {"comment": "중단"}, "ON_HOLD"),
    ("IN_PROGRESS", "cancel", MANAGER, "approve_cancel", {}, "CANCELLED"),
    ("ANALYSIS_REVISION_REQUESTED", "cancel", MANAGER, "approve_cancel", {}, "CANCELLED"),
    ("ON_HOLD", "cancel", MANAGER, "approve_cancel", {}, "CANCELLED"),
    ("ON_HOLD", "cancel", MANAGER, "decline_cancel", {"comment": "진행 필요"}, "ON_HOLD"),
    ("IN_PROGRESS", None, ANALYST, "register_result", {"result_summary": "결과"}, "RESULT_REVIEW"),
    ("RESULT_REVIEW", None, OWNER, "request_rework", {"comment": "조건 누락"}, "IN_PROGRESS"),
    ("RESULT_REVIEW", None, OWNER, "confirm_result", {}, "COMPLETED"),
]


@pytest.mark.parametrize("start,pending,user,action,inputs,expected", CASES,
                         ids=[f"{c[0]}-{c[3]}-{c[2].id}" for c in CASES])
def test_transition_and_history(engine, make_request, clock, start, pending, user, action, inputs, expected):
    request = make_request(start, pending)
    before = len(request.events)

    event = engine.execute(user, request, action, inputs, clock())

    assert request.status == expected
    assert request.events[-1] is event and len(request.events) == before + 1
    assert (event.action, event.from_status, event.to_status, event.actor_id) == (action, start, expected, user.id)
    assert event.reason_code == inputs.get("reason_code")
    assert event.comment == inputs.get("comment")
    assert event.event_type == engine.rules.actions[action].event


def test_accept_records_analyst(engine, make_request):
    request = make_request("IN_PROGRESS")
    assert request.analyst_id == ANALYST.id
    assert request.events[-1].payload["analyst_id"] == ANALYST.id


def test_reassign_moves_assignment_and_view(engine, make_request, clock):
    request = make_request("IN_PROGRESS")
    event = engine.execute(MANAGER, request, "reassign", {"analyst": OTHER_ANALYST, "comment": "부하"}, clock())

    assert request.analyst_id == OTHER_ANALYST.id
    assert event.payload == {"previous_analyst_id": ANALYST.id, "analyst_id": OTHER_ANALYST.id}
    assert "register_result" in engine.available_actions(OTHER_ANALYST, request)
    assert engine.available_actions(ANALYST, request) == []


def test_rework_returns_to_same_analyst(engine, make_request, clock):
    request = make_request("RESULT_REVIEW")
    engine.execute(OWNER, request, "request_rework", {"comment": "범위 부족"}, clock())
    assert request.analyst_id == ANALYST.id
    assert "register_result" in engine.available_actions(ANALYST, request)


def test_resume_by_holder_only_or_manager(engine, make_request, clock):
    request = make_request("IN_PROGRESS")
    engine.execute(MANAGER, request, "hold", {"reason_code": "SCHEDULE", "comment": "일정"}, clock())

    # 관리자가 보류했으면 담당자는 재개할 수 없다
    assert "resume" not in engine.available_actions(ANALYST, request)
    engine.execute(MANAGER, request, "resume", {}, clock())
    assert request.held_by is None


def test_reassign_hands_over_analyst_hold(engine, make_request, clock):
    """3.4-12 담당자가 보류한 의뢰를 재배정하면 보류 책임도 넘어간다."""
    request = make_request("ON_HOLD")  # 담당자 ANALYST 가 보류
    engine.execute(MANAGER, request, "reassign", {"analyst": OTHER_ANALYST, "comment": "부하"}, clock())

    assert request.held_by == OTHER_ANALYST.id
    assert engine.available_actions(ANALYST, request) == []
    assert not engine.can_view(ANALYST, request)
    assert not engine.is_todo(ANALYST, request)
    assert engine.available_actions(OTHER_ANALYST, request) == ["resume"]
    assert engine.is_todo(OTHER_ANALYST, request)


def test_reassign_keeps_manager_hold(engine, make_request, clock):
    request = make_request("IN_PROGRESS")
    engine.execute(MANAGER, request, "hold", {"reason_code": "SCHEDULE", "comment": "일정"}, clock())
    engine.execute(MANAGER, request, "reassign", {"analyst": OTHER_ANALYST, "comment": "부하"}, clock())

    assert request.held_by == MANAGER.id
    assert engine.available_actions(OTHER_ANALYST, request) == []


def test_unknown_action(engine, make_request, clock):
    with pytest.raises(ActionNotAllowed):
        engine.execute(OWNER, make_request(), "approve_everything", {}, clock())
