# progress-dev3 — 개발3 (SHP · PRP · COL · RPT / 화면 22)

> §1 공표(다른 사람이 그대로 쓰는 것) · §2 진행 · §3 요청(스키마 · 계약 · 공용 파일). 실측한 것만 적는다.
> v2(2026-10-21 정본) 기준. W1 범위 = SHP 3 · PRP 3 · `stats.py`. COL(W2) · RPT(W3) 는 아직 만들지 않았다(placeholder 16).

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

- **`stats.customer_receivable(customer_id)` 는 W2 에 만든다 — 아직 없다.** 개발1 TRK-030 의 수금 칸은 그때까지 `미수집`.

### 1.2 SHP 이 남기는 것 (다른 화면 · QA 가 읽는 모양)

| 무엇 | 값 |
|---|---|
| `shipment_order.status` | `지시`(F-SHP-011) → `확정`(F-SHP-021). `취소` 로 바꾸는 기능은 아직 없다(§3-3) |
| 할당 | `shipment_line.qty` = 그 (LOT, 위치) `lot_stock.allocated_qty` 에 더한 양. 할당은 `select … from lot_stock … for update`(id 오름차순) 안에서 판정 |
| 확정 | LOT 라인마다 `lot_stock.qty` · `allocated_qty` 를 같은 양만큼 줄이고 `stock_move` 1행: `move_kind='출하'` · `lot_kind='제품'` · `lot_id`=제품 LOT · `from_location_id`=위치 · `to_location_id` NULL · `ref_table='shipment_order'` · `ref_id`=출하 id |
| 판정 판단 | LOT 의 판정 = 그 LOT(없으면 판정이 있는 가장 가까운 원 LOT — 분할)의 최대 seq 행(D-515 · 개발2 `trace` 와 같은 규칙). 미판정 · 불합격 · 재고 상태 가용 아님 → 확정 422 |
| 반품·정정 | `shipment_adjust.qty` 저장 부호: 반품은 항상 음수(입력이 양수여도), 정정은 입력 그대로(0 금지). 반품 누계 ≤ 출하 수량(LOT 를 고르면 그 LOT). 재고 불변 |
| 알림 `shipment_ordered` (→ SH) | link `/shp/confirm?no=<출하번호>` · dedupe `shipment_ordered:<출하번호>` — 확정하면 `handle_by_link` 로 닫힌다 |
| 알림 `shipment_confirmed` (→ SL · AC) | link `/shp/history?no=<출하번호>` · dedupe `shipment_confirmed:<출하번호>` |
| 개발2 `judged` 알림 | link `/shp/orders?lot=<제품 LOT>` 를 SHP-010 이 받는다(1번 줄에 그 LOT 선택). 그 LOT 를 할당해 출하 지시를 등록하면 등록한 부서의 그 알림이 닫힌다 |
| 화면 조회 인자 | SHP-010 `?customer=&status=&due_from=&due_to=&request_no=&lot=&edit=<id>` · SHP-020 `?no=` · SHP-030 `?date_from=&date_to=&customer=&item=&no=` · 역추적 링크 `LOT-020?shipment_no=` |

## 2. 진행 (W1 — 기능 10/10)

| 기능 | API | 상태 | 테스트 (`@pytest.mark.fn`) |
|---|---|---|---|
| F-SHP-011 출하 지시 등록 | `POST /shp/orders` | 완료 | 6 — 할당·알림·변경 로그 · 의뢰 불러오기 · 422 11가지 · 403 · **동시 할당(스레드 2 → 200 1 · 422 1, 라우터 문장)** · **행 잠금 대기** |
| F-SHP-012 출하 지시 수정 | `POST /shp/orders/{id}` | 완료 | 2 — 할당 이동·해제 · 가용 초과 · 누락 · 404 · 403 · 확정된 출하 422 |
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
| 개발3 테스트 | **18 passed** (2.9s) | `uv run pytest tests/test_dev3_*.py -q` |
| 테스트가 남긴 행 | customer · item · product_lot `T3%` 0 · 알림 0 | `psql -h /tmp lcomfine_db -c "select count(*) from customer where customer_code like 'T3%'"` |
| G-02 SHP · PRP 고아 | 고아 ①②③ 목록에 SHP · PRP 0 | `uv run python tools/check_trace.py` |
| G-03 SHP · PRP 화면 | 칸 있는 부서 전부 200 · 칸 없는 부서 403 · placeholder 개발3 16 (COL 7 · RPT 9 — W2 · W3) | `uv run python tools/check_routes.py` |
| G-04 쓰기 경계 | PASS (PRP 쓰기 0) | `uv run python tools/check_schema.py` |

커밋: `d1c9a12` SHP · `c8aecd7` stats · PRP · D-801 · `b9bad23` 경로 인자 `{id}`.

## 3. 요청 (스키마 · 계약 · 공용 파일)

1. **[아키텍트 · function-list.md / db-schema.md §2.2]** F-SHP-021 계약 문장 「`stock_move` 한 행(사유 출하)」 → 「LOT 라인마다 `stock_move` 한 행」. 구현 · 브리프(w1-dev3)는 라인마다 1행이다(LOT 별 추적 · `stock_move.lot_id` 가 한 LOT 만 담는다).
2. **[아키텍트 · 사람]** D-801(가동률 = 가동 ÷ (가동 + 정지)) 을 `decisions.md` 에 `가설` 로 올렸다. 정본에 산식이 없다 — 확정되면 `stats._rate` 한 곳만 고친다. W3 RPT-020 도 같은 산식을 쓸 예정.
3. **[아키텍트 · 계약]** 출하 지시를 `취소` 하는 기능이 없다(`shipment_order.status` 에 값은 있음). 지금은 F-SHP-012 가 LOT 줄을 1줄 이상 요구해 할당 전부 해제가 안 된다(D-515 「할당 해제는 출하 지시 수정으로 사람이 한다」는 다른 LOT 로 바꾸는 것까지만). F-SHP-012 에 「취소(할당 전부 해제)」를 넣을지 정해 주면 붙인다.
4. **[QA 참고]** 테스트 정리에서 불변 이력 `shipment_adjust` 테스트 행은 `set local session_replication_role = replica`(슈퍼유저 필요) 한 트랜잭션 안에서만 지운다. 로컬 DB 역할이 슈퍼유저가 아니면 이 정리가 실패한다(조용히 넘어가지 않는다).
5. `seed_dev3.py` 는 만들지 않았다 — 출하 시드는 개발2 의 제품 LOT 시드에 기대야 해서 W1 에서는 넣지 않았다. 시나리오 시드가 필요하면 알려 달라.
