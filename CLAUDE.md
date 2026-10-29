# h12_v0 — 해석의뢰 업무 플랫폼

## 기준 문서

- **[docs/해석의뢰_업무정의.md](docs/해석의뢰_업무정의.md)가 유일한 업무 기준이다.** 동작이 정의서와 다르면 코드를 고친다.
- 정의서에 없거나 모호해서 구현하며 해석한 내용은 [docs/spec-gaps.md](docs/spec-gaps.md)에 남긴다. 몰래 정하지 않는다.
- h10_v0, i0_0 등 이전 버전 코드는 참고하지도, 가져오지도 않는다. 기준 데이터 파일(xlsx, json)만 데이터로 가져올 수 있다.

## 범위

- **Word 출력은 만들지 않는다** (폐기된 기능).
- **Agent 기능은 지금 만들지 않는다.** 업무 플랫폼을 먼저 완성하고, Agent는 나중에 application 계층 API를 호출하는 클라이언트로 붙인다. 도메인에 Agent 전용 경로를 만들지 않는다.

## 구조

```
rules/              업무 규칙 데이터 (YAML). 정의서의 표를 옮긴 것
backend/h12/
  domain/           순수 업무 규칙. Flask, DB, YAML, 파일 입출력 금지
    workflow/       3장 상태·기능·대기 요청·revision·이력
  reference/        9장 기준 데이터 (2단계)
  application/      유스케이스 (5단계)
  infra/            DB·알림 구현 (5단계)
  api/              Flask HTTP 계층
  rulebook.py       rules/*.yaml 로더
frontend/           React + TypeScript (Vite)
tests/              정의서 절 번호로 파일 이름을 붙인다 (test_3_2_*.py)
```

- 의존 방향은 `api → application → domain`, `infra → application/domain` 이다. [tests/architecture/test_layers.py](tests/architecture/test_layers.py)가 검사한다.
- **규칙은 데이터로 둔다.** 상태, 기능, 수행자, 사유 코드, 할 일 목록은 `rules/*.yaml` 에 있다. 엔진은 yaml 의 이름(actors, effects, requires, checks)만 해석한다. 새 이름이 필요할 때만 엔진과 `rules.py` 의 이름 목록을 함께 고친다.
- 정의서의 `[검토 필요]` 항목은 되도록 yaml 값으로 둬서 확정 시 코드 수정 없이 바꿀 수 있게 한다.
- 도메인 변경은 `WorkflowEngine` 을 거친다. `execute` 는 모든 검사를 마친 뒤에만 의뢰를 바꾼다.

## 테스트 원칙

- 기대값은 yaml 에서 읽어 만들지 않고 **정의서 표를 테스트에 직접 옮겨 적는다.** 그래야 yaml 오류를 잡는다.
- 의뢰를 특정 상태로 만들 때는 상태를 직접 넣지 않고 실제 기능을 순서대로 수행한다 (`tests/domain/workflow/conftest.py` 의 `make_request`).

## 명령

```bash
# 백엔드 (저장소 루트)
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
.venv/Scripts/python -m h12              # http://127.0.0.1:8512

# 프론트엔드 (frontend/)
npm install
npm run dev                              # /api 는 8512 로 프록시
npm run build && npm run lint
```

## 단계

0 골격 ✔ → 1 Workflow 도메인 ✔ → 2 기준 데이터 → 3 의뢰서·조건 엔진 → 4 Case·제출 검증 → 5 DB·API → 6 UI → 7 알림·지표 → 8 Agent

- 정의서는 v1.1(2026-10-30)이다. 1단계 중 확인한 9건(G-1~G-9)은 결정되어 정의서에 반영했다.
- 1단계 이후 미룬 항목은 [docs/spec-gaps.md](docs/spec-gaps.md) "다음 단계로 미룬 것"에 있다.

### 2단계 — 기준 데이터 (정의서 9장, 3.4-10, 4.2, 5.3.4)

원본 파일 (h12 밖에 있다. 가공한 결과만 h12 로 가져오고, 원본에서 다시 만들 수 있게 변환 스크립트를 남긴다):

| 기준 데이터 | 원본 | 비고 |
|---|---|---|
| 제품 분류 | `G:\Tech\00_Agent\01_Agent_Code\총조립도 분류체계.xlsx` | 252행, 사업부 5개. h10 의 `product_taxonomy.json` 은 이 파일을 가공한 것이라 대조용으로만 쓴다 |
| 열교환기 Catalog | `G:\Tech\00_Agent\01_Agent_Code\docs\열교환기압력손실DB_Final.xlsx` 의 "압손DB_과제결과" 시트 | 표준 사양 표시 포함 |
| PMS 프로젝트 | `G:\Tech\00_Agent\01_Agent_Code\request_ai_agent_h10_v0\docs\20260915_PMS_Project_Running_{Aircare,CAC,Chiller,RAC}.xlsx` | 사업부별 |
| 해석유형 11종, 선택지 목록 | 정의서 부록 A, 4.3 | rules/ YAML 로 둔다 |
| 측정·판정 기준 표준값 | 없음 [추후 정의] | 빈 값 자리만 만든다 |

요구사항 요점:
- 3.4-10: 의뢰 대상을 확정한 시점의 기준 데이터 버전을 의뢰에 고정한다. 나중에 기준 데이터가 바뀌어도 확정한 의뢰는 영향받지 않는다 → 기준 데이터는 **버전(스냅샷)** 단위로 다룬다.
- 4.2: 제품 분류는 등록된 조합에서만 고른다. 사업부별 Platform 규칙(SAC·Chiller 목록, RAC·Air Care 자동, AIDC 해당 없음), Chassis 빈 값과 "NA" 구분.
- 5.3.4: 관 직경이 W 로 시작하면 Micro-Channel, Micro-Channel 이면 Fin type 은 Flat. 네 사양 조합은 Catalog 에 있어야 한다.
- 4.4: PMS 프로젝트는 제품 사업부에 종속된다. Project 또는 Rep Model 로 검색한다.
- xlsx 를 읽으려면 openpyxl 이 필요하다 (아직 설치하지 않았다). 런타임이 아니라 변환 스크립트에서만 쓴다.
