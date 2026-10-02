# 진행 상태

검증된 것만 적는다. 여기 없는 숫자는 화면에 지어내지 않는다. 형식: `| 항목 | 실측 | 검증 방법 |`.

## 지금 해야 할 것

1. **웨이브 C 재검 (QA 1명)** — 남은 FAIL 2개가 전부 QA 쪽 판정이다.
   - G-21: `tests/test_qa1_rbac.py::test_forbidden_comes_before_validation`(198행)이 `POST /qua/inspections/abc/delete` 에 422 를 기대하고, `test_qa1_errors.py::test_404_non_numeric_path_key`(DEF-QA1-007)는 같은 요청에 404 를 기대한다 — QA1 자기 모순. DEF-QA1-007 의 기대값(404)으로 정리.
   - G-22: **브라우저 한 바퀴 재실행**(`tools/e2e/run_e2e.py`) — 11·12단계가 스캔만으로 진행되는지 보고 리포트의 `G-22` 행 갱신.
   - 결함 19건 재검 결과를 리포트 3종에 기록. 수정 라운드에서 바뀐 것(Job 마감 규칙 D-107 · 롤이 붙는 Job D-208 · 이관 변경 없음 D-311 · 세션 D-26)에 새 결함이 없는지. 개발1 이 남긴 틈(작업 시작과 마감이 겹칠 때 — `progress-dev1.md` §3-8)의 재현 여부.
2. 그 뒤 `make gate-full` 전건 PASS + 치명 0 + 연속 2회전 변화 없음 → 종료(goal.md §4.4).
3. 사람이 정해야 풀리는 것: D-01~D-07 · D-10 · D-12 · D-14 · D-16 · D-17 · D-18 · D-25/D-301 · D-107 · D-202 · D-208 · D-303/D-309/D-311 · D-401~D-415. Docker 는 데몬이 꺼져 있어 **빌드·기동 미확인**(D-31).

## 2026-10-03 — 웨이브 D 2차 완료 (개발1 · 개발3) · 오케스트레이터 재실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 20 · FAIL 2 / 22** — FAIL: G-21(pytest 1건 — QA1 자기 모순) · G-22(리포트 판정이 재검 전) | `make gate-full` |
| pytest | **1587 passed · 1 failed** (직전 1580 · 2). 남은 1건 = `test_qa1_rbac.py::test_forbidden_comes_before_validation` | `uv run pytest -q` |
| 조용한 실패 정적 검사 | `qua.py` · `shp.py` · `trc.py` 의 스캔 422 처리를 `except` 없이 값으로 가름 → `test_static_scan_finds_no_unreviewed_swallowing_except` 통과 | `uv run pytest -q tests/test_qa3_ops.py` |
| Job 마감 (D-107) | 진행·정지 중인 작업 실적이 있는 Job 은 `완료` 422(사유에 열린 실적). 취소는 원래 실적 1건이라도 있으면 422 | `uv run pytest -q tests/test_dev1_job.py` |
| 이관 재실행 (D-311) | 실적 있는 Job 이라도 파일 값 = DB 값이면 「변경 없음」 통과(쓰지 않음), 다르면 오류 · `read = loaded + 변경 없음 + error` | `uv run pytest -q tests/test_dev3_migration.py` (17 passed) |
| 계약 반영 (오케스트레이터 직접) | `function-list.md` F-JOB-02(D-107) · B-MIG-04(D-311) · `migration-files.md` §1 · §5 #4 | `uv run python tools/gen_contracts.py --check` → "렌더본 = 원본" · `make check-trace` G-01·G-02 PASS |

## 2026-10-03 — 웨이브 D 1차 완료 (아키텍트 · 개발2 · 개발3) · 오케스트레이터 재실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 20 · FAIL 2 · 미검증 0 / 22** — FAIL: G-21(pytest 2건 실패) · G-22(QA3 리포트의 판정이 아직 재검 전 FAIL). G-08 · G-13 · G-15 · G-19 · G-20 이 FAIL → PASS | `make gate-full` (혼자 돌 때 직접 실행) |
| pytest | **1580 passed · 2 failed** (직전 1522 · 39). QA 테스트·검사기는 수정하지 않음 | `uv run pytest -q` |
| 남은 실패 2건 | ① `test_qa1_rbac.py::test_forbidden_comes_before_validation` — QA1 의 두 테스트가 같은 요청(`POST /qua/inspections/abc/delete`)에 422 와 404 를 각각 기대(자기 모순). 개발3 은 DEF-QA1-007 대로 404 로 고침 ② `test_qa3_ops.py::test_static_scan_finds_no_unreviewed_swallowing_except` — 개발3 이 이번에 넣은 스캔 422 처리의 `except` 2곳 | 위와 같음 |
| 세션 무효화 (G-19) | 요청마다 `sys_user` 확인 · 로그아웃은 그 세션만 서버에서 무효 · 상태·비밀번호 변경은 DB 트리거가 세션 판 번호를 올려 전부 끊음. `sys_user` 컬럼 2개 추가(`session_epoch` · `revoked_sessions`) — `ALTER` 로 반영, 계약 컬럼 296 → **298** = DB | `make check-schema` (G-04 15/15) · `tests/test_qa3_channel_e2e.py -k "session or cookie"` |
| POP 스캔 (G-13) | 검사 14 전부 PASS — 알림 중 스캔 글자가 스캔칸으로, 닫으면 포커스 복귀(공용 `static/app.js`) · 검사·출하 화면의 없는 번호 스캔이 같은 화면 422 · 현황판이 오류·서버 끊김 뒤 스스로 복귀 | `uv run python tools/check_security.py` (gate-full 안에서) |
| G-08 키 연결 | 후가공·슬리팅 롤 이력에 조상 인쇄 롤의 생산 실적 · splice/후가공/슬리팅 롤이 붙는 Job 은 부모의 Job 이고 `등록` 상태여야 함(D-208) | `uv run python tools/check_data.py --only G-08` |
| G-15 이관 | 실적·롤·출하가 있는 Job 은 덮어쓰지 않고 오류 리포트(D-309) | gate-full 의 G-15 (10/10) |
| G-20 백업 | `make backup` → 덤프 + 행 수 · `make restore-check` → 임시 DB 복구 · 테이블 30개 행 수 일치 · 임시 DB 삭제 | gate-full 의 G-20 (2/2) |
| 결정 | D-26~D-31(아키텍트) · D-208~210(개발2) · D-308~310(개발3) · D-401~D-415(QA 「사람 확인」) 추가 — 전부 가설, 차단 0 | `grep -c "^## D-" decisions.md` |
| 미확인 | Docker 이미지 빌드·기동(데몬 꺼짐 — `docker compose config` 문법만) · 워커 여러 개 · 실물 스캐너·프린터 | 아키텍트 보고 |

## 2026-10-03 — 웨이브 C 완료 (QA 1·2·3) · 오케스트레이터 재실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 15 · FAIL 6 · 미검증 1 / 22** — PASS: G-01~G-07 · G-09~G-12 · G-14 · G-16 · G-17 · G-18. FAIL: G-08 · G-13 · G-15 · G-19 · G-20 · G-21. 미검증: G-22(gate.py 가 리포트를 읽지 않음 — QA3 판정은 **FAIL**) | `make gate-full` (04:1x 직접 실행) |
| pytest | **1522 passed · 39 failed** — 실패 39 전부 QA 가 결함을 드러내려고 둔 테스트(QA1 26 · QA2 3 · QA3 10), skip/xfail 0 | `uv run pytest -q` |
| G-06 · G-07 계보 | QA2 가 개발 테스트를 쓰지 않고 API 로 직접 재현: `roll_genealogy` **10행**(투입 3 · splice 2 · 슬리팅 3 · 출하 2) = 설계도 화살표 10 · 화면 폼만으로도 10행 · 양방향 추적 화면 = 독립 재귀 SQL(임의 계보 5개 · 추적 313건 · 깊이 8~12단 · 불일치 0) · 막기 28/28 | `uv run python tools/check_data.py --only G-06,G-07` |
| G-10 집계 | 생산·품질·납기·불량 유형·현황판 화면값 = QA2 독립 SQL (대조 248칸 · 불일치 0) | `uv run python tools/check_data.py --only G-10` |
| G-17 권한 | 48칸 전수 — 요청 686건(화면 128 · 메뉴 48 · 읽기 160 · 쓰기 216 · 미로그인 134) 위반 0 · 괄호 조건 2 · 권한 표는 데이터 | `uv run python tools/check_screens.py` |
| G-14 출력물 | 5종 인쇄 화면 · 바코드 `zbarimg` 판독 5/5 · 외부 요청 0 · 디코드 값으로 스캔 진입 | `uv run python tools/check_security.py` |
| G-22 브라우저 한 바퀴 | **FAIL** (QA3) — 헤드리스 Chromium 으로 16단계 전부 화면 조작, 계보 10행·역추적까지 완주했으나 11(품질 검사)·12(출하 롤 스캔)단계에서 알림 중 스캔 유실 1건 + 포커스 상실로 손 조작 우회 7건. 캡처 86장 | `outputs/qa3-채널보안.md` · `outputs/e2e/` |
| 결함 | **19건 — 치명 0 · 중대 12 · 경미 7** (QA1 7: 중대 4 · 경미 3 / QA2 3: 중대 2 · 경미 1 / QA3 9: 중대 6 · 경미 3). 같은 원인 중복 포함(세션 무효화 · 스캔칸 사라짐) | `outputs/qa{1,2,3}-*.md` |
| 테스트 잔여물 | `Q1-` · `Q2-` · `Q3` 업무 행 0 (QA 보고) · sys_permission 48 · sys_user 4 | QA 리포트 · 다음 회전에서 재확인 |

## 2026-10-03 — 웨이브 B 완료 (개발 1·2·3) · 오케스트레이터 재실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate-full` | **PASS 5 · FAIL 1 · 미검증 16 / 22** — PASS: G-01 · G-02 · G-03 · G-04 · G-21. FAIL: G-20(백업 도구 없음). 미검증 16 은 QA 검사기 대기 | `make gate-full` (03:2x 직접 실행) |
| pytest | **369 passed** (arch 34 · dev1 127 · dev2 152 · dev3 56) | `uv run pytest -q` |
| G-02 기능 | 기능 ↔ 라우트 **94/94** · 고아 라우트 0 · 테스트 표식 **100/100** · 이관 배치 명령 **6/6** | `make check-trace` |
| G-03 화면 | HTTP 200 35/35 · placeholder **0** | `make check-routes` |
| 계보 시나리오 | `tests/test_lineage_scenario.py` 9 passed — 설계도 §3 예시 10행(투입 3 · splice 2 · 슬리팅 3 · 출하 2)을 화면 API 로 생성, 양방향 추적, 6단 이상 임의 계보. **G-06·G-07 판정은 QA2 대기(미검증)** | `uv run pytest -q tests/test_lineage_scenario.py` |
| 시드 멱등 | 재실행 행 수 diff 0 (테이블 29 · 행 98) | `make gate-full` 의 G-09 실측 |
| 테스트 잔여물 | roll 0 · roll_genealogy 0 · job 0 · shipment 0 · inspection 0 · sys_migration_log 0 · 시드만 남음(material_lot 4 · item 5 · sys_user 4 · sys_permission 48) | `psql -h /tmp -d lcomfine_db -Atc "select count(*) from roll"` 등 |
| 용어 오염 | 0건 | `grep -rnE "솥\|인분\|검식\|절임\|숙성\|염도\|needsfood" src tools tests contracts Makefile` |
| 게이트 도구 수정 | `tools/check_trace.py` 가 `include_router` 한 라우터를 펴지 못해 기능 ↔ 라우트가 항상 0/94, 고아 검사가 빈 집합으로 통과하던 것을 고침 (`all_routes`) — 게이트를 낮춘 것이 아니라 재는 방법을 바로잡음 (개발1 §3-1) | 수정 전 0/94 → 수정 후 94/94 · 고아 0 |
| 결정 | D-101~106(개발1) · D-201~207(개발2) · D-301~307(개발3) 추가, 전부 가설 · 차단 0 | `grep -c "^## D-" decisions.md` |
| 개발 보고 중 미확인 | 실제 브라우저 조작은 개발2 의 POP 헤드리스 한 바퀴뿐 · 모바일 390px 는 정적 HTML 측정 · 현황판 30초 새로고침 미실측 · 실물 스캐너/프린터 미확인(D-04) → QA3 G-13 · G-22 | `progress-dev{1,2,3}.md` |

## 2026-10-03 — Phase 0 오케스트레이터 재실측 · 웨이브 B 기동

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| `make gate` | **PASS 2 · FAIL 11 · 미검증 9 / 22** — 아키텍트 보고와 동일 (G-01 · G-04 PASS, G-03 placeholder 32) | `make gate` (오케스트레이터 직접 실행 02:27) |
| pytest | **34 passed** | `uv run pytest -q` |
| 시드 멱등 | 재실행 행 수 diff 0 (테이블 29 · 행 56) | `make gate-full` 의 G-09 실측 |
| 정본·메타프롬프트 | `goal.md` 33,604B · 설계도 50,360B — Phase 0 전과 같음 | `wc -c` |
| 웨이브 B | 개발 1·2·3 병렬 기동. 규칙: 커밋은 오케스트레이터만 · `make db-reset`/`db-schema` 금지(공유 DB) · 스키마·계약 변경은 `progress-devN.md` §3 요청 · 포트 8021/8022/8023 | goal.md §5 |

## 2026-10-03 — Phase 0 (아키텍트) 완료

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 설계도 수치 (goal.md §9) | 대메뉴 **12** · 중메뉴 **32** · 기능 **94** / 권한칸 **48** = 입력 **19** · 조회 **24** · 없음 **5** | goal.md §9 스니펫을 그대로 실행 (`uv run python - <<'EOF' …`) |
| 설계도 수치 (그 밖) | 묶음 4 · 프로세스 10(P1~P10) · §3 그림의 계보 화살표 **10** | `uv run python -c "import sys; sys.path.insert(0,'tools'); import design_doc as d; print(len(d.ia()['groups']), len(d.processes()), d.lineage_arrows())"` |
| 환경 | git 저장소(로컬 · main) · uv / Python 3.12 · DB `lcomfine_db` · `.env`(gitignore, 난수 비밀 2개) | `make setup` · `git check-ignore .env` |
| G-01 메뉴 | **PASS** — 검사 9 전부 PASS (nav 묶음 4 · 대메뉴 12 · 중메뉴 32 = 설계도 이름·순서·기능 수·채널, screen-map 렌더본 일치) | `make check-trace` |
| G-02 기능 | **FAIL(정상)** — 검사 10 중 7 PASS: 계약 100줄 = 화면 94 + 배치 6 · 대메뉴별 20·12·7·8·8·5·7·6·7·3·4·7 = 설계도 · 쓰는 저장소 ⊆ 설계도 §2 표(예외 2건 D-12) · 권한 열 = 설계도 §6. 3 FAIL: 기능 ↔ 라우트 0/94 · 테스트 표식 0/100 · 배치 명령 0/6 | `make check-trace` |
| G-03 화면 | **FAIL(정상)** — HTTP 200 **35/35**(중메뉴 32 + 공통 3) · placeholder **32**(개발1 13 · 개발2 11 · 개발3 8) | `make check-routes` |
| 권한 없음 = 403 | 역할 4 × 화면 32 = 128건 조회 검사, 없음 5칸 → 403 + 메뉴 숨김, 위반 **0** · 미로그인 브라우저 303 / 그 밖 401 | `make check-routes` |
| G-04 저장소 | **PASS** — 검사 7 전부 PASS. 계약 테이블 30 = DB 30 · 계약 컬럼 **296** = DB 296 · D1 9 · D2 2 · D3 1 · D4 2 · D5 4 · D6 2 · D7 2 · D8 1 (+ SYS 7) · 뷰 2 | `make check-schema` |
| 공통 시드 | 역할 4 · 권한 48칸(입력 19 · 조회 24 · 없음 5) · 계정 4 — **2회 실행 행 수 동일** (sys_permission 48 · sys_role 4 · sys_user 4) | `uv run python -m lcomfine.db.seed` ×2 · `make gate-full` 의 G-09 실측 "diff 0" |
| pytest | **34 passed** — `test_arch_smoke.py` 19(메뉴 수 · 계약 100줄 · 권한 48칸 · health · 303/401 · 로그인 401→303 · placeholder 32 · 권한 없음 403 5건 · 괄호 권한 2개 · ERP 501 · 404 · 채널 훅 · 접근 로그) + `test_arch_genealogy.py` 15 | `uv run pytest -q` |
| 계보 스키마 (SQL 직접) | 설계도 §3 예시 = **10행**(투입 3 · splice 2 · 슬리팅 3 · 출하 2) · 역방향 추적이 LOT ①② 에 닿음(9행) · 정방향이 출하 LOT 에 닿고 슬리팅 ③ 은 `재고` · 깊이 12단 사슬 추적 · DB 가 막는 것 10종(자기 자신 · 순환 · 재출하 · 소진 롤 출하 · 출하 롤 재사용 · 중복 · LOT→출하 · 관계 불일치 · 행 수정 · 다른 Job) — 각각 **그 제약으로** 막혔는지 확인 | `uv run pytest -q tests/test_arch_genealogy.py` (행은 전부 롤백 — DB 에 남지 않음) |
| 서버 기동 | 포트 8020 `/health` 200 `{"status":"ok", groups 4, menus 12, screens 32, functions 94, batch_functions 6, placeholders 32}` · `/login` 200 · `/static/style.css` 200 | `make run` 후 `curl -s localhost:8020/health` |
| 용어 오염 | 다른 사업의 용어·패키지명 **0건** (goal.md 자체 제외) | `grep -rnE "솥\|인분\|검식\|절임\|숙성\|염도\|needsfood" src tools tests contracts *.md Makefile` |
| 계약 | `contracts/{function-list,db-schema,screen-map,interfaces,api-contract}.md` — 렌더본(db-schema §4 · screen-map §1) = 원본 | `uv run python tools/gen_contracts.py --check` → "렌더본 = 원본" |
| 결정 | `decisions.md` D-01~D-07(설계도 §7, 전부 가설) + D-08~D-25(아키텍트 18건, 전부 가설) · 차단 0 | `grep -c "^## D-" decisions.md` → 25 |

`make db-reset && make gate` 판정표 (원문):

```
게이트 판정 — 엘컴화인 MES · 2026-10-03 02:25

G-01  메뉴 — 묶음 4 · 대메뉴 12 · 중메뉴 32 (nav = 설계도)      PASS  검사 9 전부 PASS
G-02  기능 — 94 + 이관 6 · 계약 = API = 테스트 · 고아 0       FAIL  검사 10 · 통과 못한 3 — 기능 94 ↔ 라우트 (API 열의 메서드·경로가 등록됨): 이어진 기능 0/94 · 미연결 예 ['F-BAS-01', 'F-BAS-02', 'F-BAS-03'] / 기능 100 ↔ 테스트 (@pytest.mark.fn 표식): 표식이 붙은 기능 0/100 · 테스트 파일 2 / 이관 배치 6 ↔ 명령 (lcomfine.migration.COMMANDS): 이어진 배치 0/6 · src/lcomfine/migration 없음 (개발3)
G-03  화면 — 중메뉴 32 + 공통 3 전부 200 · placeholder 0    FAIL  HTTP 200 35/35 · placeholder 32 (개발1 13 · 개발2 11 · 개발3 8)
G-04  저장소 — D1~D8 ↔ 계약 ↔ 실제 DB                     PASS  검사 7 전부 PASS
G-05  쓰기 경계 — 프로세스별 쓰는 저장소 · P9·P10 쓰기 0           미검증  tools/check_data.py 없음 (QA2) — 쓰기 라우터 0개
G-06  계보 재현 — §3 예시 roll_genealogy 10행 (API)       FAIL  tests/test_lineage_scenario.py 없음 (개발2 R1) · roll_genealogy 0행
G-07  추적 — 역방향·정방향 재귀 조회 · 분기 5단 이상                FAIL  app/lineage.py 스텁 — 미구현 — 담당 개발2 (app/lineage.py)
G-08  키 연결 — 롤 번호 → 지시·조색·실적·검사·출하 · 채번 한 곳        FAIL  app/numbering.py 스텁 — 미구현 — 담당 개발1 (app/numbering.py) · sys_number_rule 0행
G-09  시드 멱등 — 2회 실행 행 수 diff 0 · (예시) 표기           미검증  이 실행에서는 시드를 돌리지 않았다 — `make gate-full`
G-10  집계 — 생산·품질·납기 = 독립 SQL 재계산                   FAIL  app/stats.py 스텁 — 미구현 — 담당 개발3 (app/stats.py)
G-11  빈 화면 — 미수집 / 미확정 (D-nn)                      미검증  tools/check_data.py 없음 (QA2)
G-12  범위 밖 0 — PLC 수집 · 비전 · AI 없음                 미검증  tools/check_data.py 없음 (QA2)
G-13  4채널 — POP 스캔 · 모바일 390px · 현황판 새로고침          미검증  tools/check_security.py 없음 (QA3) — 채널 레이아웃 훅(body.ch-*)만 있다
G-14  출력물 5종 — 작업지시서 · 라벨 3 · COA · 바코드            FAIL  app/printing.py 스텁 — 미구현 — 담당 개발2 (app/printing.py)
G-15  이관 배치 6 — Import 파일 · 멱등 · 리포트               FAIL  src/lcomfine/migration 없음 (개발3) · 파일 규격 contracts/migration-files.md 없음
G-16  ERP — 어댑터 + 501 명시 · 조용한 폴백 0                미검증  자체 실측 /erp/status → 501 `ERP 연계 미확정 (D-02)` · 조용한 폴백 검사는 check_security(QA3) 대기
G-17  RBAC — 48칸 (입력 19 · 조회 24 · 없음 5) · 괄호 조건 2  미검증  자체 실측 DB 권한 표 48칸 = 설계도 §6 (입력 19 · 조회 24 · 없음 5) · 없음 칸 403 위반 0 · 쓰기 403 전수는 쓰기 API 가 생긴 뒤 check_security(QA3)·QA1
G-18  접근 로그 — 로그인 · 조회 · 변경 · 로그 화면                FAIL  sys_access_log 로그인 6 · 조회 151 · 변경 0 · 오류 0 · 로그 화면(SYS-03) placeholder — 조회 불가
G-19  비밀 — 저장소·문서에 비밀 값 없음                         미검증  자체 실측 저장소 대상 파일 70개 중 비밀 값이 든 파일 0 · .env gitignore 됨 · check_security(QA3) 대기
G-20  백업 — make backup · restore-check             FAIL  tools/backup.py 없음 — `make backup` · `make restore-check` 미구현
G-21  빌드 — pytest 전건 · check-routes · /health 200  FAIL  pytest passed 34 · failed 0 · check-routes FAIL · /health 200
G-22  브라우저 한 바퀴 — outputs/e2e 캡처                   미검증  outputs/e2e 파일 0개 — 브라우저 한 바퀴는 QA3 가 돌고 `outputs/qa3-채널보안.md` 에 판정을 적는다

PASS 2 · FAIL 11 · WARN 0 · BLOCKED 0 · 미검증 9 / 전체 22
※ WARN·미검증은 통과가 아니다. BLOCKED 는 decisions.md 에 D-번호와 사유가 있어야 종료 조건(goal.md §4.4)을 만족한다.
```

만든 것 —
`pyproject.toml`(uv · Python 3.12 · `lcomfine-mes`) · `Makefile` · `.env.example` · `CLAUDE.md` · `decisions.md` ·
`src/lcomfine/app/{main,nav,rbac,auth,templating,settings,contracts}.py` · `util/{http,audit,screen}.py` ·
`routers/home.py`(메인 최소 구현) + 12 모듈 빈 스텁 · 공용 모듈 스텁 `{numbering,lineage,printing,stats}.py`(시그니처) · `erp.py`(전부 501) ·
`templates/{base,login,_error,_placeholder}.html` + `home/{main,_macros}.html` · `static/{style.css,app.js}` ·
`db/{schema.sql,conn.py,seed.py}` · `tools/{gate,check_routes,check_trace,check_schema,gen_contracts,design_doc,init_env}.py` ·
`tests/{test_arch_smoke,test_arch_genealogy}.py`.

Phase 0 에서 만들지 않은 것 — `tools/backup.py`(G-20, Makefile 타깃은 실패로 나온다) · `Dockerfile`/`docker-compose.yml`(D-03) ·
`tools/{check_data,check_security,check_screens}.py`(QA 가 만든다 → 그때까지 해당 게이트는 `미검증`).

게이트 판정표에서 주의할 것 — G-16·G-17·G-19 는 `gate.py` 가 사실을 재서 실측 칸에 적지만 판정은 `미검증` 이다(D-24). PASS 는 QA3 의 `check_security.py` 가 준다.
`make check-routes` · `make check-trace` 는 지금 종료코드 1 이다(placeholder 32 · 기능 미연결) — 정상.

다음: 웨이브 B — 개발 1·2·3 병렬 기동 (goal.md §5).
