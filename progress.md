# 진행 상태 (v2 · 2026-10-21 정본 기준)

검증된 것만 적는다. 여기 없는 숫자는 화면에 지어내지 않는다. 형식: `| 항목 | 실측 | 검증 방법 |`.
옛 판(설계도 기준 · 대메뉴 12)의 기록은 `progress-v1.md` 에 있다 — v2 의 실측이 아니다.

## 최종 보고 (2026-10-22) — 루프 종료: goal.md §4.4 충족

W1 핵심 흐름 → W2 수금 → W3 대시보드 → W4 문서 SSO 를 모두 끝냈다. `make gate-full` 이 **PASS 21 · FAIL 0 · BLOCKED 1**(G-24 · D-525) · **제외 2**(G-16 · G-17 · D-529 데이터 질의 제거)이다.
QA 리포트 3종에 **치명 결함 0** · 열린 결함 0 이다. 남은 것은 사람이 정하거나 켜야 하는 `차단` 뿐이다(§4.4 「남은 것이 전부 차단 뿐이어도 멈춘다」).
완료 기준 「출하 1건에서 원자재 LOT 까지」는 화면(LOT-020) · `trace.backward` · QA2 독립 SQL 셋이 같은 사슬을 낸다(`outputs/qa2-흐름데이터.md` 맨 앞 · G-07).

### 게이트 판정표 (`make gate-full` · 2026-10-22 21:01 · 데이터 질의 제거 D-529 뒤)

| 게이트 | 판정 | 실측 |
|---|---|---|
| 빌드 전제 | PASS | pytest **404 passed · 0 failed**(gate-full 때 · 그 뒤 gate 판정 테스트 1 추가 → 405) · /health 200 |
| G-01 정본 ↔ nav | PASS | 묶음 8 · 대메뉴 17 · 화면 **66** · 흐름 7 · RPT 「대시보드」 · RPT-090~130 없음 |
| G-02 기능 ↔ 라우트 ↔ 표식 | PASS | 기능 **134/134**(GET 68 · POST 66) · 고아 0 · 오류 계약 어긋남 0 · 5xx 0 |
| G-03 화면 응답 | PASS | 칸 있는 257 → 200 · 칸 없는 271 → 403 · placeholder **0** |
| G-04 스키마 | PASS | 테이블 **46** · 뷰 **1**(v_work_order_status) |
| G-05 쓰기 경계 | PASS | 라우터 · 공용 모듈 쓰기 ⊆ 계약 · TRK · LOT · PRP · RPT 쓰기 0 |
| G-06 E2E 1건 | PASS | 의뢰 → 지시 → 입고 → 검사 → 불출 → 일보 → 제품 입고 → 판정 → 출하 지시 → 확정 (HTTP 만 · 부서 교대) |
| G-07 · G-08 역 · 정추적 | PASS | 화면 = trace = 독립 SQL · 분할 LOT 포함 · 완료 기준 사슬 |
| G-09 · G-10 차단 · 가용 | PASS | 검사대기 · 보류 LOT 불출/확정 422 · 가용 = 현재고 − 할당 · 동시 할당 초과 0 |
| G-11 알림 9종 | PASS | 수신 부서 · dedupe · 처리 화면에서 닫힘 · 사실이 사라지면 해소 |
| G-12 ~ G-14 수금 | PASS | 회차 교체 · 이전 회차 보존 · 오류 행 제외 · 미매핑 · 출하 대비 수금 = 독립 SQL |
| G-15 대시보드 8 | PASS | 함수 = 독립 SQL = 화면 표 = SVG title |
| G-16 · G-17 데이터 질의 · 키 없음 | **제외 (D-529)** | 기능을 없앴다 — 제외 근거: 옛 경로 GET · POST 404(부서 8) · 메뉴 · 대시보드 탭에 없음 · 기능 · 칸 0 · 로그 표 · 허용 뷰 · 채번 DQ 가 DB 에 없음 · 모듈 없음 · SYS-040 옛 탭 422 · AI 키 환경변수 · 바깥 호출 0 (근거 행 6 PASS) |
| G-18 SSO 토큰 | PASS | 서명 · 60초 만료 · 1회 사용 · 동시 사용 1 · 비활성 · 미매핑 거부 · 토큰 평문 hidden 1곳만 |
| G-19 · G-20 권한 · 세션 | PASS | 쓰기 66 × 부서 8 전수 · 비활성 · 로그아웃 다음 요청 401 |
| G-21 비밀 · 시드 멱등 | PASS | 비밀 값 0 · 시드 재실행 행 수 diff 0 |
| G-22 변경 감사 로그 | PASS | 쓰기 성공마다 1행 · 실패 0행 |
| G-23 백업 · 복구 | PASS | 테이블 46 전부 복구 · 행 220,585 일치 |
| G-24 Docker · health | **BLOCKED (D-525)** | compose 두 벌 config 성립 · 앱은 최소 권한 역할(D-524) · 실기동은 Docker 데몬이 꺼져 있어 못 쟀다 |

### 사람이 정할 것 — 정해지면 바뀌는 것

| 결정 | 모르는 것 | 정해지면 바뀌는 것 |
|---|---|---|
| **D-525** Docker 실기동 | Docker Desktop 이 꺼져 있다 | 켜고 `docker compose up -d --build` → `curl -s localhost:8020/health` 200 이면 G-24 PASS(로컬 앱이 8020 을 쓰면 먼저 내리거나 `LCOMFINE_HOST_PORT` 변경) |
| **D-509** 채번 6종 형식 | 현업 번호 규칙 | `sys_number_rule` 6행 데이터만(코드 변경 없음) |
| **D-516** ERP 수금 엑셀 열 | 열 이름 · 매출액 · 잔액 열 유무 | `erp_upload.py` 필수 열 목록 · 시드 매핑 한 벌 — 그동안 COL-010 열 매핑 화면이 흡수 |
| **D-517** 문서관리 SSO | 주소 · 방식(SAML/OIDC/서명 토큰) · 사번 동일 여부 | `.env` 에 `LCOMFINE_DOC_SSO_URL` 을 넣으면 DOC-010 이 바로 동작 · 방식이 SAML/OIDC 면 `sso.py` 한 곳 · 사번 동일이면 DOC-020 매핑 생략 |
| **D-518** 알림 메일 · 메신저 | 서버 · 종류 | `notify` 에 발송 수단 · HOME-030 칸 저장 |
| **D-519** 표준 · 예외제품 적용 · 로스율 산식 | FINE_MES 규칙 · 산식 | PRD-040 · INS-040 · RPT-020 · 030 의 `미확정 (D-519)` 자리에 수치 · STD-020 · 060 적용 |
| **D-520** 병목 기준일 · 배치 시각 | RPT-070 기준일 · due-check 시각 | RPT-070 병목 칸 · 배치 스케줄 등록 |
| **D-526** HOME-030 「개인 추가 알림」 | 정본 문장과 부서 단위 알림의 모순 | F-HOME-031 계약 한 행 · `notify.unread` 필터 |
| 가설 확인 | D-501~D-526 의 `가설` · 개발 D-601~611 · D-701~704 · D-801~806 | 대장에 산식 · 형식이 적혀 있고, 바뀌면 한 곳(`stats` · `dashboard` · `numbering` 데이터)만 고친다 |

### 실 LOT 검증 절차 (현업 데이터로 한 번 더)
1. 실제 원자재 입고 1건을 MAT-010 에 넣는다(공급사 LOT 번호 그대로) → QC-010 입고검사 합격 → MAT-020 불출(실제 지시번호).
2. PRD-010 · INS-010 일보 → MAT-030 제품 입고 → QC-020 판정 → SHP-010 출하 지시 → SHP-020 확정.
3. LOT-020 에 그 출하 번호를 넣어 원자재 LOT · 공급사 LOT 이 현장 기록(입고 전표 · 라벨)과 같은지 본다. LOT-010 에 원자재 LOT 을 넣어 정방향도 본다.
4. 같은 출하로 `uv run python tools/check_data.py` 의 G-07 독립 SQL 대조가 PASS 인지 확인한다(검사기는 자기 `QA2-` 세계를 만들고 지우므로 현업 행을 건드리지 않는다).

### VPS 재배포 절차 (push · 배포는 사람이 한다 — 루프는 하지 않았다)
1. 서버에서 `.env` 를 만든다(`make setup` 이 비밀 6개를 난수로 채운다: 세션 · 시드 비밀번호 · DB 소유자 · **앱 DB 역할(`LCOMFINE_APP_DB_PASSWORD` · D-524)** · SSO 비밀). SSO 주소는 사람이 넣는다.
2. `docker compose up -d --build` — `seed` 서비스가 빈 DB 면 스키마 → 시드 → 앱 역할 `lcomfine_app` 생성(superuser 아님 · 불변 이력 INSERT 만)을 하고 끝나며, `app` 은 그 역할로 붙는다. Hostinger 류는 `deploy/hostinger/docker-compose.yml`(같은 구조).
3. `curl -s <호스트>:8020/health` 200 · 로그인 · `make gate` 상당의 확인은 로컬에서.
4. 백업은 `docker compose run --rm seed /app/.venv/bin/python tools/backup.py backup` · 복구 검사는 같은 방식의 `restore-check`(createdb 는 소유자 역할에만 있다).
5. 이미 데이터가 있는 DB 의 스키마 변경은 ALTER 이관으로 하고 `schema.sql` 과 맞춘다.

## 2026-10-23 업무별 유스케이스 (D-530 · 아키텍트)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 페이지 | `/guide/usecases` 「업무별 유스케이스」 — 공통 참고 페이지(`main.py` · `/ia` 방식 · nav 66 · 기능 134 · 칸 257 그대로) · 로그인 200 · 미로그인 303 · 상단 바 「내 할 일 · 대시보드 · 업무별 유스케이스」(8 부서 · 디자인·개발실은 대시보드 없이) | `tests/test_arch_usecases.py` 15 passed |
| 내용 | 유스케이스 10 · 단계 39 · 알림 9종 전부 등장 · 스윔레인(인라인 SVG) 10 · 흐름 지도 · 유스케이스 × 부서 표. 정의는 `app/usecases.py` 한 곳 — 이름 · 경로 = nav, 하는 부서 = W 칸, 알림 수신 = `notify.EVENTS` | 테스트가 기능 ↔ 화면 · W 칸 ↔ permission-matrix · emit 위치 · 알림 link 화면 · 422 문장을 소스에서 대조 |
| 읽기만 | 열기 전후 public 표 전부 행 수 같음 | `test_page_writes_no_business_rows` |
| 화면 | 1280(admin · sl · pr) · 390(admin) · 다크 — 가로 스크롤 0(scrollWidth = 뷰포트 · 그림은 상자 안에서만 민다 · 390 단계 표는 세로 카드) | Playwright 캡처 `scratchpad/ui/usecases/` |
| 게이트 | `uv run pytest -q` 420 passed · `make gate` PASS 20 · 제외 2 · BLOCKED 1(D-525) · 미검증 1(G-23 — gate-full 몫) | 2026-10-23 00:23 |

## 2026-10-22 데이터 질의 제거 (D-529 · 아키텍트)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 기획서 반영 | `contracts/ia-overrides.json` `remove_screens` 에 `RPT-130: D-529`(정본 HTML 은 그대로) → 정본 추출 화면 67 → **66** · 권한 칸 260 → **257**(W 64 · R 196 → 193 / 528) · 기능 136 → **134**(쓰기 67 → 66 · 읽기 69 → 68) | `uv run python tools/gen_function_list.py --summary` · `make check-trace` |
| 지운 것 | `app/ai.py` · `app/dataquery.py` · `templates/rpt/query.html` · `rpt.py` 질의 GET/POST · SYS-040 「AI 호출」 · 「데이터 질의」 탭(탭 6 → 4) · `numbering` `DQ`(채번 7 → 6) · settings · `.env.example` · `docker-compose.yml` 의 OpenAI 환경변수 | `grep` 0(제거 확인 검사 · 결정 기록 제외) · 개발 서버 `/rpt/query` 404 · SYS-040 탭 4 |
| 스키마 | `data_query_log` · `sys_ai_call_log` · `v_dq_*` 8 을 `schema.sql` 과 DB 에서 DROP(한 트랜잭션 · 전에 `make backup` 한 벌 `backups/lcomfine_db-20261022-193729.dump`) · `roles.APPEND_ONLY` 6 → 4 · 시드가 RPT-130 칸 3행 · DQ 채번 행을 지운다 | `make check-schema` PASS(테이블 46 · 뷰 1) · `sys_permission` 257 |
| 게이트 | `gate.py` 새 상태 「제외」 — `EXCLUDED_GATES` 의 게이트는 decisions.md 에 그 D-번호가 `확정` 이고 근거 행이 전부 PASS 일 때만 제외(아니면 FAIL · 근거 없으면 미검증) · 종료코드에 세지 않고 요약에 「제외 n」 | `make gate-full` PASS 21 · 제외 2 · BLOCKED 1 · FAIL 0 · `tests/test_arch_gate.py` |
| 검사기 · 테스트 | check_security 의 G-16 · G-17 검사 → 제외 근거 6 행 · check_screens · check_data 의 질의 · `v_dq_*` 사용 → 업무 표 직접 SQL · 질의 기능 테스트는 「없어졌음(404 · 메뉴 · 모듈 · 표 없음)」 테스트로 | `uv run pytest -q` 405 passed |

## 2026-10-22 샘플 데이터 (`tools/sample_data.py`)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 넣은 것 | 거래처 100 · 품목 100(원자재 50 · 제품 50) · 생산의뢰 100 → 지시 92 · 원자재 LOT 144 · 제품 LOT 94 · 출하 99(확정 83) (2026-10-22 재삽입 · 품목 · 거래처 SMP- 기준 psql) · ERP 수금 행 100(6 회차 · 오류 3 · 미매핑 3) — 이름 전부 `(예시)` · 코드 `SMP-` | `psql` 행 수 · 실행 출력 |
| 넣는 방법 | 앱 HTTP 로 부서 계정을 교대하며(1,524 요청 · 15초) — 채번 · 재고 · 알림 · 감사 로그가 계약대로 · 불변 이력 0 행 | `uv run python tools/sample_data.py` (`--count N` · `--clean`) |
| 넣은 뒤 | 전 DB 출하 역추적 104 · 정방향 135 = 독립 SQL 불일치 0 · `make gate` PASS 22 · BLOCKED 1 · 미검증 1(G-23 은 gate-full) | `uv run python tools/check_data.py` (rc 0) · `make gate` |
| 검사기 손질 | `check_data.py` 의 「SHP-010 LOT 목록에 없음」 두 검사가 페이지 전체에서 `value="id"` 를 찾아 거래처 선택지 숫자와 겹치면 거짓 판정 → LOT 선택 칸 안에서만 찾게(`stock_listed`) | `tests/test_qa2_*.py` 45 passed |
| 시각 맞추기 · 납기 | HTTP 로 넣은 뒤 `SMP-` 행의 시스템 시각(등록 · 판정 · 재고 이동 · 출하 확정 · 알림 · ERP 업로드)을 업무 날짜에 맞춰 과거로(한 트랜잭션 · 검산 10). `plan()` 납기는 그 확정 규칙과 짝(정시 = 납기 − 0~10일에 확정 · 지연 = 납기 ≤ 제품 입고일) — 다시 넣은 뒤 RPT-070 단계 평균 0.9 · 5.4 · 1.0 · 11.7 · 의뢰 → 출하 19.0일(최대 39) · RPT-050 납기 안 완료 50 · 지연 완료 5 · 지연 12 · 준수율 74.6% · 확정 출하 5~10월 16 · 20 · 11 · 11 · 11 · 14 | `uv run python tools/sample_data.py` (끝에 retime 자동 · `--retime` 단독) · `tools/check_data.py` rc 0 · pytest 통과 |
| 로그인 | 로컬 개발용 — 시드 계정 8 의 비밀번호를 `.env` 의 `LCOMFINE_SEED_PASSWORD` 로 맞췄다(값은 `.env` 에만 · `admin` 으로 로그인) | `uv run python tools/reset_passwords.py` |

## 2026-10-22 VPS 배포 (v2 · 새 앱)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 코드 | `main` 51 커밋 빨리감기 push → Actions `image` 성공 → `ghcr.io/superpjh-stack/lcomfine_mes:sha-6c7aae6…` · `latest` | `gh run view 39795900843` |
| 앱 | Hostinger Docker Manager 새 앱 `lcomfine-mes-v2` · 포트 **8041** · 새 DB 볼륨 · 앱은 최소 권한 역할(D-524) · 이미지 커밋 고정 · 기존 `lcomfine-mes`(v1 · 8040)와 그 DB 는 손대지 않음 | hPanel |
| 동작 | `/health` 200 (`screens 66 · placeholders 0 · db ok`) · `admin` 로그인 303 · HOME · WO-010 · RPT-080 · LOT-020 · COL-010 · DOC-010 200 · `/rpt/query` 404 · 상단 대시보드 메뉴 · v1 8040 200 그대로 | `curl http://187.52.127.215:8041/health` |
| 비밀 | 환경 칸은 사람이 넣었다(DB 소유자 · 앱 역할 · 세션 · SSO · 시드 비밀번호 · 포트) — 값은 저장소에 없다 | hPanel 「환경」 |
| 데이터 | 시드만(부서 8 · 계정 8 · 권한 257 · 채번 6 · `(예시)` 기준정보). 샘플 100건은 넣지 않았다 | `tools/docker_init.py` |
| 재배포 2026-10-23 | 업무별 유스케이스(D-530) — hPanel yaml 의 이미지 태그만 `sha-e0a2d68…` 로 바꿔 재배포(환경 · DB 볼륨 그대로) · `/guide/usecases` 200 · 유스케이스 10 · 상단 바 3 메뉴 · `/health` 200 · v1 8040 그대로 | `curl http://187.52.127.215:8041/guide/usecases` (로그인) |

## 2026-10-22 W4 문서 SSO 실측 (개발1 · 아키텍트 → QA 3 → 결함 수정 → gate-full)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| W4 화면 · 기능 | DOC-010 · DOC-020 · 기능 6 → 라우트 · 표식 **136/136** · placeholder **0** | `make check-trace` · `make check-routes` |
| SSO (G-18) | 발급 → 1회 사용 · 재사용 거부 · +60초 만료 · 변조 20종 거부 · 동시 사용 하나만 · 비활성 즉시 거부(받은 토큰도) · 미매핑 「관리자에게 계정 연결을 요청하세요」 · 주소 · 비밀 없음 422 `미확정 (D-517)` · SSO 로그 호출마다 1행 · 토큰 평문 hidden 1곳만(헤더 · URL · 쿠키 · JSON · 48 표 · 서버 로그 0) | `make check-security` G-18 (검사 16) · `tests/test_qa3_doc.py` · `tests/test_dev1_doc.py` |
| 메뉴 동작 | 좌측 메뉴 DOC-010 = 새 창(`target="_blank"`) → 준비됐으면 자동 POST(`app.js` `data-auto-submit`) → 문서관리 · 준비 안 됐으면 안내만 | `tests/test_qa1_doc.py` · DEF-QA1-010 |
| 앱 DB 역할 (D-524) | `lcomfine_app` — superuser · 소유자 · DDL 아님 · 불변 이력 · 감사 로그 6 표 UPDATE/DELETE/TRUNCATE 거부 24/24 · 권한 상승 시도 15 거부 · compose 두 벌 `app` = 앱 역할 · `seed` = 소유자 | `tests/test_arch_roles.py` · `make check-security` X-11 · G-24 정적 |
| QA 리포트 | 「W4」 절 3종 — QA1 결함 1 · QA2 0 · QA3 2(+ 003 해소) · 전부 해소 · 치명 0 · E2E 캡처 **54** | `outputs/qa{1,2,3}-*.md` · `outputs/e2e/` |
| pytest | **449 passed · 0 failed** | `uv run pytest -q` |
| 게이트 | **PASS 23 · FAIL 0 · BLOCKED 1**(G-24 D-525) · gate-full 종료코드 0 | `make gate-full` |
| 커밋 | `W4 문서 SSO 끝 · 루프 종료: …` (이 커밋) | `git log --oneline -1` |

## 2026-10-22 W3 대시보드 실측 (개발3 · 개발1 → QA 3 → 결함 수정 → gate-full)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| W3 화면 · 기능 | RPT 9 화면(대시보드 8 + 데이터 질의) · 기능 10 → 라우트 · 표식 **130/136** · placeholder **2**(DOC) · SYS-040 로그 탭 6(접속 · 변경 · ERP 업로드 · AI 호출 · 데이터 질의 · SSO) | `make check-trace` · `make check-routes` |
| 대시보드 8 수치 (G-15) | 8 화면마다 `dashboard.<함수>` 반환 = QA2 독립 SQL = 화면 KPI 글자 = SVG `<title>` = 표 · 어긋남 0 · 0건은 `미수집` · 로스율 `미확정 (D-519)` · 병목 `미확정 (D-520)` · RPT-060 · 070 에 ERP 업로드 기준일 · 거래처 필터는 010 · 050 · 060 · 070 · 080 만 · 화면 GET 전후 업무 테이블 diff 0(캐시 없음) | `tools/check_data.py` G-15 (검사 11) · `tests/test_qa2_rpt.py` |
| 데이터 질의 (G-16) | 우회 54건(쓰기 · 다중 문장 · 주석 · 허용 밖 뷰 · 카탈로그 · 함수 · CTE · NUL · 유니코드 공백 등) 전부 422 「허용되지 않는 질의 — 이유」 + 질의 로그 1행 · 실행 0 · 읽기 전용 연결 · statement_timeout 5s · 행 상한 200 · 수금 뷰는 SL · AC · ADM · EX 만 | `make check-security` G-16 (검사 7) · `tests/test_qa3_rpt.py` |
| 키 없음 (G-17) | 키 없는 하위 프로세스에서 RPT-130 → 422 「AI 키가 설정되지 않았습니다 — LCOMFINE_OPENAI_API_KEY」 화면에 그대로 · AI 호출 로그 1행 · 하드코딩 결과 0 · 호출 실패 문장에서도 키 글자 가림 | `make check-security` G-17 (검사 5) |
| 권한 · 감사 | RPT 9 × 8 계정 200/403 전수 · F-RPT-132 칸 없는 5 부서 403(권한 예외 = 칸 없으면 403) · 성공 질의 변경 로그 1행 · 거부 0행 · 오류 계약 사례 240 어긋남 0 · 5xx 0 | `tools/check_screens.py`(rc 0) · `make check-security` G-19 · G-22 |
| 실제 OpenAI 호출 | QA · 테스트 0회(fake 주입 · urlopen 차단) | QA3 보고서 §8 |
| QA 리포트 | 「W3」 절 3종 — QA1 결함 3 · QA2 결함 1 · QA3 결함 3 · 전부 해소 · **치명 0** · 열림 1 = DEF-QA3-003(경미 · D-524 · W4) · E2E 캡처 **50** | `outputs/qa{1,2,3}-*.md` · `outputs/e2e/` |
| 계약 · 결정 | `interfaces.md` §9(dashboard · ai · dataquery) · `api-contract.md` §2 예외 2(F-RPT-132 브라우저 200 · RPT 422 재렌더 · Ruling 28) · F-RPT-071 기준일 명시(Ruling 29) · nav 묶음 설명 「대시보드」 · D-609 · D-805 · D-806 | `contracts/` · `decisions.md` |
| pytest | **402 passed · 0 failed** | `uv run pytest -q` |
| 시드 멱등 · 백업 | 시드 재실행 diff 0 · 백업 → 복구 테이블 48 · 행 83,998 일치 | `make gate-full` G-21 · G-23 |
| 게이트 판정표 | **PASS 20 · FAIL 3 · BLOCKED 1** / 24 — W1~W3 범위 전부 PASS. FAIL 3 = G-02 · 03(DOC 몫) · G-18(W4) · BLOCKED G-24(D-525). gate-full 종료코드 3 | `make gate-full` |
| 커밋 | `W3 대시보드 끝: …` (이 커밋) | `git log --oneline -1` |

알아둘 것(W3): QA 와 개발을 같은 DB 에서 동시에 돌리면 전 DB 집계 대조가 흔들린다 — QA2 는 REPEATABLE READ 한 트랜잭션에서 함수 · 독립 SQL · 화면을 같은 순간에 읽어 풀었다. 결함 테스트는 xfail 로 가리지 않고 실패 상태로 둔다. 테스트에 가짜 키를 쓸 때는 글자를 실행 때 합친다(비밀 스캔).

## 2026-10-22 W2 수금 실측 (개발3 · 개발1 → QA 3 → 결함 수정 → gate-full)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| W2 화면 · 기능 | COL 7 화면 · 기능 11 등록 → 라우트 · 표식 **120/136** · placeholder **11**(RPT 9 · DOC 2 = W3/W4) · 쓰기 4(`POST /col/uploads` · `/col/customer-map` · `/{id}` · `/{id}/delete`) — 수금 금액을 고치는 엔드포인트 없음 | `make check-trace` · `make check-routes` · `tools/check_data.py` G-12 정적 |
| 회차 교체 (G-12) | 같은 기간 재업로드 → 새 회차 `반영` · 이전 `교체` + `replaced_by` · 이전 행 보존 · 기간마다 반영 1 · `v_dq_collections` 는 반영 회차만 | `tools/check_data.py` G-12 (검사 4) |
| 오류 행 · 미매핑 (G-13) | 날짜 · 금액 · 누락 · 미매핑 행이 `error` + 원문으로 보존 · 반영 · COL-040 · COL-050 에서 제외 · COL-030 미매핑 목록 → 매핑 뒤 반영 회차만 재해석(「다시 해석 N · 그중 반영 M」) · `erp_upload_row` 쓰기 = parsed · error 만 | `tools/check_data.py` G-13 (검사 5) |
| 출하 대비 수금 (G-14) | COL-070 = QA2 독립 SQL(확정 출하 월 × 반영 회차 매핑 행 월) · 매핑 전 출하만 · ERP 만 · 미매핑 어디에도 없음 | `tools/check_data.py` G-14 (검사 4) |
| 알림 9종 (G-11) | `erp_upload_error` → AC 1행 · dedupe · 회차 교체 · 재해석 오류 0 이면 **누가 바꿨든 닫힘**(`notify.resolve_by_link` · Ruling 27 · DEF-QA1-006) → 9종 전부 PASS | `tools/check_data.py` G-11 (검사 13) · `tests/test_arch_notify.py` |
| TRK · HOME 연결 | TRK-030 수금 칸 = `stats.customer_receivable`(미수집 / 미확정 (D-516) / ok · ERP 업로드 기준일) · TRK-020 준수율 = `stats.due_compliance(period)`(D-804) · HOME 회계부 「90일 초과 미수」 = `stats.aging` | `tests/test_dev1_trk.py` · `test_dev1_home.py` · QA1 사람 판정 표(W2-4) |
| 오류 계약 · 권한 | 기능 120 · 사례 236 어긋남 0 · 5xx 0 · 422 160 전부 항목을 짚음 · 화면 67×8 200/403 전수 · 쓰기 62×8 R/없음 361 → 403 · COL 업로드 이상 파일 11 종 → 422 · 셀 속 `<script>` · DDE · 경로 글자는 글자로만(화면 이스케이프 · **xlsx 내려받기 수식 셀 0** DEF-QA3-004) · 파일을 디스크에 쓰지 않음 | `tools/check_screens.py`(rc 0) · `make check-security`(rc 3 = G-16 · 17 · 18 W3/W4) |
| 감사 로그 (G-22) | COL 쓰기 표본 8 각 1행 · preview · 422 · 403 · 404 → 0행 | `make check-security` G-22 |
| QA 리포트 | 「W2 수금」 절 3종 — QA1 결함 1(해소) · QA2 결함 1(해소) · QA3 결함 1(해소) · **치명 0** · 열림 1 = DEF-QA3-003(경미 · D-524 · W4) · E2E 캡처 **32**(W1 16 + W2 16 · 1280 · 390 · 가로 스크롤 0) | `outputs/qa{1,2,3}-*.md` · `outputs/e2e/` |
| 계약 · 결정 | `interfaces.md` §9 코드대로(`stats` 7 · `erp_upload` 11 · `notify.resolve_by_link`) · F-TRK-011 · 021 · 031 문장(Ruling 26: 진행 · 단계 조회 SQL 은 라우터 · 수치 집계만 `stats`) · D-608(개발1) · D-802~D-804(개발3) · Ruling 27 | `contracts/` · `decisions.md` |
| pytest | **300 passed · 0 failed** (테스트 파일 39) | `uv run pytest -q` |
| 시드 멱등 · 백업 | 시드 재실행 diff 0(테이블 46 · 행 313 — `seed_dev3` 열 매핑 7 포함) · 백업 → 복구 테이블 48 · 행 56,635 일치 | `make gate-full` G-21 · G-23 |
| 게이트 판정표 | **PASS 17 · FAIL 6 · 미검증 0 · BLOCKED 1** / 24 — W1 + W2 범위(G-01 · 04~14 · 19~23) 전부 PASS. FAIL 6 = G-02 · 03(RPT · DOC 몫) · G-15(W3) · G-16 · 17(W3) · G-18(W4) · BLOCKED G-24(D-525). gate-full 종료코드 6 | `make gate-full` |
| 커밋 | `W2 수금 끝: COL 7 · erp_upload · stats 공표 · TRK 연결 · QA 3 W2 절 · 결함 3 해소 · gate-full PASS 17` (이 커밋) | `git log --oneline -1` |

`make gate-full` 요약 (2026-10-22 09:26): 빌드 전제 PASS(pytest 300) · G-01 · G-04~G-14 · G-19~G-23 PASS · G-02 FAIL(고아 16 = RPT 10 · DOC 6) · G-03 FAIL(placeholder 11) · G-15~G-18 FAIL(W3/W4 미구현) · G-24 BLOCKED(D-525) → PASS 17 · FAIL 6 · BLOCKED 1 · 종료코드 6.

알아둘 것(W2): 알림을 「처리」(`handle_by_link` · 그 부서 사람이 처리 화면에서)와 「해소」(`resolve_by_link` · 사실이 사라짐 · 부서 무관)로 나눈다 — ADM 이 올린 회차의 회계부 알림이 남는 결함(DEF-QA1-006)이 그 경계였다. xlsx 내려받기는 글자 셀을 `data_type="s"` 로 고정한다(수식 주입).

## 2026-10-21 W1 핵심 흐름 실측 (개발 3 → QA 3 → 결함 수정 → gate-full)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| W1 화면 | 49 등록(개발1 23 · 개발2 20 · 개발3 6) · placeholder **18** = W2~W4 몫(COL 7 · RPT 9 · DOC 2) · W1 화면 placeholder 0 | `make check-routes` · `uv run python tools/check_screens.py` G-03 |
| W1 기능 | 136 중 **109** 라우트 · 표식 109/109 · 고아(W1) 0 — 남은 27 은 COL · RPT · DOC(W2~W4) | `make check-trace` G-02 |
| 화면 응답 | 칸 있는 260/260 → 200 · 칸 없는 276/276 → 403 「이 화면을 볼 권한이 없습니다」 · 쓰기 58 × 8 계정 R/없음 337 → 403 · W 127 통과 · 권한 예외 8/8 | `tools/check_screens.py` G-03 · G-19 |
| 오류 계약 | 쓰기 58 × 사례 209 어긋남 0 · 5xx 0 · GET 조회 칸 142 → 422 · 422 는 항목을 짚음(일반 문장 0 — DEF-QA1-003 수정 뒤) | `tools/check_screens.py` G-02 「오류 계약」 행 · `tests/test_qa1_errors.py` |
| E2E (HTTP 만) | 의뢰 → 지시 → 입고 LOT(분할 포함) → 입고검사 → 불출 → 일보 · 검사일보 → 제품 입고 → 판정 → 출하 지시 → 확정 · 부서 교대 sl → pr → sl → sh · 요청 28 전부 기대 응답 | `uv run python tools/check_data.py --transcript` G-06 · `outputs/qa2-흐름데이터.md` ③ |
| 역추적 · 정추적 | 출하 1건 → 제품 LOT → 지시 → 불출 LOT(분할 → 원 LOT) → 원자재 입고 LOT = QA2 독립 SQL 불일치 0 · DB 전 출하 · 전 원 LOT 대조 불일치 0 · 「출하 후 불합격」 표시 | `tools/check_data.py` G-07 · G-08 |
| 차단 · 가용 | 검사대기 · 보류 LOT 불출 422 · 보류 LOT 확정 422 · 중지 품목 입고/지시 422 · 가용 = qty − allocated · 동시 불출/할당(스레드 2) [200, 422] · 전 LOT 할당 = 열린 출하 행 합 · 라인 전부 제거 = 지시 취소 · 할당 0(Ruling 21) | `tools/check_data.py` G-09 · G-10 |
| 알림 | W1 8종 수신 부서 = D-511 · dedupe(D-522) · 처리 화면에서 닫힘 · HOME-020 남의 부서 404 · due-check 2회 멱등 · `erp_upload_error` 는 W2 미검증 | `tools/check_data.py` G-11 |
| 쓰기 경계 | 라우터 14 쓰기 테이블 ⊆ 계약 · TRK · LOT · PRP · trace · stats 쓰기 0 · 조회 화면 GET 전후 업무 테이블 diff 0 · 공용 모듈(numbering → `sys_number_seq` · auth → `sys_user`) §2.2 등재 | `tools/check_data.py` G-05 |
| 보안 · 운영 | G-19 · G-20 · G-21 · G-22 PASS · DB 끊김 503(화면 · 쓰기 · 로그인 · /health 본문에 접속 문자열 없음) · 이상 입력 26 POST 500 0 · Docker 정적 PASS(COPY 원본 7) · 실기동은 D-525 | `make check-security` (rc 3 = G-16 · 17 · 18 W3/W4) |
| QA 리포트 | 3종 — `outputs/qa1-기능계약.md`(결함 5 · 해소 5) · `qa2-흐름데이터.md`(결함 3 · 해소 3) · `qa3-보안운영.md`(결함 3 · 해소 2 · 열림 1 = DEF-QA3-003 경미 → D-524 W4) · **치명 0** · E2E 캡처 16 `outputs/e2e/` | `ls outputs/` · 각 보고서 §1 |
| 결정 | D-524 앱 DB 역할(가설 · W4) · D-525 Docker 데몬(차단) · D-526 HOME-030 개인 추가 알림(차단 · 정본 모순) · 개발 가설 D-601~607 · D-701~704 · D-801 · Ruling 21~25 반영 | `decisions.md` |
| pytest | **249 passed · 0 failed** (arch 8 · dev1 8 · dev2 7 · dev3 3 · qa1 3 · qa2 2 · qa3 3 = 35 파일) | `uv run pytest -q` |
| 시드 멱등 · 백업 | 시드 재실행 행 수 diff 0(테이블 46 · 행 305) · 백업 → 임시 DB 복구 테이블 48 전부 · 행 36,316 일치 | `make gate-full` G-21 · G-23 |
| 게이트 판정표 | **PASS 13 · FAIL 9 · 미검증 1 · BLOCKED 1** / 24 — W1 범위(G-01 · 04~10 · 19~23) 전부 PASS. FAIL 9 = G-02 · 03(W2~W4 몫) · G-12~18(W2~W4) · 미검증 G-11 1종(W2) · BLOCKED G-24(D-525). gate-full 종료코드 10 | `make gate-full` |
| 커밋 | `W1 핵심 흐름 끝: QA 3 보고서 · 결함 11 중 10 해소(1 = D-524 W4) · gate-full PASS 13` (이 커밋) | `git log --oneline -1` |

`make gate-full` 출력 (2026-10-21 23:42):

```
빌드 전제  PASS  pytest passed 249 · failed 0 (rc=0) · /health 200

G-01  정본(ia.json + overrides) ↔ nav.py           PASS  검사 10 전부 PASS
G-02  기능 목록 ↔ 라우트 ↔ 테스트 표식 · 고아 0                FAIL  [check_trace FAIL] 라우트 없는 계약 27 · 이어진 기능 109/136 / 표식 없는 기능 27 · 표식 있는 기능 109/136 · 테스트 파일 35 / [check_screens PASS] 검사 4 전부 PASS
G-03  화면 응답 — 67 + 공통 200 · placeholder 0 · 403  FAIL  [check_routes FAIL] placeholder 18 (개발1 2 · 개발3 16) / [check_screens PASS] 검사 3 전부 PASS
G-04  스키마 계약 ↔ 실제 DB                             PASS  검사 10 전부 PASS
G-05  쓰기 경계                                      PASS  검사 5 전부 PASS
G-06  E2E 흐름 1건                                  PASS  검사 3 전부 PASS
G-07  역추적                                        PASS  검사 5 전부 PASS
G-08  정방향 추적                                     PASS  검사 3 전부 PASS
G-09  차단 규칙                                      PASS  검사 7 전부 PASS
G-10  가용 재계산                                     PASS  검사 9 전부 PASS
G-11  알림 9종                                      미검증  검사 12 · 통과 못한 1 — erp_upload_error: W2 — COL-010 ERP 업로드가 아직 없어 발생시킬 수 없다
G-12  회차 교체                                      FAIL  W2 — 화면 · 기능이 아직 없다
G-13  오류 행 · 미매핑                                 FAIL  W2 — 화면 · 기능이 아직 없다
G-14  출하 대비 수금                                   FAIL  W2 — 화면 · 기능이 아직 없다
G-15  대시보드 8 수치                                  FAIL  W3 — 화면 · 기능이 아직 없다
G-16  데이터 질의 검증                                  FAIL  W3/W4 — RPT-130 데이터 질의 미구현
G-17  키 없음                                       FAIL  W3/W4 — AI 호출(ai.py · sys_ai_call_log) 미구현
G-18  SSO 토큰                                     FAIL  W3/W4 — DOC-010 SSO 미구현
G-19  권한 403 전수                                  PASS  [check_security PASS] 검사 6 전부 PASS / [check_screens PASS] 검사 8 전부 PASS
G-20  세션 상태                                      PASS  검사 9 전부 PASS
G-21  비밀 · 시드 멱등                                 PASS  비밀 스캔 파일 206 · 비밀 값 0 / 시드 (예시) PASS / 시드 멱등 PASS 행 수 diff 0 (테이블 46 · 행 305)
G-22  변경 감사 로그                                   PASS  검사 5 전부 PASS
G-23  백업 · 복구                                    PASS  테이블 48개 전부 복구 · 테이블별 행 수 일치 (행 36,316)
G-24  Docker · health                            BLOCKED  docker compose config 성립 · 환경변수 4 전달 — 컨테이너 기동 · /health 200 은 아직 재지 않음 — 차단 D-525

PASS 13 · FAIL 9 · 미작성 0 · 미검증 1 · WARN 0 · BLOCKED 1 / 전체 24 · 통과 못한 게이트 10 → 종료코드 10
```

알아둘 것: 개발 · QA 에이전트를 같은 DB 에서 동시에 돌리면 조회 diff · 유니크 충돌로 검사기가 일시 FAIL 할 수 있다 — 종료 판정(`make gate-full`)은 전원이 멈춘 뒤 혼자 돌린다. `make gate` 는 앱을 띄우지 않은 상태에서도 스스로 띄워 잰다.

## 2026-10-21 Phase 0 실측 (Task 9 — Phase 0 끝)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 정본 추출 | `contracts/ia.json` = 정본 HTML 재추출 · `ia-overrides.json`(D-505) | `make check-trace` (G-01 「ia.json = 정본 HTML 재추출」 PASS) |
| 기대값 | 묶음 8 · 대메뉴 17 · 화면 67 · 흐름 7 · 권한 260(W 64 · R 196) | `goal.md` §2.0 명령 (`design_doc.effective()`) |
| 문서 체계 | `goal.md` · `CLAUDE.md` · `decisions.md`(D-501~D-523) · `progress.md` · 옛 대장 `decisions-v1.md` · `progress-v1.md` | `git log --oneline` |
| 계약 | `contracts/` 8 파일(api-contract · db-schema · function-list · interfaces · permission-matrix · screen-map · ia.json · ia-overrides.json) | `ls contracts/` |
| 기능 | 136 (GET 69 · POST 67) · ID 중복 0 | `make check-trace` (G-02 첫 행) |
| 스키마 | 테이블 48 · 뷰 9 · G-04 PASS (검사 10) | `make check-schema` |
| 시드 | 부서 8 · 계정 8(전부 `(예시)`) · 권한 260 · 채번 7(`(예시)`) · 재실행 행 수 diff 0 (테이블 46 · 행 291) | `make gate-full` (G-21 「시드 멱등」) |
| 시드와 권한 | **시드를 다시 돌리면 `sys_permission` 이 권한 매트릭스 260칸으로 되돌아간다**(SYS 화면에서 바꾼 칸도) — Task 7 관찰 | `make db-seed` 뒤 `select count(*) from sys_permission` = 260 |
| nav | 정본과 글자 단위 일치 — 묶음 8 · 대메뉴 17 · 화면 67 · 흐름 7 · RPT 「대시보드」 · RPT-090~120 없음 | `make check-trace` (G-01 PASS, 검사 10) |
| 화면 응답 | 부서 8 로그인 8/8 · 칸 있는 260/260 → 200 · 칸 없는 276/276 → 403 · 공통 /login · /error · /health · /ia 200 | `make check-routes` |
| placeholder | **67** (개발1 25 · 개발2 20 · 개발3 22) — G-03 FAIL 은 Phase 0 의 정상 상태 | `make check-routes` · `curl localhost:8020/health` 의 `placeholders` |
| G-02 고아 | 라우트 없는 계약 136 · 계약 없는 라우트 0 · 표식 없는 기능 134 | `make check-trace` (목록 출력) |
| 백업 · 복구 | 테이블 48 전부 복구 · 행 수 일치 (G-23 PASS, gate-full) | `make gate-full` 또는 `make backup && make restore-check` |
| Docker | `docker compose config -q` rc 0 · 환경변수 4(OPENAI 키 · 모델 · DOC SSO 주소 · SSO 비밀) 전달 · 실제 기동은 미검증(Task 16) | `docker compose config -q` |
| pytest | 62 passed (`tests/test_arch_*.py` 8 파일 · smoke 8 포함) | `uv run pytest -q` |
| 게이트 판정표 | PASS 3 (G-01 · G-04 · G-21) · FAIL 2 (G-02 · G-03) · 미작성 17 · 미검증 2 / 24 — `make gate` 종료코드 21. gate-full 은 G-23 까지 PASS 4 | `make gate` · `make gate-full` |
| 커밋 | `Phase 0 끝: placeholder 67 · 게이트 24 판정표 · check-routes/trace` | `git log --oneline -1 -- progress.md` |

`make gate` 출력 (2026-10-21):

```
게이트 판정 — 엘컴화인 MES · 2026-10-21 19:02 · 읽기 전용 (gate)
빌드 전제  PASS  pytest passed 62 · failed 0 (rc=0) · /health 200

G-01  정본(ia.json + overrides) ↔ nav.py           PASS  검사 10 전부 PASS
G-02  기능 목록 ↔ 라우트 ↔ 테스트 표식 · 고아 0                FAIL  검사 5 · 통과 못한 2 — 고아 ① 라우트 없는 계약 0 (API 열이 글자 그대로 등록됨): 라우트 없는 계약 136 · 이어진 기능 0/136 / 고아 ③ 표식 없는 기능 0 (@pytest.mark.fn): 표식 없는 기능 134 · 표식 있는 기능 2/136 · 테스트 파일 8
G-03  화면 응답 — 67 + 공통 200 · placeholder 0 · 403  FAIL  검사 7 · 통과 못한 1 — placeholder 0: placeholder 67 (개발1 25 · 개발2 20 · 개발3 22)
G-04  스키마 계약 ↔ 실제 DB                             PASS  검사 10 전부 PASS
G-05  쓰기 경계                                      미작성  tools/check_data.py 없음 — QA2 가 만든다
G-06  E2E 흐름 1건                                  미작성  tools/check_data.py 없음 — QA2 가 만든다
G-07  역추적                                        미작성  tools/check_data.py 없음 — QA2 가 만든다
G-08  정방향 추적                                     미작성  tools/check_data.py 없음 — QA2 가 만든다
G-09  차단 규칙                                      미작성  tools/check_data.py 없음 — QA2 가 만든다
G-10  가용 재계산                                     미작성  tools/check_data.py 없음 — QA2 가 만든다
G-11  알림 9종                                      미작성  tools/check_data.py 없음 — QA2 가 만든다
G-12  수금 회차 교체                                   미작성  tools/check_data.py 없음 — QA2 가 만든다
G-13  오류 행 · 미매핑                                 미작성  tools/check_data.py 없음 — QA2 가 만든다
G-14  출하 대비 수금                                   미작성  tools/check_data.py 없음 — QA2 가 만든다
G-15  대시보드 8 수치                                  미작성  tools/check_data.py 없음 — QA2 가 만든다
G-16  데이터 질의 검증                                  미작성  tools/check_security.py 없음 — QA3 가 만든다
G-17  키 없음                                       미작성  tools/check_security.py 없음 — QA3 가 만든다
G-18  SSO 토큰                                     미작성  tools/check_security.py 없음 — QA3 가 만든다
G-19  권한 403 전수                                  미작성  tools/check_security.py 없음 — QA3 가 만든다
G-20  세션 상태                                      미작성  tools/check_security.py 없음 — QA3 가 만든다
G-21  비밀 · 시드 멱등                                 PASS  [비밀 스캔 PASS] 파일 81 · 비밀 값이 든 파일 0 · 키 패턴 줄 0 · .env.example 비밀 값 0 · .env gitignore 됨 · .env 추적 안 됨 / [시드 (예시) PASS] 시드 계정 8 중 (예시) 없음 0 · 채번 7 중 (예시) 없음 0 · 시드 멱등: 이 실행에서는 시드를 돌리지 않았다 — `make gate-full` · check_security: tools/check_security.py 없음 (QA3) — 그 몫은 아직 재지 않음
G-22  변경 감사 로그                                   미작성  tools/check_security.py 없음 — QA3 가 만든다
G-23  백업 · 복구                                    미검증  이 실행에서는 덤프 · 복구를 돌리지 않았다 — `make gate-full` (또는 `make backup && make restore-check`)
G-24  Docker · health                            미검증  docker compose config 성립 · 환경변수 4 전달 — 컨테이너 기동 · /health 200 은 아직 재지 않음 (`docker compose up -d --build` → `curl localhost:8020/health`)

PASS 3 · FAIL 2 · 미작성 17 · 미검증 2 · WARN 0 · BLOCKED 0 / 전체 24 · 통과 못한 게이트 21 · 빌드 전제 PASS → 종료코드 21
※ 미작성 · 미검증 · WARN 은 통과가 아니다(FAIL 로 센다). BLOCKED 는 decisions.md 에 D-번호와 사유가 있어야 종료 조건(goal.md §4.4)을 만족한다.
```
