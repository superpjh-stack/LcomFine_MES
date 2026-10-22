# progress-dev3 — 개발3 (SHP · PRP · COL · RPT / 화면 22)

> §1 공표(다른 사람이 그대로 쓰는 것) · §2 진행 · §3 요청(스키마 · 계약 · 공용 파일). 실측한 것만 적는다.
> v2(2026-10-21 정본) 기준. W1 = SHP 3 · PRP 3 · `stats.py`(끝). W2 = COL 7 · `erp_upload.py` · `stats` 수금 함수(끝). **W3 = RPT 9 · `dashboard.py` · `ai.py` · `dataquery.py`(이 판)** — 개발3 placeholder 0.

## 1. 공표

### 1.1 `lcomfine.app.stats` — 집계 SQL (읽기만 · 캐시 없음 · 화면을 열 때마다 다시 센다)

```python
from lcomfine.app import stats

stats.utilization(year: int, month: int) -> dict          # PRP-010
#   {"period": (시작일, 다음 달 1일), "formula": str,
#    "rows": [{equipment_code, equipment_name, days, entries, run_minutes, stop_minutes, rate}],   # rate: Decimal(소수 1) | None(=미수집)
#    "total": {run_minutes, stop_minutes, rate}}
#   설비 = 공통코드(그룹 설비 · 사용) ∪ 그 달 일보에 나온 설비 코드(equipment_name None). 가동률 산식 가설 D-801
stats.machine_stats(date_from: date, date_to: date) -> list[dict]     # PRP-020 · 양끝 포함
#   [{equipment_code, equipment_name, work_orders, entries, produced_qty, good_qty, loss_qty, run_minutes, stop_minutes}]
#   일보가 없는 설비는 값이 None. 로스율은 내지 않는다(미확정 D-519 — stats.LOSS_RATE_DECISION)
stats.completion(date_from: date, date_to: date, customer_id: int | None = None) -> dict   # PRP-030
#   생산 완료 = product_receipt(취소 표시 제외) · 기간 = 입고일(양끝 포함) · 거래처 = 지시 → 의뢰의 거래처
#   {"rows": [{customer_id, customer_code, customer_name, item_code, item_name, work_orders, receipts, qty}],
#    "monthly": [{"ym": "YYYY-MM", "receipts", "qty"}], "total": {"work_orders", "receipts", "qty"}}
stats.request_shipments(request_ids: list[int] | None = None) -> dict[int, dict]          # 납기 보조 (TRK · HOME 이 써도 된다)
#   {request_id: {"ordered_qty": 상태 지시 출하의 할당 합, "shipped_qty": 확정 출하의 출하 행 합, "last_confirmed_at"}}
#   취소 출하는 세지 않는다 · 반품·정정(shipment_adjust)은 빼지 않는다(D-515) · 출하가 없는 의뢰는 키가 없다
stats.UTILIZATION_FORMULA · stats.LOSS_RATE_DECISION ("D-519")
```

### 1.2 SHP 이 남기는 것 (다른 화면 · QA 가 읽는 모양)

| 무엇 | 값 |
|---|---|
| `shipment_order.status` | `지시`(F-SHP-011) → `확정`(F-SHP-021) / `취소`(F-SHP-012 에서 LOT 줄을 전부 지우고 저장 — Ruling 21 · 할당 전부 해제 · `shipment_line` 0 · 알림 없음 · 되돌리지 않는다). 취소 출하는 `request_shipments` 에 세지 않는다 |
| 할당 | `shipment_line.qty` = 그 (LOT, 위치) `lot_stock.allocated_qty` 에 더한 양. 할당은 `select … from lot_stock … for update`(id 오름차순) 안에서 판정 |
| 확정 | LOT 라인마다 `lot_stock.qty` · `allocated_qty` 를 같은 양만큼 줄이고 `stock_move` 1행: `move_kind='출하'` · `lot_kind='제품'` · `lot_id`=제품 LOT · `from_location_id`=위치 · `to_location_id` NULL · `ref_table='shipment_order'` · `ref_id`=출하 id |
| 판정 판단 | LOT 의 판정 = 그 LOT(없으면 판정이 있는 가장 가까운 원 LOT — 분할)의 최대 seq 행(D-515 · 개발2 `trace` 와 같은 규칙). 미판정 · 불합격 · 재고 상태 가용 아님 → 확정 422 |
| 반품·정정 | `shipment_adjust.qty` 저장 부호: 반품은 항상 음수(입력이 양수여도), 정정은 입력 그대로(0 금지). 반품 누계 ≤ 출하 수량(LOT 를 고르면 그 LOT). 재고 불변 |
| 알림 `shipment_ordered` (→ SH) | link `/shp/confirm?no=<출하번호>` · dedupe `shipment_ordered:<출하번호>` — 확정하면 `handle_by_link` 로 닫힌다 |
| 알림 `shipment_confirmed` (→ SL · AC) | link `/shp/history?no=<출하번호>` · dedupe `shipment_confirmed:<출하번호>` |
| 개발2 `judged` 알림 | link `/shp/orders?lot=<제품 LOT>` 를 SHP-010 이 받는다(1번 줄에 그 LOT 선택). 그 LOT 를 할당해 출하 지시를 등록하면 등록한 부서의 그 알림이 닫힌다 |
| 화면 조회 인자 | SHP-010 `?customer=&status=&due_from=&due_to=&request_no=&lot=&edit=<id>` · SHP-020 `?no=` · SHP-030 `?date_from=&date_to=&customer=&item=&no=` · 역추적 링크 `LOT-020?shipment_no=` |

### 1.3 W2 공표 — `stats.customer_receivable` · `stats.due_compliance` (개발1 TRK-030 · TRK-020 이 그대로 쓴다 · Ruling 23)

```python
from lcomfine.app import stats

stats.customer_receivable(customer_id: int) -> dict        # TRK-030 수금 칸 — 읽기만 · 화면을 열 때마다 다시 센다
#   {"customer_id": int,
#    "asof": date | None,            # ERP 업로드 기준일 = 반영 회차의 마지막 기준 기간 끝 (= stats.erp_asof()) · 회차가 없으면 None
#    "erp_codes": [str],             # 그 거래처에 매핑된(사용 중) ERP 거래처코드
#    "rows": int,                    # 반영 회차의 오류 없는 행 수 (그 거래처)
#    "sales_amount": Decimal | None, "collected_amount": Decimal | None,
#    "receivable_amount": Decimal | None,   # = Σ매출 − Σ수금 (D-803) · 기간 제한 없음(올라온 전부)
#    "last_txn_date": date | None,
#    "status": "ok" | "미수집" | "미확정 (D-516)",   # 화면 글자로 그대로 쓴다
#    "decision": None | "D-516"}
#   매핑된 코드가 없거나 반영 행이 없으면 status "미수집" (금액 전부 None).
#   매출액 열이 매핑되지 않았으면 status "미확정 (D-516)" — collected_amount 는 값, sales · receivable 은 None.
#   화면 표기 권장: status != "ok" 이면 status 글자를 그대로 칸에, "ok" 이면 숫자 + 「기준일 asof」.

stats.due_compliance(period) -> dict                       # TRK-020 납기 준수율 — 읽기만 (산식 가설 D-804)
#   period = "YYYY-MM" 또는 (시작일, 종료일) (date · 양끝 포함). 그 밖 ValueError.
#   {"period": (f, t), "total": n, "on_time": n, "late_done": n, "late_open": n, "in_progress": n,
#    "rate": Decimal(소수 1) | None,     # None = 분모 0 = 미수집 (0 % 로 지어내지 않는다)
#    "rows": [{request_id, request_no, customer_code, customer_name, item_code, item_name, qty, due_date, shipped_qty,
#              last_confirmed_on, bucket}],   # bucket ∈ 납기 안 완료 · 지연 완료 · 지연 · 진행
#    "formula": stats.DUE_COMPLIANCE_FORMULA}
#   모집단 = 납기(due_date)가 기간 안인 취소 아닌 의뢰 · 완료 = 확정 출하 합 ≥ 의뢰 수량 · 준수율 = 납기 안 완료 ÷ (납기 안 완료 + 지연 완료 + 지연) × 100

stats.erp_asof() -> date | None                            # 「ERP 업로드 기준일」 한 줄 — HOME 회계부 카드 · TRK-030 이 써도 된다
stats.aging(asof) -> dict                                  # HOME 회계부 카드 「90일 초과 미수」 = len(stats.aging(asof)["over90"]) · undecided 면 `미확정 (D-516)`
```

### 1.4 COL 이 남기는 것 · `erp_upload` 시그니처 (interfaces.md §9 대비 실제 — §3 에 갱신 요청)

```python
from lcomfine.app import erp_upload
erp_upload.FIELDS                                   # {"customer_code": "거래처코드", "txn_date": "일자", "sales_amount": "매출액", "collected_amount": "수금액",
                                                    #  "balance_amount": "잔액", "method": "수단", "bill_due_date": "어음 만기"} — parsed 키 · erp_column_map.field
erp_upload.read_xlsx(file: bytes) -> list[dict]     # 첫 시트 · 1행 열 이름 · 행 {열 이름: 글자, "__row_no": 엑셀 행} · 빈 줄 제외
erp_upload.headers(file: bytes) -> list[str]
erp_upload.column_map() -> dict[str, str]           # 항목 → 엑셀 열 이름 (없으면 {})
erp_upload.save_column_map(cur, mapping, user) -> int
erp_upload.check_map(cmap, file_headers=None)       # 필수 · 금액 · 열 존재 — 어긋나면 UploadError(field, reason, message)
erp_upload.validate(rows, cmap, customer_map=None) -> [{"row_no", "raw", "parsed", "error"}]
erp_upload.apply(cur, period_from, period_to, validated_rows, user, *, source_file="") -> int   # 새 회차 id (교체 · 알림 포함)
erp_upload.remap(cur, batch_id=None, erp_code=None, user=None) -> dict                         # {"reviewed": 다시 해석한 행, "changed": error 글자 바뀜, "applied": error → None(반영에 듦), "still_error": 여전히 오류} (DEF-QA2-004)
erp_upload.unmapped_codes() -> [{erp_code, rows, batches, first_seen, last_seen, has_error}]
erp_upload.mapped_fields() -> {항목: bool} · erp_upload.error_link(batch_id) -> "/col/upload-history?batch=<id>"
erp_upload.UNMAPPED_PREFIX == "거래처 코드 미매핑" · erp_upload.DECISION == "D-516" · erp_upload.MAX_BYTES (20MB)
```

| 무엇 | 값 |
|---|---|
| `erp_upload_batch.status` | `반영`(기간마다 하나) → `교체`(+ `replaced_by` = 새 회차 · 행 보존). 같은 기간 재업로드 = `round_no` + 1 |
| `erp_upload_row.error` | None = 반영에 든 행 · 글자 = 제외(「항목: 사유 · 항목: 사유」 · 미매핑은 `거래처 코드 미매핑: <코드>`) |
| 미매핑 목록 | 반영 회차 행의 `parsed.customer_code` 중 사용 중 매핑 없는 코드(`erp_upload.unmapped_codes`) |
| 알림 `erp_upload_error` (→ AC) | link `/col/upload-history?batch=<id>` · dedupe `erp_upload_error:<회차 번호>` · 교체되거나 재해석으로 오류 0 이면 `handle_by_link` 로 닫힘 |
| `POST /col/uploads` 폼 | `action` = `apply`(기본) · `preview`(쓰지 않음) · `map`(`map_<항목>` 7칸) · `period_from` · `period_to` · `file`(.xlsx) — JSON 응답 `{id, batch_no, round_no, rows, errors, replaced}` / preview `{applied: false, rows, errors, items}` / map `{changed, mapping}` |
| `POST /col/customer-map` 폼 | `erp_code`(필수) · `erp_name` · `customer_id`(필수) → `{id, reinterpreted, applied, still_error, remapped(=applied)}` · 문장 「다시 해석한 행 N · 그중 반영 M (· 다른 오류로 여전히 제외 K)」 / `/{id}` + `use_yn` → 같은 키 + `use_yn` / `/{id}/delete` → `{id, disabled, refs}` |
| 화면 조회 인자 | COL-010 `?batch=` · COL-020 `?batch=&status=` · COL-030 `?q=&use=&edit=&code=` · COL-040 `?date_from=&date_to=&customer=&method=&format=xlsx` · COL-050 `?asof=&show_zero=1` · COL-060 `?asof=` · COL-070 `?ym_from=&ym_to=&customer=` |
| 집계 원천 (COL-040~070 · TRK) | 반영 회차 · `error is null` · 사용 중 매핑 — `v_dq_collections` 와 같은 모양(`stats._ERP_CTE`) |


### 1.5 W3 공표 — `dashboard` 8 함수 · `ai` · `dataquery` (QA2 G-15 독립 재계산 · QA3 G-16 · G-17 · 개발1 SYS-040 이 그대로 쓴다)

```python
from lcomfine.app import dashboard, ai, dataquery

# ── dashboard — 집계 SQL 은 여기(+ 재사용하는 stats)뿐 · 읽기만 · 캐시 없음 · 세부 정의 D-805 (D-512 의 빈칸)
dashboard.orders(period, customer_id=None)      # RPT-010   dashboard.shipment(period, customer_id=None)    # RPT-050
dashboard.production(period, customer_id=None)  # RPT-020   dashboard.collection(period, customer_id=None)  # RPT-060
dashboard.quality(period, customer_id=None)     # RPT-030   dashboard.order_flow(period, customer_id=None)  # RPT-070
dashboard.inventory(period, customer_id=None)   # RPT-040   dashboard.summary(period, customer_id=None)     # RPT-080
#   period = "YYYY-MM" | (시작일, 종료일)(date · 양끝 포함) — 그 밖 ValueError. customer_id 는 010 · 050 · 060 · 070 · 080 만 적용(020 · 030 · 040 은 기간만 · D-805)
#   반환(8 함수 공통):
#   {"kpis":   [{"key", "label", "value": 수 | None, "digits", "unit", "text": str | None, "note"}],   # value None = 미수집 · text 가 있으면 수 대신 글자(미확정 (D-519) 등)
#    "series": {이름: [{"label", "value": 수 | None}]},     # 구간 라벨 전부(일 'YYYY-MM-DD' 또는 월 'YYYY-MM') · 행 없는 구간 None
#    "tables": {이름: [dict, …]},
#    "asof":   date | None,            # RPT-060(+ 070 · 080) = stats.erp_asof() · 그 밖 None
#    "period": (f, t), "bucket": "day" | "month", "customer_id", "notes": [str]}
#   kpi key 목록 —
#   orders:     requests qty customers not_started                       series: requests qty due        tables: top_customers not_started due_distribution
#   production: work_orders order_qty produced_qty good_qty loss_qty loss_rate(text D-519) utilization(D-801)
#                                                                         series: good_qty produced_qty by_equipment   tables: by_work_order by_equipment(= stats.machine_stats)
#   quality:    inspected_qty defect_qty loss_rate(text D-519) judgements rejected_lots rejudged
#                                                                         series: defect_qty inspected_qty defects     tables: rejected rejudged defects_by_type daily_by_work_order
#   inventory:  material_receipts material_receipt_qty issues issue_qty product_receipts product_receipt_qty adjusts adjust_diff
#                                                                         series: receipt_qty issue_qty               tables: top_moves long_stay adjusts receipts_by_item
#   shipment:   shipments qty customers due_rate(D-804) on_time late_done late_open
#                                                                         series: qty shipments by_customer           tables: by_customer by_item recent due_rows
#   collection: asof(text) collected sales(text D-516 가능) shipped_qty over90(text 미수집/D-516 가능)
#                                                                         series: collected shipped_qty aging         tables: monthly by_customer over90 aging aging_buckets
#   order_flow: requests shipped avg_1..avg_5(단계 평균 소요일) bottleneck(text D-520)
#                                                                         series: avg_days collected                  tables: rows(days[단계]) stages collection_monthly collection_by_customer
#   summary:    위 KPI 들을 group 과 함께(kind 일일 = RPT-040 · 050 / 주간 · 월간 = + 010 · 020 · 060) · tables.sections[{title, screen_id, kpis}] · 추가 키 "kind"
dashboard.period_bounds(period) · dashboard.summary_kind(f, t) · dashboard.TOP_N(10) · dashboard.DAY_BUCKET_MAX_DAYS(31) · dashboard.FLOW_STAGES
dashboard.UNDECIDED_LOSS == "미확정 (D-519)" · dashboard.UNDECIDED_BOTTLENECK == "미확정 (D-520)"

# ── ai — OpenAI 를 부르는 유일한 곳(D-504) · 호출마다 sys_ai_call_log 1행(실패 · 키 없음 포함) · 키 값은 어디에도 적지 않는다
ai.complete(system, user, *, kind, cur=None, user_id=None) -> str   # 키 없음 → ai.NotConfigured · 실패 → ai.CallFailed(사유) — 둘 다 로그 뒤 올린다
ai.NotConfigured · ai.CallFailed · ai.NOT_CONFIGURED_MESSAGE == "AI 키가 설정되지 않았습니다 — LCOMFINE_OPENAI_API_KEY"
ai.set_client(fake)             # 테스트 주입 — fake(model, system, user) -> str · None 이면 실제 호출로
#   sys_ai_call_log 행: kind('데이터 질의') · model · ok · ms · error(키 없음 문장 · HTTP n · 연결 실패 …) · user_id · created_at

# ── dataquery — 검증 · 실행 · 로그는 여기뿐(D-513 · D-806)
dataquery.VIEWS                              # {뷰: None | (부서 코드…)} — 수금 뷰 2 = ("SL", "AC", "ADM", "EX")
dataquery.allowed_views(role_code) -> [str]
dataquery.validate_sql(sql, allowed_views) -> str    # 통과 = 정리된 SQL · 어긋나면 dataquery.QueryRejected(이유) — 라우터는 422 「허용되지 않는 질의 — 이유」
dataquery.ask(cur, user, question) -> dict   # {"query_no", "question", "sql", "ok", "columns", "rows", "row_count", "truncated", "error", "ms", "views"}
#   거부 · 키 없음 · 호출 실패 · 실행 실패는 예외가 아니라 ok=False + error (로그를 남긴 뒤 라우터가 422). data_query_log 1행 / 질의 · sys_ai_call_log 1행 / 호출
dataquery.recent(user, limit=20)             # 최근 질의 목록(화면)
dataquery.MAX_ROWS(200) · STATEMENT_TIMEOUT_MS(5000) · QUESTION_MAX_CHARS(1000) · REJECT_PREFIX("허용되지 않는 질의")
```

| 무엇 | 값 |
|---|---|
| RPT 화면 조회 인자 | RPT-010~070 `?date_from=&date_to=&customer=`(거래처는 010 · 050 · 060 · 070) · 기본 = 이번 달 1일 ~ 오늘 · 기간 상한 3년 · 형식 오류는 422 로 화면을 다시 그린다 · RPT-080 `?tab=daily|weekly|monthly&asof=&customer=` · RPT-130 GET 인자 없음 |
| 화면 표식 | KPI `data-kpi="<key>"` · 차트 `<section data-series="<이름>">`(SVG `<title>` 「라벨: 값」 + `table[data-series-table]` 같은 숫자 · 소수 0 `num`) · 표 `<section data-table="<이름>">` · RPT-080 `data-section="<화면 ID>"` · RPT-130 결과 `data-result="<질의 번호>"` |
| `POST /rpt/query` | 폼 `question`(필수 · 1000자) → JSON 200 `{ok, message, query_no, sql, columns, rows, row_count, truncated, ms}` / 422 `{message: "허용되지 않는 질의 — …" \| "AI 키가 설정되지 않았습니다 — LCOMFINE_OPENAI_API_KEY" \| "AI 호출 실패 — …" \| "실행 실패 — …", fields: [질의 번호 · SQL]}` · 브라우저 성공은 같은 화면 200 에 SQL · 결과 표(D-806) |
| 변경 로그 | `sys_change_log` function_id `F-RPT-132` · target `data_query_log:<질의 번호>` (성공만) |


## 2. 진행 (W1 — 기능 10/10)

| 기능 | API | 상태 | 테스트 (`@pytest.mark.fn`) |
|---|---|---|---|
| F-SHP-011 출하 지시 등록 | `POST /shp/orders` | 완료 | 6 — 할당·알림·변경 로그 · 의뢰 불러오기 · 422 11가지 · 403 · **동시 할당(스레드 2 → 200 1 · 422 1, 라우터 문장)** · **행 잠금 대기** |
| F-SHP-012 출하 지시 수정 | `POST /shp/orders/{id}` | 완료 | 3 — 할당 이동·해제 · 가용 초과 · 누락(LOT 만 · 수량 만) · 404 · 403 · 확정된 출하 422 · **라인 전부 제거 = 지시 취소(Ruling 21)**: 상태 취소 · 할당 0 · 현재고 불변 · 알림 없음 · 변경 로그 1 · 취소 뒤 확정 422 · 수정 422 · 확정된 출하는 줄을 비워도 422 |
| F-SHP-013 출하 지시 조회 | `GET /shp/orders` | 완료 | 1 — 목록 · 의뢰 채움 · `?lot=` · 422 · 404 · 403 |
| F-SHP-021 출하 확정 | `POST /shp/confirm/{id}/confirm` | 완료 | 2 — qty·allocated 함께 감소 · stock_move 라인마다 1행 · 알림 · 재확정 422 · 미판정/재판정 불합격 422(재고 불변) |
| F-SHP-022 출하 확정 대상 조회 | `GET /shp/confirm` | 완료 | 1 |
| F-SHP-023 반품·정정 등록 | `POST /shp/confirm/{id}/adjust` | 완료 | 1 — 확정 전 422 · 재고 불변 · 누계 초과 · 불변 이력 트리거 |
| F-SHP-031 출하 이력 조회 | `GET /shp/history` | 완료 | 1 — 반품·정정 행이 원 출하 아래 |
| F-PRP-011 월별 가동률 조회 | `GET /prp/utilization` | 완료 | 1 — 손으로 센 값 = 화면 · 미수집 · 422 · 403 · 읽기만 |
| F-PRP-021 기계별통계 조회 | `GET /prp/machines` | 완료 | 1 — 원 수량 · `미확정 (D-519)` |
| F-PRP-031 생산완료집계 조회 | `GET /prp/completion` | 완료 | 1 — 취소 입고 제외 · 기간 밖 제외 |
| (stats) `request_shipments` | — | 완료 | 1 (표식 없음 — API 가 아님) |

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 개발3 테스트 | **19 passed** (3.2s) | `uv run pytest tests/test_dev3_*.py -q` |
| 테스트가 남긴 행 | customer · item · product_lot `T3%` 0 · 알림 0 | `psql -h /tmp lcomfine_db -c "select count(*) from customer where customer_code like 'T3%'"` |
| G-02 SHP · PRP 고아 | 고아 ①②③ 목록에 SHP · PRP 0 | `uv run python tools/check_trace.py` |
| G-03 SHP · PRP 화면 | 칸 있는 부서 전부 200 · 칸 없는 부서 403 「이 화면을 볼 권한이 없습니다」(ST→SHP-010 · PR→SHP-020 · PR→SHP-030 · SH→PRP-010 · SH→PRP-020 · SL→PRP-030 실측) · placeholder 개발3 16 (COL 7 · RPT 9 — W2 · W3) | `uv run python tools/check_routes.py` |
| G-04 쓰기 경계 | PASS (PRP 쓰기 0) | `uv run python tools/check_schema.py` |

커밋: `d1c9a12` SHP · `c8aecd7` stats · PRP · D-801 · `b9bad23` 경로 인자 `{id}`.


### 2.1 W1 QA 결함 · 아키텍트 판정 반영 (2026-10-21 · 커밋은 오케스트레이터)

| 결함 | 고친 것 | 실측 | 검증 |
|---|---|---|---|
| QA1 — 화면 GET 의 403 문장 | 화면 GET 6 개(SHP-010 · 020 · 030 · PRP-010 · 020 · 030)의 의존성을 `rbac.require_fn("F-…")` → `rbac.require_screen("<화면 ID>")` 로. 쓰기 POST 4 개의 `require_fn` 은 그대로 | 칸 없는 부서 6 쌍 전부 403 `이 화면을 볼 권한이 없습니다` | `grep -n "require_" src/lcomfine/app/routers/{shp,prp}.py` · 위 G-03 행 |
| QA2 — Ruling 21 (F-SHP-012 라인 전부 제거 = 지시 취소) | `_lines(…, allow_empty=True)` 로 빈 목록을 받고, 상태 `지시` 의 출하에서 줄이 0 이면 **같은 트랜잭션**에서 `shipment_order.status='취소'` · `shipment_line` 삭제 · 옛 할당 `lot_stock.allocated_qty` 전부 해제. 알림 없음. `http.saved` 「출하 지시 … 를 취소했습니다 — 할당 n줄(합) 해제」 · `audit.log_change` detail 「지시 취소(라인 전부 제거 · Ruling 21) …」. 확정·취소된 출하는 여전히 422(취소 문장은 「취소된 출하는 고칠 수 없습니다」 — 반품·정정 안내는 확정에만). SHP-010 수정 패널에 안내 한 줄 「LOT 줄을 전부 지우고 저장하면 지시가 취소됩니다(할당 전부 해제 …)」 | 테스트 `test_update_with_no_lines_cancels_order`: 200 · status 취소 · line 0 · allocated (0, 0) · qty 불변 · 알림 건수 불변 · change_log 1 · 확정 422 · 재수정 422 · 확정된 출하 빈 줄 422(상태 확정 유지) | `uv run pytest -q tests/test_dev3_shp.py -k cancels` |
| (딸림) 「누락 422」 테스트 | `data={}` 는 이제 취소라서, 누락 검사는 LOT 만 있고 수량 없음 · 수량만 있고 LOT 없음 두 경우로 바꿈(지우지 않았다) | 둘 다 422 | 같은 파일 `test_update_order_moves_allocation` |

실측 명령 결과(이 수정 뒤): `uv run pytest -q tests/test_dev3_*.py` → **19 passed**; 테스트 잔류 행 customer · product_lot · shipment_order `T3%` **0 · 0 · 0**; `check_routes` · `check_trace` 의 실패 목록에 SHP · PRP 는 0 건(실패는 개발1 WO-040 · SYS-010 · SYS-040 500 · DOC 고아 — 개발3 밖).

## 2-W2. 진행 (W2 수금 — 기능 11/11 · 2026-10-22)

| 기능 | API | 상태 | 테스트 (`@pytest.mark.fn`) |
|---|---|---|---|
| F-COL-011 ERP 수금현황 업로드 | `POST /col/uploads` | 완료 | 1 — 반영 · 오류 2행 제외 · AC 알림 1행(link · 문장) · 재업로드 → 회차 2 반영 · 이전 교체 + `replaced_by` · 이전 행 4 보존 · 교체 회차 알림 닫힘 · `v_dq_collections` 반영분만 · 변경 로그 · 422 9가지(파일 · 기준 기간 · 역순 · 비 xlsx · 열 없음 · 데이터 행 0 · 동작 · 매핑 필수 · 같은 열 두 항목 · NUL) · SL/SH 403 |
| F-COL-012 업로드 결과 조회 | `GET /col/uploads` | 완료 | 1 — 회차 번호 · 오류 행 `data-row` · `?batch=` · 404 2 · SL 200(폼 없음) · SH 403 · **preview 는 batch · row · notification 수 불변** · HTML 미리보기 |
| F-COL-021 업로드 이력 조회 | `GET /col/upload-history` | 완료 | 1 — 반영/교체됨 칩 · `?batch=` 오류 행 · `?status=` 필터 · 422 · 404 · SH/EX 403 |
| F-COL-031 거래처 코드 매핑 등록 | `POST /col/customer-map` | 완료 | 1 — 미매핑 목록 → 등록 → `remapped 2` · error_count 0 · 알림 닫힘 · `customer_receivable` 미수집 → ok(100/40/60) · 중복 422 · 누락 2 · NUL(ERP 거래처명) · 없는 거래처 422 · SL 403 |
| F-COL-032 거래처 코드 매핑 수정 | `POST /col/customer-map/{id}` | 완료 | 1 — 사용 중지 → 미매핑 목록에 다시 · 행 불변 · 재개 → 재해석 · 404 2 · 422 2 · 403 |
| F-COL-033 거래처 코드 매핑 삭제 | `POST /col/customer-map/{id}/delete` | 완료 | 1 — 참조 있음 → 사용 중지(`disabled` · `refs`) · 없음 → 삭제 · 404 · 403 |
| F-COL-034 거래처 코드 매핑 조회 | `GET /col/customer-map` | 완료 | 1 — 검색 · `?use=` · 422 · 404 · `?code=` 채움 · SL 200 · SH 403 |
| F-COL-041 수금 현황 조회 | `GET /col/collections` | 완료 | 1 — 기간 · 거래처 · 수단 필터 · 어음 도래/예정 · `?format=xlsx`(EX · openpyxl 로 다시 읽어 행 4) · 422 3 · SH 403 · SL 200 |
| F-COL-051 거래처별 미수 조회 | `GET /col/receivables` | 완료 | 1 — 매출 100 − 수금 70 = 미수 30 · ERP 잔액 마지막 행 · 미수 0 숨김/보임 · **매출 열 매핑 제거 → `미확정 (D-516)`**(화면 · `customer_receivable` status · COL-060) → 복원 · 422 · 403 |
| F-COL-061 미수 연령 조회 | `GET /col/aging` | 완료 | 1 — 경과 10/45/75/120 일 → 구간 80/150/300/300 · 기준일 뒤 행 제외 · `data-over90` · D-803 표기 · 422 · SH 403 · EX 200 |
| F-COL-071 출하 대비 수금 조회 | `GET /col/shipment-vs-collection` | 완료 | 1 — 확정 출하 2건 15 + ERP 1,000/400 (3월) · 4월 1건 7 + 0/600 · 지시 상태 출하 제외 · 미매핑 코드 제외 · **독립 SQL(shipment_order · v_dq_collections) 과 일치** · SH 200(R) · PR 403 · 422 3 |
| (stats) `due_compliance` | — | 완료 | 1 (표식 없음) — 납기 안 완료 · 지연 완료 · 지연 = 1 · 1 · 1 → 33.3 · 진행 · 분모 0 → None · ValueError 2 |

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 개발3 테스트 | **31 passed** (4.7s) = W1 19 + W2 12 (`tests/test_dev3_col.py`) | `uv run pytest -q tests/test_dev3_*.py` |
| 전체 테스트 | **261 passed · 0 failed** (40.7s) | `uv run pytest -q` |
| 테스트 잔류 행 | `erp_upload_batch` 0 · `erp_upload_row` 0 · `erp_customer_map` 0 · `erp_upload_error` 알림 0 · `T3%` 거래처 0 · `erp_column_map` 7(시드 · 테스트가 스냅샷으로 되돌림) | `psql -h /tmp lcomfine_db -c "select count(*) from erp_upload_batch"` 등 |
| G-02 COL | 라우트 없는 계약 27 → **16**(COL 0 · 남은 16 = RPT · DOC) · 표식 없는 기능 27 → **16**(COL 0) · 이어진 기능 **120/136** | `make check-trace` |
| G-03 COL | 화면 67 × 칸 있음 260/260 → 200 · 칸 없음 276/276 → 403 · placeholder 18 → **11**(개발1 2 DOC · 개발3 9 RPT · **COL 0**) | `make check-routes` |
| G-05 쓰기 경계 | PASS — 라우터 15(col.py 포함) 쓰기 테이블 ⊆ 계약 · `stats.py` 쓰기 0 | `uv run python tools/check_data.py` G-05 행 |
| 시드 | `seed_dev3.py` — `erp_column_map` 7행(정본 낱말 · D-802) · 멱등(`on conflict do nothing`) | `uv run python -m lcomfine.db.seed_dev3` 2회 → 「새 행 0 · 전체 7」 |
| G-11 `erp_upload_error` · G-12~14 | 기능은 있다 — **QA2 의 `check_data.py` 가 아직 「W2 — 없다」로 적어 미검증/FAIL** (QA2 가 W2 로 잰다). 재현: 테스트 `test_upload_applies_replaces_and_keeps_history` 가 회차 교체 · 보존 · 오류 제외 · 알림 AC 1행을, `test_shipment_vs_collection_independent_aggregates` 가 G-14 독립 재계산을 그대로 보인다 | `uv run pytest -q tests/test_dev3_col.py -k "replaces or shipment_vs"` |
| 결정 | D-802(업로드 규칙 · 미매핑 · 교체 3단계 · 알림 · 시드 열 이름) · D-803(미수 · 연령 산식) · D-804(납기 준수율) — 전부 `가설` | `decisions.md` |

### 2-W2.1 QA2 결함 반영 (2026-10-22)

| 결함 | 고친 것 | 실측 | 검증 |
|---|---|---|---|
| DEF-QA2-004 (경미) — F-COL-031 · 032 「다시 반영된 행 N」 이 error 글자가 바뀐 행 수 | `erp_upload.remap` 이 `{reviewed, changed, applied, still_error}` 를 돌려주고, 라우터 `_remap_text` 가 「다시 해석한 행 N · 그중 반영 M · 다른 오류로 여전히 제외 K」 로 적는다(M = error 가 None 이 된 행). JSON `reinterpreted · applied · still_error · remapped(=applied)` | 미매핑 2 + (미매핑+날짜 오류) 1 + (미매핑+금액 오류) 1 → 「다시 해석한 행 4 · 그중 반영 2 · 다른 오류로 여전히 제외 2」 · `error_count` 2 · 뷰 2행 · 미매핑 글자 0 · 알림 열린 채 | `uv run pytest -q tests/test_dev3_col.py -k counts_only` (새 테스트 `test_customer_map_create_counts_only_rows_that_become_applied` · `@pytest.mark.fn("F-COL-031")`) · **13 passed** |

| DEF-QA1-006 (QA1) — 전산 관리자(ADM)가 업로드 · 매핑하면 회계부 알림이 닫히지 않음 | **아키텍트 수정(Ruling 27)** — `notify.resolve_by_link(cur, link, user)`(수신 부서 무관하게 닫음) 추가 · `erp_upload.py` 의 `notify.handle_by_link(cur, error_link(...), user)` 두 곳(회차 교체 · 재해석 오류 0)을 `notify.resolve_by_link(...)` 로 바꿈(오케스트레이터 적용 · 개발3 코드 변경 없음) | `grep -n resolve_by_link src/lcomfine/app/erp_upload.py` → 2곳 | `uv run pytest -q tests/test_dev3_col.py` **13 passed** |
| (계약) `interfaces.md` §9 | 아키텍트가 `erp_upload.remap` 의 dict 반환(§1.4 · §3-11)을 반영했다 | `grep -n "remap" contracts/interfaces.md` | — |

| DEF-QA3-004 (QA3 · 경미) — COL-040 `?format=xlsx` 가 `=CMD|…` · `=HYPERLINK(…)` 원문을 수식 셀로 내려줌 | `routers/col.py` `_xlsx_text_cell(ws, row, col, value)` — 글자 셀은 전부 `data_type = "s"` 로 고정(날짜는 ISO 글자 · 수는 그대로). `_xlsx` 가 머리 행 · 데이터 행 모두 이 함수로 쓴다. 다른 xlsx 내려받기는 없다(생기면 같은 함수) | 원문 `=CMD|' /C calc'!A0` · `=HYPERLINK(…)` · `+1+1` · `@SUM(1)` 4행 → 내려받은 파일에 `data_type f` 셀 0 · 글자는 그대로 | 새 테스트 `test_collections_xlsx_has_no_formula_cells`(`@pytest.mark.fn("F-COL-041")`) · `tests/test_qa3_col.py::test_collections_xlsx_export_has_no_live_formula_cells` 통과 |

파일: `src/lcomfine/app/erp_upload.py`(새) · `src/lcomfine/app/routers/col.py`(새) · `src/lcomfine/app/templates/col/{_c,uploads,history,customer_map,collections,receivables,aging,shipment_vs_collection}.html`(새) · `src/lcomfine/app/stats.py`(수금 함수 7 추가) · `src/lcomfine/db/seed_dev3.py`(새) · `tests/test_dev3_col.py`(새) · `decisions.md`(D-802~804 덧붙임). 커밋은 오케스트레이터.

## 2-W3. 진행 (W3 대시보드 — 기능 10/10 · 2026-10-22)

| 기능 | API | 상태 | 테스트 (`@pytest.mark.fn`) |
|---|---|---|---|
| F-RPT-011 수주 리포트 조회 | `GET /rpt/orders` | 완료 | 1 — 의뢰 2 · 수량 80 · 미착수 1 · 일 구간 31(값 2 · 미수집 29) · 납기 월 분포 · SVG title = 표 · 422 3 · SH/DS 403 · 업무 테이블 diff 0 |
| F-RPT-021 생산 리포트 조회 | `GET /rpt/production` | 완료 | 1 — 생산 150 · 양품 138 · 로스 12 · 가동률 80.0(D-801) · `미확정 (D-519)` · 다음 달 제외 · 기계별 = `stats.machine_stats` · SL 403 |
| F-RPT-031 품질 리포트 조회 | `GET /rpt/quality` | 완료 | 1 — 검사 150 · 불량 5 · 불량유형 합 · 판정 3 · 불합격 LOT 2(입고 1 · 제품 1) · 재판정 1(이전 불합격 → 합격) · AC 403 |
| F-RPT-041 재고·창고 리포트 조회 | `GET /rpt/inventory` | 완료 | 1 — 입고 2 · 150 · 불출 1 · 30 · 제품 입고 1 · 조정 1 · 차이 −3 · 변동 상위 · 장기 체류 · SL 403 |
| F-RPT-051 출하 리포트 조회 | `GET /rpt/shipment` | 완료 | 1 — 확정 2 · 55 · 준수율 50.0(납기 안 완료 1 · 지연 1 · 의뢰번호 없는 출하 제외) · 거래처 필터 · PR 403 |
| F-RPT-061 수금 리포트 조회 | `GET /rpt/collection` | 완료 | 1 — 회차 없음 = `미수집` → 반영 회차 1(매출 1,000 · 수금 400 · 1990 매출 300) → 기준일 명시 · 월별 수금 400 · 출하 20 · 90일 초과 거래처 · PR/SH 403 |
| F-RPT-071 주문 흐름 리포트 조회 | `GET /rpt/order-flow` | 완료 | 1 — 의뢰 05-02 → 지시 05-03 → 생산 05-06 → 입고 05-08 → 출하 05-12 = 1 · 3 · 2 · 4 · 10일 · 미착수 의뢰는 전부 미수집 · `미확정 (D-520)` · PR 403 |
| F-RPT-081 경영 요약 조회 | `GET /rpt/summary` | 완료 | 1 — 일일(040 · 050) · 주간 · 월간(+ 010 · 020 · 060) · 탭 · 기준일 422 · PR/SL 403 |
| F-RPT-131 데이터 질의 조회 | `GET /rpt/query` | 완료 | 1 — 질문 폼 · 허용 뷰(ST 는 수금 뷰 흐림) · 최근 질의 · PR/AC 403 · 스크립트 없음 |
| F-RPT-132 질의 실행 | `POST /rpt/query` | 완료 | 7 — `validate_sql` 거부 29 사례(쓰기 · 다중 문장 · 주석 · CTE · 허용 밖 뷰 · 하위 질의 · 카탈로그 · `pg_sleep` · 함수 · for update · into · 큰따옴표 · $$ · NUL) · 통과 4 · 부서 뷰 제한(PR · ST 거부 · SL · EX 허용) · 키 없음 → `NotConfigured` → 422 문장 그대로 + `sys_ai_call_log` 실패 + `data_query_log` 거부 행 · fake 실패 → 422 「AI 호출 실패」 + 로그 · fake 성공 → 200 · 결과 2행 · 로그 ok · 변경 로그 1 · 브라우저 200 결과 표 · 실행 실패(없는 열) 422 · 질의 6 → 로그 6 · 6 · 행 상한 · PR/SL 403 · 업무 테이블 diff 0 |
| (dashboard) 빈 기간 | — | 완료 | 1 (표식 없음) — 6 함수 KPI · series 전부 None · 요약 kind 일일/주간/월간 · ValueError |

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 개발3 테스트 | **78 passed** (7.9s) = W1 19 + W2 14 + W3 45 (`tests/test_dev3_rpt.py`) | `uv run pytest -q tests/test_dev3_*.py` |
| 전체 테스트 | **351 passed · 1 failed** — 실패 1 = `tests/test_qa3_security.py::test_g19_write_403_full_sweep`(QA3 검사기의 기대값 결함 · §3-12) | `uv run pytest -q` |
| G-02 RPT | 라우트 없는 계약 16 → **6**(RPT 0 · 남은 6 = DOC) · 표식 없는 기능 16 → **6**(RPT 0) · 이어진 기능 **130/136** | `make check-trace` |
| G-03 RPT | 화면 67 × 칸 있음 260/260 → 200 · 칸 없음 276/276 → 403 · placeholder 11 → **2**(개발1 DOC 2 · **RPT 0**) | `make check-routes` |
| G-05 쓰기 경계 | PASS — 라우터 16(rpt.py 포함) 쓰기 테이블 ⊆ 계약 · `rpt.py` 직접 쓰기 0(로그는 `dataquery` · `ai`) · RPT 8 화면 GET 전후 업무 테이블 24 diff 0(테스트마다 확인) | `uv run python tools/check_data.py` G-05 · `tests/test_dev3_rpt.py` `_counts()` |
| G-15 · G-16 · G-17 | 기능은 있다 — QA2 `check_data.py` · QA3 `check_security.py` 가 아직 「W3 — 없다」로 적어 FAIL(QA 가 W3 로 잰다 · §3-13 · §3-14) | `make check-data` · `make check-security` |
| 테스트 잔류 행 | `data_query_log` 0 · `sys_ai_call_log` 0 · `T3%` 거래처 · 원자재 LOT · ERP 회차 0 | `psql -h /tmp lcomfine_db -c "select count(*) from data_query_log"` 등 |
| 실제 OpenAI 호출 | 테스트 0회(`ai.set_client(fake)`) · 개발 중 수동 확인 1회(RPT-130 질의 · 로그 행은 지웠다) | `grep -n set_client tests/test_dev3_rpt.py` |
| 결정 | D-805(대시보드 집계 세부) · D-806(질의 검증 · 실행 · 응답 · ai 시그니처) — `가설` | `decisions.md` |

파일: `src/lcomfine/app/dashboard.py` · `ai.py` · `dataquery.py` · `routers/rpt.py`(새) · `templates/rpt/{_d,orders,production,quality,inventory,shipment,collection,order_flow,summary,query}.html`(새) · `stats.py`(`period_bounds` 공개 한 줄) · `tests/test_dev3_rpt.py`(새) · `decisions.md`(D-805 · 806 덧붙임). 커밋은 오케스트레이터.

### 2-W3.1 QA3 결함 반영 (2026-10-22)

| 결함 | 고친 것 | 실측 | 검증 |
|---|---|---|---|
| DEF-QA3-005 (경미) — AI SQL 속 NUL → 로그 insert DataError → 롤백(로그 0행) · 사유 없는 422 | `dataquery._strip_fence` 가 NUL 을 표시 글자 `\x00`(`dataquery.NUL_GLYPH`) 로 바꾸고, `ask` 가 원문에 NUL 이 있었으면 **검증 전에** 「허용되지 않는 질의 — 쓸 수 없는 글자(NUL) · 원문 N자」 로 거부(`validate_sql` 도 같은 이유로 거부 — 심층 방어). `sql_text` · 422 `fields.SQL` 에는 표시 글자가 간다 | 422 message 「허용되지 않는 질의 — 쓸 수 없는 글자(NUL) · 원문 N자」 · `data_query_log` 1행(sql_text `select * from v_dq_orders\x00 where 1=1`) · `sys_ai_call_log` 1행(fake 성공) · 응답에 NUL 0 | `uv run pytest -q tests/test_dev3_rpt.py -k nul_is_rejected` · QA3 G-16 「우회 SQL」 54/54 PASS |
| DEF-QA3-006 (경미) — 실제 호출 경로 `CallFailed` 문장의 키가 dq 로그 · 422 · 화면에 노출 | `ai._mask` 가 설정 키 값 + `Bearer …` + `sk-…` 꼴을 가리고, `complete` 의 `except CallFailed` 가 가린 문장으로 **다시 만든 예외**를 올린다(`raise CallFailed(masked) from None`) — 로그 · 예외 · 응답 어디로 가도 키 없음 | sentinel 키 · `_openai` 가 「HTTP 401 … key …」 로 실패 → `ai.complete` 예외 문장 · 422 본문 · `sys_ai_call_log.error` · `data_query_log.error` · RPT-130 최근 질의 전부 sentinel 0 · `***` 표식 | `uv run pytest -q tests/test_dev3_rpt.py -k never_carries_key` · QA3 G-17 「키 값이 로그 · 예외 문장 · 응답에 없다」 PASS |

| DEF-QA1-007 (경미) — RPT 8 화면 조회 칸 형식 오류 422 가 `Accept` 에 text/html 이 없어도 HTML 재렌더 | `routers/rpt.py` `_render` — `http.wants_html(request)` 가 아니면 `http.validation_error` 를 그대로 raise(계약 §2 JSON `{code, message, fields}`), 브라우저는 같은 화면 422 재렌더 유지(아키텍트가 api-contract §2 에 예외로 적는다). `_dashboard` · `summary` 둘 다 `_render` 를 거친다 | JSON: `date_from=2002-13-01` → 422 `code validation_error` · `fields[0].name` 시작일 · `customer=abc` → 거래처 · `tab=yearly` → 탭 / `Accept: text/html` → 422 text/html · 입력칸 유지 | `uv run pytest -q tests/test_dev3_rpt.py -k json_422_without_html` (`@pytest.mark.fn("F-RPT-011")`) |
| DEF-QA2-005 (경미) — RPT-070 이 거래처·월별 수금을 보이면서 「ERP 업로드 기준일」 글자가 없다 | `templates/rpt/order_flow.html` 에 RPT-060 과 같은 `c.asof_line(data.asof)` 한 줄(Ruling 29 · asof = `dashboard.order_flow` 가 돌려주는 `stats.erp_asof()` · None 이면 「미수집 — 반영된 회차가 없다」) | 화면 본문에 「ERP 업로드 기준일: <날짜 또는 미수집>」 | `uv run pytest -q tests/test_dev3_rpt.py -k order_flow`(`@pytest.mark.fn("F-RPT-071")` 테스트에 한 줄 추가) |

실측 명령 결과(이 수정 뒤): `uv run pytest -q tests/test_dev3_rpt.py tests/test_qa3_rpt.py tests/test_qa1_rpt.py` → **79 passed · 1 xfailed · 2 failed = XPASS(strict)**(`test_rpt_422_json_shape_when_not_browser` = DEF-QA1-007 해소로 XPASS · `test_menu_has_no_old_name_ai_report` XPASS — 둘 다 QA1 이 xfail 표식을 뗀다); `uv run pytest -q tests/test_dev3_rpt.py tests/test_qa3_rpt.py` → **63 passed**(dev3 RPT 47 · QA3 RPT 16); `uv run pytest -q tests/test_dev3_*.py` → **80 passed**; `uv run python tools/check_security.py` G-16 7행 · G-17 5행 전부 PASS. 테스트 0회 실제 OpenAI 호출(fake · sentinel · `_openai` 치환).

## 3. 요청 (스키마 · 계약 · 공용 파일)

1. **[아키텍트 · function-list.md / db-schema.md §2.2]** F-SHP-021 계약 문장 「`stock_move` 한 행(사유 출하)」 → 「LOT 라인마다 `stock_move` 한 행」. 구현 · 브리프(w1-dev3)는 라인마다 1행이다(LOT 별 추적 · `stock_move.lot_id` 가 한 LOT 만 담는다).
   **종결(Ruling 22)** — 계약 F-SHP-021 · db-schema §2.2 가 「LOT 라인마다 1행」으로 고쳐졌다(커밋 `1fd01fd`). 코드 변경 없음.
2. **[아키텍트 · 사람]** D-801(가동률 = 가동 ÷ (가동 + 정지)) 을 `decisions.md` 에 `가설` 로 올렸다. 정본에 산식이 없다 — 확정되면 `stats._rate` 한 곳만 고친다. W3 RPT-020 도 같은 산식을 쓸 예정.
3. **[아키텍트 · 계약]** 출하 지시를 `취소` 하는 기능이 없다(`shipment_order.status` 에 값은 있음). 지금은 F-SHP-012 가 LOT 줄을 1줄 이상 요구해 할당 전부 해제가 안 된다(D-515 「할당 해제는 출하 지시 수정으로 사람이 한다」는 다른 LOT 로 바꾸는 것까지만). F-SHP-012 에 「취소(할당 전부 해제)」를 넣을지 정해 주면 붙인다.
   **종결(Ruling 21)** — 계약 F-SHP-012 에 「라인을 전부 제거하면 지시 취소(status 취소 · 할당 전부 해제) — 별도 취소 기능 없음」이 들어왔고 §2.1 대로 구현했다.
4. **[QA 참고]** 테스트 정리에서 불변 이력 `shipment_adjust` 테스트 행은 `set local session_replication_role = replica`(슈퍼유저 필요) 한 트랜잭션 안에서만 지운다. 로컬 DB 역할이 슈퍼유저가 아니면 이 정리가 실패한다(조용히 넘어가지 않는다).
5. `seed_dev3.py` 는 만들지 않았다 — 출하 시드는 개발2 의 제품 LOT 시드에 기대야 해서 W1 에서는 넣지 않았다. 시나리오 시드가 필요하면 알려 달라.
6. **[아키텍트 · interfaces.md §9]** `erp_upload` 의 실제 시그니처가 공표(§1.4)와 같다 — 계약 §9 를 코드대로 갱신해 달라: `headers` · `save_column_map` · `check_map` · `unmapped_codes` · `mapped_fields` · `error_link` 가 더 있고, `apply(..., *, source_file="")` 는 **새 회차 id** 를, `remap(cur, batch_id=None, erp_code=None, user=None)` 은 **error 가 바뀐 행 수**를 돌려준다. `stats.customer_receivable` · `due_compliance` 의 반환 모양은 §1.3. (계약 파일은 읽기만 해서 고치지 않았다.)
   **종결** — 아키텍트가 interfaces.md §9 를 §1.3 · §1.4 공표대로 갱신했다(2026-10-22). 코드 변경 없음.
7. **[아키텍트 · static/style.css]** 정본 「오류 행은 빨간색으로 표시」를 지금은 `<tr style="color: var(--bad)">`(인라인 style · `class="is-error"`)로 한다. `.is-error td { color: var(--bad) }` 한 줄을 style.css 에 넣어 주면 인라인 style 을 뺀다(템플릿 `col/_c.html`).
   **종결** — 아키텍트가 `.is-error td { color: var(--bad); }` 를 style.css 에 넣었고, `col/_c.html` 의 오류 행 인라인 style 을 빼고 `class="is-error"` 만 남겼다(2026-10-22).
8. **[아키텍트 · 스키마 참고]** 회차 교체는 `erp_upload_batch_live_uq`(기간당 `반영` 하나) 와 `erp_upload_batch_replace_chk`(`교체 ⇔ replaced_by`) 때문에 새 회차를 `교체(→이전)` 로 넣고 두 번 UPDATE 하는 세 단계다(D-802 · 한 트랜잭션 · 중간 상태도 제약 안). 그대로 두어도 된다 — `replaced_by` FK 를 `deferrable initially deferred` 로 바꾸면 두 단계가 되지만 요청까지는 아니다.
9. **[QA2 · check_data.py]** G-11 `erp_upload_error` · G-12 · G-13 · G-14 를 W2 로 잴 수 있다. 재현 절차: ① `POST /col/uploads action=map`(또는 시드 매핑 7 — 열 이름 거래처코드 · 일자 · 매출액 · 수금액 · 잔액 · 수단 · 어음 만기) ② openpyxl 로 그 열 이름의 xlsx 를 만들어 `POST /col/uploads action=apply period_from period_to file` → JSON `{id, batch_no, round_no, rows, errors, replaced}` ③ 같은 기간 재업로드 → `replaced` = 이전 회차 번호 · 이전 회차 `status='교체'` · 행 수 그대로 ④ 미매핑 코드 행 → `erp_upload_row.error like '거래처 코드 미매핑%'` · `notification(event_key='erp_upload_error', to_role='AC', link='/col/upload-history?batch=<id>')` 1행 ⑤ `POST /col/customer-map` 뒤 그 행 `error is null` ⑥ G-14 는 `stats.shipment_vs_collection(ym_from, ym_to, customer_id)` 와 `shipment_order(status='확정', confirmed_at 월)` · `v_dq_collections(txn_date 월)` 독립 SQL 대조. 수금 수정 엔드포인트는 없다(`grep -n "router.post" routers/col.py` → 4개 전부 업로드 · 매핑).
10. **[개발1 · TRK-030 · TRK-020 · HOME-010]** §1.3 공표대로 `stats.customer_receivable(cid)` 를 수금 칸에, `stats.due_compliance(period)` 를 납기 준수율에, HOME 회계부 카드 「90일 초과 미수」는 `len(stats.aging(stats.erp_asof() or date.today())["over90"])`(undecided 면 `미확정 (D-516)`) 로 붙일 수 있다. TRK-030 의 `erp_asof` 조회는 `stats.erp_asof()` 로 바꾸면 집계 SQL 이 `stats` 한 곳이 된다(progress-dev1 §3 「stats 가 공표되면 옮긴다」).
11. **[아키텍트 · interfaces.md §9]** DEF-QA2-004 수정으로 `erp_upload.remap(...)` 반환이 `int` → **`dict {"reviewed", "changed", "applied", "still_error"}`** 로 바뀌었다(§1.4). F-COL-031 · 032 응답 문장은 「다시 해석한 행 N · 그중 반영 M · 다른 오류로 여전히 제외 K」, JSON 은 `reinterpreted · applied · still_error · remapped(=applied)`. §9 의 `remap` 한 줄을 이대로 갱신해 달라.
    **종결** — 아키텍트가 interfaces.md §9 에 반영했다(2026-10-22). 같이 DEF-QA1-006 수정으로 `erp_upload.py` 의 알림 닫기가 `notify.resolve_by_link` 로 바뀌었다(Ruling 27 · 아키텍트 수정).
12. **[QA3 · tools/check_security.py:274 · tests/test_qa3_security.py]** G-19 「R·없음 부서 쓰기 403」의 기대값 `expect_403 = (r.code not in f.roles_w) and not f.permission_exception` 이 권한 예외 기능(F-RPT-132 · F-DOC-011 · F-HOME-022)을 **모든 부서 통과**로 본다. 계약은 `api-contract.md` §4 「권한 예외 쓰기 기능 … 칸이 없으면 → 403(R 이면 통과)」 — RPT-130 은 ST · EX · ADM 만 칸이 있어 SL · PR · SH · DS · AC 의 `POST /rpt/query` 403 이 맞다(`rbac.require_fn` · `can_do` 가 그렇게 판정 · 화면 GET 도 403). 기대값을 `expect_403 = (rbac.level(r.code, f.screen_id) is None) if f.permission_exception else (r.code not in f.roles_w)` 로 고쳐 달라. HOME-020 · DOC-010 은 전 부서 칸이 있어 지금까지 드러나지 않았다. (전체 pytest 의 실패 1 이 이것이다.)
13. **[QA2 · check_data.py G-15]** `dashboard` 8 함수의 반환 모양과 집계 정의는 §1.5 · D-805. 재계산 절차: ① `tests/test_dev3_rpt.py` 의 `RptWorld` 처럼 2002-05 에 행을 만들거나 실 DB 의 기간을 고른다 ② `dashboard.<fn>((f, t), customer_id)` 의 `kpis[key].value` · `series[name][i].value` 를 D-805 의 SQL 정의로 따로 센다 ③ 화면은 `data-kpi="<key>"` 안의 숫자 · `data-series="<name>"` 안 SVG `<title>` 「라벨: 값」 과 표 둘째 열(`num` 소수 0)로 대조 ④ 0건은 `미수집` 글자, 로스율 `미확정 (D-519)`, 병목 `미확정 (D-520)`, RPT-060 의 `asof` = `stats.erp_asof()`(KPI `asof` · 화면 「ERP 업로드 기준일」). 수금 · 납기 · 기계별은 `stats` 를 다시 쓰므로 G-14 · D-804 · PRP-020 과 같은 수가 나와야 한다.
14. **[QA3 · check_security.py G-16 · G-17]** 우회 시도는 `dataquery.validate_sql(sql, dataquery.allowed_views(role))` 로 직접, 또는 `ai.set_client(lambda m, s, u: "<sql>")` 주입 뒤 `POST /rpt/query`(폼 `question`) 로 — **실제 OpenAI 를 부르지 않는다**(`.env` 에 키가 있다). 키 없음은 `monkeypatch.setattr(ai, "_config", lambda: ("", "gpt-4.1"))` + `ai.set_client(None)` → 422 문장 「AI 키가 설정되지 않았습니다 — LCOMFINE_OPENAI_API_KEY」 · `sys_ai_call_log` ok=false 행 · `data_query_log` ok=false 행. 거부 사례 29 는 `tests/test_dev3_rpt.py::test_validate_sql_rejects`. `POST /rpt/query` 에 빈 폼은 422(질문 누락 · AI 호출 전) — G-19 전수 두드리기는 그래서 OpenAI 를 부르지 않는다.
15. **[개발1 · SYS-040 로그 탭]** `sys_ai_call_log` 열: `kind`(데이터 질의) · `model` · `ok` · `ms` · `error`(키 없음 문장 · HTTP n · 연결 실패 · 응답 형식 — 키 값은 없다) · `user_id` · `created_at`. `data_query_log` 열: `query_no`(DQ-…) · `user_id` · `role_code` · `question` · `sql_text`(AI 실패면 NULL) · `ok` · `row_count` · `error`(「허용되지 않는 질의 — …」 · 「AI 호출 실패 — …」 · 「실행 실패 — …」 · 키 없음 문장) · `ms` · `created_at`. 둘 다 읽기만(쓰는 곳은 `ai` · `dataquery` 뿐). 거부 행도 한 줄이다 — 탭에서 `ok=false` 를 빨간 행(`is-error`)으로 보이면 G-16 「거부 포함」이 눈에 보인다.
16. **[아키텍트 · interfaces.md §9]** 코드대로 갱신해 달라: `ai.complete(system, user, *, kind, cur=None, user_id=None)`(+ `ai.CallFailed` · `ai.NOT_CONFIGURED_MESSAGE`) · `dataquery.ask` 반환 dict 모양 · `dataquery.VIEWS · allowed_views · QueryRejected · recent · MAX_ROWS` · `dashboard` 반환의 `period · bucket · customer_id · notes` 키와 `period_bounds · summary_kind` (§1.5). `stats.period_bounds(period)` 도 공개했다.
    **종결** — 아키텍트가 interfaces.md §9 를 §1.5 대로 갱신했다(2026-10-22). 코드 변경 없음.
17. **[아키텍트 · api-contract.md §2 참고]** F-RPT-132 의 브라우저 성공 응답은 303 이 아니라 **같은 화면 200**(SQL · 결과 표 — 결과 행을 저장하지 않아 303 뒤에 보일 수 없다 · D-806). 변경 로그 · JSON `http.saved` 는 계약 그대로. 계약 표에 이 예외 한 줄을 적어 주면 QA1 의 사례와 맞는다.
    **종결** — 아키텍트가 api-contract.md §2 에 F-RPT-132 브라우저 200 예외 한 줄을 넣었다(2026-10-22).
18. **[아키텍트 · static/style.css · 선택]** RPT 템플릿은 색을 전부 토큰 클래스로 썼고 인라인 style 은 레이아웃(패널 안 `h2` 여백 `margin: 12px 16px 0` · 질문 칸 `flex: 1 1 100%`)만 남았다. `.panel--grid > h2 { margin: 12px 16px 0 }` 와 `.search .field--wide { flex: 1 1 100% }` 를 넣어 주면 인라인 style 을 뺀다.
    **종결** — 아키텍트가 두 클래스를 style.css 에 넣었고, `templates/rpt/` 의 인라인 `style=` 를 전부(h2 여백 → `.panel--grid > h2` · 질문 칸 → `.field--wide` · 결과 `<pre>` · 요약 탭 nav 의 style 제거) 빼서 **`style=` 0** 이다(`grep -rc 'style=' src/lcomfine/app/templates/rpt/` → 전부 0 · `uv run pytest -q tests/test_dev3_rpt.py` 45 passed · 2026-10-22).

## UI 정리 (2026-10-22 · 운영 화면 · docs/ui-guide.md)

- 범위: `templates/{shp,prp,col,rpt}/` 22 화면 — 본문 개발 메모 · 기능 ID · D 번호 나열을 걷어내고 `screen_head` · `.filters` · `form_details` · 오른쪽 `{% block help %}` 로. 대시보드 7 + RPT-020 은 `d.head` → KPI 줄 → 2열 차트 격자(접힌 데이터 표) → 상세 표. RPT-130 은 질문 칸 · 예시 칩(`?q=`) · 결과 표 · 생성된 쿼리 접기.
- `dashboard.py` 는 KPI `note` 문장만 운영 말투로(수치 · key · 계산 그대로). `shp/_f.html` `denied` 는 기능 ID 없이 문장만. `col/_c.html` 에 `asof_chip` · `rpt/_d.html` 의 옛 `header` 를 지우고 `head(show_asof=)`.
- 공용에 더한 것(기존 동작 불변): `_charts.html` `lines(rows, keys)`(같은 단위 여러 줄 선 · 축 하나) · `util/viz.py` `multi` + GLOBALS `viz_multi` · `style.css` `.viz__line--sN` · `.viz__dot--sN`.
- 테스트 최소 수정(옮겨진 문장): test_dev3_rpt 3곳(D-805 → 「체류일(오늘 − LOT 생성일)」 · D-804 → 「납기 안 완료 ÷」 · 「해설 문장은 없다」 → 「…없습니다」) · test_dev3_prp 1(D-801 → 「임시 산식」) · test_dev3_col 1(「F-COL-011」 → 권한 없음 문장).
- 검증: `uv run pytest -q tests/test_dev3_*.py tests/test_qa1_*.py tests/test_qa2_*.py tests/test_qa3_*.py` 241 통과(G-05 두 건은 동시 세션 쓰기로 겹쳐 실패 → 단독 재실행 통과) · `uv run python tools/check_data.py` 종료코드 0(G-15 전부 PASS) · `uv run python tools/check_screens.py` 종료코드 0.
