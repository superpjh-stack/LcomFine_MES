# DB 스키마 계약 v2 (아키텍트 · 2026-10-21 · D-521 · D-522)

> 원본은 `src/lcomfine/db/schema.sql` 이다. **§2.3 · §4 · §5 표는 렌더본**이라 손으로 고치지 않는다 —
> `schema.sql`(또는 `function-list.md`)을 고치고 `make db-schema && make contracts`. `make check-schema` 가 이 문서 ↔ `schema.sql` ↔ 실제 DB 를 대조한다(G-04).
> 데이터가 있는 DB 는 `make db-schema` 로 지우지 않고 **`ALTER` 로 같은 모양을 만든 뒤** `make contracts` 를 돌린다 —
> 새 컬럼은 `schema.sql` 에서도 그 테이블의 맨 끝에 적는다(`ADD COLUMN` 이 맨 끝에 붙으므로 컬럼 순서가 같아야 한다).
> 스키마를 고치는 사람은 아키텍트뿐이다. 개발자는 `progress-devN.md` §3 에 요청을 남긴다.

DB `lcomfine_db` (PostgreSQL 17 · unix socket `/tmp`) · 테이블 **48** (업무 39 + SYS 9) · 뷰 **9**.
G-04 의 기대값은 아래 §1 표의 **이름 집합**이다(D-521) — 수로 판정하지 않는다. 테이블을 더하거나 빼면 스펙 §4.1 표와 이 표를 함께 고친다.

공통 규칙 — 모든 테이블 `id bigserial primary key`(자연키가 분명한 `sys_role` · `sys_permission` · `sys_number_rule` · `sys_number_seq` · `sso_token` 은 그 키,
골격이 쓰는 `sys_user.user_id` · `sys_access_log.log_id` 는 기존 이름) · `created_at` · `created_by` · `updated_at` · `updated_by`(불변 행 · 로그 테이블은 `updated_*` 없음).
코드 `text` · 수량 `numeric(14,3)` · 금액 `numeric(16,2)` · 날짜 `date` · 시각 `timestamptz` · 상태는 한글 그대로 `check`(§6).

## 1. 영역 → 테이블

영역 = 그 테이블에 쓰는 대메뉴 코드(`nav.py`) 또는 `SYS`. `TRK` 통합 조회 · `LOT` LOT 추적 · `PRP` 생산 보고서는 테이블이 없다 — 읽기만 한다.

| 영역 | 테이블 | 목적 |
|---|---|---|
| BAS | `item` | 품목 — 제품 · 원자재. 품목 코드 중복 금지 · 사용 중지 품목은 의뢰 · 입고 · 출하 지시에서 못 고른다 |
| BAS | `customer` | 거래처 — 의뢰 · 출하의 상대 |
| BAS | `warehouse` | 창고 |
| BAS | `location` | 위치(랙 · 구역) — 창고 아래. 재고가 남은 위치는 지울 수 없다 |
| STD | `spec_sheet` | 제조사양기준서 — 제품별 인쇄 사양. 생산지시서가 불러온다 |
| STD | `standard` | 표준 조건 — 등록 · 조회만(적용 규칙 D-519) |
| STD | `plate` | 인쇄 판 — 보유 판 |
| STD | `plate_usage` | 판 사용 이력 — 판을 쓴 지시 · 날짜 |
| STD | `artwork` | 시안 이미지 — 제품에 연결 |
| STD | `sample_sheet` | 표준견본서 — 제품별 작성 · 출력 |
| STD | `exception_item` | 예외제품 지정 — 지정 · 조회만(적용 규칙 D-519) |
| WO | `production_request` | 생산의뢰 = 「수주」. 의뢰번호가 지시 → 일보 → 제품 입고 → 출하의 연결 키 |
| WO | `work_order` | 생산지시서 — 의뢰 한 건에서 만든다 |
| WO | `work_sequence` | 설비별 작업 순서 |
| MAT | `material_receipt` | 원자재 입고 헤더 — 공급사 · 입고일 |
| MAT | `material_lot` | 원자재 입고 LOT — 추적 척추의 맨 앞 |
| MAT | `material_issue` | 불출 헤더 |
| MAT | `material_issue_line` | 불출 행 — 원자재 LOT → 생산지시 (척추 첫 고리) |
| MAT | `product_receipt` | 제품 입고 — 생산지시 → 제품 LOT (척추 둘째 고리) |
| MAT | `product_lot` | 제품 LOT — 지시번호와 묶인다. 분할 LOT 는 `parent_lot_id` |
| PRD | `production_daily` | 생산일보 — 지시 × 일자 × 설비 |
| INS | `inspection_daily` | 검사일보 — 공정 검사(지시 × 일자) |
| QC | `incoming_inspection` | 입고검사 판정 — 원자재 LOT × 차수. 재판정은 새 행 |
| QC | `product_inspection` | 제품검사 판정 — 제품 LOT × 차수. 재판정은 새 행 |
| INV | `lot_stock` | LOT × 위치 현재고 · 할당량 · 상태(가용 · 검사대기 · 보류) |
| INV | `stock_move` | 재고 이동 — 불출 · 이동 · 분할 · 출하 한 행씩 |
| INV | `stock_adjust` | 재고 조정 — 실사 수량 · 차이 사유. 불변 |
| SHP | `shipment_order` | 출하 지시 — 지시 → 확정 |
| SHP | `shipment_line` | 출하 행 — 출하 지시 → 제품 LOT (척추 마지막 고리) · 할당 |
| SHP | `shipment_adjust` | 확정 후 반품 · 정정 행. 불변 · 재고 불변(D-515) |
| COL | `erp_upload_batch` | ERP 수금현황 업로드 회차 — 반영 / 교체 |
| COL | `erp_upload_row` | 업로드 행 — 원문 · 매핑 값 · 오류 |
| COL | `erp_customer_map` | ERP 거래처코드 ↔ MES 거래처 |
| COL | `erp_column_map` | ERP 엑셀 열 이름 ↔ MES 항목(D-516) |
| RPT | `data_query_log` | 데이터 질의 로그 — 거부 포함 모든 질의(D-513) |
| DOC | `doc_account_map` | MES 사용자 ↔ 문서관리 계정 ID (1:1) |
| DOC | `sso_token` | 일회용 SSO 토큰 — jti · 만료 · 사용 시각(D-514) |
| HOME | `notification` | 알림 — 수신 부서마다 1행 · (dedupe_key, to_role) 유일(D-522) |
| HOME | `notification_setting` | 개인 추가 알림 켜고 끄기 |
| SYS | `sys_role` | 역할(부서) 8 |
| SYS | `sys_user` | 사용자 계정 |
| SYS | `sys_permission` | 권한 칸 — 부서 × 화면 (W · R). 행이 없으면 권한 없음 |
| SYS | `sys_common_code` | 공통코드 — 설비 · 불량유형 · 수금수단 |
| SYS | `sys_access_log` | 접근 로그 — 로그인 · 조회 · SSO · 오류 |
| SYS | `sys_change_log` | 데이터 변경 로그 — `audit.log_change` |
| SYS | `sys_number_rule` | 채번 형식 7행(D-509) |
| SYS | `sys_number_seq` | 채번 카운터 |
| SYS | `sys_ai_call_log` | AI 호출 로그 |

뷰 9 (테이블 수에 세지 않는다 · 읽기 전용 · 열은 §5 렌더본):

| 영역 | 뷰 | 목적 |
|---|---|---|
| WO | `v_work_order_status` | WO-040 공정상태 — 지시별 지시 수량 · 일보 완료 합 · 제품 입고 합 · 출하 합 · 상태 |
| RPT | `v_dq_orders` | 데이터 질의 허용 뷰 — 수주(=생산의뢰) |
| RPT | `v_dq_work_orders` | 데이터 질의 허용 뷰 — 생산지시 |
| RPT | `v_dq_stock` | 데이터 질의 허용 뷰 — 재고 |
| RPT | `v_dq_shipments` | 데이터 질의 허용 뷰 — 출하 |
| RPT | `v_dq_quality` | 데이터 질의 허용 뷰 — 품질 판정 |
| RPT | `v_dq_production_daily` | 데이터 질의 허용 뷰 — 생산일보 |
| RPT | `v_dq_collections` | 데이터 질의 허용 뷰 — 수금 (영업부 · 회계부 · 전산 관리자 · 경영진만 · D-513) |
| RPT | `v_dq_receivables` | 데이터 질의 허용 뷰 — 미수 (영업부 · 회계부 · 전산 관리자 · 경영진만 · D-513) |

## 2. 쓰기 경계 (G-05 의 기대값)

### 2.1 규칙

1. **화면은 자기 대메뉴 영역의 테이블에만 쓴다.** 쓰는 테이블은 `function-list.md` 의 「쓰는 테이블」 열이 원본이다(§2.3 렌더본).
2. 그 밖에 쓰는 것은 §2.2 의 예외 표에 있는 것뿐이다 — `make check-schema` 가 기능마다 대조한다.
3. 모든 쓰기 뒤의 `sys_change_log`(`audit.log_change`)는 공통 규칙이라 「쓰는 테이블」에 적지 않는다.
4. **TRK · LOT · PRP · RPT 대시보드는 어떤 업무 테이블에도 쓰지 않는다.** 데이터 질의(F-RPT-132)는 `data_query_log` · `sys_ai_call_log` 만. 추적 · 집계 결과를 캐시 테이블에 쌓지 않는다.
5. 수금 데이터는 업로드 회차 교체로만 바뀐다(MES 는 수금을 고치지 않는다). `stock_adjust` · `shipment_adjust` 는 불변(트리거가 UPDATE · DELETE 를 막는다).

### 2.2 예외 (영역 밖에 쓰는 것 — 이 표가 전부다)

스펙 §4.3 의 예외 3(QC 판정 → `lot_stock.status` · 출하 지시 → `lot_stock.allocated_qty` · 쓰기 트랜잭션 → `notification`)과,
`function-list.md` 가 이미 그렇게 적어 둔 나머지(입고 · 불출 · 출하 확정의 재고 반영, SSO · AI 로그)를 함께 적는다.

| 기능 | 테이블 | 쓰는 것 | 근거 |
|---|---|---|---|
| F-QC-011 F-QC-012 F-QC-021 F-QC-022 | `lot_stock` | `status` 만 — 검사대기 → 가용 / 보류, 재판정 | 스펙 §4.3 · D-510 · D-515 |
| F-SHP-011 F-SHP-012 | `lot_stock` | `allocated_qty` 만 — 할당을 잡고 다시 잡는다 | 스펙 §4.3 · D-510 |
| F-SHP-021 | `lot_stock` `stock_move` | 확정 수량만큼 `qty` · `allocated_qty` 를 함께 줄이고 `stock_move` 한 행(출하) | D-510 · function-list F-SHP-021 |
| 모든 쓰기 | `notification` | `notify.emit` 한 곳 · 쓰기 트랜잭션 안 | 스펙 §4.3 · D-511 |
| 모든 쓰기 | `sys_change_log` | 쓰기 성공 직후 `audit.log_change` 한 행 (「쓰는 테이블」 열에 적지 않는 공통 규칙) | §2.1 규칙 3 · G-18 |
| 모든 화면 조회 | `sys_access_log` | 화면 GET 마다 `templating.render` 가 조회 로그 한 행 (로그인 · 오류도 같은 표) | G-18 |
| F-MAT-011 F-MAT-012 F-MAT-031 F-MAT-032 | `lot_stock` | 입고 LOT 의 재고 행 — 검사대기로 넣고 고친다 | D-510 · function-list F-MAT-011 · F-MAT-031 |
| F-MAT-021 F-MAT-022 | `lot_stock` `stock_move` | 불출 수량만큼 `qty` 를 줄이고 `stock_move` 한 행(불출 · 불출 취소) | function-list F-MAT-021 |
| F-INV-021 | `product_lot` `material_lot` | 분할 LOT 의 새 LOT 행 — `parent_lot_id` = 원 LOT · 번호 원 번호 + `-01` 순번 | D-509 · function-list F-INV-021 |
| F-DOC-011 | `sys_access_log` | SSO 진입 로그(구분 SSO) | D-514 · G-18 |
| F-RPT-132 | `sys_ai_call_log` | AI 호출 로그 | D-513 |

### 2.3 화면 → 쓰는 테이블 (렌더본 — `function-list.md` 에서 찍는다)

<!-- BEGIN:generated writes -->
| 화면 ID | 화면 | 대메뉴 | 쓰기 기능 | 쓰는 테이블 |
|---|---|---|---|---|
| HOME-020 | 알림함 | HOME | F-HOME-022 | `notification` |
| HOME-030 | 알림 설정 | HOME | F-HOME-031 | `notification_setting` |
| BAS-010 | 품목 관리 | BAS | F-BAS-011 F-BAS-012 F-BAS-013 | `item` |
| BAS-020 | 거래처 관리 | BAS | F-BAS-021 F-BAS-022 F-BAS-023 | `customer` |
| BAS-030 | 창고·위치 관리 | BAS | F-BAS-031 F-BAS-032 F-BAS-033 | `warehouse` `location` |
| STD-010 | 제조사양기준서 | STD | F-STD-011 F-STD-012 F-STD-013 | `spec_sheet` |
| STD-020 | 표준관리 | STD | F-STD-021 F-STD-022 F-STD-023 | `standard` |
| STD-030 | 판관리 | STD | F-STD-031 F-STD-032 F-STD-033 | `plate` `plate_usage` |
| STD-040 | 시안등록 | STD | F-STD-041 F-STD-042 | `artwork` |
| STD-050 | 표준견본서 | STD | F-STD-051 F-STD-052 | `sample_sheet` |
| STD-060 | 예외제품관리 | STD | F-STD-061 F-STD-062 F-STD-063 | `exception_item` |
| WO-010 | 생산의뢰서 | WO | F-WO-011 F-WO-012 | `production_request` `notification` |
| WO-020 | 생산지시서 | WO | F-WO-021 F-WO-022 | `work_order` `notification` |
| WO-030 | 생산순서관리 | WO | F-WO-031 | `work_sequence` |
| MAT-010 | 원자재 입고 | MAT | F-MAT-011 F-MAT-012 | `material_receipt` `material_lot` `lot_stock` `notification` |
| MAT-020 | 불출 | MAT | F-MAT-021 F-MAT-022 | `material_issue` `material_issue_line` `lot_stock` `stock_move` |
| MAT-030 | 제품 입고 | MAT | F-MAT-031 F-MAT-032 | `product_receipt` `product_lot` `lot_stock` `notification` |
| PRD-010 | 생산일보 | PRD | F-PRD-011 F-PRD-012 | `production_daily` |
| INS-010 | 검사일보 | INS | F-INS-011 F-INS-012 | `inspection_daily` |
| QC-010 | 입고검사 | QC | F-QC-011 F-QC-012 | `incoming_inspection` `lot_stock` |
| QC-020 | 제품검사 판정 | QC | F-QC-021 F-QC-022 | `product_inspection` `lot_stock` `notification` |
| INV-020 | 재고 이동 | INV | F-INV-021 F-INV-022 | `stock_move` `lot_stock` `product_lot` `material_lot` |
| INV-030 | 재고 조정·실사 | INV | F-INV-031 | `stock_adjust` `lot_stock` |
| SHP-010 | 출하 지시 | SHP | F-SHP-011 F-SHP-012 | `shipment_order` `shipment_line` `lot_stock` `notification` |
| SHP-020 | 출하 확정 | SHP | F-SHP-021 F-SHP-023 | `shipment_order` `lot_stock` `stock_move` `notification` `shipment_adjust` |
| COL-010 | ERP 수금현황 업로드 | COL | F-COL-011 | `erp_upload_batch` `erp_upload_row` `erp_column_map` `notification` |
| COL-030 | 거래처 코드 매핑 | COL | F-COL-031 F-COL-032 F-COL-033 | `erp_customer_map` `erp_upload_row` |
| RPT-130 | 데이터 질의 | RPT | F-RPT-132 | `data_query_log` `sys_ai_call_log` |
| DOC-010 | 문서관리 바로가기 | DOC | F-DOC-011 | `sso_token` `sys_access_log` |
| DOC-020 | 문서관리 계정 매핑 | DOC | F-DOC-021 F-DOC-022 F-DOC-023 | `doc_account_map` |
| SYS-010 | 사용자 관리 | SYS | F-SYS-011 F-SYS-012 F-SYS-013 | `sys_user` |
| SYS-020 | 역할·권한 | SYS | F-SYS-021 | `sys_role` `sys_permission` |
| SYS-030 | 공통코드 | SYS | F-SYS-031 | `sys_common_code` |
<!-- END:generated writes -->

## 3. 추적 척추 (완료 기준 — 스펙 §4.2)

출하 번호 또는 제품 LOT 하나에서 원자재 LOT 까지 거슬러 올라갈 수 있어야 한다. 경로는 FK 다섯 고리이고, 추적은 이 FK 를 따라가는 **읽기 전용 조회**(`trace.py`)다.

```
material_receipt ──< material_lot ──< material_issue_line >── material_issue
                       (원자재 LOT)       │ material_lot_id · work_order_id
                                          ▼
production_request ──< work_order  ◄──────┘
   (의뢰 = 수주 키)     (생산지시)
                          │ product_receipt.work_order_id · product_lot_id
                          ▼
                       product_lot ──< product_receipt
                       (제품 LOT)   ◄── parent_lot_id (분할 LOT → 원 LOT)
                          │ shipment_line.product_lot_id · shipment_order_id
                          ▼
                       shipment_order ──< shipment_adjust (확정 후 반품·정정)
                       (출하)
```

| 고리 | FK |
|---|---|
| 원자재 LOT → 지시 | `material_issue_line.material_lot_id → material_lot` · `material_issue_line.work_order_id → work_order` |
| 지시 → 의뢰 | `work_order.request_id → production_request` |
| 지시 → 제품 LOT | `product_receipt.work_order_id → work_order` · `product_receipt.product_lot_id → product_lot` (`product_lot.work_order_id` 도 같은 지시) |
| 제품 LOT → 출하 | `shipment_line.product_lot_id → product_lot` · `shipment_line.shipment_order_id → shipment_order` |
| 분할 LOT → 원 LOT | `product_lot.parent_lot_id → product_lot` · `material_lot.parent_lot_id → material_lot` + `stock_move`(구분 `분할`, `source_lot_id` = 원 LOT) |

- **LOT-020 역방향**: 출하 → `shipment_line` → 제품 LOT →(`parent_lot_id` 를 끝까지)→ 원 제품 LOT → `work_order` → `material_issue_line` → 원자재 LOT(→ `parent_lot_id` 로 원 입고 LOT → `material_receipt`).
- **LOT-010 정방향**: 원자재 LOT(과 그 분할 자식) → `material_issue_line` → `work_order` → `product_lot`(과 분할 자식) → `shipment_line` → `shipment_order`.
- 분할 LOT 는 원 LOT 의 지시(`work_order_id`) · 품목을 그대로 가진다. 분할 번호는 원 번호 + `-01`(D-509).
- `lot_stock` · `stock_move` · `stock_adjust` 의 `lot_id` 는 `lot_kind`(원자재 → `material_lot.id`, 제품 → `product_lot.id`)가 가리키는 다형 키라 FK 가 없다 — 쓰는 쪽(`MAT` · `INV` · `QC` · `SHP` 라우터)이 같은 트랜잭션에서 LOT 행을 확인한다.

## 4. 테이블 · 컬럼 (렌더본 — 손으로 고치지 않는다)

<!-- BEGIN:generated tables -->
#### BAS 기준정보 — 테이블 4

### `item` — BAS · 품목 — 제품과 원자재를 한 테이블에 구분으로. 품목 코드는 바꾸지 않는다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| item_code | text | N | 품목 코드 (중복 금지 · 수정 불가) |
| item_name | text | N | 품목명 |
| item_type | text | N | 구분: 제품 | 원자재 |
| spec | text | Y | 규격 (글자 그대로 — 값은 받은 적 없다) |
| unit | text | Y | 단위 |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N — N 이면 의뢰·입고·출하 지시에서 고를 수 없다 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `customer` — BAS · 거래처 — 의뢰·출하의 상대. ERP 거래처와는 erp_customer_map 으로 잇는다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| customer_code | text | N | 거래처 코드 (중복 금지 · 수정 불가) |
| customer_name | text | N | 거래처명 |
| contact_name | text | Y | 담당자 |
| phone | text | Y | 연락처 |
| address | text | Y | 주소 |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `warehouse` — BAS · 창고

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| warehouse_code | text | N | 창고 코드 (중복 금지 · 수정 불가) |
| warehouse_name | text | N | 창고명 |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `location` — BAS · 위치(랙·구역) — 창고 아래에 둔다. 재고(lot_stock)가 남은 위치는 지울 수 없다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| warehouse_id | bigint | N | 창고 |
| location_code | text | N | 위치 코드 (창고 안에서 중복 금지) |
| location_name | text | N | 위치명 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

#### STD 인쇄 기준 — 테이블 7

### `spec_sheet` — STD · 제조사양기준서 — 제품별 인쇄 사양. 생산지시서가 불러온다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| item_id | bigint | N | 제품 (BAS-010) |
| revision | integer | N | 개정 차수 |
| title | text | N | 제목 |
| content | jsonb | N | 사양 항목 → 값 (양식 미수집 — 항목 이름을 정하지 않는다) |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N — N 이면 지시서에서 불러오지 않는다 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `standard` — STD · 표준 조건 — 등록·조회만 한다. 적용 규칙은 미확정 (D-519)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| standard_code | text | N | 표준 코드 (중복 금지) |
| standard_name | text | N | 표준명 |
| content | jsonb | N | 조건 항목 → 값 (FINE_MES 화면 미수집) |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `plate` — STD · 인쇄 판 — 보유 판. 사용 이력은 plate_usage

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| plate_code | text | N | 판 코드 (중복 금지 · 수정 불가) |
| plate_name | text | N | 판 이름 |
| item_id | bigint | Y | 제품 (없을 수 있다) |
| made_on | date | Y | 제작일 |
| storage | text | Y | 보관 위치 (글자) |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `artwork` — STD · 시안 이미지 — 제품에 연결해 작업지시와 함께 본다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| item_id | bigint | N | 제품 |
| title | text | N | 시안 이름 |
| version | integer | N | 시안 차수 |
| file_name | text | N | 올린 파일 이름 |
| content_type | text | N | 이미지 형식 (MIME — 이미지가 아니면 422) |
| image | bytea | N | 이미지 바이트 |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `sample_sheet` — STD · 표준견본서 — 제품별로 만들고 출력한다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| item_id | bigint | N | 제품 |
| title | text | N | 제목 |
| content | jsonb | N | 견본서 항목 → 값 (양식 미수집) |
| issued_on | date | Y | 작성일 |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `exception_item` — STD · 예외제품 지정 — 지정·조회만 한다. 적용 규칙은 미확정 (D-519)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| item_id | bigint | N | 제품 (한 제품에 한 행) |
| reason | text | N | 예외 사유 |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `plate_usage` — STD · 판 사용 이력 — 판을 쓴 지시·날짜 한 행 (지시를 참조하므로 WO 뒤에 만든다)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| plate_id | bigint | N | 판 |
| work_order_id | bigint | Y | 사용한 생산지시 (없을 수 있다) |
| used_on | date | N | 사용일 |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

#### WO 작업지시 — 테이블 3

### `production_request` — WO · 생산의뢰 — IA 전체의 「수주」. 의뢰번호가 지시 → 일보 → 제품 입고 → 출하의 연결 키

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| request_no | text | N | 의뢰번호 numbering.next("REQ") (형식 D-509 · 수정 불가) |
| request_date | date | N | 의뢰일 |
| customer_id | bigint | N | 거래처 |
| item_id | bigint | N | 제품 (사용 중지 품목은 고를 수 없다) |
| qty | numeric(14,3) | N | 의뢰 수량 |
| due_date | date | N | 납기 |
| status | text | N | 확인대기 → 확정 → 지시완료 | 취소 |
| note | text | Y | 비고 (발주 내용 요약 — 발주서는 FINE_MES 에 남는다) |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `work_order` — WO · 생산지시서 — 의뢰 한 건에서 만든다. 지시번호는 불출·제품 입고에서 고르는 값

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| work_order_no | text | N | 지시번호 numbering.next("WO") (형식 D-509 · 수정 불가) |
| request_id | bigint | N | 생산의뢰 (수정 불가) |
| item_id | bigint | N | 제품 (의뢰에서 복사) |
| spec_sheet_id | bigint | Y | 불러온 제조사양기준서 (STD-010) |
| artwork_id | bigint | Y | 불러온 시안 (STD-040) |
| qty | numeric(14,3) | N | 지시 수량 |
| equipment_code | text | Y | 설비 (sys_common_code 그룹 설비) |
| planned_on | date | Y | 생산 예정일 |
| status | text | N | 발행 → 진행 → 완료 | 취소 |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `work_sequence` — WO · 작업 순서 — 설비별로 지시의 순서를 정한다. 같은 설비 안에서 옮긴다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| work_order_id | bigint | N | 생산지시 (한 지시에 한 행) |
| equipment_code | text | N | 설비 (sys_common_code 그룹 설비) |
| seq_no | integer | N | 설비 안의 순서 (1부터) |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

#### MAT 자재·입고 — 테이블 6

### `material_receipt` — MAT · 원자재 입고 헤더 — 공급사 · 입고일. LOT 는 material_lot 행

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| supplier_name | text | N | 공급사 (글자 — 공급사 기준정보는 정본에 없다) |
| received_on | date | N | 입고일 |
| note | text | Y | 비고 |
| canceled_at | timestamp with time zone | Y | 취소 일시 (지우지 않고 표시만 — MAT-040) |
| canceled_by | text | Y | 취소자 login_id |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `material_lot` — MAT · 원자재 입고 LOT — 추적 척추의 맨 앞. 입고 직후 lot_stock 에 검사대기로 잡힌다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| lot_no | text | N | 입고 LOT 번호 numbering.next("MLOT") · 분할 LOT 는 원 번호 + -01 (D-509 · 수정 불가) |
| receipt_id | bigint | N | 입고 헤더 |
| item_id | bigint | N | 원자재 품목 |
| qty | numeric(14,3) | N | 입고 수량 (분할 LOT 는 나눈 수량). 현재고는 lot_stock |
| supplier_lot_no | text | Y | 공급사 LOT 번호 |
| parent_lot_id | bigint | Y | 분할 원 LOT (INV-020) — 없으면 입고 LOT |
| canceled_at | timestamp with time zone | Y | 취소 일시 |
| canceled_by | text | Y | 취소자 login_id |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `material_issue` — MAT · 불출 헤더 — 불출일. LOT·지시·수량은 material_issue_line

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| issued_on | date | N | 불출일 |
| note | text | Y | 비고 |
| canceled_at | timestamp with time zone | Y | 취소 일시 (지우지 않고 표시만 — MAT-040) |
| canceled_by | text | Y | 취소자 login_id |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `material_issue_line` — MAT · 불출 행 — 원자재 LOT → 생산지시. 추적 척추 첫 고리 (가용 LOT 만 · 가용 수량 안에서)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| issue_id | bigint | N | 불출 헤더 |
| material_lot_id | bigint | N | 불출한 원자재 LOT (검사대기·보류 LOT 는 422) |
| work_order_id | bigint | N | 생산지시 (지시서 목록에서 고른다) |
| location_id | bigint | N | 꺼낸 위치 (lot_stock 의 키) |
| qty | numeric(14,3) | N | 불출 수량 (가용 수량 이하) |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `product_lot` — MAT · 제품 LOT — 지시번호와 묶여 LOT 추적에 쓰인다. 분할 LOT 는 parent_lot_id + stock_move

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| lot_no | text | N | 제품 LOT 번호 numbering.next("PLOT") · 분할 LOT 는 원 번호 + -01 (D-509 · 수정 불가) |
| item_id | bigint | N | 제품 품목 |
| work_order_id | bigint | N | 생산지시 (분할 LOT 는 원 LOT 의 지시 · 수정 불가) |
| parent_lot_id | bigint | Y | 분할 원 LOT (INV-020) — 없으면 입고 LOT |
| qty | numeric(14,3) | N | 생성 수량 (분할 LOT 는 나눈 수량). 현재고는 lot_stock |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `product_receipt` — MAT · 제품 입고 — 생산지시 → 제품 LOT. 추적 척추 둘째 고리. 기본 수량 = 일보 완료 수량

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| work_order_id | bigint | N | 생산지시 (수정 불가) |
| product_lot_id | bigint | N | 만든 제품 LOT (입고 한 건에 LOT 하나) |
| location_id | bigint | N | 입고 위치 (lot_stock 의 키) |
| qty | numeric(14,3) | N | 입고 수량 |
| received_on | date | N | 입고일 |
| note | text | Y | 비고 |
| canceled_at | timestamp with time zone | Y | 취소 일시 (지우지 않고 표시만 — MAT-040) |
| canceled_by | text | Y | 취소자 login_id |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

#### PRD 생산일보 — 테이블 1

### `production_daily` — PRD · 생산일보 — 지시 × 일자 × 설비 한 행. 로스율 산식은 미확정 (D-519)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| work_order_id | bigint | N | 생산지시 (수정 불가) |
| work_date | date | N | 일자 (수정 불가) |
| equipment_code | text | N | 설비 (sys_common_code 그룹 설비 · 수정 불가) |
| produced_qty | numeric(14,3) | N | 생산 수량 (투입 기준) |
| good_qty | numeric(14,3) | N | 완료(양품) 수량 — 제품 입고의 기본값 |
| loss_qty | numeric(14,3) | N | 로스 수량 |
| run_minutes | integer | Y | 가동 시간(분) — 가동률 원천 |
| stop_minutes | integer | Y | 정지 시간(분) |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

#### INS 검사일보 — 테이블 1

### `inspection_daily` — INS · 검사일보 — 공정 검사(지시 × 일자). 입고검사·제품검사 판정(QC)과는 다른 기록

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| work_order_id | bigint | N | 생산지시 |
| work_date | date | N | 일자 |
| inspected_qty | numeric(14,3) | N | 검사 수량 |
| defect_qty | numeric(14,3) | N | 불량 수량 (합) |
| defects | jsonb | N | 불량유형 코드(sys_common_code 그룹 불량유형) → 수량 |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

#### QC 품질 검사 — 테이블 2

### `incoming_inspection` — QC · 입고검사 판정 — 원자재 LOT 마다 차수(seq). 합격 → lot_stock 가용, 불합격 → 보류

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| material_lot_id | bigint | N | 원자재 LOT |
| seq | integer | N | 판정 차수 (1 = 첫 판정, 2 이상 = 재판정) |
| result | text | N | 합격 | 불합격 |
| items | jsonb | N | 검사 항목 → 값 (항목 미수집) |
| inspected_at | timestamp with time zone | N | 판정 일시 |
| inspector | text | Y | 판정자 login_id |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 (판정 행은 고치지 않는다 — 재판정은 새 행) |
| updated_by | text | Y | 수정자 login_id |

### `product_inspection` — QC · 제품검사 판정 — 제품 LOT 마다 차수(seq). 미판정·불합격 LOT 는 출하 확정 불가

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| product_lot_id | bigint | N | 제품 LOT |
| seq | integer | N | 판정 차수 (1 = 첫 판정, 2 이상 = 재판정) |
| result | text | N | 합격 | 불합격 |
| items | jsonb | N | 검사 결과 항목 → 값 (항목 미수집) |
| inspected_at | timestamp with time zone | N | 판정 일시 |
| inspector | text | Y | 판정자 login_id |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 (판정 행은 고치지 않는다 — 재판정은 새 행) |
| updated_by | text | Y | 수정자 login_id |

#### INV 재고 — 테이블 3

### `lot_stock` — INV · LOT 재고 — (구분, LOT, 위치) 한 행. 가용 수량 = qty − allocated_qty (D-510)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| lot_kind | text | N | LOT 구분: 원자재 (material_lot.id) | 제품 (product_lot.id) |
| lot_id | bigint | N | LOT 키 — lot_kind 가 가리키는 테이블의 id (다형 키라 FK 없음) |
| location_id | bigint | N | 위치 |
| qty | numeric(14,3) | N | 현재고 — 입고 +, 불출·이동·출하 확정 −, 조정은 실사 수량으로 |
| allocated_qty | numeric(14,3) | N | 출하 지시 할당량 (SHP-010 이 잡고 SHP-020 확정이 qty 와 함께 줄인다) |
| status | text | N | 검사대기 → 가용 | 보류 (QC 판정 · 재판정이 바꾼다) |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `stock_move` — INV · 재고 이동 — 불출 · 위치 이동 · LOT 분할 · 출하 확정 한 행씩. 분할 LOT 는 source_lot_id 로 원 LOT 에 잇는다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| move_kind | text | N | 불출 | 불출 취소 | 이동 | 분할 | 출하 |
| lot_kind | text | N | LOT 구분: 원자재 | 제품 |
| lot_id | bigint | N | 옮긴 LOT (분할이면 새 LOT) |
| source_lot_id | bigint | Y | 분할 원 LOT (분할일 때만) |
| from_location_id | bigint | Y | 출발 위치 (없으면 밖에서 들어옴) |
| to_location_id | bigint | Y | 도착 위치 (없으면 밖으로 나감 — 불출·출하) |
| qty | numeric(14,3) | N | 이동 수량 (가용 수량 이하) |
| ref_table | text | Y | 원천 행의 테이블 (material_issue_line · shipment_order …) |
| ref_id | bigint | Y | 원천 행의 id |
| moved_at | timestamp with time zone | N | 이동 일시 |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `stock_adjust` — INV · 재고 조정 — 실사 수량 · 차이 사유(필수). 불변 이력: UPDATE · DELETE 는 트리거가 막는다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| lot_kind | text | N | LOT 구분: 원자재 | 제품 |
| lot_id | bigint | N | LOT 키 |
| location_id | bigint | N | 위치 |
| book_qty | numeric(14,3) | N | 조정 전 장부 수량 (lot_stock.qty) |
| actual_qty | numeric(14,3) | N | 실사 수량 — lot_stock.qty 가 이 값이 된다 |
| diff_qty | numeric(14,3) | Y | 차이 = 실사 − 장부 |
| reason | text | N | 차이 사유 (필수 — 빈 글자 금지) |
| adjusted_at | timestamp with time zone | N | 조정 일시 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |

#### SHP 출하 — 테이블 3

### `shipment_order` — SHP · 출하 지시 — 영업부가 등록하고 출하실이 확정한다. 의뢰번호가 있으면 납기 준수율을 낸다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| shipment_no | text | N | 출하 번호 numbering.next("SHP") (형식 D-509 · 수정 불가) |
| request_id | bigint | Y | 생산의뢰 (공정 이관 시 — 없을 수 있다) |
| customer_id | bigint | N | 거래처 |
| due_date | date | N | 납기 |
| status | text | N | 지시 → 확정 | 취소 (확정된 출하는 고치지 않는다) |
| confirmed_at | timestamp with time zone | Y | 확정 일시 |
| confirmed_by | text | Y | 확정자 login_id |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `shipment_line` — SHP · 출하 행 — 출하 지시 → 제품 LOT(위치). 추적 척추 마지막 고리. 할당 = 이 행의 qty

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| shipment_order_id | bigint | N | 출하 지시 |
| product_lot_id | bigint | N | 할당한 제품 LOT |
| location_id | bigint | N | 할당한 위치 (lot_stock 의 키) |
| qty | numeric(14,3) | N | 할당·출하 수량 (가용 수량 이하) |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `shipment_adjust` — SHP · 반품·정정 — 확정 후 정정은 이 행으로만. 불변 이력 · 재고는 바꾸지 않는다 (D-515)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| shipment_order_id | bigint | N | 원 출하 (확정된 출하만) |
| kind | text | N | 구분: 반품 | 정정 |
| qty | numeric(14,3) | N | 수량 — 음수 = 반품(줄어든 수량), 양수 = 정정으로 늘어난 수량 |
| reason | text | N | 사유 (필수 — 빈 글자 금지) |
| product_lot_id | bigint | Y | 대상 제품 LOT (없을 수 있다) |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |

#### COL 수금리포트 — 테이블 4

### `erp_upload_batch` — COL · ERP 업로드 회차 — 같은 기준 기간을 다시 올리면 새 회차가 반영, 이전 회차는 교체로 남는다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| batch_no | text | N | 회차 번호 numbering.next("ERP") (형식 D-509) |
| period_from | date | N | 기준 기간 시작 |
| period_to | date | N | 기준 기간 끝 |
| round_no | integer | N | 그 기간의 회차 (1부터) |
| status | text | N | 반영 → 교체 (새 회차가 올라오면) |
| replaced_by | bigint | Y | 이 회차를 교체한 새 회차 |
| source_file | text | N | 올린 파일 이름 |
| row_count | integer | N | 읽은 행 수 |
| error_count | integer | N | 오류·미매핑 행 수 (반영에서 뺀다) |
| uploaded_at | timestamp with time zone | N | 업로드 일시 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 (교체 표시) |
| updated_by | text | Y | 수정자 login_id |

### `erp_upload_row` — COL · ERP 업로드 행 — 원문(raw) · 매핑 적용 값(parsed) · 오류. error 가 있으면 반영에서 뺀다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| batch_id | bigint | N | 업로드 회차 |
| row_no | integer | N | 엑셀 행 번호 |
| raw | jsonb | N | 원문 열 이름 → 글자 (양식 변환 없이 그대로) |
| parsed | jsonb | Y | erp_column_map 적용 값 (customer_code · txn_date · sales_amount · collected_amount · balance_amount · method · bill_due_date — D-516) |
| error | text | Y | 오류 사유 (필수 열 · 형식 · 거래처 미매핑). 있으면 반영 제외 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 (매핑 뒤 재반영) |
| updated_by | text | Y | 수정자 login_id |

### `erp_customer_map` — COL · ERP 거래처코드 ↔ MES 거래처 — 출하(MES)와 수금(ERP)을 잇는 유일한 키

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| erp_code | text | N | ERP 거래처코드 (ERP 코드 하나에 MES 거래처 하나) |
| erp_name | text | Y | ERP 거래처명 (참고) |
| customer_id | bigint | N | MES 거래처 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `erp_column_map` — COL · ERP 엑셀 열 매핑 — 처음 한 번 저장하면 다음 업로드부터 자동 적용 (열 구성 미확정 D-516)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| field | text | N | MES 항목 (customer_code · txn_date · sales_amount · collected_amount · balance_amount · method · bill_due_date) |
| column_name | text | N | ERP 엑셀의 열 이름 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

#### RPT 대시보드 — 테이블 1

### `data_query_log` — RPT · 데이터 질의 로그 — 거부를 포함한 모든 질의 한 행 (D-513)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| query_no | text | N | 로그 번호 numbering.next("DQ") (형식 D-509) |
| user_id | bigint | Y | 질의한 사용자 |
| role_code | text | Y | 그때의 부서 (부서별 뷰 제한의 근거) |
| question | text | N | 질문 원문 |
| sql_text | text | Y | 생성된 SQL (AI 실패면 없다) |
| ok | boolean | N | 실행했는가 (검증 거부·실패는 false) |
| row_count | integer | Y | 돌려준 행 수 |
| error | text | Y | 거부·실패 사유 |
| ms | integer | Y | 걸린 시간(밀리초) |
| created_at | timestamp with time zone | N | 질의 일시 |

#### DOC 문서관리 — 테이블 2

### `doc_account_map` — DOC · MES 사용자 ↔ 문서관리 계정 ID (1:1). 매핑이 없으면 SSO 토큰을 발급하지 않는다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| user_id | bigint | N | MES 사용자 |
| account_id | text | N | 문서관리 계정 ID |
| active | boolean | N | 사용 여부 (삭제 대신 false) |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `sso_token` — DOC · 일회용 SSO 토큰 — jti · 만료(60초) · 사용 시각. 재사용을 막는다 (D-514)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| jti | uuid | N | 토큰 ID |
| user_id | bigint | N | 발급받은 사용자 |
| account_id | text | N | 넘긴 문서관리 계정 ID |
| issued_at | timestamp with time zone | N | 발급 시각 |
| expires_at | timestamp with time zone | N | 만료 시각 (발급 + 60초) |
| used_at | timestamp with time zone | Y | 사용 시각 (한 번만 — 있으면 재사용 거부) |
| created_at | timestamp with time zone | N | 등록 일시 |

#### HOME 내 업무 — 테이블 2

### `notification` — HOME · 알림 — 수신 부서마다 1행. (dedupe_key, to_role) 유일. 한 사람이 처리하면 같은 부서에 처리됨 (D-511 · D-522)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| event_key | text | N | 이벤트 키 (notify.EVENTS — request_created · … 9종) |
| to_role | text | N | 수신 부서 |
| link | text | Y | 눌렀을 때 여는 화면 경로 |
| dedupe_key | text | N | 중복 방지 키 (같은 키 재발생은 무시) |
| message | text | N | 알림 문장 |
| handled_at | timestamp with time zone | Y | 처리 일시 (부서 안 누구든 처리하면 채운다) |
| handled_by | text | Y | 처리자 login_id |
| created_at | timestamp with time zone | N | 발생 일시 |

### `notification_setting` — HOME · 개인 추가 알림 설정 — 부서 기본 알림은 끌 수 없다. 메일·메신저는 미확정 (D-518)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| user_id | bigint | N | 사용자 |
| event_key | text | N | 이벤트 키 |
| enabled | boolean | N | 켜짐 여부 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

#### SYS 시스템 — 테이블 9

### `sys_role` — SYS · 역할(부서) — 정본 8부서. 역할을 늘리려면 행을 넣는다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| role_code | text | N | 부서 코드 (SL · PR · SH · DS · AC · ST · EX · ADM) |
| role_name | text | N | 부서 이름 (영업부 · 생산부 · …) |
| sort_no | integer | N | 표시 순서 (권한 표의 열 순서) |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `sys_user` — SYS · 사용자 계정 — 퇴사자는 지우지 않고 중지로 둔다(SYS-010)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| user_id | bigint | N | 내부 키 |
| login_id | text | N | 로그인 ID (사번) |
| user_name | text | N | 이름 |
| password_hash | text | N | 비밀번호 해시 (PBKDF2 · 화면에 내보내지 않는다) |
| role_code | text | N | 부서(역할) — 요청마다 DB 에서 읽는다 |
| status | text | N | 정상 | 잠금 | 중지. 정상만 로그인한다 |
| fail_count | integer | N | 연속 로그인 실패 횟수 |
| last_login_at | timestamp with time zone | Y | 마지막 로그인 |
| session_epoch | integer | N | 세션 판 번호 — 상태·비밀번호가 바뀌면 트리거가 +1. 로그인 때의 값과 다른 세션은 무효 |
| revoked_sessions | jsonb | N | 로그아웃한 세션 ID → 로그아웃 시각(epoch 초) |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `sys_permission` — SYS · 권한 칸 — 부서 × 화면 한 칸이 한 행 (W | R). 행이 없으면 권한 없음. 코드가 아니라 데이터다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| role_code | text | N | 부서 |
| screen_id | text | N | 화면 ID (nav.py · 정본 그대로) |
| level | text | N | W = 처리·조회 | R = 조회 |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `sys_common_code` — SYS · 공통코드 — 설비 · 불량유형 · 수금수단. 참조가 있으면 지우지 않고 사용 중지

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| group_code | text | N | 코드 그룹 (설비 · 불량유형 · 수금수단) |
| code | text | N | 코드 값 (그룹 안에서 중복 금지) |
| code_name | text | N | 코드 이름 |
| sort_no | integer | N | 표시 순서 |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | Y | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `sys_access_log` — SYS · 접근 로그 — 로그인 성공·실패 · 화면 조회 · SSO 진입 · 오류 (G-18)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| log_id | bigint | N | 내부 키 |
| logged_at | timestamp with time zone | N | 일시 (언제) |
| log_type | text | N | 구분: 로그인 | 조회 | 변경 | 오류 | SSO |
| login_id | text | Y | 누가 (실패한 로그인은 입력한 ID) |
| role_code | text | Y | 그때의 부서 |
| method | text | Y | HTTP 메서드 |
| path | text | Y | 경로 |
| screen_id | text | Y | 화면 ID (nav.py) |
| function_id | text | Y | 기능 ID (function-list.md) |
| target | text | Y | 무엇을 (테이블·업무 번호) |
| result | text | N | 성공 | 실패 |
| detail | text | Y | 내용 |
| client_ip | text | Y | 접속 IP |

### `sys_change_log` — SYS · 데이터 변경 로그 — 쓰기 성공 직후 audit.log_change 가 한 행 (누가 · 언제 · 무엇을)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| changed_at | timestamp with time zone | N | 일시 |
| login_id | text | N | 누가 |
| role_code | text | Y | 그때의 부서 |
| function_id | text | N | 기능 ID (function-list.md) |
| screen_id | text | Y | 화면 ID |
| method | text | Y | HTTP 메서드 |
| path | text | Y | 경로 |
| target | text | N | 무엇을 (`테이블:업무 번호`) |
| detail | text | Y | 내용 |
| client_ip | text | Y | 접속 IP |

### `sys_number_rule` — SYS · 채번 형식 — 번호 종류별 한 행 (REQ · WO · MLOT · PLOT · SHP · ERP · DQ). 형식은 코드가 아니라 이 행이다 (D-509)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| seq_kind | text | N | 번호 종류: REQ | WO | MLOT | PLOT | SHP | ERP | DQ |
| prefix | text | N | 접두 글자 (예시 — D-509) |
| date_format | text | N | 날짜 부분 형식 (to_char 형식 · 빈 글자면 날짜 없음) |
| seq_digits | integer | N | 일련번호 자릿수 |
| note | text | Y | 비고 (가설 형식의 근거) |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `sys_number_seq` — SYS · 채번 카운터 — (번호 종류, 범위) 마다 마지막 일련번호

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| seq_kind | text | N | 번호 종류 |
| seq_scope | text | N | 범위 (날짜 부분 값 · 날짜가 바뀌면 1부터) |
| last_value | bigint | N | 마지막으로 내준 일련번호 |

### `sys_ai_call_log` — SYS · AI 호출 로그 — 모든 AI 호출 한 행 (데이터 질의의 SQL 생성 등 · D-513)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| id | bigint | N | 내부 키 |
| kind | text | N | 호출 용도 (데이터 질의 등) |
| model | text | Y | 모델 이름 |
| ok | boolean | N | 성공 여부 |
| ms | integer | Y | 걸린 시간(밀리초) |
| error | text | Y | 실패 사유 (키 없음 포함 — 키 값은 적지 않는다) |
| user_id | bigint | Y | 부른 사용자 |
| created_at | timestamp with time zone | N | 호출 일시 |
<!-- END:generated tables -->

## 5. 뷰 (렌더본 — 읽기 전용 · 저장하지 않고 계산한다)

<!-- BEGIN:generated views -->
| 뷰 | 컬럼 | 설명 |
|---|---|---|
| `v_work_order_status` | `work_order_id` `work_order_no` `request_id` `request_no` `item_id` `order_qty` `daily_good_qty` `receipt_qty` `shipped_qty` `status` | 지시별 공정 상태 (WO-040) — 지시 수량 · 일보 완료 합 · 제품 입고 합 · 출하 합(확정 출하 · shipment_adjust 반품·정정은 빼지 않는다 — D-515) · 상태 |
| `v_dq_orders` | `request_no` `request_date` `customer_code` `customer_name` `item_code` `item_name` `qty` `due_date` `status` | 데이터 질의 — 수주(=생산의뢰) |
| `v_dq_work_orders` | `work_order_no` `request_no` `item_code` `item_name` `equipment_code` `planned_on` `order_qty` `daily_good_qty` `receipt_qty` `shipped_qty` `status` | 데이터 질의 — 생산지시와 진행 수량 |
| `v_dq_stock` | `lot_kind` `lot_no` `item_code` `item_name` `warehouse_code` `location_code` `qty` `allocated_qty` `available_qty` `status` | 데이터 질의 — LOT × 위치 재고 (가용 = 현재고 − 할당) |
| `v_dq_shipments` | `shipment_no` `request_no` `customer_code` `customer_name` `due_date` `status` `confirmed_at` `lot_no` `item_code` `item_name` `qty` | 데이터 질의 — 출하 지시 행 (LOT · 수량 · 납기 · 확정) |
| `v_dq_quality` | `inspection_kind` `lot_no` `item_code` `item_name` `seq` `result` `inspected_at` `is_latest` | 데이터 질의 — 입고검사 · 제품검사 판정 (is_latest = 그 LOT 의 현재 판정) |
| `v_dq_production_daily` | `work_date` `work_order_no` `item_code` `item_name` `equipment_code` `produced_qty` `good_qty` `loss_qty` `run_minutes` `stop_minutes` | 데이터 질의 — 생산일보 (지시 × 일자 × 설비) |
| `v_dq_collections` | `batch_no` `period_from` `period_to` `erp_customer_code` `customer_code` `customer_name` `txn_date` `sales_amount` `collected_amount` `balance_amount` `method` `bill_due_date` | 데이터 질의 — 수금 (반영 회차의 오류 없는 행만 · 사용 중 매핑만 · 기간이 겹치면 올라온 그대로 센다 D-516 · 영업부·회계부·관리자·경영진만 — D-513) |
| `v_dq_receivables` | `erp_customer_code` `customer_code` `customer_name` `sales_amount` `collected_amount` `receivable_amount` `last_txn_date` `as_of` | 데이터 질의 — 거래처별 미수 (매출 합 − 수금 합 · 기준일 = 반영 회차의 마지막 기간 끝) |
<!-- END:generated views -->

- 수량 합은 취소 표시(`canceled_at`)된 입고 행을 빼고, 출하 수량은 `확정` 출하만 센다.
- `v_dq_collections` · `v_dq_receivables` 는 `erp_upload_batch.status = '반영'` 회차의 `error` 없는 행만 읽는다. `parsed` 의 키는
  `customer_code` · `txn_date` · `sales_amount` · `collected_amount` · `balance_amount` · `method` · `bill_due_date` 이다 — `erp_column_map.field` 와 같은 낱말이고 열 구성은 미확정(D-516).
- 데이터 질의(RPT-130)는 `v_dq_*` 8 만 읽는다. 뷰에는 계정 · 비밀번호 · 토큰 컬럼이 없다. 수금 두 뷰의 부서 제한은 `dataquery` 의 허용 목록에 둔다(D-513).

## 6. 상태값 (한글 그대로 `check`)

| 컬럼 | 값 | 누가 바꾸는가 |
|---|---|---|
| `production_request.status` | `확인대기` → `확정` → `지시완료` / `취소` | WO |
| `work_order.status` | `발행` → `진행` → `완료` / `취소` | WO |
| `material_receipt` · `product_receipt` | 상태 없음 — 입고 행 자체가 사실. 취소는 `canceled_at` 표시(MAT-040) | MAT |
| `lot_stock.status` | `검사대기` → `가용` / `보류` (재판정이 다시 바꾼다). 「할당」은 상태가 아니라 `allocated_qty`(D-510) | MAT(입고) · QC(판정) |
| `incoming_inspection.result` · `product_inspection.result` | `합격` / `불합격` — LOT 의 판정 = 가장 큰 `seq` | QC |
| `stock_move.move_kind` | `불출` · `불출 취소` · `이동` · `분할` · `출하` | MAT · INV · SHP |
| `shipment_order.status` | `지시` → `확정` / `취소` (`확정` ⇔ `confirmed_at` 있음) | SHP |
| `shipment_adjust.kind` | `반품` / `정정` (수량 음수 = 반품) | SHP |
| `erp_upload_batch.status` | `반영` → `교체` (`교체` ⇔ `replaced_by` 있음 · 기간마다 `반영` 은 하나) | COL |
| `sys_permission.level` | `W` / `R` (행 없음 = 권한 없음) | SYS |
| `sys_user.status` | `정상` / `잠금` / `중지` — 바뀌면 트리거 `sys_user_session_epoch_trg` 가 `session_epoch` 를 올려 살아 있는 세션을 끊는다 | SYS |
| `sys_access_log.log_type` | `로그인` · `조회` · `변경` · `오류` · `SSO` | 공통 |
