# QA3 보안 · 운영 — W1 (2026-10-21)

검증만 했다. 코드는 고치지 않았다. 계정은 부서 8 의 **임시 계정**(접두 `q3…` · 난수 비밀번호 · 이름 `(예시)`)을 만들어 쓰고 끝나면 지웠다(남은 행 0 — `select count(*) from sys_user where login_id like 'q3%'` = 0). 시드 계정 8(sl pr sh ds ac st ex admin)은 로그인 확인(G-21)과 E2E 캡처에만 썼다. 시드 계정의 상태는 바꾸지 않았다. 상태를 바꾸면 `session_epoch` 트리거가 같은 DB 를 쓰는 QA1 · QA2 · 개발 테스트의 세션까지 끊는다. 측정 시점에 sl · sh 의 `session_epoch` 가 이미 20 · 40 이었다. 권한은 부서 단위(`sys_permission`)로 판정하므로 임시 계정으로 해도 시드 계정과 결과가 같다.

## 1. 결함

| ID | 심각도 | 담당 | 요약 | 재검증 |
|---|---|---|---|---|
| DEF-QA3-001 | **중대** | 아키텍트 (Dockerfile) | Dockerfile 이 지워진 `tools/sample_data.py` 를 COPY 한다. 그래서 이미지 빌드가 실패하고 G-24 는 통과할 수 없다 | **해소(실측)** — COPY 원본 7 전부 있음(§6) |
| DEF-QA3-002 | 경미 | 개발1 (bas · wo · sys) | NUL 이 든 입력의 422 가 어느 항목인지 짚지 않는다(`fields=[{"name":"입력"}]`) | **해소(실측)** — 4 경로 모두 항목 이름을 짚음(§6) |
| DEF-QA3-003 | 경미 | 아키텍트 (DB 역할) · 참고 개발2 · 개발3 (테스트 정리) | 앱이 superuser 로 DB 에 붙는다. 불변 이력 트리거를 `session_replication_role` 로 우회할 수 있고, 테스트 정리 코드가 이 우회에 기대고 있다 | **D-524 등재(가설) · W4** 에서 앱 역할 분리 — W1~W3 은 그대로. 열림 |

치명 0 · 중대 1 · 경미 2 (처음 보고). **재검증 뒤 남은 것: DEF-QA3-003 1건(경미 · D-524 · W4).** 표의 마지막 열은 2026-10-21 재검증(§6) 결과다.

### DEF-QA3-001 · 중대 · Dockerfile COPY 원본 없음 → `docker compose build` 실패
- 재현(정적): `Dockerfile` 의 `COPY tools/backup.py tools/sample_data.py tools/docker_init.py ./tools/` 중 `ls tools/sample_data.py` → `No such file or directory`. 이 파일은 커밋 `2db6bd3`(Phase 0: 옛 도메인 삭제)에서 지워졌다. `.dockerignore` 에 걸린 것도 아니다. 파일이 아예 없다.
- 기대: goal.md §2 G-24 「`docker compose up -d --build` → 컨테이너 기동 · `/health` 200」 · D-31.
- 실제: 원본이 없는 COPY 는 BuildKit 이 `"/tools/sample_data.py": not found` 로 멈춘다. `docker compose config -q` 는 rc=0 이라 문법 검사로는 걸리지 않는다. gate.py 의 G-24 도 「config 성립」 까지만 보고 `미검증` 으로 적는다. 컨테이너는 띄우지 않았다(지시대로). 그래서 근거는 정적 검사뿐이지만 결과는 확정적이다.
- 같이 볼 것: Dockerfile 주석 「(예시) 샘플 100행: … tools/sample_data.py」 · compose 주석의 `sample_data` 안내. `deploy/hostinger` 의 GHCR 이미지 빌드(`.github/workflows/image.yml`)도 같은 Dockerfile 을 쓰면 같이 깨진다.
- 테스트: `tests/test_qa3_robustness.py::test_g24_docker_static` (실패 상태로 커밋함).
- **재검증(2026-10-21)**: 아키텍트가 `COPY tools/backup.py tools/docker_init.py ./tools/` 로 바꾸고 `sample_data` 주석을 지웠다(`git diff Dockerfile`). Dockerfile 의 COPY 원본 7(pyproject.toml · uv.lock · .python-version · src · contracts · tools/backup.py · tools/docker_init.py)을 `ls` 로 전부 확인 → 없는 것 0. `check_security` G-24 3행 PASS · `test_g24_docker_static` PASS. **해소(정적).** 실기동(`docker compose up -d --build` → `/health` 200)은 Docker 데몬이 꺼져 있어 못 잰다 — D-525(차단 · 사람이 켠다).

### DEF-QA3-002 · 경미 · NUL 입력 422 가 항목을 짚지 않는다
- 재현: 임시 ADM(또는 SL) 계정으로 아래를 보낸다. 응답은 모두 422 지만 `fields=[{"name":"입력","reason":"쓸 수 없는 글자(NUL)가 들어 있습니다"}]` 한 줄뿐이다. 즉 라우터가 아니라 `main.py` 의 `psycopg.DataError` 핸들러가 막은 것이다.
  - `POST /bas/items` `item_code=<접두>n\x00ul` (F-BAS-011)
  - `POST /bas/customers` `customer_name=a\x00b` (F-BAS-021)
  - `POST /wo/requests` `note=a\x00b` (F-WO-011)
  - `POST /sys/codes` `code=a\x00b` (F-SYS-031)
- 기대: api-contract.md §3 「사람이 읽을 문장(어느 항목이 …)은 라우터가 먼저 검사해서 준다 — 핸들러는 마지막 방어선」 · CLAUDE.md 「사람이 읽을 문장은 라우터가 먼저 검사해서 준다」. 비교하면 개발2 의 `POST /mat/receipts` 는 `공급사: 글자에 NUL(0x00)을 넣을 수 없습니다` 로 항목을 짚는다.
- 실제: 500 은 아니다(계약의 최소선은 지킴). 사용자가 어느 칸을 고칠지 알 수 없다. 개발1 의 `need()` · `s()` 공용 도우미에 NUL 검사가 없는 것으로 보인다.
- 테스트: `tests/test_qa3_robustness.py::test_nul_input_names_the_field` (실패 상태로 커밋함).
- **재검증(2026-10-21)**: 개발1 이 `routers/bas.py` 의 공용 헬퍼 `s(v, label)` 에 NUL 검사를 넣었다(`"\x00" in v → bad(label, NUL_REASON)`) — std · wo · sys · trk · home 이 같은 헬퍼를 쓴다. 임시 계정으로 같은 4 경로 + 비교 대상 1 을 다시 보냈다(아래 실측). 전부 422 이고 `fields[].name` 이 항목을 짚는다. `test_nul_input_names_the_field` PASS. **해소(실측).**
  - `POST /bas/items` item_code NUL → `[{"name":"품목 코드","reason":"글자에 NUL(0x00)을 넣을 수 없습니다"}]`
  - `POST /bas/customers` customer_name NUL → `name: 거래처명`
  - `POST /wo/requests` note NUL → `name: 비고`
  - `POST /sys/codes` code NUL → `name: 코드 값`
  - (비교) `POST /mat/receipts` supplier_name NUL → `name: 공급사` (개발2 · 전과 같음)

### DEF-QA3-003 · 경미 · 앱 DB 역할이 superuser · 테스트가 트리거 우회에 기댄다
- 재현: `psql -h /tmp lcomfine_db -tAc "select current_user, rolsuper from pg_roles where rolname=current_user"` → `gerardo92|t`. Docker 는 `POSTGRES_USER: lcomfine` 이고, postgres 이미지는 이 계정을 superuser 로 만든다. 앱도 이 계정으로 붙는다.
- 테스트 코드: `tests/test_dev2_world.py:139` · `tests/test_dev3_world.py:127` 이 `set local session_replication_role = replica` 로 불변 이력(`stock_adjust` · `shipment_adjust` append-only 트리거)을 끈 뒤 테스트 행을 지운다.
- 판정: **테스트 정리 용도로는 받아들일 수 있다.** 트랜잭션 안의 `set local` 이고, 테스트가 만든 행(자기 위치 · 자기 출하 id)만 지우고, 바로 `origin` 으로 되돌리기 때문이다. 다만 두 가지 문제가 있다. ① 이 방식은 실행 계정이 superuser 일 때만 된다. 최소 권한 계정으로 테스트를 돌리면 정리가 실패하고, 행이 남아 다음 실행이 깨진다. ② 더 큰 문제는 이 방식이 「앱이 superuser 로 돈다」는 사실을 가린다는 점이다. SQL 경로 하나만 뚫려도 불변 트리거 · 감사 로그(`sys_change_log` · `sys_access_log` 에는 불변 트리거가 아예 없다)를 지우거나 고칠 수 있다.
- 기대: db-schema.md §2 규칙 5 「`stock_adjust` · `shipment_adjust` 는 불변(트리거가 UPDATE · DELETE 를 막는다)」 가 운영에서도 성립할 것. 최소 권한 DB 역할에 대한 결정 D-번호는 아직 없다. **결정 대장에 올릴 것을 요청한다**(앱 역할 = 테이블 소유자 아님 · superuser 아님. 테스트 정리는 소유자 역할 또는 테스트 전용 DB 로).
- **재검증(2026-10-21)**: 아키텍트가 **D-524(가설)** 로 올렸다 — 운영 앱 역할 `lcomfine_app`(소유자 · superuser 아님 · 불변 이력은 INSERT 만), 스키마 · 시드 · 백업은 소유자 역할, 테스트 정리는 소유자 역할 또는 테스트 전용 DB. **W4(운영 · G-24)에서 `docker_init.py` · compose · 테스트 픽스처를 함께 바꾼다. W1~W3 은 로컬 개발 역할 그대로.** 코드는 아직 바뀌지 않았으므로 이 결함은 **열림(W4 대기)** 이다. 지금도 `select rolsuper from pg_roles where rolname = current_user` → `t`.

## 2. 게이트 판정 (QA3 몫)

명령: `uv run python tools/check_security.py` (= `make check-security`) — 종료코드 = FAIL 행 수. 처음 보고의 종료코드 4 = G-16 · G-17 · G-18(W3/W4) + G-24 COPY. **재검증(2026-10-21) 종료코드 3 = G-16 · G-17 · G-18 만(W3/W4 미구현) · PASS 36 · WARN 0 · 약 10초.** 아래 표는 재검증 값이다.

| 게이트 | 판정 | 실측 (check_security 행) |
|---|---|---|
| G-16 데이터 질의 | FAIL | W3/W4 — RPT-130 미구현 |
| G-17 키 없음 | FAIL | W3/W4 — ai.py 미구현 |
| G-18 SSO | FAIL | W3/W4 — DOC-010 미구현 |
| **G-19 권한 403 전수** | **PASS** (6/6) | 라우터 POST 58 전부 자기 기능 ID 의 `require_fn` · GET 51 전부 권한 의존성 있음 / 세션 없이 쓰기 POST 58 → 401 · 화면 GET 67 → JSON 401 · 브라우저 303 `/login` / **쓰기 기능 58 × 부서 8 전수**: 계약에 W 가 없는 337 칸 → 403, W 칸 127 → 403·401·5xx 아님 / 화면 67 + 하위 조회·출력 × 부서 8 = GET 552: 칸 없음 403 · 칸 있음 200, 메인 화면에 칸 없는 화면 링크 0 / 바꿔치기: PR 알림을 다른 부서 6 이 처리 → 404(행 그대로) · PR 이 처리 → 200 · 알림 id `999999999999`·`abc`·`-1` → 404 · W 없는 부서 5 의 남의 의뢰 수정 → 403(수량 그대로) · `/openapi.json` 미로그인 401 · 영업부 403 · `/docs` `/redoc` 404 / 권한 칸 변경(SYS-021, EX×WO-040 R → 없음 → R): 다음 요청 403 → 200 |
| **G-20 세션 상태** | **PASS** (9/9) | 중지 · 잠금(SYS-012) → GET·POST 401, 정상으로 되돌려도 옛 세션 401, 다시 로그인 200 / 비활성(F-SYS-013) → 401 / 부서 변경 PR→SL: 끊기지 않고 다음 요청부터 BAS-030 403 · 쓰기 403, 되돌리면 200 / 로그아웃 전 쿠키 재사용 401 · 같은 계정 다른 세션 200 / 비밀번호 초기화 → 401 / `session_epoch` 증가 → 401 / 계정 삭제 → 401 / 서명이 깨진 쿠키 → 401 |
| **G-21 비밀 · 시드** | **PASS** (4/4) | 추적·미무시 파일의 비밀 값 0 · `sk-` 키 패턴 0 · `.env` gitignore 됨 · 추적 안 됨 / 시드 계정 8 · 채번 7 모두 `(예시)` / 인증 없는 응답 5(`/health` `/login` `/error?status=500` 404 · 로그인 실패)에 비밀·접속 문자열 0 / 시드 8 계정이 `.env` 비밀번호로 로그인 8/8. **시드 멱등**은 이번 실행에서 돌리지 않았다(다른 QA 와 DB 를 같이 쓴다). `make gate-full` 또는 `check_security.py --run-seeds` 가 잰다 |
| **G-22 감사 로그** | **PASS** (5/5) | 쓰기 표본 **15**(BAS 6 · STD 2 · WO 2 · HOME 2 · SYS 3 — 모듈 5): 성공(200)마다 `sys_change_log` 정확히 1행, 기능 ID · 화면 ID · POST · 경로 · 대상 · login_id 일치. **F-HOME-031 은 생산부(PR) 임시 계정이 자기 부서 수신 이벤트 5 를 전부 켠 채 저장**(코드의 유일한 200 경로 · Ruling 24 · D-526) / 실패한 쓰기 **6** → 0행: 빈 본문 422 ×2 · 칸 없는 부서 403 · **F-HOME-031 ADM 이 `material_received`(다른 부서 이벤트) → 422 「범위 밖 (D-511)」 · PR 이 부서 기본 하나를 끔 → 422 · PR 이 `mail=on` → 501 (D-518)** — 응답 코드가 계약과 다르면 FAIL / 화면 GET 4 → `sys_access_log` 조회 +1씩 · 로그인 성공 +1 · 실패 +1 / SYS-040 `?tab=change` 에서 방금 쓴 15 대상이 login 별 조회로 모두 보임 / 정적: POST 58 전부 `log_change` 를 부름 |
| G-24 | **정적 PASS (3/3) · 실기동 차단 D-525** | `docker compose config -q` rc=0 · openpyxl 은 pyproject + uv.lock → `uv sync --frozen --no-dev` 로 설치됨 · **COPY 원본 7 전부 있음(DEF-QA3-001 해소)**. 실기동은 `docker info` → `failed to connect to the docker API at unix:///Users/gerardo92/.docker/run/docker.sock … connect: no such file or directory` — 데몬이 꺼져 있어 컨테이너를 띄울 수 없다. gate.py 의 G-24 는 D-525 대로 `미검증`(FAIL 로 센다) |

`uv run python tools/gate.py`(읽기 전용) 결과 비교(처음 보고 시점 · 재검증에서는 다시 돌리지 않았다): G-20 · G-21 · G-22 는 PASS 다. G-19 는 FAIL 인데, 내 검사 6 은 모두 PASS 다. FAIL 은 QA1 의 `tools/check_screens.py` 가 G-19 행은 PASS 로 찍고 종료코드 5 로 끝나서 gate.py 의 「도구 종료코드」 규칙에 걸린 것이다(QA1 몫). 처음 보고의 빌드 전제 `pytest failed 2` 는 위 결함 테스트 두 개였고, 재검증에서는 둘 다 PASS 다(§6).

### 조용한 실패 사냥 (`X-nn` 행 — 게이트 번호가 아니다)
개발 수정(`s()` NUL 검사 · HOME-030 Ruling 24) 뒤 2026-10-21 에 다시 돌렸다 — 아래 행은 재검증에서도 전부 PASS(X-01 1 · X-02 6 · X-03 1 · X-04 1).
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
- `tests/test_qa3_security.py`(G-19 · G-20) · `tests/test_qa3_audit.py`(G-21 · G-22) · `tests/test_qa3_robustness.py`(DB 끊김 · 이상한 입력 · Docker 정적 · NUL 항목) — `uv run pytest -q tests/test_qa3_*.py` → 처음 13 passed · 2 failed(DEF-QA3-001 · 002) → **재검증 14 passed · 0 failed**(§6)
- `outputs/e2e/` — 캡처 16 + `result.json`

## 6. 2026-10-21 재검증 (개발 수정 뒤)

코드는 고치지 않았다. 고친 것은 내 검사기 `tools/check_security.py` 만이다. 임시 계정(접두 `q3…`)은 끝나고 지웠다 — `select count(*) from sys_user where login_id like 'q3%'` = 0, customer · item · standard 의 `q3%` 코드 0, `notification` 의 `qa3:%` 0.

### 6.1 실측 · 명령
| 명령 | 결과 |
|---|---|
| `uv run python tools/check_security.py` | **종료코드 3** · FAIL 3(G-16 · G-17 · G-18 — W3/W4 미구현) · PASS 36 · WARN 0 · 10초 |
| `uv run pytest -q tests/test_qa3_*.py` | **14 passed** · 0 failed · 10.4초 |
| `git diff Dockerfile` + `ls` COPY 원본 7 | `tools/sample_data.py` COPY · 주석 삭제 확인 · 원본 없는 것 0 |
| `docker info` | `failed to connect to the docker API at unix:///Users/gerardo92/.docker/run/docker.sock … no such file or directory` → 실기동 측정 불가(D-525) |
| NUL 4 경로 + 비교 1 (임시 계정 · 위 §1 DEF-QA3-002) | 전부 422 · `fields[].name` = 품목 코드 · 거래처명 · 비고 · 코드 값 · 공급사 |

처음 돌렸을 때(검사기를 고치기 전) 실측: `check_security` 종료코드 4 = G-16 · 17 · 18 + **G-22 「쓰기 성공 → 1행」 FAIL** (`F-HOME-031 쓰기 422 … 다른 부서로 가는 알림은 구독할 수 없습니다 — 범위 밖 (D-511)`), G-24 3행은 이미 PASS. pytest 는 `test_g22_change_and_access_log` FAIL(같은 원인) · `test_nul_input_names_the_field` **ERROR `UniqueViolation customer_code_uq`** 2 failed · 12 passed. 둘 다 앱 결함이 아니라 내 검사기의 문제였다(6.2).

### 6.2 검사기 수정 (`tools/check_security.py` — 내 소유)
1. **G-22 쓰기 표본 F-HOME-031** — 옛 표본은 ADM 이 `material_received` 를 저장하는 것이었는데, Ruling 24 · D-526 뒤 이 본문은 계약대로 422 다(ADM 은 어떤 이벤트도 수신하지 않는다 → 「범위 밖 (D-511)」). `routers/home.py` 를 읽어 보면 200 경로가 하나 있다: **자기 부서가 수신하는 이벤트를 전부 켠 채 저장**(범위 밖이 된 옛 행만 지우고 `log_change` 1행). 계약(function-list F-HOME-031 「자기 부서가 수신하는 이벤트의 끄기만 · 부서 기본을 끄려 하면 422」)과 맞다. 표본을 **생산부(PR) 임시 계정 · `notify.EVENTS` 에서 PR 이 든 이벤트 5 = events = enabled** 로 바꿨고, 표본마다 부서 열을 두었다(로그는 그 부서 계정의 login_id 로 찾는다).
2. **음성 표본 3 추가**(「실패한 쓰기 → 0행」 행이 3 → 6): ADM `material_received` → **422** · PR 이 기본 이벤트 하나를 `enabled` 에서 뺌 → **422** · PR `mail=on` → **501**. 응답 코드가 기대와 다르거나 `sys_change_log` 가 1행이라도 늘면 FAIL — 즉 D-526 의 「저장하지 않는다」를 로그로도 확인한다. 게이트는 낮아지지 않았다(표본 13 → 15, 음성 3 → 6, 코드도 함께 판정).
3. 빈 자리를 **F-BAS-022(거래처 수정) · F-STD-022(표준 수정)** 으로 채웠다 → 쓰기 표본 15(BAS 6 · STD 2 · WO 2 · HOME 2 · SYS 3).
4. **SYS-040 조회 검사**가 ADM login 으로만 걸러 PR 의 행을 못 보던 것 → login 별로 조회해 15/15 확인.
5. **`malformed_cases(lab)` 멱등** — 같은 Lab(모듈 픽스처)에서 `check_malformed` 뒤 `test_nul_input_names_the_field` 가 다시 불러 기준 행(`{접두}c3` 거래처 등)을 두 번 넣어 `UniqueViolation` 이 났다. Lab 에 캐시해 한 번만 넣는다. 커밋 `1b5108c` 의 테스트 · 검사기도 같은 이중 호출 구조다(`git show HEAD:…` 로 확인) — 즉 모듈 픽스처로 묶어 돌리면 NUL 판정에 이르기 전에 이 중복 삽입이 터진다. 내 테스트 결함이었다. 오늘 실측에서 NUL 4 경로가 항목을 짚는 것은 6.1 의 직접 재현으로 따로 확인했다.

### 6.3 결함 현황
| ID | 등급 | 담당 | 상태 |
|---|---|---|---|
| DEF-QA3-001 | 중대 | 아키텍트 | **해소(실측 · 정적)** — 실기동은 D-525 차단(사람이 Docker Desktop 을 켜고 `docker compose up -d --build` → `/health` 200 을 잰다) |
| DEF-QA3-002 | 경미 | 개발1 | **해소(실측)** — `s(v, label)` NUL 검사 · 4 경로 모두 항목 이름 |
| DEF-QA3-003 | 경미 | 아키텍트(W4) | **열림 · D-524 등재(가설)** — W4 에서 앱 역할 분리 · 테스트 픽스처 변경. 그때 다시 잰다(`rolsuper = f` · `session_replication_role` 우회 불가 · 테스트 정리 통과) |

새 결함 0. G-16 · G-17 · G-18 FAIL 은 W3/W4 미구현이라 결함이 아니다(판정 대상이 없다).

### 6.4 하지 않은 것
- `make gate-full` · `tools/gate.py` · 시드 멱등(`--run-seeds`) — 다른 QA 와 DB 를 같이 쓰므로 돌리지 않았다(오케스트레이터 몫).
- E2E 캡처(`--e2e`)는 다시 찍지 않았다 — 이번 수정(NUL 라벨 · HOME-030 422)은 §3 의 화면 5 개 캡처와 무관하다. `outputs/e2e/` 는 처음 보고 그대로다.
- Docker 실기동(G-24) — D-525.
