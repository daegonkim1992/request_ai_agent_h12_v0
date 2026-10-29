# 해석의뢰 h12_v0

의뢰자, 해석관리자, 해석담당자가 해석의뢰를 작성부터 결과 확인까지 처리하는 업무 플랫폼이다.
업무 기준은 [docs/해석의뢰_업무정의.md](docs/해석의뢰_업무정의.md)이고, 개발 규칙은 [CLAUDE.md](CLAUDE.md)에 있다.

## 실행

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
.venv/Scripts/python -m h12            # API: http://127.0.0.1:8512/api/health

cd frontend
npm install
npm run dev                            # http://localhost:5173
```
