"""의뢰서 제출 검사 어댑터 — WorkflowEngine에 8장 검사를 연결한다."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any, Mapping

from .check import FormContext, check_form


class FormSubmissionChecker:
    def __init__(self, context: FormContext):
        self.context = context

    def check(self, form: Mapping[str, Any], *, request_date: date):
        return check_form(form, replace(self.context, request_date=request_date))
