"""5단계 API·DB 기본 흐름과 HTTP 경계."""

import hashlib
import hmac
import io
import time

from h12.api import create_app
from h12.domain.workflow import Role, User
from h12.reference import default_store

SECRET = "test-secret"


def _headers(user_id: str, *, signature: str | None = None) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signed = hmac.new(SECRET.encode(), f"{user_id}:{timestamp}".encode(), hashlib.sha256).hexdigest()
    return {
        "X-H12-User-Id": user_id,
        "X-H12-Auth-Timestamp": timestamp,
        "X-H12-Auth-Signature": signature or signed,
    }


def _client():
    app = create_app(database_url="sqlite://", auth_secret=SECRET)
    service = app.extensions["h12.service"]
    service.add_user(User("req", Role.REQUESTER, "D"))
    service.add_user(User("mgr", Role.MANAGER, "CAE"))
    service.add_user(User("an", Role.ANALYST, "CAE", "해석담당자"))
    return app.test_client()


def test_requests_and_todo_are_persisted():
    client = _client()

    created = client.post("/api/requests", headers=_headers("req"))
    assert created.status_code == 201
    request_id = created.get_json()["id"]
    assert created.get_json()["request_title"] == "[해석유형 미정] 모델명 미정"
    assert created.get_json()["request_date"]
    assert client.get("/api/requests", headers=_headers("req")).get_json()["status_counts"] == {"DRAFT": 1}
    assert client.get(f"/api/requests/{request_id}", headers=_headers("mgr")).status_code == 403
    assert client.get("/api/requests?todo=true", headers=_headers("req")).get_json()["items"][0]["id"] == request_id


def test_api_requires_authenticated_registered_actor_and_has_no_public_user_provisioning():
    client = _client()
    assert client.post("/api/requests").status_code == 401
    assert client.post("/api/requests", headers=_headers("req", signature="forged")).status_code == 401
    assert client.post("/api/requests", headers=_headers("missing")).status_code == 404
    assert client.post("/api/users", json={"id": "attacker", "role": "MANAGER", "department": "D"}).status_code == 404


def test_malformed_form_is_a_client_error():
    client = _client()
    request_id = client.post("/api/requests", headers=_headers("req")).get_json()["id"]
    response = client.put(f"/api/requests/{request_id}/form", headers=_headers("req"), json={})
    assert response.status_code == 400
    assert response.get_json()["error"] == "form: 객체가 필요하다"


def test_target_options_are_authenticated_and_have_user_facing_labels():
    client = _client()
    assert client.get("/api/reference/target-options").status_code == 401

    response = client.get("/api/reference/target-options", headers=_headers("req"))

    assert response.status_code == 200
    body = response.get_json()
    assert body["taxonomy"]
    assert {item["label"] for item in body["analysis_types"]} >= {"풍량", "PCB발열"}
    assert {item["division"] for item in body["taxonomy"]} == {"SAC", "RAC", "Air Care", "Chiller", "AIDC"}
    assert next(item for item in body["analysis_types"] if item["code"] == "PCB_HEAT")["requires_cooling_method"]
    assert not next(item for item in body["analysis_types"] if item["code"] == "AIRFLOW_RATE")["requires_cooling_method"]


def test_ui_contract_exposes_form_choices_fields_and_action_reason_codes():
    client = _client()
    assert client.get("/api/ui-contract").status_code == 401

    response = client.get("/api/ui-contract", headers=_headers("req"))

    assert response.status_code == 200
    body = response.get_json()
    assert body["options"]["request_type"] == {
        "choices": [
            {"code": "DEVELOPMENT_PROJECT", "label": "개발 프로젝트"},
            {"code": "QUALITY_IMPROVEMENT", "label": "품질 개선"},
            {"code": "FIELD_ISSUE", "label": "필드 이슈"},
            {"code": "PRE_STUDY", "label": "선행 검토"},
            {"code": "OTHER", "label": "기타"},
        ],
        "allow_custom": False,
        "default": None,
    }
    assert next(field for field in body["fields"] if field["path"] == "analysis_overview.development_grade") == {
        "path": "analysis_overview.development_grade", "label": "개발 등급", "kind": "choice",
        "unit": None, "options": "development_grade", "required": True,
        "required_for_types": ["DEVELOPMENT_PROJECT"],
    }
    assert body["reason_codes"]["reject"] == {
        "label": "반려",
        "choices": [
            {"code": "OUT_OF_SCOPE", "label": "지원 범위 밖"},
            {"code": "NOT_SUITABLE", "label": "해석 부적합"},
            {"code": "DUPLICATE", "label": "중복 의뢰"},
            {"code": "OTHER", "label": "기타"},
        ],
    }
    assert {field["path"] for field in body["fields"]} >= {"analysis_overview.pms_project"}
    assert body["geometry"] == {
        "base_product": {
            "path": "geometry.base_product", "label": "Base 제품", "required": True,
            "id": {"key": "id", "generation": "client_uuid", "preserve_on_edit": True},
            "fields": [
                {"path": "geometry.base_product.drawing_no", "label": "도면번호", "kind": "text", "required": True,
                 "pattern": "^[A-Za-z0-9-]+$"},
                {"path": "geometry.base_product.display_name", "label": "표시명", "kind": "text", "required": False},
            ],
        },
        "comparison_products": {
            "repeater": {
                "path": "geometry.comparison_products[]", "label": "비교 제품", "min_items": 0,
                "id": {"key": "id", "generation": "client_uuid", "preserve_on_edit": True},
            },
            "fields": [
                {"path": "geometry.comparison_products[].drawing_no", "label": "도면번호", "kind": "text", "required": True,
                 "pattern": "^[A-Za-z0-9-]+$"},
                {"path": "geometry.comparison_products[].display_name", "label": "표시명", "kind": "text", "required": False},
                {"path": "geometry.comparison_products[].difference_from_base", "label": "Base 대비 차이", "kind": "text", "required": True},
            ],
        },
    }
    space = next(group for group in body["condition_groups"] if group["key"] == "space_environment")
    assert space["fields"][0] == {
        "key": "room_temp", "label": "공간 온도", "kind": "number", "unit": "°C",
        "required": False, "column": "room_temp",
    }
    assert space["repeaters"] == [{
        "path": "packages[]", "label": "공간", "min_items": 1,
        "id": {"key": "id", "generation": "client_uuid", "preserve_on_edit": True},
    }]
    assert body["condition_specials"]["pcb"]["device_bases"] == [
        {"code": "temperature", "label": "온도 (°C)"}, {"code": "heat", "label": "발열량 (W)"},
    ]
    assert body["condition_specials"]["heat_exchanger"]["fields"] == [
        {"path": "packages[].hx_type", "label": "열교환기 유형", "kind": "choice", "required": True,
         "choices": [{"code": "Fin&Tube", "label": "Fin&Tube"}, {"code": "Micro-Channel", "label": "Micro-Channel"}]},
        {"path": "packages[].tube_diameter", "label": "관 직경(Pi) 또는 채널 폭", "kind": "text", "required": True},
        {"path": "packages[].fin_type", "label": "Fin type", "kind": "text", "required": True},
        {"path": "packages[].row_count", "label": "열 수", "kind": "text", "required": True},
        {"path": "packages[].fpi", "label": "FPI (또는 FPDM)", "kind": "text", "required": True},
    ]
    assert body["condition_specials"]["filter"]["fields"][-1] == {
        "path": "packages[].filters[].points[].pressure_loss", "label": "압력손실 (Pa)",
        "kind": "number", "required": True,
    }
    assert body["condition_specials"]["filter"]["repeaters"] == [{
        "path": "packages[].filters[]", "label": "물리적 필터", "min_items": 1,
        "id": {"key": "id", "generation": "client_uuid", "preserve_on_edit": True},
    }, {
        "path": "packages[].filters[].points[]", "label": "측정점", "min_items": 1,
    }]
    assert body["condition_specials"]["operating"]["repeaters"] == [{
        "path": "packages[].fans[]", "label": "팬", "min_items": 0,
        "count_from": "packages[].fan_count",
        "visible_when": {"path": "packages[].rpm_mode", "equals": "individual"},
    }]
    assert body["condition_specials"]["pcb"]["repeaters"] == [
        {"path": "devices[]", "label": "소자", "min_items": 1},
        {"path": "materials[]", "label": "재료물성", "min_items": 1},
    ]
    assert body["condition_specials"]["installation"]["fields"] == [
        {"path": "data", "label": "3D 설치 조건", "kind": "three_d", "required": True},
    ]
    assert body["condition_specials"]["measurement"]["required"] is False
    assert body["workflow"]["statuses"]["DRAFT"] == "작성 중"
    assert body["workflow"]["actions"]["reject"] == {
        "label": "반려", "requires": ["comment", "reason_code"],
        "inputs": [
            {"key": "reason_code", "request_key": "reason_code", "label": "사유 코드", "required": True, "kind": "reason_code",
             "choices": [
                 {"code": "OUT_OF_SCOPE", "label": "지원 범위 밖"},
                 {"code": "NOT_SUITABLE", "label": "해석 부적합"},
                 {"code": "DUPLICATE", "label": "중복 의뢰"},
                 {"code": "OTHER", "label": "기타"},
             ]},
            {"key": "comment", "request_key": "comment", "label": "사유 또는 설명", "required": True, "kind": "textarea"},
        ],
    }
    assert body["workflow"]["actions"]["accept_and_assign"]["inputs"] == [
        {"key": "analyst", "request_key": "analyst_id", "label": "해석담당자", "required": True, "kind": "analyst"},
    ]
    assert body["workflow"]["actions"]["request_change"]["inputs"][-1] == {
        "key": "confirm_case", "request_key": "confirm_case", "required": False,
        "label": "변경한 조건·형상의 Case 구성을 다시 확인했습니다", "kind": "boolean",
    }


def test_target_change_impact_has_server_supplied_messages():
    client = _client()
    request_id = client.post("/api/requests", headers=_headers("req")).get_json()["id"]
    taxonomy_id = default_store().load().taxonomy.paths[0].id
    initial = client.post(f"/api/requests/{request_id}/target", headers=_headers("req"),
                          json={"taxonomy_id": taxonomy_id, "analysis_type": "AIRFLOW_PATTERN"})
    assert initial.status_code == 200

    changed = client.post(f"/api/requests/{request_id}/target", headers=_headers("req"),
                          json={"taxonomy_id": taxonomy_id, "analysis_type": "PCB_HEAT", "cooling_method": "공랭식"})

    assert changed.status_code == 409
    assert "해석유형이 변경됩니다." in changed.get_json()["impact"]["messages"]


def test_lookup_apis_expose_pms_catalog_and_manager_analysts():
    client = _client()
    pms = client.get("/api/reference/pms?division=SAC&query=Water", headers=_headers("req"))
    assert pms.status_code == 200
    assert pms.get_json()["items"]
    assert client.get("/api/reference/hx-catalog", headers=_headers("req")).get_json()["items"]
    assert client.get("/api/users/analysts", headers=_headers("req")).status_code == 403
    analysts = client.get("/api/users/analysts", headers=_headers("mgr"))
    assert analysts.get_json()["items"] == [{"id": "an", "name": "해석담당자", "department": "CAE"}]


def test_form_shape_and_invalid_case_confirmation_are_400_with_locations():
    client = _client()
    request_id = client.post("/api/requests", headers=_headers("req")).get_json()["id"]
    malformed = client.put(f"/api/requests/{request_id}/form", headers=_headers("req"),
                           json={"form": {"analysis_overview": "not-an-object"}})
    assert malformed.status_code == 400
    assert malformed.get_json()["issues"][0]["location"] == "analysis_overview"

    taxonomy_id = default_store().load().taxonomy.paths[0].id
    client.post(f"/api/requests/{request_id}/target", headers=_headers("req"),
                json={"taxonomy_id": taxonomy_id, "analysis_type": "AIRFLOW_PATTERN"})
    invalid_case = client.post(f"/api/requests/{request_id}/cases/confirm", headers=_headers("req"))
    assert invalid_case.status_code == 400
    assert invalid_case.get_json()["issues"][0]["location"] == "cases"


def test_pcb_image_upload_is_request_scoped_and_retrievable():
    client = _client()
    request_id = client.post("/api/requests", headers=_headers("req")).get_json()["id"]
    taxonomy_id = default_store().load().taxonomy.paths[0].id
    client.post(f"/api/requests/{request_id}/target", headers=_headers("req"),
                json={"taxonomy_id": taxonomy_id, "analysis_type": "PCB_HEAT", "cooling_method": "공랭식"})
    uploaded = client.post(f"/api/requests/{request_id}/pcb-image", headers=_headers("req"), data={
        "image": (io.BytesIO(b"png-bytes"), "pcb.png", "image/png"),
    })
    assert uploaded.status_code == 201
    attachment_id = uploaded.get_json()["attachment_id"]
    fetched = client.get(f"/api/requests/{request_id}/attachments/{attachment_id}", headers=_headers("req"))
    assert fetched.status_code == 200
    assert fetched.data == b"png-bytes"
