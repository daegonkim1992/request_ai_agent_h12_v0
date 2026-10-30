from __future__ import annotations


class ReferenceDataError(ValueError):
    """기준 데이터가 업무 규칙과 맞지 않는다. 잘못된 데이터는 읽는 시점에 막는다."""
