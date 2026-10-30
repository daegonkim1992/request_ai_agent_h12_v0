# 해석의뢰 h12_v0

의뢰자, 해석관리자, 해석담당자가 해석의뢰를 작성부터 결과 확인까지 처리하는 업무 플랫폼이다.
업무 기준은 [docs/해석의뢰_업무정의.md](docs/해석의뢰_업무정의.md)이고, 개발 규칙은 [CLAUDE.md](CLAUDE.md)에 있다.

## 실행

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
.venv/Scripts/python -m h12.manage_users upsert --id requester-1 --role REQUESTER --department CAE
$env:H12_AUTH_SECRET = "proxy-only-secret"
.venv/Scripts/python -m h12            # API: http://127.0.0.1:8512/api/health

cd frontend
npm install
npm run dev                            # http://localhost:5173
```

`H12_AUTH_SECRET`은 인증 프록시만 알고 있어야 한다. 프록시는 로그인 사용자의 ID와 현재
Unix 시각을 `X-H12-User-Id`, `X-H12-Auth-Timestamp`에 넣고, `user_id:timestamp`의 HMAC-SHA256을
`X-H12-Auth-Signature`에 넣는다. 서명은 5분 동안만 유효하다. 사용자 생성·역할 변경은 HTTP API가
아닌 `h12.manage_users`로 수행한다.
