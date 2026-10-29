"""3.2 필수 입력, 3.7 사유 코드."""

from __future__ import annotations

import pytest

from h12.domain.workflow import InvalidInput

from .conftest import ANALYST, MANAGER, OTHER_ANALYST, OWNER


@pytest.mark.parametrize("action,codes", [
    ("request_review_supplement",
     ["INFO_MISSING", "CONDITION_UNCLEAR", "CONDITION_INVALID", "GEOMETRY_NOT_READY",
      "PURPOSE_UNCLEAR", "TYPE_MISMATCH", "OTHER"]),
    ("reject", ["OUT_OF_SCOPE", "NOT_SUITABLE", "DUPLICATE", "OTHER"]),
])
def test_3_7_review_reason_codes(engine, make_request, clock, action, codes):
    for code in codes:
        request = make_request("UNDER_REVIEW")
        engine.execute(MANAGER, request, action, {"reason_code": code, "comment": "설명"}, clock())


@pytest.mark.parametrize("action,wrong", [
    ("request_review_supplement", "OUT_OF_SCOPE"),  # 반려 코드
    ("reject", "INFO_MISSING"),                     # 보완 코드
])
def test_3_7_codes_belong_to_their_action(engine, make_request, clock, action, wrong):
    with pytest.raises(InvalidInput) as exc:
        engine.execute(MANAGER, make_request("UNDER_REVIEW"), action, {"reason_code": wrong, "comment": "x"}, clock())
    assert "reason_code" in exc.value.errors


def test_3_7_hold_codes(engine, make_request, clock):
    with pytest.raises(InvalidInput):
        engine.execute(ANALYST, make_request("IN_PROGRESS"), "hold",
                       {"reason_code": "INFO_MISSING", "comment": "정보 부족"}, clock())
    engine.execute(ANALYST, make_request("IN_PROGRESS"), "hold", {"reason_code": "SCHEDULE", "comment": "일정"}, clock())


# (상태, 대기 요청, 수행자, 기능, 빠진 입력)
MISSING = [
    ("UNDER_REVIEW", None, MANAGER, "request_review_supplement", {"reason_code": "INFO_MISSING"}, "comment"),
    ("UNDER_REVIEW", None, MANAGER, "reject", {"comment": "x"}, "reason_code"),
    ("UNDER_REVIEW", None, MANAGER, "accept_and_assign", {}, "analyst"),
    ("IN_PROGRESS", None, MANAGER, "reassign", {"analyst": OTHER_ANALYST}, "comment"),
    ("IN_PROGRESS", None, OWNER, "request_change", {"comment": "x"}, "form"),
    ("IN_PROGRESS", None, OWNER, "request_change", {"form": {}}, "comment"),
    ("IN_PROGRESS", "change", ANALYST, "decline_change", {}, "comment"),
    ("IN_PROGRESS", None, OWNER, "request_cancel", {"comment": "  "}, "comment"),
    ("IN_PROGRESS", "cancel", MANAGER, "decline_cancel", {}, "comment"),
    ("IN_PROGRESS", None, ANALYST, "register_result", {}, "result_summary"),
    ("RESULT_REVIEW", None, OWNER, "request_rework", {}, "comment"),
]


@pytest.mark.parametrize("status,pending,user,action,inputs,missing", MISSING,
                         ids=[f"{m[3]}-{m[5]}" for m in MISSING])
def test_required_inputs(engine, make_request, clock, status, pending, user, action, inputs, missing):
    with pytest.raises(InvalidInput) as exc:
        engine.execute(user, make_request(status, pending), action, inputs, clock())
    assert missing in exc.value.errors


def test_assignee_must_be_analyst(engine, make_request, clock):
    with pytest.raises(InvalidInput):
        engine.execute(MANAGER, make_request("UNDER_REVIEW"), "accept_and_assign", {"analyst": MANAGER}, clock())


def test_reassign_to_same_analyst_rejected(engine, make_request, clock):
    with pytest.raises(InvalidInput):
        engine.execute(MANAGER, make_request("IN_PROGRESS"), "reassign", {"analyst": ANALYST, "comment": "x"}, clock())


def test_unexpected_input_rejected(engine, make_request, clock):
    with pytest.raises(InvalidInput) as exc:
        engine.execute(OWNER, make_request(), "submit", {"comment": "제출합니다"}, clock())
    assert "comment" in exc.value.errors
