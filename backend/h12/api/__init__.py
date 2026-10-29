"""HTTP 계층. 요청을 application 유스케이스로 넘기고 결과를 JSON 으로 돌려준다."""

from __future__ import annotations

from flask import Flask

from h12.rulebook import load_workflow_rules


def create_app() -> Flask:
    app = Flask(__name__)
    # 규칙 파일 오류는 첫 요청이 아니라 기동 시점에 드러나게 한다
    rules = load_workflow_rules()

    @app.get("/api/health")
    def health():
        return {"status": "ok", "workflow_statuses": len(rules.statuses)}

    return app
