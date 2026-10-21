# 진행 상태 (v2 · 2026-10-21 정본 기준)

검증된 것만 적는다. 여기 없는 숫자는 화면에 지어내지 않는다. 형식: `| 항목 | 실측 | 검증 방법 |`.
옛 판(설계도 기준 · 대메뉴 12)의 기록은 `progress-v1.md` 에 있다 — v2 의 실측이 아니다.

## 지금 해야 할 것: W1 개발 3 기동

Phase 0 끝(아래 실측). `goal.md` §3.1 W1 핵심 흐름 — 개발1 · 개발2 · 개발3 을 §5 프롬프트로 **한 번에** 띄운다.
각자 자기 화면의 GET 을 등록하면 placeholder 가 빠지고(G-03), 기능 API 와 `@pytest.mark.fn` 테스트가 붙으면 G-02 고아가 준다.
QA2 · QA3 는 `tools/check_data.py` · `tools/check_security.py` 를 만든다 — 그 전까지 G-05~G-20 · G-22 는 `미작성`(FAIL 로 센다).

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
