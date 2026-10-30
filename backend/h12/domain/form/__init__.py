"""의뢰서 — 업무정의서 4장(의뢰서 구성), 5장(해석조건), 3.4-5·9·10.

의뢰서는 dict 로 저장한다 (workflow 의 Request.form, revision 스냅샷). 이 패키지는 그 dict 를 해석하고,
의뢰 대상 확정·PMS 선택처럼 시스템이 정하는 값을 바꾸는 작업과 검사를 제공한다.
"""

from .check import FormContext, check_form
from .cases import (
    MAX_AUTO_CASES, SINGLE, auto_combine_cases, case_columns, case_source_hash, check_cases, confirm_cases,
    default_cases, refresh_cases,
)
from .conditions import (
    ConditionConfig, active_groups, check_conditions, condition_config, default_pcb, field_need, group_mark,
    is_active, visible_groups,
)
from .content import check_content, clear_pms_project, request_title, select_pms_project
from .diff import FormChange, diff_forms
from .edit import merge_user_edit
from .errors import ConfirmationRequired, FormError
from .products import GeometryAxis, check_products, geometry_axis
from .rules import FormRules, RulesError
from .submission import FormSubmissionChecker
from .target import (
    InMemoryNumberIssuer, RequestNumberIssuer, TargetChange, TargetSelection, check_selection, config_of,
    confirm_target, is_locked, pinned_release, target_change, target_items,
)
from .values import Need, ValueSource, ValueStatus

__all__ = [
    "ConditionConfig", "ConfirmationRequired", "FormChange", "FormContext", "FormError", "FormRules",
    "FormSubmissionChecker",
    "GeometryAxis", "InMemoryNumberIssuer", "Need", "RequestNumberIssuer", "RulesError", "TargetChange",
    "TargetSelection", "ValueSource", "ValueStatus", "active_groups", "check_conditions", "check_content",
    "auto_combine_cases", "case_columns", "case_source_hash", "check_cases", "check_form", "check_products",
    "check_selection",
    "clear_pms_project", "condition_config", "config_of", "confirm_cases", "confirm_target", "default_pcb",
    "diff_forms", "field_need", "geometry_axis", "group_mark", "is_active",
    "is_locked", "merge_user_edit", "pinned_release", "request_title", "select_pms_project", "target_change",
    "default_cases", "MAX_AUTO_CASES", "refresh_cases", "SINGLE", "target_items", "visible_groups",
]
