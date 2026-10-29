"""2장 볼 수 있는 의뢰, 3.5 역할별 할 일 목록."""

from __future__ import annotations

import pytest

from h12.domain.workflow import ActionNotAllowed

from .conftest import ANALYST, MANAGER, OTHER_ANALYST, OTHER_DEPT, OWNER, SAME_DEPT


def test_only_requester_creates(engine, clock):
    for user in (MANAGER, ANALYST):
        with pytest.raises(ActionNotAllowed):
            engine.create_request(user, "r-x", clock())
    request = engine.create_request(OWNER, "r-x", clock())
    assert (request.status, request.requester_department) == ("DRAFT", OWNER.department)


@pytest.mark.parametrize("status,user,visible", [
    # 작성 중인 의뢰는 작성자만 본다. 관리자도 볼 수 없다 (2장)
    ("DRAFT", OWNER, True),
    ("DRAFT", SAME_DEPT, False),
    ("DRAFT", MANAGER, False),
    # 제출 전에 취소한 의뢰도 작성자만 본다
    ("CANCELLED", OWNER, True),
    ("CANCELLED", SAME_DEPT, False),
    ("CANCELLED", MANAGER, False),
    ("UNDER_REVIEW", SAME_DEPT, True),
    ("COMPLETED", SAME_DEPT, True),
    ("REJECTED", SAME_DEPT, True),
    ("UNDER_REVIEW", OTHER_DEPT, False),
    ("UNDER_REVIEW", MANAGER, True),
    ("REVISION_REQUESTED", MANAGER, True),
    ("UNDER_REVIEW", ANALYST, False),  # 배정 전
    ("IN_PROGRESS", ANALYST, True),
    ("IN_PROGRESS", OTHER_ANALYST, False),
])
def test_2_visibility(engine, make_request, status, user, visible):
    assert engine.can_view(user, make_request(status)) is visible


def test_2_cancelled_after_submit_is_shared(engine, make_request, clock):
    request = make_request("UNDER_REVIEW")
    engine.execute(OWNER, request, "cancel", {}, clock())
    assert engine.can_view(SAME_DEPT, request) and engine.can_view(MANAGER, request)


def test_2_same_department_is_read_only(engine, make_request):
    for status in ("UNDER_REVIEW", "IN_PROGRESS", "RESULT_REVIEW"):
        request = make_request(status)
        assert engine.available_actions(SAME_DEPT, request) == []
        assert not engine.can_edit_form(SAME_DEPT, make_request("REVISION_REQUESTED"))


# (상태, 대기 요청) → 할 일에 넣는 사용자
TODO = {
    ("DRAFT", None): {OWNER},
    ("UNDER_REVIEW", None): {MANAGER},
    ("REVISION_REQUESTED", None): {OWNER},
    ("IN_PROGRESS", None): {ANALYST},
    ("IN_PROGRESS", "change"): {ANALYST},
    # 취소 요청 대기 중인 의뢰는 관리자 할 일에만 들어간다 (3.4-4)
    ("IN_PROGRESS", "cancel"): {MANAGER},
    ("ANALYSIS_REVISION_REQUESTED", None): {OWNER},
    ("ANALYSIS_REVISION_REQUESTED", "cancel"): {MANAGER},
    ("ON_HOLD", "cancel"): {MANAGER},
    ("ON_HOLD", None): {ANALYST},  # 담당자 본인이 보류
    ("RESULT_REVIEW", None): {OWNER},
    ("COMPLETED", None): set(),
    ("REJECTED", None): set(),
    ("CANCELLED", None): set(),
}


@pytest.mark.parametrize("state", TODO, ids=lambda s: f"{s[0]}+{s[1]}" if s[1] else s[0])
def test_3_5_todo(engine, make_request, state):
    request = make_request(*state)
    users = [OWNER, SAME_DEPT, MANAGER, ANALYST, OTHER_ANALYST]
    assert {u for u in users if engine.is_todo(u, request)} == TODO[state]


def test_3_5_hold_by_manager_not_in_analyst_todo(engine, make_request, clock):
    request = make_request("IN_PROGRESS")
    engine.execute(MANAGER, request, "hold", {"reason_code": "SCHEDULE", "comment": "일정"}, clock())
    assert not engine.is_todo(ANALYST, request)
