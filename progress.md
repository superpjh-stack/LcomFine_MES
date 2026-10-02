# 진행 상태

검증된 것만 적는다. 여기 없는 숫자는 화면에 지어내지 않는다. 형식: `| 항목 | 실측 | 검증 방법 |`.

## 지금 해야 할 것

1. **웨이브 B 기동 — 개발 1·2·3 병렬** (goal.md §5 프롬프트). 각자 `CLAUDE.md` → `contracts/` → `decisions.md` 순으로 읽고 시작한다.
   - **R1 (기반)** 개발1: `app/numbering.py` + `sys_number_rule` 시드 6행 — 가설 형식을 `progress-dev1.md` §1 에 **가장 먼저** 공표(개발2·3 이 기다린다) · 기준정보 시드 `(예시)` · 작업지시 등록.
     개발2: `app/lineage.py` + `tests/test_lineage_scenario.py`(G-06 10행). 개발3: 추적 화면 뼈대 · `app/stats.py` · `contracts/migration-files.md` 제안.
   - **R2 (화면)** 각자 담당 중메뉴(개발1 13 · 개발2 11 · 개발3 8)의 placeholder 를 실제 화면으로.
2. 그 뒤 `make gate` 의 FAIL 순서대로: G-02(기능 ↔ 라우트 ↔ 테스트 표식) · G-03(placeholder 32) · G-06 · G-07 · G-08 · G-10 · G-14 · G-15 · G-18 · G-20 · G-21.
3. 아키텍트에게 남은 것(웨이브 D): `tools/backup.py`(G-20) · `Dockerfile` + `docker-compose.yml`(D-03).
4. 사람이 정해야 풀리는 것: D-01~D-07(설계도 §7) · D-10(「Lot」의 뜻) · D-12(P8 의 쓰는 저장소 — 설계도 모순) · D-14(괄호 권한의 해석) · D-17(검사가 출하의 필수 조건인가) · D-25(집계 산식).

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
