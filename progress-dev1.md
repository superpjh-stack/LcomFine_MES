# progress-dev1 — 개발1 (HOME · BAS · STD · WO · SYS · TRK · DOC / 화면 25)

> §1 공표(다른 사람이 그대로 쓰는 것) · §2 진행 · §3 요청(스키마 · 계약 · 공용 파일). 실측한 것만 적는다.
> v2(2026-10-21 정본) 기준으로 새로 시작한다. 옛 판 기록은 git 이력에 있다.

## 1. 공표

### 1.1 의뢰 · 지시 상태값 (WO-010 · WO-020 이 바꾼다 — `db-schema.md` §6 그대로)

| 테이블.컬럼 | 값 | 누가 · 언제 바꾸는가 |
|---|---|---|
| `production_request.status` | `확인대기` | F-WO-011 등록 직후 (기본값) |
| | `확정` | F-WO-012 수정에서 영업부 등이 단가·납기를 확인하고 고른다 |
| | `지시완료` | F-WO-021 지시서 작성이 같은 트랜잭션에서 바꾼다(그 의뢰의 첫 지시). 화면에서 직접 고를 수 없다 |
| | `취소` | F-WO-012 수정. 취소된 의뢰로는 지시서를 만들 수 없다(422) |
| `work_order.status` | `발행` | F-WO-021 작성 직후 (기본값) |
| | `진행` · `완료` · `취소` | F-WO-022 수정 (W1 에서는 사람이 고른다. 일보·제품 입고가 자동으로 바꾸지 않는다) |

- 지시서는 `확인대기` · `확정` · `지시완료` 의뢰에서 만들 수 있다(한 의뢰에 지시 여럿 가능). `취소` 의뢰는 422.
- 지시의 품목 = 의뢰의 품목(복사). 의뢰에 취소 아닌 지시가 있으면 의뢰의 품목·거래처를 바꾸지 않는다(422).

### 1.2 대기 판정 조건 (HOME-010 카드가 질의로 센다 — 저장하지 않는다)

| 조건 | SQL 요지 |
|---|---|
| **지시 대기 의뢰** | `production_request.status = '확정'` |
| **불출 대기 지시** | `work_order.status in ('발행','진행')` 이고 그 지시에 취소되지 않은 불출 행이 없다 — `not exists (select 1 from material_issue_line l join material_issue i on i.id = l.issue_id and i.canceled_at is null where l.work_order_id = w.id)` |
| 일보 미입력 지시 | `work_order.status in ('발행','진행')` 이고 `production_daily` 행이 없다 |
| 단가·납기 확인 필요 의뢰 | `production_request.status = '확인대기'` |
| 납기 D-3 미출하 | 의뢰 `status <> '취소'` · `due_date <= current_date + 3` · 출하 수량 < 의뢰 수량. 출하 수량 = `v_work_order_status.shipped_qty` 를 `request_id` 로 합한 값(확정 출하만) |
| 입고검사 · 제품검사 대기 LOT | `lot_stock.status = '검사대기'` · `qty > 0` · `lot_kind` = `원자재` / `제품` (LOT 수 = distinct lot_id) |
| 판정 끝난 출하 대기 · 판정 완료 LOT | `lot_stock.lot_kind = '제품'` · `status = '가용'` · `qty - allocated_qty > 0` |
| 출하 지시 대기(출하실) | `shipment_order.status = '지시'` |

### 1.3 알림 (D-511 · `notify.emit` 은 쓰기 트랜잭션 안)

| 이벤트 | 기능 | link | dedupe_key |
|---|---|---|---|
| `request_created` | F-WO-011 | `nav.path_of("WO-010") + "?q=<의뢰번호>"` (수신 PR · DS 둘 다 WO-010 을 볼 수 있다 — DS 는 WO-020 칸이 없다) | `request_created:<의뢰번호>` |
| `order_issued` | F-WO-021 | `nav.path_of("MAT-020") + "?wo=<지시번호>"` | `order_issued:<지시번호>` |
| `due_d3_unshipped` | `uv run python -m lcomfine.jobs due-check` | `nav.path_of("TRK-020") + "?request=<의뢰번호>"` | `due:<의뢰번호>:<YYYY-MM-DD>` |

- F-WO-021 은 같은 트랜잭션에서 `notify.handle_by_link(cur, <request_created link>, user)` 로 그 의뢰의 알림을 닫는다.
- **개발2 MAT-020 불출**은 `order_issued` 알림을 닫으려면 쓰기 트랜잭션에서 `notify.handle_by_link(cur, nav.path_of("MAT-020") + f"?wo={work_order_no}", user)` 를 부르면 된다.

## 2. 진행

| 항목 | 실측 | 검증 방법 |
|---|---|---|

## 3. 요청 (스키마 · 계약 · 공용 파일)

(아직 없음)
