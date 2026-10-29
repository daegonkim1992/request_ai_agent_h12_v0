"""3.2 모든 기능은 보이는 상태에서만 메뉴로 나타난다.

정의서의 기능 표를 (상태, 대기 요청) × 사용자 기준으로 옮겨 적었다.
여기 없는 사용자(같은 부서 의뢰자, 다른 담당자)는 어떤 상태에서도 기능이 없다.
"""

from __future__ import annotations

import pytest

from .conftest import ANALYST, MANAGER, OTHER_ANALYST, OTHER_DEPT, OWNER, SAME_DEPT

EXPECTED = {
    ("DRAFT", None): {
        OWNER: {"submit", "cancel"},
    },
    ("UNDER_REVIEW", None): {
        OWNER: {"cancel"},
        MANAGER: {"request_review_supplement", "reject", "accept_and_assign"},
    },
    ("REVISION_REQUESTED", None): {
        OWNER: {"resubmit", "cancel"},
    },
    ("IN_PROGRESS", None): {
        OWNER: {"request_change", "request_cancel"},
        MANAGER: {"request_analysis_supplement", "hold", "reassign"},
        ANALYST: {"request_analysis_supplement", "hold", "register_result"},
    },
    ("IN_PROGRESS", "change"): {
        # 변경 요청에 먼저 답해야 해석 단계 보완을 요청할 수 있다 (3.4-4)
        MANAGER: {"hold", "reassign"},
        ANALYST: {"hold", "accept_change", "decline_change"},
    },
    # 3.4-4 취소 요청 대기 중에는 관리자의 승인·거절 외에 모든 기능을 막는다
    ("IN_PROGRESS", "cancel"): {
        MANAGER: {"approve_cancel", "decline_cancel"},
    },
    ("ANALYSIS_REVISION_REQUESTED", None): {
        OWNER: {"resubmit", "request_cancel"},
        MANAGER: {"reassign"},
    },
    ("ANALYSIS_REVISION_REQUESTED", "cancel"): {
        MANAGER: {"approve_cancel", "decline_cancel"},
    },
    ("ON_HOLD", None): {  # 담당자가 보류한 의뢰
        OWNER: {"request_cancel"},
        MANAGER: {"resume", "reassign"},
        ANALYST: {"resume"},
    },
    ("ON_HOLD", "cancel"): {
        MANAGER: {"approve_cancel", "decline_cancel"},
    },
    ("RESULT_REVIEW", None): {
        OWNER: {"request_rework", "confirm_result"},
    },
    ("COMPLETED", None): {},
    ("REJECTED", None): {},
    ("CANCELLED", None): {},
}

USERS = [OWNER, SAME_DEPT, OTHER_DEPT, MANAGER, ANALYST, OTHER_ANALYST]


@pytest.mark.parametrize("state", EXPECTED, ids=lambda s: f"{s[0]}+{s[1]}" if s[1] else s[0])
@pytest.mark.parametrize("user", USERS, ids=lambda u: u.id)
def test_visible_actions(engine, make_request, state, user):
    request = make_request(*state)
    assert set(engine.available_actions(user, request)) == EXPECTED[state].get(user, set())


def test_every_action_is_visible_somewhere():
    visible = set().union(*(a for per_user in EXPECTED.values() for a in per_user.values()))
    assert len(visible) == 19
