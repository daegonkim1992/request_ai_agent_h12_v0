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
rules/              업무 규칙 데이터 (YAML). 정의서의 표를 옮긴 것. 버전 관리하지 않는다
refdata/            9장 기준 데이터. 버전 파일은 고치지 않는다 (3.4-10)
  manifest.yaml     릴리스 → 데이터셋별 버전. 의뢰는 릴리스 ID 를 남긴다
  <데이터셋>/<버전>.json|yaml   taxonomy, hx_catalog, pms 는 변환 결과, measurement_standards 는 직접 쓴다
  sources/          원본 위치와 변환 규칙 (제외·추가·오타 수정은 여기에 사유와 함께)
backend/h12/
  domain/           순수 업무 규칙. Flask, DB, YAML, 파일 입출력 금지
    workflow/       3장 상태·기능·대기 요청·revision·이력
    reference/      4.2 제품 분류, 5.3.4 열교환기, 4.4 PMS, 5.2 조건 매핑, 부록 A·4.3 선택지 규칙
    form/           4장 의뢰서, 5장 해석조건, 3.4-5 revision 비교, 3.4-9 의뢰번호. 의뢰서는 dict 로 두고 해석·검사한다
  reference/        refdata/ 읽기(store.py)와 원본 변환(build.py, openpyxl 은 여기서만)
  application/      유스케이스 (5단계)
  infra/            DB·알림 구현 (5단계)
  api/              Flask HTTP 계층
  rulebook.py       rules/*.yaml 로더
frontend/           React + TypeScript (Vite)
tests/              정의서 절 번호로 파일 이름을 붙인다 (test_3_2_*.py)
```

- 의존 방향은 `api → application → domain`, `infra → application/domain`, `reference → domain` 이다. [tests/architecture/test_layers.py](tests/architecture/test_layers.py)가 검사한다.
- **규칙은 데이터로 둔다.** 상태, 기능, 수행자, 사유 코드, 할 일 목록은 `rules/*.yaml` 에 있다. 엔진은 yaml 의 이름(actors, effects, requires, checks)만 해석한다. 새 이름이 필요할 때만 엔진과 `rules.py` 의 이름 목록을 함께 고친다.
- 정의서의 `[검토 필요]` 항목은 되도록 yaml 값으로 둬서 확정 시 코드 수정 없이 바꿀 수 있게 한다.
- 도메인 변경은 `WorkflowEngine` 을 거친다. `execute` 는 모든 검사를 마친 뒤에만 의뢰를 바꾼다.
- 의뢰서 작업(`h12.domain.form`)은 새 의뢰서 dict 를 돌려주는 순수 함수다. 의뢰자가 보낸 의뢰서는 `merge_user_edit` 로 시스템 값(의뢰 대상, 의뢰번호, PMS, 표준값)을 지킨 뒤 쓴다.
- 조건 구성은 의뢰가 남긴 기준 데이터 릴리스의 조건 매핑(`refdata/condition_mapping`)과 `rules/conditions.yaml` 이 정한다. 쓰지 않게 된 조건 값은 지우지 않는다.

## 테스트 원칙

- 기대값은 yaml 에서 읽어 만들지 않고 **정의서 표를 테스트에 직접 옮겨 적는다.** 그래야 yaml 오류를 잡는다.
- 의뢰를 특정 상태로 만들 때는 상태를 직접 넣지 않고 실제 기능을 순서대로 수행한다 (`tests/domain/workflow/conftest.py` 의 `make_request`).
- 의뢰서도 dict 를 직접 꾸미지 않고 확정 → 의뢰자 수정 → PMS 선택 순서로 만든다 (`tests/domain/form/conftest.py` 의 `make_form`, `edit`).

## 명령

```bash
# 백엔드 (저장소 루트)
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
.venv/Scripts/python -m h12              # http://127.0.0.1:8512

# 기준 데이터 새 버전 만들기 (원본 xlsx → refdata/<데이터셋>/<버전>.json). 그 뒤 manifest.yaml 에 릴리스를 직접 추가한다
.venv/Scripts/python -m pip install -e ".[convert]"
.venv/Scripts/python -m h12.reference.build 2026-11-15

# 프론트엔드 (frontend/)
npm install
npm run dev                              # /api 는 8512 로 프록시
npm run build && npm run lint
```

## 단계

0 골격 ✔ → 1 Workflow 도메인 ✔ → 2 기준 데이터 ✔ → 3 의뢰서·조건 엔진 ✔ → 4 Case·제출 검증 ✔ → 5 DB·API ✔ → 6 UI (세분화 진행 중: `docs/phase-6-ui-plan.md`) → 7 알림·지표 → 8 Agent

- 정의서는 v1.3(2026-10-30)이다. 1단계 중 확인한 9건(G-1~G-9)과 2단계 중 확인한 7건(G-10~G-16)은 결정되어 정의서에 반영했다. G-17(저장 코드 이름)은 구현 결정이다.
- 3단계 중 확인한 G-18~G-21은 결정되어 v1.3에 반영했다(운전 구분 삭제 포함). G-22(측정·판정 기준 표준값)는 추후 정의, G-23~G-27은 구현 해석·결정이다.
- 미룬 항목은 [docs/spec-gaps.md](docs/spec-gaps.md) "다음 단계로 미룬 것"에 있다.
- 6단계 UI는 [docs/phase-6-ui-plan.md](docs/phase-6-ui-plan.md)의 6.0~6.8 순서로 진행한다. 새 세션은 이 파일의 현재 단계, 완료 기록, 다음 단계를 먼저 확인하고, 작업을 마칠 때 검증 결과와 다음 단계를 갱신한다.

### 기준 데이터 원본

h12 밖에 있다. 가공한 결과만 `refdata/` 로 가져오고, 원본 위치와 변환 규칙은 `refdata/sources/*.yaml` 에 있다.
h10 의 `product_taxonomy.json` 은 같은 원본을 가공한 것이라 대조용으로만 쓴다 (2026-10-30 버전은 h10 의 252개와 같다).

| 기준 데이터 | 원본 |
|---|---|
| 제품 분류 | `G:\Tech\00_Agent\01_Agent_Code\총조립도 분류체계.xlsx` |
| 열교환기 Catalog | `G:\Tech\00_Agent\01_Agent_Code\docs\열교환기압력손실DB_Final.xlsx` 의 "압손DB_과제결과" 시트 |
| PMS 프로젝트 | `G:\Tech\00_Agent\01_Agent_Code\request_ai_agent_h10_v0\docs\20260915_PMS_Project_Running_{Aircare,CAC,Chiller,RAC}.xlsx` |
| 해석유형 11종, 선택지 목록 | 정의서 부록 A, 4.2·4.3 → `rules/analysis_types.yaml`, `rules/options.yaml` |
| 측정·판정 기준 표준값 | 없음 [추후 정의] → `refdata/measurement_standards/` 에 빈 자리만 있다 |

- 원본이 있으면 `tests/reference/test_9_build.py` 가 저장소의 버전 파일이 원본에서 그대로 다시 만들어지는지 확인한다 (없으면 건너뛴다).
