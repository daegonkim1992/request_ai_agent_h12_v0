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
from h12.domain.form import ConfirmationRequired, FormError, TargetSelection
from h12.domain.workflow import ActionNotAllowed, InvalidInput, Request, SubmissionBlocked, User
from h12.infra import Database
from h12.reference import default_store
from h12.rulebook import load_workflow_rules


class AuthenticationRequired(Exception):
    pass


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
    def confirm(e): return {"error": "확인 필요", "impact": asdict(e.impact)}, 409
    @app.errorhandler(FormError)
    def form_error(e): return {"error": str(e)}, 400
    @app.errorhandler(ConcurrentModification)
    def conflict(e): return {"error": str(e)}, 409

    @app.get("/api/health")
    def health(): return {"status": "ok", "workflow_statuses": len(rules.statuses)}

    @app.post("/api/requests")
    def create_request(): return _request(service.create(_actor(service))), 201

    @app.get("/api/requests")
    def list_requests():
        actor = _actor(service)
        todo_only = request.args.get("todo") == "true"
        items, status_counts = service.list_with_status_counts(actor, todo_only=todo_only)
        return {"items": [_request(x) for x in items], "status_counts": status_counts}

    @app.get("/api/requests/<request_id>")
    def get_request(request_id: str): return _request(service.get(_actor(service), request_id), detail=True)

    @app.put("/api/requests/<request_id>/form")
    def edit_form(request_id: str):
        data = _body()
        return _request(service.edit_form(
            _actor(service), request_id, _mapping(data, "form"), confirm_case=_flag(data, "confirm_case")
        ))

    @app.post("/api/requests/<request_id>/target")
    def target(request_id: str):
        data = _body()
        selection = TargetSelection(**{
            key: _optional_text(data, key)
            for key in ("taxonomy_id", "analysis_type", "analysis_scope", "cooling_method")
        })
        return _request(service.confirm_target(
            _actor(service), request_id, selection, accept_change=_flag(data, "accept_change")
        ))

    @app.post("/api/requests/<request_id>/pms")
    def pms(request_id: str): return _request(service.select_pms(_actor(service), request_id, _text(_body(), "code")))

    @app.post("/api/requests/<request_id>/cases/confirm")
    def cases(request_id: str): return _request(service.confirm_case(_actor(service), request_id))

    @app.post("/api/requests/<request_id>/actions/<action>")
    def action(request_id: str, action: str): return _request(service.action(_actor(service), request_id, action, _body()))
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


def _request(item: Request, *, detail: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"id": item.id, "status": item.status, "requester_id": item.requester_id,
        "requester_department": item.requester_department, "analyst_id": item.analyst_id,
        "created_at": item.created_at.isoformat()}
    if detail:
        result.update({"form": item.form,
          "revisions": [{"revision_no": r.revision_no, "form": r.form, "created_by": r.created_by, "created_at": r.created_at.isoformat(), "cause_event": r.cause_event} for r in item.revisions],
          "results": [{"round_no": r.round_no, "summary": r.summary, "registered_by": r.registered_by, "registered_at": r.registered_at.isoformat()} for r in item.results],
          "events": [{"seq": e.seq, "event_type": e.event_type, "action": e.action, "from_status": e.from_status, "to_status": e.to_status, "actor_id": e.actor_id, "at": e.at.isoformat(), "reason_code": e.reason_code, "comment": e.comment, "payload": e.payload} for e in item.events]})
    return result
