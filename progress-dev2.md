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

## 2. 진행

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| trace 시그니처 공표 | 이 문서 §1.1 | — |

## 3. 요청 (스키마 · 계약 · 공용 파일)

(아직 없음)
