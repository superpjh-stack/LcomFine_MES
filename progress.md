# 진행 상태 (v2 · 2026-10-21 정본 기준)

검증된 것만 적는다. 여기 없는 숫자는 화면에 지어내지 않는다. 형식: `| 항목 | 실측 | 검증 방법 |`.
옛 판(설계도 기준 · 대메뉴 12)의 기록은 `progress-v1.md` 에 있다 — v2 의 실측이 아니다.

## 지금 해야 할 것: W2 수금 (개발3 → QA 3 → gate-full → 커밋)

W1 끝(아래 실측 · 커밋). 다음 회전은 `goal.md` §3.1 **W2 수금** — 개발3 을 §5 프롬프트로 기동한다:
COL 7 화면(COL-010~070) · `erp_upload.py` · `stats.customer_receivable(customer_id)` · `stats.due_compliance(period)` 공표 → 개발1 이 TRK-030 수금 칸 · TRK-020 납기 준수율에 붙인다(Ruling 23).
회차 교체 · 이전 회차 보존 · 오류 행 제외 · 미매핑 → `erp_upload_error` 알림(G-11 의 마지막 1종) · 열 구성은 `차단` D-516 — 매핑 화면이 흡수한다.
끝나면 QA1 · QA2(G-12~G-14 를 W2 로 잰다) · QA3 → 결함 수정 → `make gate-full` → 커밋. 그 뒤 W3 대시보드(G-15~G-17) · W4 문서 SSO(G-18 · D-524 앱 DB 역할 · G-24 D-525).

사람이 할 것(루프는 기다리지 않는다): **D-525** Docker Desktop 을 켜고 `docker compose up -d --build` → `/health` 200 (G-24) · **D-526** HOME-030 「개인 추가 알림」의 뜻 · D-516~D-520.

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
