from __future__ import annotations

from typing import Any, Iterable


class FormError(ValueError):
    """의뢰서 작업을 할 수 없다. 이 예외가 나면 의뢰서는 바뀌지 않는다."""


class FormValidationError(FormError):
    """필드 위치를 가진 의뢰서 형식·검증 오류."""

    def __init__(self, issues: Iterable[Any]):
        self.issues = list(issues)
        super().__init__("; ".join(f"{issue.location}: {issue.message}" for issue in self.issues))


class ConfirmationRequired(FormError):
    """4.2 확정한 의뢰 대상을 바꾸려면 영향을 확인받아야 한다."""

    def __init__(self, impact: Any):
        super().__init__("의뢰 대상을 바꾸면 조건 구성이 바뀐다. 영향을 확인한 뒤 다시 요청한다")
        self.impact = impact
