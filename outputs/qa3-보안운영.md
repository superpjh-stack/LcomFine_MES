# QA3 보안 · 운영 — W1 (2026-10-21)

검증만 했다. 코드는 고치지 않았다. 계정은 부서 8 의 **임시 계정**(접두 `q3…` · 난수 비밀번호 · 이름 `(예시)`)을 만들어 쓰고 끝나면 지웠다(남은 행 0 — `select count(*) from sys_user where login_id like 'q3%'` = 0). 시드 계정 8(sl pr sh ds ac st ex admin)은 로그인 확인(G-21)과 E2E 캡처에만 썼다. 시드 계정의 상태는 바꾸지 않았다. 상태를 바꾸면 `session_epoch` 트리거가 같은 DB 를 쓰는 QA1 · QA2 · 개발 테스트의 세션까지 끊는다. 측정 시점에 sl · sh 의 `session_epoch` 가 이미 20 · 40 이었다. 권한은 부서 단위(`sys_permission`)로 판정하므로 임시 계정으로 해도 시드 계정과 결과가 같다.

## 1. 결함

| ID | 심각도 | 담당 | 요약 | 재검증 |
|---|---|---|---|---|
| DEF-QA3-001 | **중대** | 아키텍트 (Dockerfile) | Dockerfile 이 지워진 `tools/sample_data.py` 를 COPY 한다. 그래서 이미지 빌드가 실패하고 G-24 는 통과할 수 없다 | **해소(실측)** — COPY 원본 7 전부 있음(§6) |
| DEF-QA3-002 | 경미 | 개발1 (bas · wo · sys) | NUL 이 든 입력의 422 가 어느 항목인지 짚지 않는다(`fields=[{"name":"입력"}]`) | **해소(실측)** — 4 경로 모두 항목 이름을 짚음(§6) |
| DEF-QA3-003 | 경미 | 아키텍트 (DB 역할) · 참고 개발2 · 개발3 (테스트 정리) | 앱이 superuser 로 DB 에 붙는다. 불변 이력 트리거를 `session_replication_role` 로 우회할 수 있고, 테스트 정리 코드가 이 우회에 기대고 있다 | **D-524 등재(가설) · W4** 에서 앱 역할 분리 — W1~W3 은 그대로. 열림 |
| DEF-QA3-004 | 경미 | 개발3 (`routers/col.py` `_xlsx`) | **W2** — COL-040 엑셀 내려받기가 저장된 `=…` 글자(DDE · HYPERLINK)를 수식 셀로 쓴다 → 여는 사람의 엑셀에서 실행될 수 있다(§7) | **해소(실측)** — `_xlsx_text_cell` 로 글자 셀 `data_type="s"` 고정 · X-07 PASS 수식 셀 0(§7.1) |

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

## 7. W2 수금 (2026-10-22)

검증만 했다. 앱 코드는 고치지 않았다. 고친 것은 내 소유 `tools/check_security.py` · `tests/test_qa3_col.py`(새) · `outputs/e2e/` · 이 보고서뿐이다. 임시 계정(접두 `q3…`) · 거래처 · ERP 코드 · 파일 이름은 전부 내 접두이고 끝에 지웠다 — `sys_user` · `erp_upload_batch`(created_by / source_file) · `erp_customer_map` · `customer` 의 `q3%` 전부 **0**. **열 매핑(`erp_column_map`)은 바꾸지 않았다** — 지금 저장된 매핑(시드 7 · 거래처코드 · 일자 · 매출액 · 수금액 · 잔액 · 수단 · 어음 만기)의 열 이름으로 `(예시)` xlsx 를 openpyxl 로 만들어 올렸다(저장소에 바이너리 없음). 업로드 회차의 기준 기간은 1985년(개발3 테스트 1990~1993 · QA2 는 자기 접두)이다. QA1 이 같은 DB 에서 동시에 돌았다. Docker 는 켜지 않았다(D-525).

### 7.1 결함
| ID | 등급 | 담당 | 한 줄 | 상태 |
|---|---|---|---|---|
| DEF-QA3-004 | 경미 | 개발3 (`src/lcomfine/app/routers/col.py` `_xlsx` · F-COL-041) | COL-040 `?format=xlsx` 가 업로드 행에 저장된 `=CMD\|…` · `=HYPERLINK(…)` 글자를 **수식 셀**로 써서 내려준다 | **해소(실측)** 2026-10-22 |

새 결함 1(경미) → 재검증 뒤 **해소**. 남은 것: W1 의 DEF-QA3-003(D-524 · W4)만 열림. 치명 0 · 중대 0.

#### DEF-QA3-004 · 경미 · 수금 현황 엑셀 내려받기의 수식 주입 (CSV/Formula injection)
- 재현(검사기 `check_col_upload_abuse` X-07 · 테스트 `tests/test_qa3_col.py::test_collections_xlsx_export_has_no_live_formula_cells`): 회계부 임시 계정으로 ① `POST /col/customer-map` 에 ERP 코드 `{접두}M` ↔ 임시 거래처 ② 수단 셀이 `=CMD|' /C calc'!A0` · `=HYPERLINK("http://evil.example/q3","클릭")` 인 **글자 셀**(ERP 가 값으로 내려준 꼴 · openpyxl `data_type="s"`)을 가진 xlsx 를 `POST /col/uploads action=apply` 로 반영(200 · 행 6 · 오류 1 = 미매핑 코드 행만) ③ `GET /col/collections?date_from=1985-03-01&date_to=1985-03-31&customer=<id>&format=xlsx`(200 · `application/vnd.openxmlformats-…sheet`) 를 openpyxl 로 다시 열면 **수단 열 `H2` · `H3` 가 `data_type == "f"`(수식 셀)** 이다.
- 원인: `col.py:461~468 _xlsx()` 가 `ws.append([...])` 로 값을 넣는데 openpyxl 은 `=` 로 시작하는 글자를 수식으로 쓴다. 업로드 쪽(`erp_upload._sheet` · `data_only=True`)은 값만 읽어 저장하고 화면은 autoescape 로 안전하지만(X-06 PASS), **내려받기에서 글자가 수식으로 되살아난다**. 엑셀은 DDE(`=CMD|…`) 에 경고를 띄우고 보호 보기로 열지만 사용자가 「허용」하면 실행되고, `=HYPERLINK` 는 경고 없이 클릭 가능한 링크가 된다.
- 기대: api-contract · CLAUDE.md 「조용한 실패 금지」 · 정본 COL-040 「엑셀」 = 화면과 같은 값. 내려받는 셀은 화면과 같은 **글자**여야 한다(수식 셀 0).
- 경로: 공격자는 ERP 수금현황 파일의 셀 값을 넣을 수 있어야 한다(ERP 거래처명 · 수단 등은 ERP 에서 온다). 그래서 **경미**. 다만 수단 열은 어떤 글자든 받아 저장하므로(`parsed.method = text[:200]`) ERP 쪽 입력이 곧 MES 내려받기에 실린다.
- 담당 개발3 참고(고치는 쪽의 선택 · QA 는 고치지 않는다): `_xlsx` 에서 글자 셀은 `cell.data_type = "s"` 로 고정하거나(openpyxl 은 `ws.cell(...).value = v; cell.data_type = "s"`), `=` `+` `-` `@` 로 시작하는 글자 앞에 `'` 를 붙인다. 고치면 검사기 X-07 과 위 테스트가 그대로 PASS 를 잰다.
- **재검증(2026-10-22)**: 개발3 이 `col.py:461 _xlsx_text_cell(ws, row_no, col_no, value)` 로 글자 셀을 `data_type="s"` 로 고정했다(머리 행 포함 · `_xlsx` 가 셀마다 부른다). 같은 재현(DDE · HYPERLINK 글자 셀 업로드 → `GET /col/collections?…&format=xlsx` → openpyxl 로 다시 열기)을 임시 계정으로 다시 돌렸다 → **수식 셀 0**(`data_type == "f"` 인 셀 없음 · `H2` · `H3` 가 글자 셀). 검사기 X-07 PASS · `test_collections_xlsx_export_has_no_live_formula_cells` PASS. **해소(실측).**

### 7.2 G-19 · G-20 · G-22 실측 (`uv run python tools/check_security.py` · 2026-10-22)
| 행 | 판정 | 실측 |
|---|---|---|
| G-19 쓰기 라우트 require_fn | PASS | POST **62**(W1 58 + COL 4) · GET 58 중 빠짐 0 |
| G-19 세션 없음 401 | PASS | 쓰기 POST 62 · 화면 GET 67×2 중 어긋남 0 |
| G-19 R·없음 부서 쓰기 403(전수) | PASS | 쓰기 기능 62 × 부서 8 — 403 기대 361 · 통과 기대 135 · 어긋남 0 |
| G-19 칸 밖 화면 GET 403 · 메뉴 숨김(전수) | PASS | 화면 67 + 하위 조회·출력 2 × 부서 8 = GET 552 · 어긋남 0 |
| **G-19 COL 화면 7 × 부서 8** (새) | PASS | 200 기대 30 · 403 기대 26 · 어긋남 0 · **R 칸(영업부 COL-010 · COL-030)에 쓰기 폼(multipart · 열 매핑 · erp_code) 없음** |
| **G-19 COL 쓰기 4 × 부서 8** (새) | PASS | F-COL-011 · 031 · 032 · 033 × 8 — 403 기대 24(SL R · PR · SH · DS · ST · EX) · 통과 기대 8(AC · ADM → 빈 본문 422/404) · 어긋남 0 |
| G-20 세션 8행(W1) | PASS | 중지 · 잠금 · 비활성 · 부서 변경 · 로그아웃 쿠키 · 비밀번호 · epoch · 삭제 · 서명 — 전부 기대대로 |
| **G-20 COL 비활성 · 로그아웃 → 401** (새) | PASS | AC 전 200 · 비활성(F-SYS-013) 200 → COL-040 GET **401** · 매핑 POST **401** / 다른 AC 전 200 · 로그아웃 → COL-010 GET **401** · 업로드 POST **401** |
| G-22 쓰기 성공 → 1행(W1 표본) | PASS | 표본 15(모듈 5) · 어긋남 0 |
| **G-22 COL 쓰기 성공 → sys_change_log 1행** (새) | PASS | 표본 **8**(기능 4): 열 매핑 저장(같은 값 · 매핑 불변) · 업로드 apply 1회차(행 3 · 오류 3 · **AC 알림 1행**) · apply 2회차(행 4 · 오류 4 · 1회차 `교체` + `replaced_by`) · 매핑 등록(참조 있음 → 재해석 · 2회차 error_count 1 = 날짜 오류 행만) · 매핑 등록(참조 없음) · 매핑 수정 · 삭제(참조 → `use_yn=N`) · 삭제(참조 없음 → 행 삭제) — 각각 **정확히 1행** · function_id · screen_id(COL-010/COL-030) · method POST · path · target(`erp_upload_batch:<회차>` · `erp_customer_map:<코드>` · `erp_column_map:*`) 일치 |
| **G-22 COL preview · 422 · 403 · 404 → 0행** (새) | PASS | 표본 10 — preview JSON 200 · preview HTML 200 · 파일 없음 422 · 텍스트 파일 422 · 헤더만 422 · map 필수 빠짐 422 · 매핑 중복(사용 중지 코드) 422 · 수정 없는 id 404 · SL apply 403 · SL 매핑 403 — 로그 0행 · **회차/행/알림 수 불변** · 열 매핑 불변 |
| **G-22 COL 변경 로그 SYS-040** (새) | PASS | 8/8 이 `GET /sys/logs?tab=change&login=<AC>` 에 보임 |
| G-22 정적 POST 마다 log_change | PASS | POST 62 중 없음 0 |

### 7.3 G-21
| 행 | 판정 | 실측 |
|---|---|---|
| 비밀 스캔 | PASS | 파일 **221**(`git ls-files -co --exclude-standard` — 미추적 새 파일 `erp_upload.py` · `routers/col.py` · `templates/col/*` · `seed_dev3.py` · `test_dev3_col.py` · `test_qa2_col.py` · `test_qa3_col.py` 포함) · 비밀 값 0 · 키 패턴 0 · `.env` gitignore · 미추적 |
| 시드 (예시) | PASS | 시드 계정 8 · 채번 7 전부 `(예시)` |
| 응답에 비밀 없음 · 시드 로그인 8/8 | PASS | — |
| **seed_dev3 멱등 · (예시) (정적 · 새)** | PASS | `src/lcomfine/db/seed_dev3.py`: `insert … on conflict (field) do nothing` · delete/truncate 없음 · `created_by='seed'` · DB 의 `erp_column_map(created_by=seed)` **7행**. 열 이름(거래처코드 · 일자 · …)에는 `(예시)` 가 **없다** — 엑셀 열 이름과 글자 그대로 맞추는 매핑 키라 붙이면 매핑이 깨지고, 값은 정본 COL-010 문장의 낱말을 베낀 것이라 D-802 에 적혀 있다(모듈 docstring 에 `(예시)`). 결함으로 올리지 않는다. **2회 실행 diff 0 실측은 돌리지 않았다** — 오케스트레이터의 `make gate-full`(gate.py `--run-seeds`) 몫 |

### 7.4 업로드 보안 · 조용한 실패 사냥 (X-행)
| 행 | 판정 | 실측 |
|---|---|---|
| X-01 · X-02 DB 끊김 | PASS | `/health` 503 · 화면 · 메인 · 쓰기 · 로그인 503 + **COL 업로드 POST(multipart) 503 · COL 화면 GET 503**(새) · 접속 문자열 노출 0 |
| X-03 · X-04 이상한 입력(W1) | PASS | POST 26 · GET 8 · 500 0 |
| **X-05 업로드 파일 수준** (새) | PASS | 텍스트(csv) · HTML · zip(엑셀 아님) · **0 바이트** · PNG 머리 · **20MB+1** · 헤더만 · **열 이름 중복** · 1행(열 이름) 비어 있음 · `__row_no` 열 · 매핑된 열이 파일에 없음 — **11 전부 422**(`fields[].name` = 파일 / 거래처코드) · 기준 기간 NUL · 99999년 · 동작 NUL → 422 · **500 = 0** |
| **X-06 셀 내용** (새) | PASS | 행 6: 거래처코드 `<script>alert(1)</script>`(→ 미매핑 오류 행) · 수단 `=HYPERLINK(…)` · `=CMD\|' /C calc'!A0` · 10만 자 · `a_x0000_b` · `<img src=x onerror=…>` · 파일 이름 `../../../etc/{접두}<b>passwd</b>.xlsx` → apply 200 · DB 에 **글자 그대로**(raw = 원문 · parsed.method = 200자 · source_file = 올린 이름 그대로 · 디스크 경로로 쓰이지 않음) · 화면 5(COL-010 ?batch · COL-020 ?batch · COL-030 미매핑 목록 · COL-040 · HOME) 에 **이스케이프**(`&lt;script&gt;` · `&lt;img` · `&lt;b&gt;passwd`) · 원문 태그 · `href="http://evil…"` 0. 10만 자 셀은 엑셀 상한 **32,767자**로 파일에 담기고 raw 는 그 길이 그대로 |
| **X-07 내려받기 수식 주입** (새) | PASS(재검증) | 처음 **FAIL** — DEF-QA3-004 수식 셀 2(`H2` DDE · `H3` HYPERLINK) → 개발3 수정 뒤 **수식 셀 0** |
| **X-08 정적: 디스크 쓰기 없음** (새) | PASS | `erp_upload.py` · `routers/col.py` 의 `open(` · `.write(` · `Path(` · `os.` · `tempfile` **0** — `wb.save(buf)`(BytesIO) 만. 업로드 바이트는 메모리에서 읽고(`await file.read()`) DB `raw` jsonb 로만 간다 |

참고(결함 아님): ① **진짜 수식 셀**(`=1+1` · 캐시 값 없음)은 `data_only=True` 로 읽어 **빈 칸**이 된다(preview 로 확인 · parsed 에 수금액 없음 · error 없음 — 조용히 0 이 되지는 않지만 값이 사라진다. ERP 가 내려준 파일은 캐시 값이 있어 영향 없음. 수식만 있고 값이 없는 셀을 경고로 보일지는 개발3 판단). ② 20MB 상한은 **본문을 전부 읽은 뒤** 잰다(`_file_bytes` · 스트리밍 제한 없음) — 운영 리버스 프록시의 본문 상한이 전제. ③ 수금 행의 `method` 는 어떤 글자든 200자까지 저장한다 — 수단 코드 값은 받은 적이 없어 계약대로.

### 7.5 브라우저 한 바퀴 (E2E · `uv run --offline --with playwright python tools/check_security.py --e2e`)
도구: W1 과 같은 Playwright(chromium headless · `result.json` 에 적힌 방식) · 앱을 8020 에 하위 프로세스로 띄움 · 1280 · 390 두 폭 · `full_page` 캡처. **32/32 PASS**(W1 16 + W2 16) · status 200 · `scrollWidth ≤ innerWidth`(390 폭 가로 스크롤 **0**) · 로그인으로 튕김 0. `outputs/e2e/*.png` 32 + `result.json`(갱신 · `action` · `flash_seen` 열 추가).

회계부(`ac`)가 **실제로 폼으로** 올렸다: 열 매핑은 시드 그대로 두고, 그 열 이름의 `(예시)` xlsx(행 3 — `q3e2e-E` 2행 · 미매핑 `q3e2e-U` 1행)를 `input[name=file]` 에 넣고 기준 기간 1985-02-01~02-28 · 「반영」(data-confirm 승인) → 「회차 ERP-… 를 반영했습니다 — 3행 중 반영 0 · 오류·미매핑 3」 알림 · 오류 행 3 빨간색 · 미매핑 코드 2. 390 폭에서 다시 올려 **2회차 교체**도 화면에 남겼다.
| 캡처(1280 · 390) | 화면 | 본 것 |
|---|---|---|
| `ac_col_uploads-upload-apply-*` | COL-010 업로드(apply 뒤) | 반영 알림 · 반영 회차 1 · 오류 행 3(빨강) · 미매핑 2 · 열 매핑 7 |
| `ac_col_upload-history-*` | COL-020 | 회차 목록 · 390 에서 `교체됨` / `반영` 칩 |
| `ac_col_customer-map-map-create-1280` · `ac_col_customer-map-390` | COL-030 | 1280 에서 미매핑 `q3e2e-U` · `q3e2e-E` 목록 → `q3e2e-E` ↔ EX-C01 **등록**(폼) → 「다시 해석한 행 2 · 그중 반영 2」 · 목록에 사용 칩 · 참조 행 2 |
| `ac_col_collections-*` | COL-040 | 행 2 · 매출 1,000 · 수금 600 · 수단별 막대(인라인 SVG) · 어음 만기 |
| `ac_col_receivables-*` · `ac_col_aging-*` | COL-050 · 060 | 기준일 1985-02-28 · 미수 400 · 연령 구간(D-803 표기) |
| `ac_col_shipment-vs-collection-*` | COL-070 | 1984-09~1985-02 · 출하 0 ↔ ERP 1,000/600 |
| `sl_trk_customers-*` | TRK-030 수금 칸(영업부) | **1280**: 계정 순서(sl 가 ac 보다 먼저)라 매핑 전 — 「미수 잔액 **미수집** · 이 거래처에 매핑된 ERP 거래처코드가 없다」(계약대로 글자). **390**: 매핑 뒤 — 「미수 잔액 **400** · ERP 업로드 기준일 1985-02-28 · 매출 1,000 · 수금 600 · 마지막 거래일 1985-02-20」 |

눈으로 본 것: 390 폭의 COL-040 · TRK-030 표는 안쪽(`grid-wrap`) 가로 스크롤이고 문서 가로 스크롤은 0. 쓰기 성공 알림은 모달 「알림」 대화(`#popup-layer`)로 뜬다. 캡처 뒤 `q3e2e` 회차 · 행 · 알림 · 매핑을 지웠다(「남은 q3e2e 회차 0 · 매핑 0」). 시드 계정 `ac` 의 `sys_change_log` 행은 남는다(감사 로그는 지우지 않는다 — W1 과 같음).

### 7.6 명령 · 결과
| 명령 | 결과 |
|---|---|
| `uv run python tools/check_security.py` | 처음 **종료코드 4** = FAIL 4(G-16 · G-17 · G-18 W3/W4 미구현 + X-07 DEF-QA3-004) · PASS 48 → **재검증 종료코드 3** = FAIL 3(G-16 · G-17 · G-18 **W3/W4 미구현**만) · PASS **49**(W1 36 + W2 13) · WARN 0 · 10초 |
| `uv run pytest -q tests/test_qa3_*.py` | 처음 21 passed · 1 failed(`test_qa3_col.py::test_collections_xlsx_export_has_no_live_formula_cells` = DEF-QA3-004) → **재검증 22 passed · 0 failed** · 11.3초 — W1 14 + W2 8 |
| `uv run --offline --with playwright python tools/check_security.py --e2e` | 32/32 PASS · rc 0 |
| 정리 확인 `psql -h /tmp lcomfine_db` | `sys_user` · `erp_upload_batch` · `erp_customer_map` · `customer` 의 `q3%` 0 · `erp_column_map` 시드 7 그대로 |

### 7.7 하지 않은 것
- `make gate-full` · 시드 멱등 실측(`--run-seeds`) — 다른 QA 와 DB 를 같이 쓰므로 오케스트레이터 몫.
- Docker 실기동(G-24) — D-525. 정적 3행은 PASS.
- zip 폭탄 · 수백 MB 업로드 — 지시대로 하지 않았다(20MB+1 까지).
- G-16 · G-17 · G-18 — W3/W4.
