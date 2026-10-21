# progress-dev2 — 개발2 (MAT · PRD · INS · QC · INV · LOT / 화면 20)

> §1 공표(다른 사람이 그대로 쓰는 것) · §2 진행 · §3 요청(스키마 · 계약 · 공용 파일). 실측한 것만 적는다.
> v2(2026-10-21 정본) 기준으로 새로 시작한다. 옛 판 기록은 git 이력에 있다.

## 1. 공표

### 1.1 `lcomfine.app.trace` — 읽기만 한다 (어떤 테이블에도 쓰지 않는다 · 캐시 없음)

```python
from lcomfine.app import trace

trace.backward(shipment_no=None, product_lot_no=None) -> dict   # 둘 중 정확히 하나
trace.forward(material_lot_no) -> dict
trace.NotFound      # LookupError 의 하위 — 입력한 번호가 없다 (라우터는 422: 사용자가 입력한 번호)
                    # 인자가 둘 다 없거나 둘 다 있으면 ValueError
```

척추(`db-schema.md` §3)를 FK 로 따라간다. 취소된 불출(`material_issue.canceled_at`)은 잇지 않는다. 출하는 `취소` 를 빼고 `지시` · `확정` 을 모두 싣는다(`status` 로 구분).
분할 LOT 는 `parent_lot_id` 를 끝까지 따라 원 LOT 로 잇는다(정방향은 분할 자식까지 내려간다).

**`backward` 반환 모양**

```python
{
  "start": {"kind": "출하" | "제품 LOT", "no": "SHP-…" | "PLOT-…"},
  "shipments":     [{"id", "shipment_no", "status", "confirmed_at", "due_date", "customer_code", "customer_name", "request_no"}],
  "product_lots":  [{"id", "lot_no", "item_code", "item_name", "work_order_id", "work_order_no",
                     "parent_lot_id", "root_lot_id", "root_lot_no",          # 분할 LOT 면 원 LOT, 아니면 자기 자신
                     "shipped_qty",                                          # 시작 출하(들)의 shipment_line 수량 합 (제품 LOT 시작이면 None)
                     "judgement", "judgement_seq", "judged_at"}],            # 현재 판정(자기 → 원 LOT 순으로 가장 가까운 것의 최대 seq) · 없으면 None(미판정)
  "work_orders":   [{"id", "work_order_no", "status", "qty", "item_code", "item_name", "request_id", "request_no"}],
  "issues":        [{"line_id", "issue_id", "issued_on", "work_order_id", "work_order_no", "material_lot_id", "material_lot_no", "qty", "location_code"}],
  "material_lots": [{"id", "lot_no", "item_code", "item_name", "qty", "supplier_lot_no", "receipt_id", "supplier_name", "received_on",
                     "parent_lot_id", "root_lot_id", "root_lot_no"}],        # 불출된 LOT 그대로 (분할 LOT 면 root_* 가 원 입고 LOT)
  "origin_material_lot_nos": ["MLOT-…", …],   # G-07 의 집합: 불출된 원자재 LOT 의 원 입고 LOT 번호(분할 아니면 자기) — 정렬 · 중복 없음
  "issued_material_lot_nos": ["MLOT-…", …],   # 실제 불출된 LOT 번호(분할 LOT 번호 포함) — 정렬 · 중복 없음
  "rejected_after_shipment": [                 # 「출하 후 불합격」(D-515) — 확정된 출하에 들어간 제품 LOT 의 현재 판정이 불합격이고 그 판정이 확정 뒤
      {"shipment_no", "confirmed_at", "product_lot_no", "seq", "inspected_at"}],
  "steps": [  # 화면 렌더용 단계 순서 — 위 목록을 같은 키로 다시 가리킨다
      {"key": "shipments", "label": "출하"}, {"key": "product_lots", "label": "제품 LOT"},
      {"key": "work_orders", "label": "생산지시"}, {"key": "issues", "label": "불출"},
      {"key": "material_lots", "label": "원자재 LOT"}],
}
```

**`forward` 반환 모양**

```python
{
  "start": {"kind": "원자재 LOT", "no": "MLOT-…"},
  "material_lots": [ … backward 와 같은 행 모양 … ],   # 시작 LOT + 분할 자식(끝까지)
  "issues":        [ … ],                             # 그 LOT 들의 불출 행 (취소 제외)
  "work_orders":   [ … ],
  "product_lots":  [ … ],                             # 그 지시들의 제품 LOT(분할 자식 포함 · product_lot.work_order_id) · shipped_qty = 확정·지시 출하 행 합
  "shipments":     [ … ],                             # 그 제품 LOT 들이 걸린 출하 (취소 제외)
  "product_lot_nos": [...], "shipment_nos": [...],    # G-08 대조용 — 정렬 · 중복 없음
  "rejected_after_shipment": [ … backward 와 같음 … ],
  "steps": [material_lots → issues → work_orders → product_lots → shipments],
}
```

### 1.2 개발2 화면의 폼 칸 (QA2 의 G-06 HTTP 흐름 · 개발3 이 그대로 쓴다)

| 기능 | 요청 | 칸 (같은 이름 반복 = 행 목록) | 성공 JSON |
|---|---|---|---|
| F-MAT-011 | `POST /mat/receipts` | `supplier_name` · `received_on` · `note` · 행: `item_id[]` `qty[]` `location_id[]` `supplier_lot_no[]` | `receipt_id` · `lot_nos` |
| F-QC-011 | `POST /qc/incoming` | `material_lot_id` 또는 `lot_no` · `result`(합격 \| 불합격) · `item_name[]` `item_value[]` · `note` | `lot_no` · `seq` · `status` |
| F-QC-012 | `POST /qc/incoming/{material_lot.id}` | `result` · `item_name[]` `item_value[]` · `note` | 같음 |
| F-MAT-021 | `POST /mat/issues` | `work_order_id` 또는 `work_order_no` · `issued_on` · `note` · 행: `lot_no[]` `location_id[]`(비우면 재고 행이 하나일 때 그 위치) `qty[]`(비운 행은 건너뜀) | `issue_id` · `lot_nos` |
| F-MAT-022 | `POST /mat/issues/{issue.id}` | `issued_on` · `note` · `cancel=1` | `issue_id` |
| F-PRD-011 | `POST /prd/daily` | `work_order_id`/`work_order_no` · `work_date` · `equipment_code`(공통코드 설비) · `produced_qty` · `good_qty` · `loss_qty` · `run_minutes` · `stop_minutes` · `note` | `daily_id` |
| F-INS-011 | `POST /ins/daily` | `work_order_id`/`work_order_no` · `work_date` · `inspected_qty` · `defect_qty` · `defect_code[]` `defect_code_qty[]` · `note` | `daily_id` |
| F-MAT-031 | `POST /mat/product-receipts` | `work_order_id`/`work_order_no` · `qty`(비우면 일보 완료 − 기존 입고) · `location_id` · `received_on` · `note` | `product_receipt_id` · `product_lot_id` · `lot_no` · `qty` |
| F-QC-021 | `POST /qc/product` | `product_lot_id` 또는 `lot_no` · `result` · `item_name[]` `item_value[]` · `note` | `lot_no` · `seq` · `status` · `shipped_after` |
| F-QC-022 | `POST /qc/product/{product_lot.id}` | 같음 | 같음 |
| F-INV-021 | `POST /inv/moves` | `lot_kind`(원자재 \| 제품) · `lot_no` · `from_location_id` · `to_location_id` · `qty` · `split=1`(분할) · `note` | `move_id` · `lot_no`(분할이면 새 LOT `원번호-01`) |
| F-INV-031 | `POST /inv/adjustments` | `lot_kind` · `lot_no` · `location_id` · `actual_qty` · `reason`(필수) | `adjust_id` · `diff_qty` |

- 경로의 `{id}` 해석은 D-701 · 수정 · 취소 범위는 D-703 · 알림 링크는 D-704.
- 입력 오류는 전부 422(사람이 읽는 문장 · `fields`), 경로의 없는 키 · 숫자 아닌 키는 404, 입력한 없는 번호(LOT · 지시)는 422.
- 입력 헬퍼(`num_in` · `date_in` · `text_in` · `id_in` · `path_id` · `work_order_in` · `location_in` · `lot_by_no`)는 `routers/inv.py` 위쪽에 있다(개발2 라우터끼리만 쓴다 · 읽기만).

## 2. 진행 (2026-10-21 · W1)

기능 **37/37** (MAT 10 · PRD 6 · INS 6 · QC 7 · INV 6 · LOT 2) — 화면 20 전부 실화면(placeholder 0). `trace.py` 구현(읽기 전용).

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 개발2 테스트 | **39 passed** (두 번 연속 실행 · 남은 테스트 행 0) | `uv run pytest tests/test_dev2_*.py -q` |
| 전체 테스트 | 180 passed | `uv run pytest -q` |
| 개발2 기능 ↔ 라우트 ↔ 표식 | 37 기능 전부 라우트 글자 그대로 · 표식 있음 · 개발2 경로의 계약 없는 라우트 0 | `tools/check_trace.py` 의 `all_routes` · `fn_marks` 로 개발2 줄만 대조 |
| G-03 placeholder | 개발2 0 (남은 24 = 개발1 5 · 개발3 19) | `make gate` |
| G-04 스키마 · 쓰기 경계 계약 | PASS | `make gate` |
| Review Focus — 출하 후 재판정 불합격 | 재판정 행(2차) 남음 · 출하 상태/확정 시각/수량 그대로 · `shipment_adjust` 자동 생성 없음 · 남은 재고만 보류 · `trace` 의 `rejected_after_shipment` · LOT-020 화면 「출하 후 불합격」 | `tests/test_dev2_qc.py::test_rejudge_after_shipment_keeps_shipment_and_flags` |
| G-07 역추적 | 분할 원자재 LOT 을 불출 · 분할 제품 LOT 을 출하한 척추에서 `origin_material_lot_nos` = 독립 SQL 집합 · 다른 지시의 LOT 섞이지 않음 | `tests/test_dev2_lot.py::test_backward_from_shipment_reaches_origin_material_lots` |
| G-08 정방향 | 원자재 LOT → 분할 자식 · 지시 · 제품 LOT(분할 포함) · 출하 | `tests/test_dev2_lot.py::test_forward_from_material_lot_reaches_shipments` |
| trace 읽기 전용 | 추적 전후 척추 테이블 행 수 diff 0 · `trace.py` 에 쓰기 문 0 | `tests/test_dev2_lot.py::test_trace_writes_nothing` |
| G-09 (개발2 몫) | 검사대기 · 보류 LOT 불출 422 · 사용 중지 품목 입고 422 | `test_dev2_mat.py::test_issue_blocks_waiting_and_held_lots_and_moves_stock` · `test_receipt_numbers_lots_waiting_and_notifies` |
| G-10 (개발2 몫) | INV-010 가용 = qty − allocated = `v_dq_stock` 재계산 · 할당 칩 | `test_dev2_inv.py::test_stock_available_is_qty_minus_allocated_and_chips` |

기능별:

| 기능 | 상태 | 테스트 |
|---|---|---|
| F-MAT-011 · 012 · 013 | 완료 | `test_dev2_mat.py` 3 |
| F-MAT-021 · 022 · 023 | 완료 (022 는 D-703 범위) | `test_dev2_mat.py` 3 |
| F-MAT-031 · 032 · 033 | 완료 (기본 수량 = 일보 양품 합 − 기존 입고) | `test_dev2_mat.py` 3 |
| F-MAT-041 | 완료 (엑셀 = CSV · D-704) | `test_dev2_mat.py` 1 |
| F-PRD-011 · 012 · 013 · 021 · 031 · 041 | 완료 (041 로스율 `미확정 (D-519)` + 원 수량) | `test_dev2_prd.py` 6 |
| F-INS-011 · 012 · 013 · 021 · 031 · 041 | 완료 (041 `미확정 (D-519)`) | `test_dev2_prd.py` 6 |
| F-QC-011 · 012 · 013 | 완료 | `test_dev2_qc.py` 3 |
| F-QC-021 · 022 · 023 · 031 | 완료 (022 에 Review Focus 포함) | `test_dev2_qc.py` 5 |
| F-INV-011 · 021 · 022 · 023 · 031 · 032 | 완료 | `test_dev2_inv.py` 6 |
| F-LOT-011 · 021 | 완료 | `test_dev2_lot.py` 3 |

- 테스트 기준 데이터: `tests/test_dev2_world.py` 가 품목 · 거래처 · 창고 · 위치 · 의뢰 · 지시를 고유 접두 `T<시각><난수>-` 로 SQL 로 만들고, 출하(개발3 SHP)도 SQL 로 직접 만든 뒤 전부 지운다(불변 `stock_adjust` 테스트 행은 정리 트랜잭션 안에서만 `session_replication_role = replica` 로 지운다).
- 시드 `db/seed_dev2.py` 는 만들지 않았다 — 개발2 행은 BAS 품목 · 위치와 WO 지시 위에 서는데 그 시드 코드를 아직 받지 못했다(§3-1).

## 3. 요청 (스키마 · 계약 · 공용 파일)

1. **(아키텍트 · 개발1) 시드 시나리오** — G-07 을 시드 데이터로도 보이려면 개발1 시드(품목 · 위치 · 의뢰 · 지시)의 코드가 정해진 뒤 `seed_dev2.run()` 이 그 위에 입고 → 판정 → 불출 → 일보 → 제품 입고 → 판정을 HTTP 없이 SQL 로 깔 수 있다. 개발1 이 시드 행 코드(품목 · 위치 · 지시 번호)를 `progress-dev1.md` §1 에 공표하면 만든다.
2. **(아키텍트) `function-list.md` 계약 문장 보강** — D-701(재판정 경로 `{id}` = LOT id) · D-703(수정 · 취소 범위) 를 F-QC-012 · F-QC-022 · F-MAT-012 · F-MAT-022 · F-MAT-032 · F-INV-022 의 계약 문장에 이어 적어 주기를 요청한다(코드가 원본).
3. **(아키텍트 · 선택) 템플릿 필터** — `screen.num` 의 기본 자릿수 0 은 numeric(14,3) 수량의 소수를 반올림해 보인다. 개발2 화면은 자체 매크로 `templates/inv/_ui.html` `q()`(뒤 0 없이)를 쓴다. 공용 `qty` 필터가 생기면 그것으로 바꾼다.
4. **(개발1) `order_issued` 알림 링크** — `/mat/issues?wo=<지시번호>` 꼴이면 불출 등록 때 닫힌다(D-704).
5. **(개발3) 출하 쪽 연결** — 판정 알림 링크는 `/shp/orders?lot=<제품 LOT>`. 「출하 후 불합격」 은 `trace.backward(...)["rejected_after_shipment"]` 로 읽을 수 있다(§1.1).
