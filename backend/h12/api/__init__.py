"""HTTP 계층."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import asdict
from typing import Any

from flask import Flask, current_app, request

from h12.application import ConcurrentModification, NotFound, RequestService
from h12.domain.form import ConfirmationRequired, FormError, FormValidationError, TargetSelection, request_title, target_items
from h12.domain.reference import HeatExchangerType
from h12.domain.workflow import ActionNotAllowed, InvalidInput, Request, SubmissionBlocked, User
from h12.infra import Database
from h12.reference import default_store
from h12.rulebook import load_workflow_rules


class AuthenticationRequired(Exception):
    pass


_WORKFLOW_INPUTS = {
    "reason_code": {"label": "사유 코드", "kind": "reason_code"},
    "comment": {"label": "사유 또는 설명", "kind": "textarea"},
    "analyst": {"label": "해석담당자", "kind": "analyst", "request_key": "analyst_id"},
    "form": {"label": "변경 의뢰서", "kind": "form_snapshot"},
    "result_summary": {"label": "결과 요약", "kind": "textarea"},
    "confirm_case": {"label": "변경한 조건·형상의 Case 구성을 다시 확인했습니다", "kind": "boolean"},
}


def create_app(*, database_url: str | None = None, auth_secret: str | None = None) -> Flask:
    app = Flask(__name__)
    auth_secret = auth_secret or os.getenv("H12_AUTH_SECRET")
    if not auth_secret:
        raise RuntimeError("H12_AUTH_SECRET 환경 변수 또는 auth_secret 인자가 필요하다")
    app.config["H12_AUTH_SECRET"] = auth_secret.encode("utf-8")
    rules = load_workflow_rules()
    database = Database(database_url or os.getenv("H12_DATABASE_URL", "sqlite:///h12.db"))
    database.create_all()
    service = RequestService(database, default_store())
    app.extensions["h12.database"] = database
    app.extensions["h12.service"] = service

    @app.errorhandler(AuthenticationRequired)
    def unauthenticated(e): return {"error": str(e)}, 401
    @app.errorhandler(NotFound)
    def not_found(e): return {"error": str(e)}, 404
    @app.errorhandler(ActionNotAllowed)
    def forbidden(e): return {"error": str(e)}, 403
    @app.errorhandler(InvalidInput)
    def invalid(e): return {"error": "입력 오류", "fields": e.errors}, 400
    @app.errorhandler(SubmissionBlocked)
    def blocked(e): return {"error": "제출 조건 미충족", "issues": [asdict(i) for i in e.issues]}, 400
    @app.errorhandler(ConfirmationRequired)
    def confirm(e):
        impact = asdict(e.impact)
        impact["messages"] = _target_impact_messages(e.impact, service.form_rules)
        return {"error": "확인 필요", "impact": impact}, 409
    @app.errorhandler(FormValidationError)
    def validation(e): return {"error": "의뢰서 입력 오류", "issues": [asdict(i) for i in e.issues]}, 400
    @app.errorhandler(FormError)
    def form_error(e): return {"error": str(e)}, 400
    @app.errorhandler(ConcurrentModification)
    def conflict(e): return {"error": str(e)}, 409

    @app.get("/api/health")
    def health(): return {"status": "ok", "workflow_statuses": len(rules.statuses)}

    @app.get("/api/reference/target-options")
    def target_options():
        # 의뢰 대상 선택지는 사용자가 내부 taxonomy ID를 알 필요 없이 고르도록 제공한다.
        _actor(service)
        reference = service.references.load()
        form_rules = service.form_rules
        return {
            "release": reference.release,
            "taxonomy": [{
                "id": path.id, "division": path.division, "product_lineup": path.product_lineup,
                "platform": path.platform, "chassis": path.chassis,
                "requires_analysis_scope": "analysis_scope" in target_items(path, "AIRFLOW_RATE", form_rules),
            } for path in reference.taxonomy.paths],
            "analysis_types": [{"code": item.code, "label": item.label, "description": item.description,
                                "requires_cooling_method": item.code in form_rules.target.cooling_method_types}
                               for item in form_rules.analysis_types.values()],
            "analysis_scope": [{"code": key, "label": value}
                               for key, value in form_rules.options["analysis_scope"].choices.items()],
            "cooling_method": [{"code": key, "label": value}
                               for key, value in form_rules.options["cooling_method"].choices.items()],
        }

    @app.get("/api/ui-contract")
    def ui_contract():
        """UI가 업무 규칙을 복제하지 않도록 표시용 계약만 제공한다."""
        _actor(service)
        form_rules = service.form_rules
        return {
            "options": {
                key: {
                    "choices": [{"code": code, "label": label}
                                for code, label in option.choices.items()],
                    "allow_custom": option.allow_custom,
                    "default": option.default,
                }
                for key, option in form_rules.options.items()
            },
            "fields": [
                {
                    "path": f"{section}.{field.key}", "label": field.label,
                    "kind": field.kind, "unit": field.unit, "options": field.options,
                    "required": field.required,
                    "required_for_types": sorted(field.required_for_types or ()),
                }
                for section, fields in form_rules.sections.items()
                for field in fields.values()
            ] + [{
                "path": "analysis_overview.pms_project", "label": "프로젝트명(PMS)",
                "kind": "pms_project", "unit": None, "options": None,
                "required": True, "required_for_types": sorted(form_rules.pms_required_for),
            }],
            "geometry": {
                "base_product": {
                    "path": "geometry.base_product", "label": "Base 제품", "required": True,
                    "id": _client_uuid_id(),
                    "fields": [
                        _field("geometry.base_product.drawing_no", "도면번호", pattern=form_rules.drawing_no_pattern.pattern),
                        _field("geometry.base_product.display_name", "표시명", required=False),
                    ],
                },
                "comparison_products": {
                    "repeater": _repeater("geometry.comparison_products[]", "비교 제품", id_required=True),
                    "fields": [
                        _field("geometry.comparison_products[].drawing_no", "도면번호", pattern=form_rules.drawing_no_pattern.pattern),
                        _field("geometry.comparison_products[].display_name", "표시명", required=False),
                        _field("geometry.comparison_products[].difference_from_base", "Base 대비 차이"),
                    ],
                },
            },
            "condition_groups": [{
                "key": group.key, "label": group.label, "column": group.column,
                "package_label": group.package_label, "single": group.single,
                "repeaters": [] if group.single else [
                    _repeater("packages[]", group.package_label or "조건 패키지", min_items=1, id_required=True),
                ],
                "toggle": None if group.toggle is None else {
                    "key": group.toggle.key, "label": group.toggle.label, "off_when": group.toggle.off_when,
                },
                "checks": list(group.checks),
                "fields": [{
                    "key": field.key, "label": field.label, "kind": field.kind, "unit": field.unit,
                    "required": field.required, "column": field.column,
                } for field in group.fields.values()],
            } for group in form_rules.groups.values()],
            "condition_specials": {
                "operating": {
                    "max_fans": form_rules.operating["max_fans"],
                    "rpm_modes": _choices(form_rules.operating["rpm_modes"]),
                    "airflow_purposes": _choices(form_rules.operating["airflow_purposes"]),
                    "repeaters": [
                        _repeater("packages[].fans[]", "팬", count_from="packages[].fan_count",
                                  visible_when={"path": "packages[].rpm_mode", "equals": "individual"}),
                    ],
                    "fields": [
                        _field("packages[].airflow", "제품 풍량", kind="number", required=False),
                        _field("packages[].airflow_purpose", "풍량 활용 목적", kind="choice", required=False,
                               choices=_choices(form_rules.operating["airflow_purposes"])),
                        _field("packages[].fan_count", "팬 개수", kind="number", required=False),
                        _field("packages[].rpm_mode", "팬 회전수 설정 방식", kind="choice", required=False,
                               choices=_choices(form_rules.operating["rpm_modes"])),
                        _field("packages[].rpm", "팬 회전수 (rpm)", kind="number", required=False),
                        _field("packages[].fans[].location", "팬 위치", required=False),
                        _field("packages[].fans[].rpm", "팬 회전수 (rpm)", kind="number", required=False),
                    ],
                },
                "heat_exchanger": {
                    "fields": [
                        _field("packages[].hx_type", "열교환기 유형", kind="choice",
                               choices=_choices({item.value: item.value for item in HeatExchangerType})),
                        _field("packages[].tube_diameter", "관 직경(Pi) 또는 채널 폭"),
                        _field("packages[].fin_type", "Fin type"),
                        _field("packages[].row_count", "열 수"),
                        _field("packages[].fpi", "FPI (또는 FPDM)"),
                    ],
                    "catalog_endpoint": "/api/reference/hx-catalog",
                },
                "filter": {
                    "fields": [
                        _field("packages[].filters[].name", "필터 이름"),
                        _field("packages[].filters[].points[].velocity", "유속 (m/s)", kind="number"),
                        _field("packages[].filters[].points[].pressure_loss", "압력손실 (Pa)", kind="number"),
                    ],
                    "repeaters": [
                        _repeater("packages[].filters[]", "물리적 필터", min_items=1, id_required=True),
                        _repeater("packages[].filters[].points[]", "측정점", min_items=1),
                    ],
                },
                "installation": {
                    "fields": [_field("data", "3D 설치 조건", kind="three_d")],
                },
                "pcb": {
                    "device_bases": _choices(form_rules.pcb["device_bases"]),
                    "contact_resistance_default": form_rules.pcb["contact_resistance_default"],
                    "materials_default": form_rules.pcb["materials_default"],
                    "refrigerant_fields": [
                        {"key": key, **spec} for key, spec in form_rules.pcb["refrigerant_fields"].items()
                    ],
                    "fields": [
                        _field("image", "PCB 이미지", kind="image_attachment"),
                        _field("device_basis", "소자 기준", kind="choice",
                               choices=_choices(form_rules.pcb["device_bases"])),
                        _field("devices[].name", "소자 이름"),
                        _field("devices[].value", "소자 값", kind="number"),
                        _field("contact_resistance.enabled", "접촉저항 고려", kind="boolean", required=False),
                        _field("contact_resistance.material", "접촉재료", required=False),
                        _field("contact_resistance.thermal_conductivity", "열전도도 (W/(m·K))",
                               kind="number", required=False),
                        _field("contact_resistance.thickness", "두께 (mm)", kind="number", required=False),
                        _field("contact_resistance.location", "적용 위치", required=False),
                        _field("materials[].material_name", "재료 이름"),
                        _field("materials[].thermal_conductivity", "열전도도 (W/(m·K))", kind="number"),
                        _field("materials[].applied_part", "적용 부품"),
                    ] + [_field(f"refrigerant.{key}", f"냉매 조건 {spec['label']}",
                                 kind=spec.get("kind", "text"), required=False)
                         for key, spec in form_rules.pcb["refrigerant_fields"].items()],
                    "repeaters": [
                        _repeater("devices[]", "소자", min_items=1),
                        _repeater("materials[]", "재료물성", min_items=1),
                    ],
                },
                "measurement": {
                    "required": form_rules.measurement_required,
                    "items": [{"key": key, "kind": "text", **spec}
                              for key, spec in form_rules.measurement_items.items()],
                },
            },
            "reason_codes": {
                action.key: {
                    "label": action.label,
                    "choices": [{"code": code, "label": label} for code, label in
                                rules.reason_codes[action.reason_codes].items()],
                }
                for action in rules.actions.values()
                if action.reason_codes is not None
            },
            "workflow": {
                "statuses": rules.statuses,
                "actions": {
                    action.key: {
                        "label": action.label, "requires": sorted(action.requires),
                        "inputs": _action_inputs(action, rules),
                    }
                    for action in rules.actions.values()
                },
            },
        }

    @app.get("/api/reference/pms")
    def pms_options():
        _actor(service)
        division = request.args.get("division")
        if not division or not division.strip():
            raise FormError("division: 텍스트가 필요하다")
        projects = service.search_pms(division.strip(), request.args.get("query", ""))
        return {"items": [{
            "code": project.code, "division": project.division, "project_name": project.project,
            "rep_model": project.rep_model, "region": project.region,
        } for project in projects]}

    @app.get("/api/reference/hx-catalog")
    def hx_catalog():
        _actor(service)
        catalog = service.references.load().hx_catalog
        return {"items": [{
            "id": entry.id, "tube_diameter": entry.spec.tube_diameter, "fin_type": entry.spec.fin_type,
            "row_count": entry.spec.row_count, "fpi": entry.spec.fpi, "standard": entry.standard,
        } for entry in catalog.entries]}

    @app.get("/api/users/analysts")
    def analysts():
        actor = _actor(service)
        return {"items": [{"id": user.id, "name": user.name or user.id, "department": user.department}
                          for user in service.analysts(actor)]}

    @app.post("/api/requests")
    def create_request():
        actor = _actor(service)
        return _request(service.create(actor), actor=actor), 201

    @app.get("/api/requests")
    def list_requests():
        actor = _actor(service)
        todo_only = request.args.get("todo") == "true"
        items, status_counts = service.list_with_status_counts(actor, todo_only=todo_only)
        return {"items": [_request(x, actor=actor) for x in items], "status_counts": status_counts}

    @app.get("/api/requests/<request_id>")
    def get_request(request_id: str):
        actor = _actor(service)
        return _request(service.get(actor, request_id), detail=True, actor=actor)

    @app.get("/api/requests/<request_id>/revisions/<int:revision_no>/diff")
    def revision_diff(request_id: str, revision_no: int):
        actor = _actor(service)
        return {"revision_no": revision_no, "changes": [asdict(change) for change in
                                                        service.revision_diff(actor, request_id, revision_no)]}

    @app.put("/api/requests/<request_id>/form")
    def edit_form(request_id: str):
        data = _body()
        actor = _actor(service)
        return _request(service.edit_form(
            actor, request_id, _mapping(data, "form"), confirm_case=_flag(data, "confirm_case")
        ), actor=actor)

    @app.post("/api/requests/<request_id>/target")
    def target(request_id: str):
        data = _body()
        selection = TargetSelection(**{
            key: _optional_text(data, key)
            for key in ("taxonomy_id", "analysis_type", "analysis_scope", "cooling_method")
        })
        actor = _actor(service)
        return _request(service.confirm_target(
            actor, request_id, selection, accept_change=_flag(data, "accept_change")
        ), actor=actor)

    @app.post("/api/requests/<request_id>/pms")
    def pms(request_id: str):
        actor = _actor(service)
        return _request(service.select_pms(actor, request_id, _text(_body(), "code")), actor=actor)

    @app.post("/api/requests/<request_id>/cases/confirm")
    def cases(request_id: str):
        actor = _actor(service)
        return _request(service.confirm_case(actor, request_id), actor=actor)

    @app.post("/api/requests/<request_id>/cases/auto-combine")
    def auto_combine(request_id: str):
        data = _body()
        max_cases = data.get("max_cases", 200)
        if not isinstance(max_cases, int) or isinstance(max_cases, bool):
            raise FormError("max_cases: 정수여야 한다")
        actor = _actor(service)
        return _request(service.auto_combine_case(actor, request_id, max_cases=max_cases), actor=actor)

    @app.post("/api/requests/<request_id>/pcb-image")
    def upload_pcb_image(request_id: str):
        actor = _actor(service)
        image = request.files.get("image")
        if image is None or not image.filename:
            raise FormError("image: 업로드 파일이 필요하다")
        if not image.mimetype or not image.mimetype.startswith("image/"):
            raise FormError("image: 이미지 파일만 올릴 수 있다")
        content = image.read()
        if not content:
            raise FormError("image: 빈 파일은 올릴 수 없다")
        item, attachment_id = service.upload_pcb_image(
            actor, request_id, filename=image.filename, content_type=image.mimetype, content=content,
        )
        return {**_request(item, actor=actor), "attachment_id": attachment_id}, 201

    @app.get("/api/requests/<request_id>/attachments/<attachment_id>")
    def attachment(request_id: str, attachment_id: str):
        actor = _actor(service)
        item = service.attachment(actor, request_id, attachment_id)
        return item.content, 200, {
            "Content-Type": item.content_type,
            "Content-Disposition": f'inline; filename="{item.filename}"',
        }

    @app.post("/api/requests/<request_id>/actions/<action>")
    def action(request_id: str, action: str):
        actor = _actor(service)
        return _request(service.action(actor, request_id, action, _body()), actor=actor)
    return app


def _actor(service: RequestService) -> User:
    user_id = request.headers.get("X-H12-User-Id")
    timestamp = request.headers.get("X-H12-Auth-Timestamp")
    signature = request.headers.get("X-H12-Auth-Signature")
    if not user_id or not timestamp or not signature:
        raise AuthenticationRequired("인증 헤더가 필요하다")
    try:
        issued_at = int(timestamp)
    except ValueError as error:
        raise AuthenticationRequired("인증 시각 형식이 올바르지 않다") from error
    if abs(time.time() - issued_at) > 300:
        raise AuthenticationRequired("인증 정보가 만료되었다")
    expected = _signature(user_id, timestamp, current_app.config["H12_AUTH_SECRET"])
    if not hmac.compare_digest(signature, expected):
        raise AuthenticationRequired("인증 서명이 올바르지 않다")
    return service.user(user_id)


def _signature(user_id: str, timestamp: str, secret: bytes) -> str:
    return hmac.new(secret, f"{user_id}:{timestamp}".encode("utf-8"), hashlib.sha256).hexdigest()


def _body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict): raise FormError("JSON 객체 본문이 필요하다")
    return data


def _text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip(): raise FormError(f"{key}: 텍스트가 필요하다")
    return value.strip()


def _optional_text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise FormError(f"{key}: 텍스트 또는 null 이어야 한다")
    return value.strip()


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise FormError(f"{key}: 객체가 필요하다")
    return value


def _flag(data: dict[str, Any], key: str) -> bool:
    value = data.get(key, False)
    if not isinstance(value, bool):
        raise FormError(f"{key}: true 또는 false 이어야 한다")
    return value


def _choices(values: Any) -> list[dict[str, Any]]:
    return [{"code": code, "label": label} for code, label in values.items()]


def _field(path: str, label: str, *, kind: str = "text", required: bool = True,
           choices: list[dict[str, Any]] | None = None, pattern: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"path": path, "label": label, "kind": kind, "required": required}
    if choices is not None:
        result["choices"] = choices
    if pattern is not None:
        result["pattern"] = pattern
    return result


def _action_inputs(action: Any, rules: Any) -> list[dict[str, Any]]:
    inputs = []
    for key in sorted(action.requires, key=lambda item: list(_WORKFLOW_INPUTS).index(item)):
        item = {"key": key, "request_key": key, "required": True, **_WORKFLOW_INPUTS[key]}
        if key == "reason_code":
            item["choices"] = _choices(rules.reason_codes[action.reason_codes])
        inputs.append(item)
    if action.key == "request_change":
        inputs.append({"key": "confirm_case", "request_key": "confirm_case", "required": False,
                       **_WORKFLOW_INPUTS["confirm_case"]})
    return inputs


def _repeater(path: str, label: str, *, min_items: int = 0, id_required: bool = False,
              count_from: str | None = None, visible_when: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"path": path, "label": label, "min_items": min_items}
    if id_required:
        result["id"] = _client_uuid_id()
    if count_from is not None:
        result["count_from"] = count_from
    if visible_when is not None:
        result["visible_when"] = visible_when
    return result


def _client_uuid_id() -> dict[str, Any]:
    return {"key": "id", "generation": "client_uuid", "preserve_on_edit": True}


def _target_impact_messages(impact: Any, form_rules: Any) -> list[str]:
    messages = []
    if impact.product_changed:
        messages.append("제품 분류가 변경됩니다.")
    if impact.analysis_type_changed:
        messages.append("해석유형이 변경됩니다.")
    if impact.pms_cleared:
        messages.append("선택한 PMS 프로젝트가 초기화됩니다.")
    if impact.hidden_groups:
        labels = ", ".join(form_rules.groups[key].label for key in impact.hidden_groups)
        messages.append(f"표시하지 않게 되는 조건: {labels}. 기존 값은 보존됩니다.")
    if impact.added_groups:
        labels = ", ".join(form_rules.groups[key].label for key in impact.added_groups)
        messages.append(f"새로 입력할 조건: {labels}.")
    return messages


def _request(item: Request, *, detail: bool = False, actor: User | None = None) -> dict[str, Any]:
    service = current_app.extensions["h12.service"]
    request_date = item.revisions[0].created_at.date() if item.revisions else service.now().date()
    result: dict[str, Any] = {"id": item.id, "status": item.status, "requester_id": item.requester_id,
        "requester_department": item.requester_department, "analyst_id": item.analyst_id,
        "created_at": item.created_at.isoformat(), "request_title": request_title(item.form, service.form_rules),
        "request_date": request_date.isoformat(),
        "held_by": item.held_by,
        "pending": None if item.pending is None else {
            "kind": item.pending.kind, "requested_by": item.pending.requested_by,
            "comment": item.pending.comment, "requested_at": item.pending.requested_at.isoformat(),
        }}
    if actor is not None:
        result["available_actions"] = service.engine.available_actions(actor, item)
        result["can_edit_form"] = service.engine.can_edit_form(actor, item)
    if detail:
        result.update({"form": item.form,
          "revisions": [{"revision_no": r.revision_no, "form": r.form, "created_by": r.created_by, "created_at": r.created_at.isoformat(), "cause_event": r.cause_event} for r in item.revisions],
          "results": [{"round_no": r.round_no, "summary": r.summary, "registered_by": r.registered_by, "registered_at": r.registered_at.isoformat()} for r in item.results],
          "events": [{"seq": e.seq, "event_type": e.event_type, "action": e.action, "from_status": e.from_status, "to_status": e.to_status, "actor_id": e.actor_id, "at": e.at.isoformat(), "reason_code": e.reason_code, "comment": e.comment, "payload": e.payload} for e in item.events]})
    return result
