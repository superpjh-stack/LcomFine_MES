# QA3 보안 · 운영 — W1 (2026-10-21)

검증만 했다. 코드는 고치지 않았다. 계정은 부서 8 의 **임시 계정**(접두 `q3…` · 난수 비밀번호 · 이름 `(예시)`)을 만들어 쓰고 끝나면 지웠다(남은 행 0 — `select count(*) from sys_user where login_id like 'q3%'` = 0). 시드 계정 8(sl pr sh ds ac st ex admin)은 로그인 확인(G-21)과 E2E 캡처에만 썼다. 시드 계정의 상태는 바꾸지 않았다. 상태를 바꾸면 `session_epoch` 트리거가 같은 DB 를 쓰는 QA1 · QA2 · 개발 테스트의 세션까지 끊는다. 측정 시점에 sl · sh 의 `session_epoch` 가 이미 20 · 40 이었다. 권한은 부서 단위(`sys_permission`)로 판정하므로 임시 계정으로 해도 시드 계정과 결과가 같다.

## 1. 결함

| ID | 심각도 | 담당 | 요약 |
|---|---|---|---|
| DEF-QA3-001 | **중대** | 아키텍트 (Dockerfile) | Dockerfile 이 지워진 `tools/sample_data.py` 를 COPY 한다. 그래서 이미지 빌드가 실패하고 G-24 는 통과할 수 없다 |
| DEF-QA3-002 | 경미 | 개발1 (bas · wo · sys) | NUL 이 든 입력의 422 가 어느 항목인지 짚지 않는다(`fields=[{"name":"입력"}]`) |
| DEF-QA3-003 | 경미 | 아키텍트 (DB 역할) · 참고 개발2 · 개발3 (테스트 정리) | 앱이 superuser 로 DB 에 붙는다. 불변 이력 트리거를 `session_replication_role` 로 우회할 수 있고, 테스트 정리 코드가 이 우회에 기대고 있다 |

치명 0 · 중대 1 · 경미 2.

### DEF-QA3-001 · 중대 · Dockerfile COPY 원본 없음 → `docker compose build` 실패
- 재현(정적): `Dockerfile` 의 `COPY tools/backup.py tools/sample_data.py tools/docker_init.py ./tools/` 중 `ls tools/sample_data.py` → `No such file or directory`. 이 파일은 커밋 `2db6bd3`(Phase 0: 옛 도메인 삭제)에서 지워졌다. `.dockerignore` 에 걸린 것도 아니다. 파일이 아예 없다.
- 기대: goal.md §2 G-24 「`docker compose up -d --build` → 컨테이너 기동 · `/health` 200」 · D-31.
- 실제: 원본이 없는 COPY 는 BuildKit 이 `"/tools/sample_data.py": not found` 로 멈춘다. `docker compose config -q` 는 rc=0 이라 문법 검사로는 걸리지 않는다. gate.py 의 G-24 도 「config 성립」 까지만 보고 `미검증` 으로 적는다. 컨테이너는 띄우지 않았다(지시대로). 그래서 근거는 정적 검사뿐이지만 결과는 확정적이다.
- 같이 볼 것: Dockerfile 주석 「(예시) 샘플 100행: … tools/sample_data.py」 · compose 주석의 `sample_data` 안내. `deploy/hostinger` 의 GHCR 이미지 빌드(`.github/workflows/image.yml`)도 같은 Dockerfile 을 쓰면 같이 깨진다.
- 테스트: `tests/test_qa3_robustness.py::test_g24_docker_static` (실패 상태로 커밋함).

### DEF-QA3-002 · 경미 · NUL 입력 422 가 항목을 짚지 않는다
- 재현: 임시 ADM(또는 SL) 계정으로 아래를 보낸다. 응답은 모두 422 지만 `fields=[{"name":"입력","reason":"쓸 수 없는 글자(NUL)가 들어 있습니다"}]` 한 줄뿐이다. 즉 라우터가 아니라 `main.py` 의 `psycopg.DataError` 핸들러가 막은 것이다.
  - `POST /bas/items` `item_code=<접두>n\x00ul` (F-BAS-011)
  - `POST /bas/customers` `customer_name=a\x00b` (F-BAS-021)
  - `POST /wo/requests` `note=a\x00b` (F-WO-011)
  - `POST /sys/codes` `code=a\x00b` (F-SYS-031)
- 기대: api-contract.md §3 「사람이 읽을 문장(어느 항목이 …)은 라우터가 먼저 검사해서 준다 — 핸들러는 마지막 방어선」 · CLAUDE.md 「사람이 읽을 문장은 라우터가 먼저 검사해서 준다」. 비교하면 개발2 의 `POST /mat/receipts` 는 `공급사: 글자에 NUL(0x00)을 넣을 수 없습니다` 로 항목을 짚는다.
- 실제: 500 은 아니다(계약의 최소선은 지킴). 사용자가 어느 칸을 고칠지 알 수 없다. 개발1 의 `need()` · `s()` 공용 도우미에 NUL 검사가 없는 것으로 보인다.
- 테스트: `tests/test_qa3_robustness.py::test_nul_input_names_the_field` (실패 상태로 커밋함).

### DEF-QA3-003 · 경미 · 앱 DB 역할이 superuser · 테스트가 트리거 우회에 기댄다
- 재현: `psql -h /tmp lcomfine_db -tAc "select current_user, rolsuper from pg_roles where rolname=current_user"` → `gerardo92|t`. Docker 는 `POSTGRES_USER: lcomfine` 이고, postgres 이미지는 이 계정을 superuser 로 만든다. 앱도 이 계정으로 붙는다.
- 테스트 코드: `tests/test_dev2_world.py:139` · `tests/test_dev3_world.py:127` 이 `set local session_replication_role = replica` 로 불변 이력(`stock_adjust` · `shipment_adjust` append-only 트리거)을 끈 뒤 테스트 행을 지운다.
- 판정: **테스트 정리 용도로는 받아들일 수 있다.** 트랜잭션 안의 `set local` 이고, 테스트가 만든 행(자기 위치 · 자기 출하 id)만 지우고, 바로 `origin` 으로 되돌리기 때문이다. 다만 두 가지 문제가 있다. ① 이 방식은 실행 계정이 superuser 일 때만 된다. 최소 권한 계정으로 테스트를 돌리면 정리가 실패하고, 행이 남아 다음 실행이 깨진다. ② 더 큰 문제는 이 방식이 「앱이 superuser 로 돈다」는 사실을 가린다는 점이다. SQL 경로 하나만 뚫려도 불변 트리거 · 감사 로그(`sys_change_log` · `sys_access_log` 에는 불변 트리거가 아예 없다)를 지우거나 고칠 수 있다.
- 기대: db-schema.md §2 규칙 5 「`stock_adjust` · `shipment_adjust` 는 불변(트리거가 UPDATE · DELETE 를 막는다)」 가 운영에서도 성립할 것. 최소 권한 DB 역할에 대한 결정 D-번호는 아직 없다. **결정 대장에 올릴 것을 요청한다**(앱 역할 = 테이블 소유자 아님 · superuser 아님. 테스트 정리는 소유자 역할 또는 테스트 전용 DB 로).

## 2. 게이트 판정 (QA3 몫)

명령: `uv run python tools/check_security.py` (= `make check-security`) — 종료코드 = FAIL 행 수. 실측 종료코드 4 = G-16 · G-17 · G-18(W3/W4) + G-24 COPY. 실행 시간 약 10초.

| 게이트 | 판정 | 실측 (check_security 행) |
|---|---|---|
| G-16 데이터 질의 | FAIL | W3/W4 — RPT-130 미구현 |
| G-17 키 없음 | FAIL | W3/W4 — ai.py 미구현 |
| G-18 SSO | FAIL | W3/W4 — DOC-010 미구현 |
| **G-19 권한 403 전수** | **PASS** (6/6) | 라우터 POST 58 전부 자기 기능 ID 의 `require_fn` · GET 51 전부 권한 의존성 있음 / 세션 없이 쓰기 POST 58 → 401 · 화면 GET 67 → JSON 401 · 브라우저 303 `/login` / **쓰기 기능 58 × 부서 8 전수**: 계약에 W 가 없는 337 칸 → 403, W 칸 127 → 403·401·5xx 아님 / 화면 67 + 하위 조회·출력 × 부서 8 = GET 552: 칸 없음 403 · 칸 있음 200, 메인 화면에 칸 없는 화면 링크 0 / 바꿔치기: PR 알림을 다른 부서 6 이 처리 → 404(행 그대로) · PR 이 처리 → 200 · 알림 id `999999999999`·`abc`·`-1` → 404 · W 없는 부서 5 의 남의 의뢰 수정 → 403(수량 그대로) · `/openapi.json` 미로그인 401 · 영업부 403 · `/docs` `/redoc` 404 / 권한 칸 변경(SYS-021, EX×WO-040 R → 없음 → R): 다음 요청 403 → 200 |
| **G-20 세션 상태** | **PASS** (9/9) | 중지 · 잠금(SYS-012) → GET·POST 401, 정상으로 되돌려도 옛 세션 401, 다시 로그인 200 / 비활성(F-SYS-013) → 401 / 부서 변경 PR→SL: 끊기지 않고 다음 요청부터 BAS-030 403 · 쓰기 403, 되돌리면 200 / 로그아웃 전 쿠키 재사용 401 · 같은 계정 다른 세션 200 / 비밀번호 초기화 → 401 / `session_epoch` 증가 → 401 / 계정 삭제 → 401 / 서명이 깨진 쿠키 → 401 |
| **G-21 비밀 · 시드** | **PASS** (4/4) | 추적·미무시 파일의 비밀 값 0 · `sk-` 키 패턴 0 · `.env` gitignore 됨 · 추적 안 됨 / 시드 계정 8 · 채번 7 모두 `(예시)` / 인증 없는 응답 5(`/health` `/login` `/error?status=500` 404 · 로그인 실패)에 비밀·접속 문자열 0 / 시드 8 계정이 `.env` 비밀번호로 로그인 8/8. **시드 멱등**은 이번 실행에서 돌리지 않았다(다른 QA 와 DB 를 같이 쓴다). `make gate-full` 또는 `check_security.py --run-seeds` 가 잰다 |
| **G-22 감사 로그** | **PASS** (5/5) | 쓰기 표본 13(BAS 5 · STD 1 · WO 2 · HOME 2 · SYS 3): 성공마다 `sys_change_log` 정확히 1행, 기능 ID · 화면 ID · POST · 경로 · 대상 · login_id 일치 / 실패한 쓰기(422 · 403) → 0행 / 화면 GET 4 → `sys_access_log` 조회 +1씩 · 로그인 성공 +1 · 실패 +1 / SYS-040 `?tab=change` 에서 방금 쓴 12 대상이 모두 보임 / 정적: POST 58 전부 `log_change` 를 부름(같은 모듈 도우미 한 단계까지) |
| G-24 (정적만) | **FAIL** | `docker compose config -q` rc=0 · openpyxl 은 pyproject + uv.lock → `uv sync --frozen --no-dev` 로 설치됨 · **COPY 원본 없음 1(DEF-QA3-001)** |

`uv run python tools/gate.py`(읽기 전용) 결과 비교: G-20 · G-21 · G-22 는 PASS 다. G-19 는 FAIL 인데, 내 검사 6 은 모두 PASS 다. FAIL 은 QA1 의 `tools/check_screens.py` 가 G-19 행은 PASS 로 찍고 종료코드 5 로 끝나서 gate.py 의 「도구 종료코드」 규칙에 걸린 것이다(QA1 몫). 빌드 전제 `pytest failed 2` 는 위 결함 테스트 두 개다.

### 조용한 실패 사냥 (`X-nn` 행 — 게이트 번호가 아니다)
| 행 | 판정 | 실측 |
|---|---|---|
| X-01 DB 끊김 /health | PASS | 하위 프로세스에서 `LCOMFINE_PG_DSN=postgresql:///lcomfine_qa3_absent_db` → `/health` 503, 본문에 접속 문자열 · DB 이름 없음 |
| X-02 DB 끊김 화면 · 쓰기 · 로그인 | PASS (6) | 유효한 세션 쿠키로 화면 GET(JSON · 브라우저) · 메인 · 쓰기 POST · 로그인 화면 · 로그인 POST → 전부 503. 「미수집」 이나 멀쩡한 화면으로 보인 것 0 |
| X-03 이상한 입력 | PASS | POST 26(API 9: bas items·customers · wo requests · mat receipts · shp orders · inv adjustments · prd daily · sys codes · 경로 키): NUL · 음수 · 1e30 · NaN · 10^40 · 99999년 날짜 · 없는 FK · bigint 초과 id → 422(경로 키는 404), 500 은 0 |
| X-04 조회 인자 | PASS | GET 8 에 NUL · 틀린 날짜 → 500 0 |

참고(결함 아님): 품목명 · 거래처명 10만 자는 200 으로 저장된다. db-schema 의 `text` 컬럼이고 길이를 정한 계약이 없다. 길이 상한이 필요하면 결정을 받아야 한다.

## 3. E2E 캡처
- 명령: `uv run --offline --with playwright python tools/check_security.py --e2e`. 프로젝트에는 Playwright 가 없다. uv 캐시에 있던 playwright 1.63 과 `~/Library/Caches/ms-playwright` 의 chromium 을 오프라인으로 썼다. 전역 설치나 다운로드는 하지 않았다. 앱은 127.0.0.1:8020 하위 프로세스로 띄웠고 끝나고 내렸다.
- 결과: 16/16 PASS. 계정 · 경로: admin `/` `/wo/requests` `/shp/orders` `/lot/backward` `/ia`, sl `/wo/requests`, sh `/shp/orders`, pr `/lot/backward`. 폭은 1280 과 390. 모두 status 200 이고 `scrollWidth ≤ innerWidth`(1280 ≤ 1280 · 390 ≤ 390), 로그인 화면으로 튕긴 것 0. 파일은 `outputs/e2e/*.png` 와 `outputs/e2e/result.json`.
- 눈으로 본 것: 390 폭 `/ia` 권한 매트릭스에 부서 8 중 3 열(영업부 · 생산부 · 출하실)만 보인다. 문서 가로 스크롤은 0 이다. 나머지 열이 안쪽 스크롤로 나머지 열을 볼 수 있는지는 확인하지 못했다(QA1 · 화면 담당이 확인할 것).
- 범위: goal.md 의 「G-06 흐름을 부서를 바꿔 로그인하며 단계별 캡처」는 W1 범위 밖이라 하지 않았다. 이번 캡처는 화면 5 개 · 폭 2 개뿐이다.

## 4. 관찰 (결함으로 올리지 않음 — 계약에 기준 없음)
- `GET /logout` 이 상태를 바꾼다. 다른 사이트에 `<img src=…/logout>` 을 심으면 사용자가 강제로 로그아웃된다. 쓰기 POST 에는 CSRF 토큰이 없고, 쿠키 `SameSite=lax` · `HttpOnly` 에 기댄다. 쿠키에 `Secure` 가 없다(`https_only=False` — 운영이 HTTPS 면 켜야 한다).
- `audit.log_change` 는 쓰기 트랜잭션이 커밋된 뒤 따로 돈다(interfaces 계약이 정한 순서다). 그래서 로그 적재만 실패하면 쓰기는 남고 변경 로그는 빠진다(응답은 5xx).
- `rbac` 권한 표 캐시는 프로세스마다 5초다. 워커 하나(Dockerfile CMD)에서만 「다음 요청부터」 가 성립한다(D-106 · D-26 에 적혀 있음).
- 열린 리다이렉트: `next=//evil.com` · `/\evil.com` · `https://evil.com` → `/` 로 막힌다. `/\t/evil.com` 은 `/%09/evil.com`(같은 사이트 경로)이 된다. `/static/../.env` 류는 404 다. 템플릿은 autoescape 가 켜져 있다(저장한 `<script>` 가 `&lt;script&gt;` 로 나온다).
- 로그인 실패 횟수는 세기만 하고 잠그지 않는다(D-20).

## 5. 산출물 · 다시 돌리는 법
- `tools/check_security.py` — `make check-security` · `--run-seeds`(시드 멱등까지) · `--e2e`(캡처)
- `tests/test_qa3_security.py`(G-19 · G-20) · `tests/test_qa3_audit.py`(G-21 · G-22) · `tests/test_qa3_robustness.py`(DB 끊김 · 이상한 입력 · Docker 정적 · NUL 항목) — `uv run pytest -q tests/test_qa3_*.py` → 13 passed · 2 failed(DEF-QA3-001 · 002)
- `outputs/e2e/` — 캡처 16 + `result.json`
