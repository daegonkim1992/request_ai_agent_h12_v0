from h12.api import create_app


def test_health():
    response = create_app(auth_secret="test-secret").test_client().get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "workflow_statuses": 10}
