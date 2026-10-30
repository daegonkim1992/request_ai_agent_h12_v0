"""5단계 API·DB 기본 흐름과 HTTP 경계."""

import hashlib
import hmac
import time

from h12.api import create_app
from h12.domain.workflow import Role, User

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
    return app.test_client()


def test_requests_and_todo_are_persisted():
    client = _client()

    created = client.post("/api/requests", headers=_headers("req"))
    assert created.status_code == 201
    request_id = created.get_json()["id"]
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
