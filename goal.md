# /goal — 엘컴화인 MES v2 (묶음 8 · 대메뉴 17 · 화면 67 · 부서 8 · LOT 추적)

> 사람이 2026-10-21 정본 교체(새 기획서)를 지시해 아키텍트가 다시 썼다. 옛 판(설계도 기준 · 대메뉴 12)은 git 이력에 있다.
> **이 문서가 메타프롬프트다.** `/loop` 가 매 회전마다 이 문서를 판정 기준으로 읽는다. 투입되는 에이전트(아키텍트 1 · 개발 3 · QA 3)도
> 작업 전에 이 문서와 `CLAUDE.md` · `contracts/` · `decisions.md` · `progress.md` 를 먼저 읽는다. **이 문서는 사람만 고친다.**
> 여기 적힌 수치는 전부 정본에서 기계로 센 값(`contracts/ia.json` + `contracts/ia-overrides.json`)이다. 의심되면 §2.0 명령으로 다시 센다.

| 항목 | 값 | 출처 |
|---|---|---|
| 시스템 | 엘컴화인 MES — 신규 웹 시스템. 웹 애플리케이션 하나 + DB 하나 | 정본 |
| 정본 | `docs/엘컴화인_MES_기획서_2026-10-21.html` (**읽기 전용**) — 옛 설계도는 `docs/archive/` 참고만 | D-501 |
| 설계 스펙 | `docs/superpowers/specs/2026-10-21-mes-v2-design.md` (사람과 합의한 설계) | — |
| 규모 | 묶음 **8** · 대메뉴 **17** · 화면 **67**(정본 71 − RPT 4) · 기능 **136**(규칙 A 가 내는 수 133 · 유형 예외 3 · D-508) | ia.json · D-505 |
| 부서(역할) | 영업부 SL · 생산부 PR · 출하실 SH · 디자인·개발실 DS · 회계부 AC · 전략부 ST · 경영진 EX · 전산 관리자 ADM = **8** | ia.json `roles` |
| 권한 | **260 칸**(W 64 · R 196) / 536(= 8 × 67). 칸이 없으면 메뉴 숨김 · 403. 전산 관리자는 전 화면 R 이상 | ia.json + overrides |
| 채널 | **1**(Web). 반응형 1280 · 390 가로 스크롤 0 | 스펙 §3.1 |
| 업무 흐름 | **7단계** 수주 → 작업지시 → 자재 불출 → 생산·검사 → 제품 입고 → 출하 → 수금 | ia.json `flow` |
| 알림 | **9종**(D-511 · 구성 D-523) — 쓰기 트랜잭션 안에서 부서 단위로 | ia.json HOME `batch` · D-523 |
| 바깥 접점 | ERP 수금현황 엑셀 업로드(열 구성 D-516) · 문서관리 시스템 SSO(D-517) · OpenAI(데이터 질의만 · D-504) | 정본 · D-504 |
| 범위 밖 | 설비 실시간 수집 · 비전 검사 · 매출전표/세금계산서/발주/근태/품의/원가 · 문서 저장 · AI 해설 리포트 · POP/모바일/현황판 채널 | 스펙 §10 |
| 완료 기준 | **출하 1건에서 원자재 LOT 까지 거슬러 올라갈 수 있어야 한다**(G-07) · 의뢰 → 출하 1건을 화면 조작만으로(G-06) | 스펙 §4.2 · §7 |
| 코드 위치 | `/Users/gerardo92/Desktop/AI Coding/lcomFine MES` (이 폴더) | — |

---

## 1. 목표

**정본의 대메뉴 17 · 화면 67 을 PostgreSQL 실 테이블과 FastAPI 실 API 에 연동하고, 생산의뢰 → 생산지시 → 자재 불출 → 생산·검사 → 제품 입고 → 판정 → 출하 → ERP 수금 흐름 한 건이 화면 조작만으로 흐른 뒤, 출하 1건에서 원자재 LOT 까지 역추적되게 한다. 부서마다 자기 일을 「내 할 일」과 알림으로 받고, 대시보드 8 은 화면을 열 때 실시간으로 집계되며, 문서관리는 SSO 로 열린다.**

끝났다고 말할 수 있는 상태는 이것뿐이다.

1. 묶음 8 · 대메뉴 17 · 화면 67 이 정본과 글자 단위로 같고, 전부 HTTP 200 이며 placeholder 가 **0건**이다.
2. 기능 목록(`contracts/function-list.md`)의 줄마다 화면 · API · 테스트(`@pytest.mark.fn`)가 **1:1** 로 이어진다.
3. G-06 흐름 1건을 화면 조작(HTTP)만으로 다시 만들 수 있고, 그 출하에서 원자재 LOT 까지 역추적 · 원자재 LOT 에서 출하까지 정방향 추적된다.
4. 권한 260 칸이 그대로 동작한다(칸 없음 = 403 · R 부서의 쓰기 = 403).
5. 알림 9종이 전부 발생하고, 처리하면 닫힌다.
6. ERP 수금 업로드는 회차 교체 · 이전 회차 보존 · 오류 행 제외가 되고, 출하 대비 수금이 월 · 거래처 단위로 맞는다.
7. 대시보드 8 의 수치가 독립 재계산과 같고, 데이터 질의는 허용 뷰만 읽는다. 키가 없으면 조용히 넘어가지 않고 오류를 보인다.
8. 범위 밖 기능(§ 머리 표)이 메뉴 · 엔드포인트 · 테이블 어디에도 없다.
9. QA 3명의 리포트 3종이 `outputs/` 에 있고 치명 결함이 0이다.

### 재사용 자산 — 새로 짓기 전에 먼저 본다 (D-503)

| 자산 | 위치 | 쓰임 |
|---|---|---|
| 정본 추출 | `contracts/ia.json` · `contracts/ia-overrides.json` · `tools/design_doc.py` | 게이트의 기대값. 이름은 여기서 복사한다 — 기억으로 다시 치지 않는다 |
| 골격 | `src/lcomfine/app/` 의 `rbac` `templating` `nav` `conn` `audit` `http` `numbering` `settings` · `main.py` 자동 include | 유지. 채널 분기 · 스캔칸 · `device=` 는 걷어낸다 |
| 게이트 도구 | `tools/{gate,check_trace,check_routes,check_schema,check_data,check_security,check_screens,backup}.py` · `Makefile` | 출력 형식 `G-nn  항목  PASS\|FAIL\|WARN\|BLOCKED\|미검증  실측` 과 `make gate` 판정표를 그대로 따른다 |
| Docker | `Dockerfile` · `docker-compose.yml` | 유지(G-24) |

**용어.** 이 회사 v2 용어는 생산의뢰 · 생산지시 · 불출 · 생산일보 · 검사일보 · 판정 · 재판정 · LOT · 분할 순번 · 출하 지시 · 출하 확정 · 회차 · 미수 연령 · 대시보드 · SSO 다. 옛 판의 Job · Roll · splice · 슬리팅 · 조색 · 아니록스 · 판사양 · POP · 현황판은 옮겨 오지 않는다(D-502).

---

## 2. 수용 게이트 G-01~G-24

**루프는 매 회전마다 이 표를 실행한다.** 판정은 명령의 출력으로만 한다(`make gate` · 종료 판정은 `make gate-full`). 검사기가 아직 없는 게이트는 `미검증` 이며 PASS 가 아니다 — 명령은 Task 9 와 QA 가 만든다.

### 2.0 기대값 다시 세기

```bash
uv run python - <<'EOF'
from tools import design_doc
e = design_doc.effective()          # ia.json + ia-overrides.json
scr = [s for m in e["menus"] for s in m["screens"]]
cells = [v for s in scr for v in s["roles"].values()]
print("묶음", len(e["bundles"]), "대메뉴", len(e["menus"]), "화면", len(scr), "흐름", len(e["flow"]))
print("권한", len(cells), "W", cells.count("W"), "R", cells.count("R"))
EOF
# → 묶음 8 대메뉴 17 화면 67 흐름 7 / 권한 260 W 64 R 196
```

### 2.1 구조

| # | 게이트 | 판정 명령 | 기대값 |
|---|---|---|---|
| G-01 | 정본(ia.json + overrides) ↔ `nav.py` | `make check-trace` | 묶음 8 · 대메뉴 17 · 화면 67 · 흐름 7 의 **순서 · 이름 · 화면 유형이 글자 단위로 일치**. RPT 이름 「대시보드」 · RPT-090~120 없음(D-505) |
| G-02 | 기능 목록 ↔ 라우트 ↔ 테스트 표식 | `make check-trace` | `function-list.md` 줄마다 API 열의 메서드 · 경로가 라우트에 글자 그대로 있고, `@pytest.mark.fn("F-…")` 테스트가 1건 이상. 고아(계약 없는 라우트 · 라우트 없는 계약 · 표식 없는 기능) **0** |
| G-03 | 화면 응답 | `make check-routes` | 화면 67 + 공통(`/login` · `/error`) + 참고 `/ia` 전부 HTTP 200(권한 있는 부서로) · placeholder **0** · 칸 없는 부서 403 |
| G-04 | 스키마 계약 ↔ 실제 DB | `make check-schema` | 스펙 §4.1 표의 **테이블 이름 집합** = `contracts/db-schema.md` = 실제 DB(수가 아니라 이름 — D-521) · 컬럼 · 뷰(`v_work_order_status` · `v_dq_*`) 일치 |

### 2.2 흐름

| # | 게이트 | 판정 명령 | 기대값 |
|---|---|---|---|
| G-05 | 쓰기 경계 | `make check-data` | 라우터별 쓰기 SQL 정적 스캔 = 계약의 쓰는 테이블. 예외 3(QC-010/020 → `lot_stock.status` · 출하 지시 → `lot_stock` 할당 · 쓰기 트랜잭션 → `notification`)만 허용. TRK · LOT · PRP · RPT 대시보드는 업무 테이블 쓰기 **0**(조회 전후 행 수 diff 0) · 데이터 질의는 `data_query_log` · `sys_ai_call_log` 만 |
| G-06 | **E2E 흐름 1건** | `make check-data` (+ `tests/test_qa2_*`) | 의뢰 → 지시 → 입고 → 입고검사 → 불출 → 일보 → 제품 입고 → 판정 → 출하 지시 → 확정 1건을 **화면이 부르는 HTTP 만으로** 만든다. 각 단계 응답 2xx/303 · DB 에 의뢰번호로 이어진 행 |
| G-07 | **역추적** | `make check-data` | 출하 번호 또는 제품 LOT 하나 → `trace.backward` → 그 출하에 들어간 **원자재 LOT 전부**(분할 LOT 는 원 LOT 로 이어서). QA2 의 독립 SQL 과 같은 집합 |
| G-08 | 정방향 추적 | `make check-data` | 원자재 LOT → 불출 → 지시 → 제품 입고 → 출하까지(`trace.forward`). 독립 SQL 과 같은 집합 |
| G-09 | 차단 규칙 | `make check-data` | 검사대기 · 불합격(보류) LOT 의 불출 422 · 그 LOT 가 걸린 출하 확정 422 · 중지 품목은 입고 · 출하 지시에서 못 고름 |
| G-10 | 가용 재계산 | `make check-data` | 모든 LOT 에서 가용 = 현재고 − 출하 지시 할당. 화면 값 = 독립 재계산 |
| G-11 | 알림 9종 | `make check-data` (+ `tests/test_arch_notify.py`) | D-511 의 9종(구성 D-523)이 각 트리거에서 **수신 부서마다 1행** 생기고, 같은 키 재발생은 무시(D-522), 한 사람이 처리하면 부서 전체 「처리됨」 · 연 화면에서 처리하면 닫힘 |

### 2.3 수금

| # | 게이트 | 판정 명령 | 기대값 |
|---|---|---|---|
| G-12 | 회차 교체 | `make check-data` | 같은 기준 기간 재업로드 = 새 회차가 반영 회차, 이전 회차는 지우지 않고 이력에 「교체됨」 |
| G-13 | 오류 행 · 미매핑 | `make check-data` | 필수 열 · 숫자/날짜 형식 · 거래처 코드 오류 행은 반영 제외 · 미매핑 코드는 COL-030 목록에 쌓이고 매핑 후 재반영 가능 · MES 화면에 수금 수정 경로 없음 |
| G-14 | 출하 대비 수금 | `make check-data` | COL-070 의 월 · 거래처별 출하(MES) · 매출/수금(ERP) = 독립 재계산(건 단위 짝짓기 없음) |

### 2.4 대시보드 · AI

| # | 게이트 | 판정 명령 | 기대값 |
|---|---|---|---|
| G-15 | 대시보드 8 수치 | `make check-data` | RPT-010~080 의 모든 수치 = QA2 가 따로 짠 SQL 재계산(D-512) · 0건이면 `미수집` · 수금 대시보드에 최근 업로드 기준일 |
| G-16 | 데이터 질의 검증 | `make check-security` | 쓰기 문 · 허용 밖 뷰/테이블 · 다중 문장 · 시스템 카탈로그 접근 거부(422) · 수금 뷰는 SL · AC · ADM · EX 만 · 질의마다 `data_query_log`(거부 포함) |
| G-17 | 키 없음 | `make check-security` | `LCOMFINE_OPENAI_API_KEY` 가 없거나 호출이 실패하면 화면에 명시적 오류 · `sys_ai_call_log` 에 실패 기록 · 하드코딩 결과 0 |

### 2.5 SSO

| # | 게이트 | 판정 명령 | 기대값 |
|---|---|---|---|
| G-18 | SSO 토큰 | `make check-security` | 재사용 · 만료(60초) · 비활성 사용자 · 계정 미매핑 → 거부 · 토큰이 주소창(GET)에 없음 · 호출마다 로그(사용자 · 시각 · 성공 여부) · 주소 없으면 `미확정 (D-517)` |

### 2.6 보안 · 운영

| # | 게이트 | 판정 명령 | 기대값 |
|---|---|---|---|
| G-19 | 권한 403 전수 | `make check-security` | 260 칸 밖의 화면 GET 403(메뉴에도 없음) · R 부서의 모든 쓰기 기능 403 · 쓰기 라우트 전부 `require_fn` |
| G-20 | 세션 상태 | `make check-security` | 사용자 상태 · 부서를 요청마다 DB 에서 읽는다 — 비활성 · 로그아웃 다음 요청 401, 부서 변경 다음 요청 반영 |
| G-21 | 비밀 · 시드 멱등 | `make check-security` · `make gate-full` | 저장소 · 문서에 비밀 값 0(`LCOMFINE_*` 값은 `.env` 에만) · 시드 2회 실행 행 수 diff 0 · 시드 값 `(예시)` |
| G-22 | 변경 감사 로그 | `make check-security` | 쓰기 성공마다 `sys_change_log`(누가 · 언제 · 무엇을) · 로그인 성공/실패 · 화면 조회 `sys_access_log` · SYS-040 에서 조회 |
| G-23 | 백업 · 복구 | `make backup && make restore-check` | 덤프 생성 · 임시 DB 에 복구해 테이블별 행 수 일치(운영 DB 는 그대로) |
| G-24 | Docker · health | `docker compose up -d --build` → `curl -s localhost:8020/health` | 컨테이너 기동 · `/health` 200 · 응답에 접속 문자열 · 비밀 없음 |

빌드 조건(모든 게이트의 전제): `uv run pytest -q` 전건 통과 · 서버 `uv run …` 기동 후 `/health` 200.
브라우저 확인: QA3 가 실제 브라우저로 G-06 흐름을 부서를 바꿔 로그인하며 돌고 단계별 캡처를 `outputs/e2e/` 에 남긴다. 테스트가 통과해도 화면에서 안 되면 결함이다.

### 2.7 오류 계약 — QA1 이 그대로 테스트 케이스로 쓴다 (`contracts/api-contract.md`)

| 상황 | HTTP | 화면 |
|---|---|---|
| 필수값 누락 · 코드 중복 · 검사대기/불합격 LOT 불출 · 가용 초과 할당 · 미판정 LOT 출하 확정 · DB 가 담을 수 없는 값 · 비허용 질의 | **422** | 사람이 읽는 문장(라우터가 먼저 검사) |
| 없는 번호 · 없는 행 | **404** | `찾을 수 없습니다` |
| 인증 실패 · 비활성 · 로그아웃한 세션 | **401** | 브라우저 GET 은 `/login` 303 |
| 권한 없음 | **403** | `접근 권한이 없습니다` |
| 정해지지 않은 연계 · 규칙 | **501** | `미확정 (D-nn)` 명시. **조용한 폴백 금지** |
| DB 연결 실패 | **503** | `서비스 일시 중단` |
| 처리되지 않은 예외 · AI 호출 실패 | **500** | `예상하지 못한 오류` + 로그(AI 는 `sys_ai_call_log` 도) |

### 2.8 범위 밖 — 실패로 보지 않는다

실 ERP 자동 연동(엑셀 업로드까지가 범위) · 실 문서관리 시스템 접속 확인(D-517) · 메일 · 메신저 발송(D-518) · 실제 운영 서버 재배포(최종 보고에 절차만) · 실제 생산 LOT 으로 하는 완료 기준 검증(시드 시나리오까지가 루프의 몫, 실 LOT 검증은 도입 후 사람이 한다).

---

## 3. 팀 편성과 웨이브 (D-506 · 스펙 §8)

```
Phase 0  정본 추출 · 계약 7종 · 스키마 · 시드 · 게이트 도구 · placeholder 67 · CSS · 로그인/레이아웃 (아키텍트)
   ↓
W1 핵심 흐름 → W2 수금 → W3 대시보드 → W4 문서 SSO      (멈추지 않고 이어 간다)
   각 웨이브: 개발(병렬) → QA 3(병렬) → 결함 수정 → make gate-full PASS → 로컬 커밋
```

### 3.1 웨이브

| 웨이브 | 범위 | 분담 |
|---|---|---|
| **Phase 0** | `contracts/ia.json` 추출 · 계약 7종 · `schema.sql` · 시드(부서 8 · 권한 260 · 계정 8 · 채번 7 · 공통코드 3그룹) · 게이트 도구 · placeholder 67 · `static/style.css` · 로그인/레이아웃 · `rbac` 화면 단위 · `notify` · `numbering` | 아키텍트 |
| **W1 핵심 흐름** | HOME · BAS · STD · WO · SYS · TRK / MAT · PRD · INS · QC · INV · LOT / SHP · PRP | 개발1 · 개발2 · 개발3 |
| **W2 수금** | COL 7 · `erp_upload` · 통합 조회(TRK-030)의 수금 칸 | 개발3 (TRK 수금 칸은 개발3 이 `stats.customer_receivable` 을 공표하고 개발1 이 붙인다) |
| **W3 대시보드** | RPT 9(대시보드 8 + 데이터 질의) · `dashboard` · `ai` · `dataquery` · 허용 뷰 `v_dq_*` | 개발3 + 개발1(공통코드 · 로그 화면 보강) |
| **W4 문서 SSO** | DOC 2 · `sso` · 사용자 비활성 연동 · SSO 로그 | 개발1 |
| 매 웨이브 끝 | QA1 기능·계약 / QA2 흐름·데이터 / QA3 보안·운영 → 결함 수정 → `make gate-full` PASS → 커밋 | 전원 |

### 3.2 개발 3명 — 한 파일은 한 사람만 만진다

| 담당 | 대메뉴 (화면 수) | 화면 | 공용 모듈 |
|---|---|---|---|
| **개발1** 기준·지시·시스템 | HOME 내 업무(3) · BAS 기준정보(3) · STD 인쇄 기준(6) · WO 작업지시(4) · SYS 시스템(4) · TRK 통합 조회(3) · DOC 문서관리(2, W4) | **25** | `jobs.py`(배치 `due-check`) · `sso.py`(W4) |
| **개발2** 자재·생산·품질·재고 | MAT 자재·입고(4) · PRD 생산일보(4) · INS 검사일보(4) · QC 품질 검사(3) · INV 재고(3) · LOT LOT 추적(2) | **20** | `trace.py`(정·역방향 LOT 추적 — **가장 먼저 공표**) |
| **개발3** 출하·수금·분석 | SHP 출하(3) · PRP 생산 보고서(3) · COL 수금리포트(7, W2) · RPT 대시보드(9, W3) | **22** | `stats.py` · `erp_upload.py` · `dashboard.py` · `ai.py` · `dataquery.py` |

합계 **25 + 20 + 22 = 67**. 각 개발자는 자기 모듈의 `src/lcomfine/app/routers/<module>.py` · `src/lcomfine/app/templates/<module>/` · `src/lcomfine/db/seed_devN.py` · `tests/test_devN_*.py` 와 위 공용 모듈을 소유한다.
아키텍트 소유: `src/lcomfine/db/schema.sql` · `nav.py` · `main.py` · `contracts/*` · `rbac` · `templating` · `notify` · `numbering` (+ `conn` · `audit` · `http` · `settings` · `static/` · `templates/base.html` · `tools/gate.py` · `tools/gen_function_list.py` · `tools/gen_permissions.py` · `tools/gen_contracts.py` · `tools/check_trace.py` · `tools/check_routes.py` · `tools/check_schema.py` · `tools/backup.py` · `tests/test_arch_*.py` · `Makefile`). 소유 밖 파일이 필요하면 `progress-devN.md` §3 에 요청한다.

- 화면 간 흐름(계약): WO-010 생산의뢰(의뢰번호 = 수주 키) → WO-020 생산지시 → MAT-010 원자재 입고(입고 LOT 자동 채번 · 검사대기) → QC-010 입고검사(합격 → 가용) → MAT-020 불출(가용 LOT 만) → PRD-010 생산일보 · INS-010 검사일보 → MAT-030 제품 입고(일보 완료 수량 기본값 · 제품 LOT) → QC-020 제품검사 판정 → SHP-010 출하 지시(가용 안에서 LOT 할당) → SHP-020 출하 확정 → COL-010 ERP 수금 업로드 → LOT-020 역추적.
- 공용 함수 · 시그니처는 **먼저 정한 사람이 `progress-devN.md` §1 에 공표**하고 나머지가 그대로 쓴다. 시그니처 원본은 `contracts/interfaces.md`.

### 3.3 QA 3명 — 서로 다른 관점으로 교차 검증

| 담당 | 범위 | 소유 · 산출 |
|---|---|---|
| **QA1** 기능·계약 | G-01~G-04 · 기능 목록 1:1 · §2.7 오류 계약 · 화면별 계약 문장(정본 L3 · logic) 대조 | `tools/check_screens.py` · `tests/test_qa1_*` · `outputs/qa1-기능계약.md` |
| **QA2** 흐름·데이터 | G-05~G-15 — 쓰기 경계 · **E2E 1건 · 정/역추적** · 차단 규칙 · 가용 재계산 · 알림 9종 · 수금 회차 · 대시보드 독립 재계산 | `tools/check_data.py` · `tests/test_qa2_*` · `outputs/qa2-흐름데이터.md` |
| **QA3** 보안·운영 | G-16~G-24 — 데이터 질의 거부 · 키 없음 · SSO · 403 전수 · 세션 · 비밀 · 감사 로그 · 백업 · Docker · **브라우저 한 바퀴** · 조용한 실패 사냥 | `tools/check_security.py` · `tests/test_qa3_*` · `outputs/qa3-보안운영.md` · `outputs/e2e/` |

결함 ID 는 `DEF-QA{n}-nnn`, 등급은 치명/중대/경미. **QA 는 고치지 않는다.** 재현 절차와 실측을 적어 담당 개발에게 넘긴다.

### 3.4 화면 디자인 (스펙 §6)

- 정본의 시각 언어: IBM Plex Sans KR(+ 시스템 글꼴 대체) · 액센트 `--cyan #0b7a8a` · 라이트/다크 토큰(`:root` · `prefers-color-scheme` · `data-theme`) · 표 중심 밀도 · 상태 칩. `static/style.css` 는 새로 쓰고(아키텍트), `app.js` 는 폼 보조(확인 대화 · 포커스)만.
- 메인 `/` = **HOME-010 내 할 일**: 업무 흐름 띠(7단계 · 권한 있는 단계만 링크) → 부서별 대기 카드(건수 + 조건이 걸린 처리 화면 링크) → 납기 임박·지연 → 오늘 처리한 건.
- `/ia` 참고 화면: 계약(nav · 권한 표 · 기능 목록)에서 그린 사이트맵 · 권한 매트릭스. 정본 글은 옮기지 않고 수는 DB · 계약에서 센다.
- 대시보드 차트는 인라인 SVG(외부 차트 라이브러리 없음) + 같은 숫자의 표. 반응형 1280 · 390 가로 스크롤 0.

---

## 4. 루프 엔지니어링 프로토콜

### 4.0 루프 기동 — 이 한 줄을 붙여 넣는다

```
/loop goal.md 를 판정 기준으로 엘컴화인 MES v2 를 만든다. §4.2 한 회전 절차를 그대로 따른다 —
progress.md·decisions.md 를 읽고(없으면 §3.1 Phase 0 부터), `make gate` 로 §2 게이트 G-01~G-24 를 실측하고,
FAIL 중 가장 앞선 웨이브의 항목 하나를 골라 §5 프롬프트로 담당 에이전트를 기동하고(병렬 가능한 것은 한 번에),
보고를 믿지 말고 게이트 명령을 직접 다시 돌려 확인한 뒤 실측값과 검증 명령을 progress.md 에 적고 커밋한다.
막히면 decisions.md 에 D-번호로 `차단`을 올리고 다음 항목으로 넘어간다 — 사람을 기다리며 멈추지 않는다.
게이트를 낮추거나 테스트를 건너뛰지 않는다. §4.4 종료 조건을 만족하면 최종 보고를 쓰고 루프를 멈춘다.
```

중단 후 재개는 `/re-begin` 또는 위 한 줄을 다시 붙여 넣는다. 상태는 전부 파일에 있다(§4.5).

### 4.1 상태 파일 — 이것 말고 다른 곳에 상태를 두지 않는다

| 파일 | 역할 | 쓰는 사람 |
|---|---|---|
| `goal.md` | 목표 · 게이트 (이 문서). **판정 기준** | 사람만 |
| `progress.md` | **검증된 현황의 유일한 진실.** `\| 항목 \| 실측 \| 검증 방법 \|` 3열 + 맨 위에 "지금 해야 할 것" | 루프 오케스트레이터 |
| `decisions.md` | 결정 대장 `D-5nn~` — `확정` / `가설` / `차단` (옛 대장은 `decisions-v1.md`) | 전원 |
| `progress-dev{1,2,3}.md` | 개발자별 §1 공표 · §2 진행 · §3 요청 | 각 개발자 |
| `outputs/qa{1,2,3}-*.md` | QA 리포트 | 각 QA |
| `contracts/*` | 코드 계약 · 정본 추출(`ia.json` · `ia-overrides.json`). 코드와 다르면 코드가 맞다 — 계약을 고친다(단 `schema.sql` · `nav.py` · `function-list.md` 는 아키텍트만) | 아키텍트 |

### 4.2 한 회전에서 하는 일 (이 순서를 바꾸지 않는다)

1. **읽기** — `progress.md` 최신 섹션 · `decisions.md` 미결 · 직전 QA 리포트. `progress.md` 에 Phase 0 완료 기록이 없으면 Phase 0 이다.
2. **판정** — `make gate`. FAIL 목록을 만든다. (Phase 0 전이면 전부 FAIL 로 본다.)
3. **선택** — FAIL 중 **가장 앞선 웨이브의 항목 1개**. 웨이브를 건너뛰지 않는다.
4. **기동** — §5 프롬프트로 담당 에이전트를 띄운다. 병렬 가능한 것(개발 3, QA 3)은 한 번에 같이. 작은 수정은 직접 한다.
5. **검증** — 보고를 믿지 않는다. 게이트 명령을 **직접 다시 실행**한다.
6. **기록 · 커밋** — `progress.md` 에 실측과 명령을 적고, 새 결정은 `decisions.md`. `git add -A && git commit -m "<G-nn|웨이브>: <한 줄>"` (로컬만, push 없음).
7. **다음 회전** — FAIL 이 남았으면 다음 회전을 예약한다. 에이전트가 돌고 있으면 완료 알림이 먼저 깨우므로 예약은 긴 대기(20분 이상)로 건다.

### 4.3 멈추지 않기 위한 규칙

- **막히면 우회한다.** 사람 확인이 필요한 값은 `decisions.md` 에 `차단` 으로 올리고, 화면에는 `미확정 (D-nn)` 을 렌더링한 뒤 다음 항목으로 넘어간다.
- **같은 실패를 2회 넘게 반복하지 않는다.** 3회째면 접근을 바꾸고, 그래도 안 되면 `차단`.
- **게이트를 낮추지 않는다.** 테스트를 지우거나 `skip` 하거나 수치를 내리는 것은 실패다. 이 문서는 사람만 고친다.
- **한 파일은 한 사람만.** 담당 밖 파일이 필요하면 `progress-devN.md` §3 에 요청을 남긴다.
- **동시에 3명 이하.** 시드와 스키마 재생성은 한 번에 하나만 돈다.
- **이 폴더 밖은 읽기만 한다.** 다른 사업 폴더와 그 DB 를 고치지 않는다. 포트는 8020(8000 은 다른 사업).
- **밖으로 내보내지 않는다.** push · 배포 · 외부 서비스 전송 없음(데이터 질의의 OpenAI 호출은 D-504 로 허용된 유일한 예외 — 키가 있을 때만). 정본 HTML 을 고치거나 옮기지 않는다.

### 4.4 종료 조건 (EXIT) — 셋을 동시에 만족하면 루프를 멈춘다

1. §2 게이트 **G-01~G-24 전건 PASS** (`차단` 항목은 사유와 D-번호가 `decisions.md` 에 있을 것)
2. QA 리포트 3종이 있고 **치명 결함 0**
3. **연속 2회전 동안 `progress.md` 에 새 실측 변화가 없음**

남은 것이 전부 `차단` 뿐이어도 멈춘다. 멈출 때 `progress.md` 맨 위에 최종 보고를 쓴다 — 게이트 판정표, 사람이 정해야 할 D-목록(D-516~D-520 · 채번 형식 D-509 · 정해지면 무엇이 바뀌는지 한 줄씩), 실 LOT 검증 절차, VPS 재배포 절차.

### 4.5 중단 · 재개

세션이 끊기면 `progress.md` 최신 섹션 + `decisions.md` 미결만 읽고 **4.2 의 1번부터** 다시 한다. 대화 기록에 의존하지 않는다.

---

## 5. 에이전트 기동 프롬프트 (그대로 복사해 쓴다)

모든 프롬프트는 아래 **공통 서두**로 시작한다.

> 너는 엘컴화인 MES v2 개발팀의 [역할]이다. 작업 폴더는 `/Users/gerardo92/Desktop/AI Coding/lcomFine MES`.
> 작업 전에 `CLAUDE.md` · `goal.md` · `contracts/` · `decisions.md` · `progress.md` 를 읽는다. 정본은 `docs/엘컴화인_MES_기획서_2026-10-21.html` 이며 읽기만 한다. 화면 · 메뉴 · 부서 이름은 `contracts/ia.json` 에서 복사한다.
> 이 시스템의 본체는 **생산의뢰 → 지시 → 불출 → 생산·검사 → 제품 입고 → 판정 → 출하 → ERP 수금 흐름과 LOT 추적**이다. 추적은 `trace.py` 가 읽기만 하는 조회다.
> **계약만 보고 만든다** — 컬럼 · 경로 · 함수 시그니처는 `contracts/` 가 출처다. 계약에 없는 것을 혼자 정하지 않는다. 모자라면 `decisions.md` 에 `가설` 로 올리고(본인 번호 대역) 아키텍트에게 계약 수정을 요청한 뒤 쓴다.
> **쓰기 엔드포인트에는 `rbac.require_fn("F-…")`**, 화면 GET 에는 `rbac.require_screen("…")`. 쓰기 성공은 `http.saved(request, msg)` 직후 `audit.log_change(...)`. 오류는 422(입력 · 사람이 읽는 문장) · 404(없음) · 501 `http.undecided("D-nn")`(미확정) — 입력 오류를 500 으로 내지 않는다.
> **범위 밖 금지** — 설비 실시간 수집 · 비전 검사 · AI 해설 리포트 · POP/모바일/현황판 은 메뉴 · 엔드포인트 · 테이블 어디에도 만들지 않는다.
> **지어내지 않는다** — 데이터가 없으면 `미수집`, 정해지지 않았으면 `미확정 (D-nn)`, 시드는 `(예시)` 를 붙인다. **조용한 실패 금지** — `try/except` 로 하드코딩 결과를 끼워넣지 않는다.
> 테스트는 기능마다 하나 이상, `@pytest.mark.fn("F-…")` 표식. **소유 파일만 고친다**(아래 목록). 보고 전에 `uv run pytest tests/test_devN_*.py` (QA 는 자기 `tests/test_qaN_*`)를 돌리고 실측값과 명령을 [본인 진행 파일]에 적는다.
> 환경: PostgreSQL 17 (unix socket `/tmp`) DB `lcomfine_db` · 포트 8020 · `uv` / Python 3.12 · 명령은 `uv run …` · 환경변수 접두 `LCOMFINE_` · 비밀 값은 `.env` 에만, 문서 · 코드에 적지 않는다. 이 폴더 밖은 읽기만 하고, push · 배포 · 외부 전송은 하지 않는다.

**아키텍트 (Phase 0)**
> §3.1 Phase 0 을 순서대로 한다. `tools/design_doc.py` 로 정본에서 `contracts/ia.json` 을 뽑고 §2.0 명령으로 수치(17 · 67 · 8 · 260 · 7)를 직접 세어 `progress.md` 에 실측으로 적는다.
> 가장 공들일 것은 `function-list.md`(D-508 전개)와 `db-schema.md`(스펙 §4.1 · 쓰기 경계) · `interfaces.md` 다 — 개발 3명이 이 셋만 보고 서로 맞물리는 화면을 만든다. 추적의 척추(스펙 §4.2)가 끊기지 않는지 종이 위에서 먼저 따져 본다.
> 끝나면 `make gate` 판정표를 `progress.md` 에 붙인다. Phase 0 끝 = G-01 · G-04 PASS, G-02 는 계약 존재, G-03 은 placeholder 67 로 FAIL(정상).

**개발1 (HOME · BAS · STD · WO · SYS · TRK · DOC / 화면 25)**
> 담당 화면: HOME-010 내 할 일 · HOME-020 알림함 · HOME-030 알림 설정 / BAS-010 품목 관리 · BAS-020 거래처 관리 · BAS-030 창고·위치 관리 / STD-010 제조사양기준서 · STD-020 표준관리 · STD-030 판관리 · STD-040 시안등록 · STD-050 표준견본서 · STD-060 예외제품관리 / WO-010 생산의뢰서 · WO-020 생산지시서 · WO-030 생산순서관리 · WO-040 공정상태 / SYS-010 사용자 관리 · SYS-020 역할·권한 · SYS-030 공통코드 · SYS-040 로그 / TRK-010 주문 진행 조회 · TRK-020 납기 현황 · TRK-030 거래처 종합 조회 / (W4) DOC-010 문서관리 바로가기 · DOC-020 문서관리 계정 매핑.
> 소유 파일: `routers/{home,bas,std,wo,sys,trk,doc}.py` · `templates/{home,bas,std,wo,sys,trk,doc}/` · `db/seed_dev1.py` · `tests/test_dev1_*.py` · `app/jobs.py` · (W4) `app/sso.py`.
> 먼저 공표(`progress-dev1.md` §1): WO-010 · WO-020 이 쓰는 의뢰 · 지시의 상태값과 「지시 대기 · 불출 대기」 판정 조건(개발2 · 개발3 의 대기 카드 · 출하 지시가 쓴다). HOME-010 의 부서별 대기 카드는 저장하지 않고 질의로 센다. 의뢰 · 지시 등록은 같은 트랜잭션에서 `notify.emit`(D-511). 번호는 `numbering.next` 만. STD-020 · STD-060 의 적용 규칙과 로스율은 `차단`(D-519). SYS-020 은 `sys_permission` 행을 바꾸고 `rbac.invalidate()`. TRK-030 의 수금 칸은 W2 에 개발3 `stats.customer_receivable` 로 붙인다. W4 의 SSO 는 D-514 규격, 주소가 없으면 `미확정 (D-517)`.

**개발2 (MAT · PRD · INS · QC · INV · LOT / 화면 20)**
> 담당 화면: MAT-010 원자재 입고 · MAT-020 불출 · MAT-030 제품 입고 · MAT-040 입고·불출 내역 / PRD-010 생산일보 · PRD-020 생산일보출력 · PRD-030 생산일보현황 · PRD-040 생산지시서 대비 생산 로스율 / INS-010 검사일보 · INS-020 검사일보출력 · INS-030 검사일보현황 · INS-040 생산지시서 대비 검사 로스율 / QC-010 입고검사 · QC-020 제품검사 판정 · QC-030 검사 이력 / INV-010 LOT별 재고 조회 · INV-020 재고 이동 · INV-030 재고 조정·실사 / LOT-010 정방향 추적 · LOT-020 역방향 추적.
> 소유 파일: `routers/{mat,prd,ins,qc,inv,lot}.py` · `templates/{mat,prd,ins,qc,inv,lot}/` · `db/seed_dev2.py` · `tests/test_dev2_*.py` · `app/trace.py`.
> **가장 먼저 공표**(`progress-dev2.md` §1): `trace.backward(…)` · `trace.forward(…)` 의 시그니처와 반환 모양(개발3 의 출하 이력 · 통합 조회가 쓴다). 추적은 스펙 §4.2 척추를 따라가는 **읽기만** 하는 조회 — 경로를 따로 저장하지 않는다(G-05). 분할 LOT 는 `stock_move` 의 원 LOT 로 잇는다.
> 재고 상태는 D-510: 입고 직후 검사대기, QC 합격 → 가용 · 불합격 → 보류, 재판정은 새 행(D-515). 검사대기 · 보류 LOT 의 불출은 422(G-09). 가용 = 현재고 − 할당(G-10). 조정 이력은 수정 · 삭제하지 않는다. 입고 · 제품 입고 · 판정은 같은 트랜잭션에서 `notify.emit`. 로스율 산식은 `미확정 (D-519)`.

**개발3 (SHP · PRP · COL · RPT / 화면 22)**
> 담당 화면: SHP-010 출하 지시 · SHP-020 출하 확정 · SHP-030 출하 이력 / PRP-010 월별 가동률 · PRP-020 기계별통계 · PRP-030 생산완료집계 / (W2) COL-010 ERP 수금현황 업로드 · COL-020 업로드 이력 · COL-030 거래처 코드 매핑 · COL-040 수금 현황 조회 · COL-050 거래처별 미수 조회 · COL-060 미수 연령 조회 · COL-070 출하 대비 수금 조회 / (W3) RPT-010 수주 리포트 · RPT-020 생산 리포트 · RPT-030 품질 리포트 · RPT-040 재고·창고 리포트 · RPT-050 출하 리포트 · RPT-060 수금 리포트 · RPT-070 주문 흐름 리포트 · RPT-080 경영 요약 · RPT-130 데이터 질의 (대메뉴 이름은 「대시보드」 — D-505).
> 소유 파일: `routers/{shp,prp,col,rpt}.py` · `templates/{shp,prp,col,rpt}/` · `db/seed_dev3.py` · `tests/test_dev3_*.py` · `app/stats.py` · `app/erp_upload.py` · `app/dashboard.py` · `app/ai.py` · `app/dataquery.py`.
> W1: 출하 지시는 가용 안에서만 LOT 를 할당하고(`lot_stock` 할당 — 계약된 예외), 미판정 · 불합격 LOT 가 있으면 확정 422, 확정 후 정정은 `shipment_adjust` 행. 지시 · 확정은 같은 트랜잭션에서 `notify.emit`. PRP 집계 SQL 은 `stats.py` 한 곳.
> **W2 먼저 공표**(`progress-dev3.md` §1): `stats.customer_receivable(…)` 시그니처와 반환 모양(개발1 의 TRK-030 이 쓴다). ERP 업로드는 회차 교체 · 이전 회차 보존 · 오류 행 제외 · MES 는 수금을 고치지 않음(G-12~14). 열 구성은 `차단`(D-516) — 매핑 화면이 흡수한다.
> W3: 대시보드 8 은 화면을 열 때 `dashboard.py` 로 집계(D-512 · 캐시 테이블 없음), 차트는 인라인 SVG + 표. 데이터 질의는 D-513 검증을 통과한 SELECT 만, AI 는 `ai.py` 로만 부르고 키가 없으면 명시적 오류(G-17).

**QA1 (기능·계약)**
> §3.3 QA1 범위를 §2 게이트와 §2.7 오류 계약으로 검증한다. **고치지 않는다.** 소유 파일: `tools/check_screens.py` · `tests/test_qa1_*` · `outputs/qa1-기능계약.md`.
> 기대값은 개발이 짠 테스트가 아니라 `contracts/ia.json` + `ia-overrides.json` 과 `function-list.md` 에서 직접 끌어온다. 화면마다 정본 L3 · logic 문장이 화면에서 지켜지는지 확인한다. 결함은 `DEF-QA1-nnn` 으로 재현 절차 · 실측 · 기대값 · 담당 개발을 적고, 통과 항목도 실측과 명령을 함께 적는다.

**QA2 (흐름·데이터)**
> G-05~G-15 를 검증한다. **고치지 않는다.** 소유 파일: `tools/check_data.py` · `tests/test_qa2_*` · `outputs/qa2-흐름데이터.md`.
> G-06 흐름을 HTTP 만으로 직접 돌리고, 역/정추적 · 가용 · 출하 대비 수금 · 대시보드 8 수치를 **자기 SQL 로 다시 계산**해 화면 값과 대조한다. 검사기 출력은 `G-nn  항목  PASS|FAIL|WARN|BLOCKED|미검증  실측` 행(`tools/gate.py` 가 파싱). 결함은 `DEF-QA2-nnn`.

**QA3 (보안·운영)**
> G-16~G-24 를 검증한다. **고치지 않는다.** 소유 파일: `tools/check_security.py` · `tests/test_qa3_*` · `outputs/qa3-보안운영.md` · `outputs/e2e/`.
> 260 칸 밖 403 전수 · R 부서 쓰기 403 · 세션 · 데이터 질의 우회 시도(쓰기 문 · 다중 문장 · 허용 밖 뷰 · 카탈로그) · SSO 재사용/만료/비활성/미매핑 · 비밀 스캔 · 백업 복구 · Docker. 실제 브라우저로 G-06 흐름을 부서를 바꿔 로그인하며 돌고 단계별 캡처를 `outputs/e2e/` 에 남긴다. DB 를 끊었는데 화면이 멀쩡하면 결함이다. 결함은 `DEF-QA3-nnn`.

---

## 6. 권한 — 기대값은 `contracts/permission-matrix.md`

- 부서 8 × 화면 67 = 536 칸 중 **260 칸**(W 64 · R 196)에 권한이 있다. 원본은 정본(`ia.json` 의 화면별 `roles` · `self_grants` · 전산 관리자 전 화면 R 이상 규칙) + `ia-overrides.json`(D-505 로 RPT-090~120 제거).
- 렌더본은 `contracts/permission-matrix.md`, 시드는 `sys_permission` 260행(`tools/gen_permissions.py`). **코드에 부서 · 칸을 박지 않는다** — `rbac.require_screen` · `rbac.require_fn` 이 DB 행을 읽는다.
- 데이터 질의의 수금 뷰 제한(SL · AC · ADM · EX)은 권한 표가 아니라 `dataquery` 의 허용 목록이다(D-513).

---

## 7. 차단 목록 — 사람이 정할 것 (`decisions.md`)

| # | 정할 것 | 그동안 | 정해지면 바뀌는 곳 |
|---|---|---|---|
| D-516 | ERP 수금현황 엑셀의 열 구성(매출액 · 잔액 열 존재 여부 포함) | 열 매핑 화면이 흡수 · 매출/잔액 미매핑이면 COL-050 · 060 `미확정 (D-516)` | `erp_upload.py` 필수 열 |
| D-517 | 문서관리 SSO 주소 · 방식(SAML/OIDC/서명 토큰) · 사번 동일 여부 | D-514 서명 토큰 · 주소 없으면 `미확정 (D-517)` · 매핑 필수 | `sso.py` · `.env` |
| D-518 | 알림 메일 · 메신저 | MES 안 알림함만 | `notify.py` 발송 어댑터 |
| D-519 | 표준관리 · 예외제품 적용 규칙 · 생산/검사 로스율 산식 | 등록 · 조회만 · 로스율 `미확정 (D-519)` + 원 수량 | STD 적용 지점 · `stats` / `dashboard` 산식 |
| D-520 | 주문 흐름 병목 기준일 · 알림 배치 시각 | 병목 `미확정 (D-520)` · `jobs due-check` 수동 실행 | `dashboard.py` 기준값 · 배치 스케줄 |

채번 형식 7종은 `가설`(D-509 · `(예시)` 형식)로 진행하고 사람이 규칙을 주면 `sys_number_rule` 행만 바꾼다.

---

## 8. 지켜야 할 것 (Global Constraints)

- **명령은 전부 `uv run …`** — 시스템 `python3` 를 쓰지 않는다.
- DB **`lcomfine_db`**(PostgreSQL 17 · unix socket `/tmp`) · 포트 **8020** · 환경변수 접두 **`LCOMFINE_`**.
- **비밀은 `.env` 에만** — 세션 비밀 · 시드 비밀번호 · `LCOMFINE_OPENAI_API_KEY` · `LCOMFINE_SSO_SECRET` 의 값을 코드 · 문서 · 커밋에 적지 않는다(G-21).
- **정본은 고치거나 옮기지 않는다.** 정본의 결함이나 모순은 고치지 말고 `decisions.md` 에 적고 최종 보고에 올린다.
- **게이트를 낮추지 않는다.** 테스트를 지우거나 `skip` 하거나 수치를 내리지 않는다.
- **한 파일은 한 사람만.** 소유는 §3.2 · §3.3.
- **로컬 커밋만.** push · 배포 · 외부 전송 없음.
- **이 폴더 밖은 읽기만 한다.** 다른 사업 폴더와 그 DB 를 고치지 않는다.
- **추적 · 집계는 조회다.** 추적 결과 · 대시보드 수치를 캐시 테이블에 쌓지 않는다(D-505). 번호는 `numbering`, 알림은 `notify`, 집계 SQL 은 `dashboard` · `stats`, AI 는 `ai` 한 곳에서만.
- **조용한 실패 금지 · 지어내지 않기 · 중복 만들지 않기**(공용 매크로 · 헬퍼를 쓴다).
