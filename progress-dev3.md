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
- (웨이브 D) 스캔 진입에서 없는 번호: JSON 은 422, 브라우저는 **같은 화면을 422 로** 다시 그린다 — `#scan-result` 배너(큰 글씨) + 빈 스캔칸(D-201 · D-308). 검사 결과·출하 LOT 열기는 `lineage.resolve` 로 찾는다(공백 제거 · 소문자 → 대문자).
- (웨이브 D) `routers/qua.py` 의 `scan_failure(request, exc)` · `scanned_roll(roll_no) -> lineage.Node` — 출하(`shp.py`)가 같이 쓴다. 템플릿 조각 `templates/qua/_scan.html`(`scan.styles()` · `scan.result(flash, scan_error)`), 스크립트 없음.

### 1.3 이관 배치 `lcomfine.migration`

```
uv run python -m lcomfine.migration <validate|load-master|load-print-std|load-jobs|load-history|report> --dir <Import 폴더> [--by <실행자>]
```
`COMMANDS: dict[str, Callable[(directory, *, by=None) -> int]]`. 파일 규격은 `contracts/migration-files.md`(제안본), `(예시)` 파일 한 벌은 `src/lcomfine/migration/examples/`(코드 접두 `IMP-`).

(웨이브 D · D-309) **적재는 화면이 422 로 막는 변경을 하지 않는다** — 그 행은 건너뛰고 오류(줄 번호·키·사유), 종료코드 1. `validate` 도 같은 행을 미리 알린다.
① 작업 실적·롤·출하가 있는 Job 은 덮어쓰지 않는다(값이 같아도 건드리지 않는다) ② 취소된 Job 을 되살리지 않는다 ③ `제품` 이 아닌 품목의 Job ④ 아니록스 선수·셀 용적 ≤ 0. 구현 `migration/commands.py` 의 `_check_rules`.

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

## 2-D. 웨이브 D — QA 결함 수정 실측 (2026-10-03 04:2x)

| 결함 | 고친 것 | 실측 | 검증 방법 |
|---|---|---|---|
| DEF-QA1-004 · DEF-QA3-002 (스캔칸 사라짐) | `GET /qua/inspections?no=` · `GET /shp/shipments?no=` 의 없는 번호 → 같은 화면을 HTTP 422 로 다시 그림(`#scan-result .err.big` · 스캔칸 유지). LOT 추적(`/trc/trace/forward|backward`)도 같게 (D-308) | QA 테스트 **9/9 · 9/9 통과**(그중 개발3 화면 2 + 2) · 브라우저: 두 화면 `http 422 · scan_present · focus_on_scan · message_px 26 · next_scan_received = true` | `uv run pytest -q tests/test_qa1_errors.py -k pop_scan_get_422` · `tests/test_qa3_channel_e2e.py -k "unknown_number"` |
| DEF-QA3-001 (알림 중 스캔 유실 · 포커스) | 개발3 쪽: 두 화면의 스캔칸은 `ui.scan_box`, **자체 스크립트 없음**. 스캔·저장 결과를 본문 배너로도 남김(알림이 다음 스캔으로 닫혀도 사유가 보인다). 알림·포커스 처리는 **아키텍트의 공용 `static/app.js`**(04:24 반영) — 그것이 들어오기 전에 `qua/_scan.html` 에 두었던 임시 스크립트는 **지웠다**(이중 처리 없음) | 브라우저(Playwright Chromium 153 · headless): `/qua/inspections` · `/shp/shipments` `typed_while_popup_reaches_scan = true`(스캔칸 값 `ABC123` — 한 번만 들어감) · `focus_on_scan_after_close = true` · 출하 연속 스캔 `first_scan_rows 1 · second_scan_while_popup_rows 1 · rescan_rows 1 · rescan_warn true` | `uv run pytest -q tests/test_qa3_channel_e2e.py -k test_browser` → 6 passed · 같은 probe 를 스크래치에서 돌려 JSON 값 확인 |
| G-22 의 11·12단계 | (QA 의 `run_e2e.py` 는 돌리지 않았다 — 캡처·저널을 덮어쓴다) 같은 조작을 스크래치 스크립트로: 품질 계정이 롤 3개를 스캔 → 등록 → 「확인」 → 다음 스캔, 현장(POP)이 출하 등록 → 롤 ① → (알림 떠 있는 채로) 롤 ② → 불합격 롤 ③ → ① 재스캔 | **스캔칸을 손으로 누른 횟수 0** · 검사 3건 · 출하 계보 2행 · 불합격·재출하는 경고 알림 + 배너 · 콘솔 오류 0. 임시 데이터 `T3E-` 삭제 | 스크래치 `flow_11_12.py`(Playwright · 포트 8023 을 직접 띄우고 내림) |
| DEF-QA3-005 (이관이 살아 있는 Job 을 덮어씀) | `_check_rules` — 작업 실적·롤·출하가 있는 Job 의 행은 건너뛰고 오류 · rc 1 · `validate` 도 알림 · 적재 중 그 Job 행 잠금 (D-309) | QA 테스트 통과(`overwritten = False`). 개발3 테스트: 실적/롤/출하 각각 → `job.csv 2행 [키]: 작업 실적·롤·출하가 있는 Job 은 덮어쓰지 않는다 — 롤 1개 (F-JOB-02)` · 로그 `read 2 · loaded 1 · error 1` · Job 값 전후 동일 · `report` rc 1 | `uv run pytest -q tests/test_qa3_channel_e2e.py -k test_migration_does_not_overwrite` · `tests/test_dev3_migration.py` (16 passed) |
| 같은 종류의 우회 (조사) | 실측으로 6가지를 재고 3가지를 더 막음: 취소된 Job 되살리기 · 원재료 품목의 Job · 아니록스 선수/셀 용적 ≤ 0. 막지 않은 것과 이유는 D-309 | 수정 전: 셋 다 `rc 0 · 판정 PASS` 로 적재 → 수정 후: `rc 1` + 그 행의 사유, DB 값 그대로. 롤이 달린 생산 LOT 을 다른 Job 으로 옮기는 행은 원래 DB FK 가 막는다(`roll_job_lot_fk`) | 스크래치 `bypass.py`(접두 `T3B-`, 삭제) · `tests/test_dev3_migration.py` 의 3개 테스트 |
| DEF-QA1-002 (ΔE 범위 500) | `_delta_e` — 둘째 자리로 반올림한 값이 100000 이상이면 422 `ΔE 값이 너무 큽니다`(항목 `ΔE`) (D-310) | `99999.999` · `99999.995` · `100000` · `1e15` · `1e999` → 422, `99999.994` → 200(99999.99 저장). 출하 화면에는 숫자 입력 없음. 개발3 화면에 이상한 값 34종을 넣어 500 을 찾음 → `item_id=²` 1건(500) 발견 · 수정 | `uv run pytest -q tests/test_qa1_errors.py -k out_of_range` → 7 passed · 스크래치 `sweep.py` |
| DEF-QA1-007 (숫자 아닌 검사 ID) | 경로 키를 글자로 받아 숫자가 아니거나 bigint 초과면 404 | `/qua/inspections/abc` · `/abc/delete` → 404 `not_found` | `uv run pytest -q tests/test_qa1_errors.py -k 404_non_numeric_path_key` → 9 passed |
| DEF-QA2-003 (소문자 롤 번호) | 검사 등록·스캔 진입을 `lineage.resolve` 로 | 소문자 번호 등록 200 · 스캔 진입 200 | `uv run pytest -q tests/test_qa2_lineage.py -k g08_inspection_scan` → 1 passed |
| DEF-QA3-004 (현황판) 의 개발3 쪽 | `templates/sta/board.html` 에는 새로고침 코드가 없다(공용 `base.html` · `app.js` 가 한다) — **고칠 것 없음** | `test_board_keeps_refreshing_after_an_error_page` 통과(아키텍트 수정) | `uv run pytest -q tests/test_qa3_channel_e2e.py` → 21 passed |
| pytest (개발3) | - | **69 passed** (56 + 13: quality 5 · shipment 2 · migration 5 · trace 1) | `uv run pytest -q tests/test_dev3_*.py` |
| QA 테스트 (QA1 3파일 · QA2 4파일 · QA3 채널 1파일) | - | QA1·QA2 **1163 passed · 2 failed** · QA3 채널 **21 passed** — 실패 2건은 아래 | `uv run pytest -q tests/test_qa1_errors.py tests/test_qa1_functions.py tests/test_qa1_rbac.py tests/test_qa2_*.py` · `tests/test_qa3_channel_e2e.py` |
| 테스트가 남긴 것 | - | `T3*` · `Q3*` 접두의 item·job·roll·shipment·customer·anilox·defect_code·material_lot·job_lot 0 · `sys_migration_log` 0 · inspection 0 · shipment 0 · roll 0 · job 0. 포트 8023 내림 | `psql -h /tmp -d lcomfine_db -Atc "select count(*) from … where … like 'T3%'"` |

남은 실패 2건 (개발3 이 고칠 수 없는 것)
- `tests/test_qa1_rbac.py::test_forbidden_comes_before_validation` — **QA 테스트끼리 어긋난다.** 198행은 `품질` 의 `POST /qua/inspections/abc/delete` 가 **422** `validation_error` 이기를 기대하고, `tests/test_qa1_errors.py::test_404_non_numeric_path_key[/qua/inspections/abc/delete]`(DEF-QA1-007)는 **같은 요청**이 **404** `not_found` 이기를 기대한다. 지시(DEF-QA1-007)대로 404 로 고쳤고 198행은 고치지 않았다 — QA1 이 198행의 기대값을 404 `not_found` 로 바꿔야 한다(그 테스트의 뜻 "권한 있으면 403 이 아니다 · 없으면 403 이 먼저" 는 그대로 성립한다: 199행 403 · 200행 401 은 통과).
- `tests/test_qa2_boundary.py::test_g04_schema_checker_passes` — 아키텍트가 `schema.sql` 에 `sys_user.session_epoch` · `revoked_sessions` 를 넣는 중(계약 렌더본 미반영). 개발3 변경과 무관.

확인하지 못한 것 (웨이브 D)
- `make gate` · `gate-full` · `tools/check_security.py` 는 돌리지 않았다(동시 실행 금지). 검사기의 G-13 · G-15 행은 **같은 함수를 쓰는 pytest**(`test_qa3_channel_e2e.py`)로만 확인했다.
- QA 의 `tools/e2e/run_e2e.py`(G-22 판정)는 돌리지 않았다 — 11·12단계는 스크래치 스크립트로 같은 조작을 했을 뿐이다. 판정은 QA3 재검.
- 실물 스캐너로는 재지 않았다(키보드 입력 + Enter 가정, D-04). 스캐너가 글자 사이 간격 없이 쏘는 경우는 Playwright 의 5ms 간격 타이핑으로만 보았다.
- 전체 `uv run pytest -q` 는 돌리지 않았다(다른 두 사람의 파일이 바뀌는 중) — 개발3 테스트와 QA 테스트 파일만.

## 3. 요청 (스키마 · 계약 · 공용 파일)

| # | 누구에게 | 무엇 | 왜 |
|---|---|---|---|
| 1 | 아키텍트 | `contracts/migration-files.md` 확정 (D-23 · D-303) | 개발3 제안본이다. 특히 ① 파일 이름·열 ② "실행 × 파일마다 한 줄" ③ 필수 11 / 선택 5 ④ `report` 종료코드 |
| 2 | 아키텍트 | `contracts/interfaces.md` §7 에 반영 — `stats.delivery(…, *, today=None)` · `stats.defect_rolls` · `stats.totals` · `stats.period` · `board` 의 반환 `{today, production, quality, delivery, totals}` · 품질 행의 `delta_e_count` | 코드가 계약보다 앞섰다(§1.1). QA2 가 계약만 보고 대조한다 |
| 3 | 아키텍트 | `contracts/function-list.md` 문장 보강 — F-QUA-01 "출하 승인된 롤 422"(D-304) · F-SHP-05 "담긴 롤의 최신 검사가 불합격이면 422"(D-305) · F-TRC-01/02 "출하 LOT 의 정방향 · 원재료 LOT 의 역방향 422"(D-306) | 계약 문장에 없는 422 를 더했다. QA1 이 계약 문장으로 케이스를 짠다 |
| 4 | 아키텍트 | `contracts/interfaces.md` §9 — 개발3 시드는 행을 넣지 않는다(D-307) | 시드 멱등(G-09)을 볼 때 D7·D8 이 0행인 것이 정상임을 적어 둔다 |
| 5 | 사람 (현업) | D-301(단위가 섞인 수량의 합) · D-302(현황판에 띄울 기간) · D-304(출하 뒤 재검사 기록) · D-305(COA 양식) · D-303 §5(과거 이력의 범위, 기존 MES 번호와 채번의 충돌, 파일 인코딩) | 설계도에 없다 |

| 6 | QA1 | `tests/test_qa1_rbac.py` 198행의 기대값 422 `validation_error` → 404 `not_found` (웨이브 D) | 같은 요청(`품질` · `POST /qua/inspections/abc/delete`)을 `test_qa1_errors.py::test_404_non_numeric_path_key` 는 404 로 기대한다(DEF-QA1-007). 둘을 함께 만족할 수 없다 |
| 7 | 아키텍트 | `contracts/migration-files.md` — D-309 의 문장(확정된 ① + 넓힌 ②③④)과 "`validate` 도 같은 행을 알린다" · `anilox.csv` 의 `line_count` · `cell_volume` 「0 초과」 (웨이브 D) | 지금 ④ 는 `commands.py` 의 규칙으로만 있다. §3 에 올리기로 하면 `files.SPECS` 의 `Col(positive=True)` 로 옮기고 렌더본을 다시 찍는다(`test_file_spec_doc_is_rendered_from_code` 가 대조) |
| 8 | 아키텍트 | `contracts/function-list.md` — B-MIG-04 문장에 "작업 실적·롤·출하가 있는 Job 은 덮어쓰지 않는다" · F-QUA-01/04 "소문자 롤 번호도 찾는다 · 롤이 아닌 번호 422" · F-SHP-04 "출하 LOT 이 아닌 번호 422" (웨이브 D) | 계약 문장에 없는 판정을 더했다(D-308 · D-309) |
| 9 | 아키텍트 · 개발1 | 품목 구분(`item_type`) 변경 — 원재료 LOT 이 달린 품목을 `제품` 으로, Job 이 쓰는 품목을 `원재료` 로 바꾸는 것을 **화면(F-BAS-02)도 배치도 받는다**(실측 200 · rc 0) | QA3 가 DEF-QA3-005 끝에 "재지 않았다" 로 적은 것. 배치만의 우회가 아니라 화면 규칙이 없다 — 막을지는 계약의 일 (D-309) |
| 10 | 사람 (현업) · 아키텍트 | D-309 ⓑ — 실적이 있는 Job 의 행이 파일에 **같은 값으로** 다시 들어오면 지금은 오류(rc 1)다. "변경 없음" 으로 넘길 것인가 | 확정된 문장을 글자 그대로 구현했다. 이관한 Job 으로 생산을 시작한 뒤 같은 폴더를 다시 돌리는 운영이면 오류가 줄줄이 난다 |

스키마 변경 요청은 없다. 다른 사람의 파일을 고치지 않았다(`decisions.md` 에 D-301~D-310 을 덧붙인 것과 `contracts/migration-files.md` 제안본을 만든 것뿐 — 웨이브 D 에서는 계약 파일을 건드리지 않았다).
