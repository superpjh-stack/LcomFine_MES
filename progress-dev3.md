# progress-dev3 — 개발3 (품질·출하·조회·연계 / 기능 20 + 이관 배치 6)

> §1 공표(다른 사람이 그대로 쓰는 것) · §2 진행 · §3 요청(스키마·계약·공용 파일). 실측한 것만 적는다.

## 1. 공표

### 1.1 집계 `app/stats.py` (2026-10-03 · 구현됨 — QA2 가 대조할 때 이대로 부른다)

시그니처는 `contracts/interfaces.md` §7 그대로이고 **더한 것만** 적는다. 전부 `select` 다(어떤 테이블에도 쓰지 않는다).

```python
from lcomfine.app import stats

stats.production(date_from, date_to, item_id=None) -> list[dict]   # {item_id, item_code, item_name, work_count, output_qty, scrap_qty}
stats.quality(date_from, date_to, item_id=None) -> list[dict]      # {…, inspection_count, fail_count, fail_rate, avg_delta_e, delta_e_count}
stats.delivery(date_from, date_to, item_id=None, *, today=None) -> list[dict]   # {…, job_count, on_time, late, pending, on_time_rate}
stats.defect_by_type(date_from, date_to, item_id=None) -> list[dict]            # {defect_code_id, defect_code, defect_name, defect_count, roll_count}
stats.board(today=None) -> dict   # {today, production, quality, delivery, totals} — 세 함수를 (today, today) 로 그대로 부른다

# 더한 것
stats.defect_rolls(date_from, date_to, defect_code=None, item_id=None) -> list[dict]   # F-QUA-06 — 집계와 같은 조건의 불량 행 내역
stats.totals(kind, rows) -> dict | None      # kind = production | quality | delivery. 품목별 행을 더한 한 줄. 행이 없으면 None
stats.period(date_from_text, date_to_text) -> (date, date)   # 화면의 기간. 비우면 이번 달 1일 ~ 오늘. 시작 > 끝 은 422
stats.parse_date(text, name) · stats.parse_item(item_id_text) · stats.item_options()
```

- **`delivery` 에 `*, today=None` 을 더했다**(계약 시그니처에 없던 것). "오늘" 을 고정해 다시 계산하려면 준다. 기본은 실행한 날.
- 해석은 `decisions.md` **D-301**(날짜 = `::date` 양 끝 포함 · 합은 없으면 0 · 평균/비율은 없으면 None · 비율은 float · 평균은 DB numeric 그대로) · **D-302**(현황판 = 오늘 하루).
- 행의 순서: 집계 3종은 `item_code`, 불량 유형은 `defect_count` 내림차순 → `defect_code`.
- 대조할 때 주의: `avg_delta_e` 는 PostgreSQL `avg(numeric)` 값이라 자릿수가 길다(`4.3333333333333333`). `fail_rate` · `on_time_rate` 는 파이썬 float.

### 1.2 품질 — 다른 화면이 읽을 수 있는 것

- 롤의 판정 = 그 롤의 **최신 검사**(`inspected_at` 이 가장 늦은 것, 같으면 `inspection_id` 가 큰 것). `routers/qua.py` 의 `latest_inspections(roll_ids) -> {roll_id: {inspection_id, delta_e, result, inspected_at, defects, defect_count}}`.
- 스캔 진입: 검사 결과 `/qua/inspections?no=<롤 번호>` · 출하 `/shp/shipments?no=<출하 LOT 번호>` · 추적 `/trc/trace/forward?no=` · `/trc/trace/backward?no=` · LOT 검색 `/trc/trace?q=<번호 일부>`.
- COA 인쇄 화면 `/shp/coa/{shipment_no}/print` (승인된 출하만 — 아니면 422).

### 1.3 이관 배치 `lcomfine.migration`

```
uv run python -m lcomfine.migration <validate|load-master|load-print-std|load-jobs|load-history|report> --dir <Import 폴더> [--by <실행자>]
```
`COMMANDS: dict[str, Callable[(directory, *, by=None) -> int]]`. 파일 규격은 `contracts/migration-files.md`(제안본), `(예시)` 파일 한 벌은 `src/lcomfine/migration/examples/`(코드 접두 `IMP-`).

## 2. 진행 — 실측 (2026-10-03 03:0x)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| placeholder (개발3 8화면) | **0** — 전체도 잔여 0건 · HTTP 200 35/35 · 권한 위반 0 | `make check-routes` → `PASS — 중메뉴 32 + 공통 3 전부 200 · placeholder 0 · 권한 위반 0` |
| 기능 ↔ 라우트 ↔ 테스트 표식 | 개발3 **20/20** 라우트 · **26/26**(기능 20 + 배치 6) 표식 · 고아 라우트 0 · 배치 명령 6/6. 전체 G-02 PASS(94/94 · 100/100) | `make check-trace` → `G-02 판정: PASS (검사 10 · 실패 0)` · `uv run pytest -q tests/test_dev3_contract.py` |
| pytest (개발3) | **56 passed** — contract 4 · erp 3 · migration 11 · quality 8 · shipment 10 · stats 11 · trace 7 (+ support 는 도우미) | `uv run pytest -q tests/test_dev3_*.py` |
| pytest (전체) | 367 passed · failed 0 (그 시점의 저장소 전체) | `make gate` 의 G-21 실측 |
| `stats.py` | 스텁 아님. 생산·품질·납기·불량 유형을 2001년 3월의 손계산 값과 대조(경계: 3/31 23:59:59 포함 · 4/1 00:00 제외 · 납기 = 오늘 은 미출하 · 분모 0 → None) | `uv run pytest -q tests/test_dev3_stats.py tests/test_dev3_quality.py` |
| 이관 배치 6명령 | `(예시)` CSV 로 4개 적재 명령을 **2회씩** → 행 수 동일(item 2 · customer 1 · process 2 · equipment 1 · defect_code 1 · plate_spec 1 · anilox 1 · ink_formula 1 · 조성 2 · job 2 · job_lot 1) · 로그 32줄(16파일 × 2회) · 오류 행은 건너뛰고 로그·출력에 남음 · `load-history` 데이터 행은 적재 0 + `미확정 (D-01)` · `report` PASS/FAIL · CLI 종료코드 | `uv run pytest -q tests/test_dev3_migration.py` (임시 폴더 · 접두 `T3M-` · 끝나면 삭제) |
| 이관 `(예시)` 폴더 | 16파일 · 오류 0 (검증만 — 적재하지 않았다) | `uv run python -m lcomfine.migration validate --dir src/lcomfine/migration/examples` → `판정: PASS — 파일 16/16 · 오류 0건` |
| 시드 멱등 | `seed_dev3` 2회 — inspection 0 · inspection_defect 0 · shipment 0, 전후 차이 0 (넣는 행이 없다, D-307) | `uv run python -m lcomfine.db.seed_dev3` ×2 |
| 출하 흐름 (API) | 등록(채번) → 롤 스캔(`lineage.ship_roll`, 계보 `출하` 1줄) → 관리자 승인(COA 채번) → COA 출력. 422: 없는 롤 · 재출하 · 소진 · 다른 Job · 불합격 · 롤 아닌 번호 · 승인/취소된 출하 · 롤 0개 승인 · 미승인 COA. 취소 = 계보 행 삭제 + 롤 `재고` | `uv run pytest -q tests/test_dev3_shipment.py` |
| 권한 | 품질 쓰기: 관리자·생산·현장 403 / 출하 쓰기: 품질·관리자 403 / **출하 승인: 생산·현장·품질 403, 관리자만 200** / LOT 추적: 현장 403(3경로) / 미로그인 401 | `tests/test_dev3_quality.py` · `test_dev3_shipment.py` · `test_dev3_trace.py` |
| 쓰기 경계 (P9·P10) | 추적 3경로 · 실적 현황 6경로가 돌린 SQL = select 뿐, 쓰기는 공통 접근 로그 1줄뿐(요청마다 SQL 을 가로채 확인). `trc.py` · `sta.py` 에는 SQL 이 없다 | `test_trace_screens_write_nothing` · `test_status_screens_write_nothing` |
| 접근 로그 (변경) | 쓰기 7기능 전부 `rbac.require_fn(그 ID)` + 성공 직후 `audit.log_change(…, 그 ID, …)` | `tests/test_dev3_contract.py::test_write_endpoints_require_fn_and_log_change` + 기능별 테스트의 `sys_access_log` 조회 |
| 폭 390px (브라우저) | Chrome 에서 폭 390px iframe(뷰포트 375px)으로 측정 — **추적 3화면 · 집계 · 현황판**: 문서 `scrollWidth` = 뷰포트(375), 본문에서 뷰포트를 넘는 요소 0, 안쪽 가로 스크롤 영역 0 (관리자 Web 채널 · 모바일 채널 둘 다). 측정은 로그인한 화면을 정적 HTML 로 떠서 했다(임시 데이터 `T3V-` 는 삭제) | 스크래치 스냅샷 + `document.documentElement.scrollWidth` |
| 현황판 | `?device=board` → `body.ch-board` · `<meta http-equiv="refresh">`(30초) · `마지막 갱신 <시각> · 30초마다 자동 새로고침`. 실제로 30초 뒤 다시 그려지는 것은 **재지 않았다**(태그와 문구만 확인) | `tests/test_dev3_stats.py::test_board_refreshes_itself_and_shows_today` |
| ERP | 어댑터 3메서드 전부 501 `ERP 연계 미확정 (D-02)` · `/erp/{kind}` GET·POST 501(미로그인 401) · `erp.py` 에 `try/except` 없음 | `uv run pytest -q tests/test_dev3_erp.py` |
| 서버 기동 (8023) | `/health` 200 `placeholders 0 · router_include_errors []` · 미로그인 브라우저 `/trc/trace` 303 → `/login` — 확인 뒤 내렸다 | `uv run uvicorn lcomfine.app.main:app --app-dir src --port 8023` · `curl` |
| 테스트가 남긴 것 | 0 — `T3*` 접두 품목·Job 0 · `sys_migration_log` 0 · inspection 0 · shipment 0. 남는 것은 공통인 접근 로그(조회)와 채번 카운터뿐 | `psql` 로 접두 조회 |

확인하지 못한 것
- 실제 브라우저에서 **로그인해서** 화면을 조작하지 않았다(폭 측정은 정적 스냅샷). POP 터치 조작 · 인쇄 미리보기 · COA 바코드의 스캐너 판독은 보지 않았다(G-22 · QA3).
- 현황판이 30초 뒤 실제로 새로고침되는 것, 실제 폭 390px 기기에서의 표시.
- 이관 `(예시)` 폴더(`IMP-`)를 **공유 DB 에 적재해 보지는 않았다**(행이 남는다) — 적재·멱등은 임시 폴더 테스트로만 확인했다.
- `stats` 값이 QA2 의 독립 SQL 과 맞는지(G-10)는 QA2 의 몫이다. 손계산 대조만 했다.

## 3. 요청 (스키마 · 계약 · 공용 파일)

| # | 누구에게 | 무엇 | 왜 |
|---|---|---|---|
| 1 | 아키텍트 | `contracts/migration-files.md` 확정 (D-23 · D-303) | 개발3 제안본이다. 특히 ① 파일 이름·열 ② "실행 × 파일마다 한 줄" ③ 필수 11 / 선택 5 ④ `report` 종료코드 |
| 2 | 아키텍트 | `contracts/interfaces.md` §7 에 반영 — `stats.delivery(…, *, today=None)` · `stats.defect_rolls` · `stats.totals` · `stats.period` · `board` 의 반환 `{today, production, quality, delivery, totals}` · 품질 행의 `delta_e_count` | 코드가 계약보다 앞섰다(§1.1). QA2 가 계약만 보고 대조한다 |
| 3 | 아키텍트 | `contracts/function-list.md` 문장 보강 — F-QUA-01 "출하 승인된 롤 422"(D-304) · F-SHP-05 "담긴 롤의 최신 검사가 불합격이면 422"(D-305) · F-TRC-01/02 "출하 LOT 의 정방향 · 원재료 LOT 의 역방향 422"(D-306) | 계약 문장에 없는 422 를 더했다. QA1 이 계약 문장으로 케이스를 짠다 |
| 4 | 아키텍트 | `contracts/interfaces.md` §9 — 개발3 시드는 행을 넣지 않는다(D-307) | 시드 멱등(G-09)을 볼 때 D7·D8 이 0행인 것이 정상임을 적어 둔다 |
| 5 | 사람 (현업) | D-301(단위가 섞인 수량의 합) · D-302(현황판에 띄울 기간) · D-304(출하 뒤 재검사 기록) · D-305(COA 양식) · D-303 §5(과거 이력의 범위, 기존 MES 번호와 채번의 충돌, 파일 인코딩) | 설계도에 없다 |

스키마 변경 요청은 없다. 다른 사람의 파일을 고치지 않았다(`decisions.md` 에 D-301~D-307 을 덧붙인 것과 `contracts/migration-files.md` 제안본을 만든 것뿐).
