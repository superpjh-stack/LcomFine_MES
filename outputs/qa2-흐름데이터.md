# QA2 흐름 · 데이터 — W1 (2026-10-21)

검증만 했다. 코드는 고치지 않았다(고친 것은 QA2 소유 `tools/check_data.py` 와 `tests/test_qa2_*.py` 뿐). 흐름은 **HTTP 만**(TestClient · 시드 계정 sl · pr · sh · ds · admin 을 단계마다 바꿔 로그인)으로 만들었고, DB 는 확인(SELECT)과 끝의 정리에만 썼다. 만든 행은 접두 `QA2-<난수>` 로 구분해 끝에 지웠다 — 남은 행 0 (`select count(*) from item where item_code like 'QA2-%'` = 0 · 거래처 · 창고 · 의뢰 · 입고도 0). 시드 계정의 상태 · 부서는 바꾸지 않았다(같은 DB 를 쓰는 QA1 · QA3 의 세션을 끊지 않게). 채번 카운터(`sys_number_seq`)와 감사 행(`sys_change_log` · `sys_access_log`)은 계약상 남긴다.

직전 세션(보고서 없이 끊김)의 실측과 이번 실측을 함께 적는다. 그 사이에 아키텍트가 `db-schema.md` §2.2 를 고치고(코드가 맞다), 개발3 이 F-SHP-012 를 Ruling 21 대로 고치고, 개발2 가 F-MAT-012 · 022 · 032 · F-INV-022 의 빈 본문 422 와 QC-010 · 020 의 `?status=` 필터를 더했다.

## 1. 결함

| ID | 심각도 | 담당 | 상태 | 요약 |
|---|---|---|---|---|
| DEF-QA2-001 | **중대** | 개발3 (`routers/shp.py` F-SHP-012) | **해소(실측)** | 출하 지시 수정에서 LOT 라인을 전부 제거하면 계약(function-list F-SHP-012 · Ruling 21)은 「지시 취소 · 할당 전부 해제」 인데 직전 실측은 **422** 였다. 이번 실측: 200 · `shipment_order.status` 취소 · `shipment_line` 1→0 · `lot_stock.allocated_qty` 10→0 · 독립 SQL(열린 출하 행 합) 0 · INV-010 가용 10 · 알림 없음 |
| DEF-QA2-002 | 경미 | 아키텍트 (`contracts/db-schema.md` §2.2) | **해소(실측)** | 공용 모듈의 쓰기 `numbering` → `sys_number_seq` · `auth`(로그인 · 로그아웃) → `sys_user` 가 §2.2 「이 표가 전부다」 에 없었다(직전 G-05 FAIL). 코드가 맞다 — 아키텍트가 두 줄을 더해 계약을 고쳤고 이번 G-05 는 PASS |
| DEF-QA2-003 | 경미 | 아키텍트 (`contracts/db-schema.md` §2.2 문구) | **해소(실측)** — §2.2 채번 행이 「`numbering.KINDS` 7 · 분할 LOT 번호(원 번호 + `-NN`)와 불출은 채번이 아니다」 로 고쳐졌고 재실행 G-05 정적 4 행 PASS | §2.2 채번 행이 「모든 채번 (의뢰 · 지시 · 입고 LOT · 불출 · 제품 LOT · **분할** · 출하) … `numbering.next` 한 곳」 이라 적었지만, `numbering.KINDS` 7(REQ · WO · MLOT · PLOT · SHP · ERP · DQ)에 분할은 없고 분할 번호는 `routers/inv.py` `_split_no` 가 원 번호 + `-NN` 으로 만든다. 이것은 D-509 「재고 이동으로 LOT 를 나누면 원 LOT 번호에 분할 순번 -01 (정본 문장)」 · `schema.sql` 주석 · §2.2 F-INV-021 행과 **일치**한다. 코드가 맞다 — 채번 행에서 「분할」 을 빼거나 「분할은 F-INV-021 행」 으로 문구를 고칠 것. 「불출」 도 번호가 없다(`material_issue` 는 id 만) — 같은 문구 손질. 재현: `grep -n "모든 채번" contracts/db-schema.md` · `grep -n "KINDS" src/lcomfine/app/numbering.py` · `grep -n "_split_no" src/lcomfine/app/routers/inv.py` |

치명 0 · 중대 1(해소) · 경미 2(해소 2). 미해소 0.

검사기 자체 결함(QA2 몫 · 결함 번호 없음): `check_data.py` 의 G-05 라우터 분기가 공용 모듈 쓰기를 판정할 때 §2.2 예외 표를 읽지 않아, 아키텍트가 계약을 고친 뒤에도 `sys_number_seq ← MAT, SHP, WO` 를 FAIL 로 찍었다(수정 전 종료코드 5). 라우터가 부른 공용 모듈의 쓰기 테이블은 §2.2 에 있으면 허용하도록 고쳤다(`auth` 분기는 이미 그랬다). 고친 뒤 종료코드 4(= W2/W3 몫 4행).

## 2. 게이트 판정 (QA2 몫 G-05 ~ G-15) — W1 시점 (W2 판정은 §7)

> **W2(2026-10-22) 재실측**: G-11 9종 PASS · G-12 · G-13 · G-14 PASS · 종료코드 **1**(G-15 W3 만). 아래 표의 G-11 「미검증」 · G-12~G-14 「FAIL」 은 W1 시점 값이다 — §7 참조.

명령: `uv run python tools/check_data.py --transcript` (= `make check-data` + E2E 기록). 종료코드 = FAIL 행 수. 실측 **종료코드 4** = G-12 · G-13 · G-14 · G-15(W2/W3). 실행 시간 약 3초(TestClient in-process · `jobs due-check` 하위 프로세스 2회 포함). 수정 전 첫 실행은 종료코드 5(G-05 공용 모듈 행 — 검사기 결함, 위).

| 게이트 | 판정 | 실측 (check_data 행) |
|---|---|---|
| **G-05 쓰기 경계** | **PASS** (5/5) | 라우터 14 의 insert/update/delete 테이블 ⊆ function-list 「쓰는 테이블」 ∪ `notification` · 로그 ∪ §2.2 허용 공용 모듈 쓰기 · 위반 0 · 해석 못한 동적 쓰기(f-string 테이블) 0 / 공용 모듈의 §2.2 밖 쓰기 0(§2.2 가 허용: `notification` `sys_access_log` `sys_change_log` `sys_number_seq` `sys_user`) / `update lot_stock` 4 문의 컬럼: QC 는 `status` 만 · SHP 지시 · 수정은 `allocated_qty` 만 · 확정은 `qty` · `allocated_qty` — 허용 밖 0 / `trk.py` · `lot.py` · `prp.py` · `trace.py` · `stats.py` 쓰기 SQL · `conn.x` · `conn.tx` · `notify.emit` · `numbering.next` 0 / admin 으로 조회 화면 GET 16(TRK 3 · LOT 2 · PRP 3 · WO-040 · INV-010 · QC-030 · SHP-030 · HOME + 추적 2 · 통합 조회 1) 전부 200 · 업무 테이블 행 수 diff 0(`sys_access_log` 제외) |
| **G-06 E2E 1건** | **PASS** (3/3) | HTTP 28 요청 전부 기대 응답(2xx) · 부서 sl → pr → sl → sh 교대: REQ-2610-0058 → WO-2610-0036 → MLOT-2610-0640 / MLOT-2610-0640-01(분할) / MLOT-2610-0641 → PLOT-2610-0226 → SHP-2610-0214 확정. 의뢰번호로 이어진 행: 지시 1 · 불출 행 3 · 생산일보 1 · 검사일보 1 · 제품 입고 3 · 확정 출하 1 · 출하 행 1 / `v_work_order_status`(WO-040) 일보 양품 95 · 입고 110 · 출하 60 = 흐름 값. 기록은 §3 |
| **G-07 역추적** | **PASS** (5/5) | LOT-020 `GET /lot/backward?shipment_no=SHP-2610-0214` 200 · 화면에 출하 → 제품 LOT → 지시 → 원자재 LOT 3(분할 포함) 글자 전부 / `trace.backward(출하)` 원 입고 LOT {0640, 0641} = 독립 SQL(재귀 CTE · `parent_lot_id` 끝까지) · 불출 LOT {0640, 0640-01, 0641} = 독립 SQL — 분할 LOT 가 원 LOT 로 이어짐 / `trace.backward(제품 LOT)` = 독립 SQL / DB 의 모든 출하(취소 제외 1건 — 다른 QA 정리 뒤) 대조 불일치 0 / 출하 뒤 재판정 불합격(D-515 3 · D-702): 출하 확정 · 확정 시각 · 수량 60 그대로 · `shipment_adjust` 0 · 남은 재고 35 보류 · `trace.rejected_after_shipment` 1 · LOT-020 화면 「출하 후 불합격」 표시 |
| **G-08 정방향** | **PASS** (3/3) | LOT-010 `GET /lot/forward?lot_no=MLOT-2610-0640` 200 · 화면에 원 LOT → 분할 LOT → 지시 → 제품 LOT → 출하 글자 전부 / `trace.forward` 제품 LOT {0226, 0227, 0228} · 출하 {SHP-2610-0214} = 독립 SQL / DB 의 모든 원 입고 LOT(2) 대조 불일치 0 |
| **G-09 차단 규칙** | **PASS** (7/7) | 검사대기 LOT 불출 422 · 보류(입고검사 불합격) LOT 불출 422 — 불출 행 3→3 · 재고 10/10 그대로 / 사용 중지 품목 입고 422 · LOT 0 / 검사대기 제품 LOT 할당 422 · SHP-010 LOT 목록에 없음 · 할당 0 / 보류(재판정 불합격) LOT 가 걸린 출하 확정 422 · 출하 상태 지시 · 할당 10 그대로(D-515 2) / 재판정 불합격 → 합격 = 보류 → 가용 · 판정 이력 [불합격, 합격] 두 행(D-515 1 · 4) / 사용 중지 제품 품목의 LOT 출하 지시 422 · 목록에 없음 / 출하 뒤 재판정 불합격 LOT 의 남은 지시(SHP-2610-0216) 확정 422 |
| **G-10 가용 재계산** | **PASS** (9/9) | 할당 60 뒤 PLOT-2610-0226 qty 95 − allocated 60 = 35 · INV-010 `?lot=` 가용 칸 35 / 확정 뒤 qty 95→35 · allocated 60→0 · 가용 35 불변 / 동시 불출(스레드 2 · 가용 20 에 15 × 2) 응답 [200, 422] · 남은 qty 5 / 동시 할당(스레드 2 · 가용 35 에 30 × 2) 응답 [200, 422] · 할당 30 / F-SHP-012 수정 30 → 25 / **전 LOT**(`lot_stock` 8 행) `allocated_qty` = 열린(지시) 출하 행 합 — 불일치 0 / INV-010 화면 가용(전 8 행) = qty − allocated — 값 불일치 0 · 화면에 없는 행 0 / **F-SHP-012 라인 전부 제거 = 지시 취소(Ruling 21)**: SHP-2610-0215 라인 1→0 → 200 · 상태 취소 · 할당 10→0 = 독립 SQL 0 · 가용 10 = INV-010 10 · 알림 행 그대로(정식 행으로 올림) |
| G-11 알림 9종 | **미검증** (11 PASS · 1 미검증) | W1 에서 낼 수 있는 8종 전부 수신 부서마다 1행: `request_created` → DS · PR / `order_issued` → PR / `material_received` → PR / `product_received` → PR / `judged` → SH · SL / `shipment_ordered` → SH / `shipment_confirmed` → AC · SL / `due_d3_unshipped`(`jobs due-check`) → PR · SL. 처리 화면이 닫음: 지시서 작성 → request_created PR · 불출 → order_issued · 입고 LOT 전부 판정 → material_received · 판정 → product_received · 출하 지시 등록(SL) → judged SL · 확정 → shipment_ordered / 같은 키 `notify.emit` 재호출 → 새 행 0 · 행 2 유지(D-522) / HOME-020: ds 알림함에 처리 버튼 → 처리 후 사라짐 · `handled_by` ds · 다른 부서(sh)의 처리 시도 404 · 이미 처리한 알림 재처리 200 / `due-check` 2회: rc 0/0 · `due:REQ-2610-0059:2026-10-21` → PR · SL · 2회째 같은 행(새 알림 0) · 납기 D-10 의뢰에는 알림 0 / **`erp_upload_error` 는 W2** — COL-010 이 없어 발생시킬 수 없다 → 미검증 |
| G-12 회차 교체 | FAIL | **W2 에서 잰다** — COL-010 · `erp_upload.py` 없음 |
| G-13 오류 행 · 미매핑 | FAIL | **W2 에서 잰다** — COL-010 · COL-030 없음 |
| G-14 출하 대비 수금 | FAIL | **W2 에서 잰다** — COL-070 없음 |
| G-15 대시보드 8 수치 | FAIL | **W3 에서 잰다** — RPT-010~080 · `dashboard.py` 없음 |

W1 몫(G-05 ~ G-10) PASS 6 · G-11 은 8/9 종 PASS 에 1종 W2 미검증 · G-12 ~ G-15 는 W2/W3 FAIL(정상 · 게이트를 낮추지 않는다).

## 3. E2E 기록 (HTTP 만 · 부서 계정 교대 · `--transcript` 출력 그대로)

번호(REQ · WO · MLOT · PLOT · SHP)는 `(예시)` 형식(D-509)이고 이 행들은 끝에 지웠다. 「DB 확인」 열은 그 단계 직후 QA2 가 SELECT 로 본 상태다. 1~8 기준정보(BAS) · 9~28 의뢰 → 출하 확정(G-06) · 29~30 추적 · 31~51 차단 · 할당 · 재판정 · 52~57 알림 · 배치 · 58 F-SHP-012 취소.

| # | 단계 | 계정 | 요청 | 응답 | 번호 · 메시지 | DB 확인 |
|---|---|---|---|---|---|---|
| 1 | BAS-010 품목(제품) | pr | `POST /bas/items` | 200 | item 3385 |  |
| 2 | BAS-010 품목(원자재) | pr | `POST /bas/items` | 200 | item 3386 |  |
| 3 | BAS-010 품목(원자재 · 중지용) | pr | `POST /bas/items` | 200 | item 3387 |  |
| 4 | BAS-010 품목 사용 중지 | pr | `POST /bas/items/3387` | 200 | 품목을 수정했습니다 | OK item.use_yn = N |
| 5 | BAS-020 거래처 | sl | `POST /bas/customers` | 200 | customer 1561 |  |
| 6 | BAS-030 창고 | pr | `POST /bas/warehouses` | 200 | warehouse 1241 |  |
| 7 | BAS-030 위치 L1 | pr | `POST /bas/warehouses` | 200 | location 1918 |  |
| 8 | BAS-030 위치 L2 | pr | `POST /bas/warehouses` | 200 | location 1919 |  |
| 9 | WO-010 생산의뢰 등록 | sl | `POST /wo/requests` | 200 | REQ-2610-0058 | OK production_request REQ-2610-0058 확인대기 · 100 · OK notification request_created:REQ-2610-0058 → PR · DS 1행씩 미처리 |
| 10 | WO-010 의뢰 목록에서 번호 확인 | sl | `GET /wo/requests?q=REQ-2610-0058` | 200 |  | OK 목록 화면에 REQ-2610-0058 |
| 11 | WO-010 의뢰 확정(수정) | sl | `POST /wo/requests/1483` | 200 | 생산의뢰를 수정했습니다 (REQ-2610-0058) | OK 의뢰 확정 |
| 12 | WO-010 생산의뢰 등록(납기 D-2 · 출하 없음) | sl | `POST /wo/requests` | 200 | REQ-2610-0059 |  |
| 13 | WO-020 생산지시서 작성 | pr | `POST /wo/orders` | 200 | WO-2610-0036 | OK work_order WO-2610-0036 발행 · 의뢰 REQ-2610-0058 · 제품 품목 · OK 의뢰 지시완료 · OK order_issued:WO-2610-0036 → PR 1행 미처리 · OK request_created PR 처리됨(지시서 작성이 닫음) · DS 미처리 |
| 14 | MAT-010 원자재 입고 | pr | `POST /mat/receipts` | 200 | MLOT-2610-0640, MLOT-2610-0641 | OK lot_stock MLOT-2610-0640 120 · MLOT-2610-0641 80 검사대기 · OK material_received:MLOT-2610-0640 → PR 1행 |
| 15 | QC-010 입고검사 합격 | pr | `POST /qc/incoming` | 200 | MLOT-2610-0640 #1 → 가용 | OK MLOT-2610-0640 가용 · 입고 알림은 아직 열림(같은 입고의 MLOT-2610-0641 미판정) |
| 16 | QC-010 입고검사 합격 | pr | `POST /qc/incoming` | 200 | MLOT-2610-0641 #1 → 가용 | OK MLOT-2610-0641 가용 · material_received 처리됨(입고 LOT 전부 판정) |
| 17 | INV-020 원자재 LOT 분할 | pr | `POST /inv/moves` | 200 | MLOT-2610-0640-01 | OK MLOT-2610-0640-01 parent=MLOT-2610-0640 · MLOT-2610-0640 100 · MLOT-2610-0640-01 20 가용 |
| 18 | MAT-020 불출 | pr | `POST /mat/issues` | 200 | issue 388 ← MLOT-2610-0640, MLOT-2610-0640-01, MLOT-2610-0641 | OK lot_stock qty MLOT-2610-0640 20 · MLOT-2610-0640-01 0 · MLOT-2610-0641 30 · OK stock_move 불출 3행 · 합 150 · OK order_issued 처리됨(불출이 닫음) |
| 19 | PRD-010 생산일보 | pr | `POST /prd/daily` | 200 | daily 411 | OK production_daily 양품 95 |
| 20 | INS-010 검사일보 | pr | `POST /ins/daily` | 200 | daily 137 | OK inspection_daily 95 · 불량 2 |
| 21 | MAT-030 제품 입고(수량 비움 = 일보 양품) | pr | `POST /mat/product-receipts` | 200 | PLOT-2610-0226 · 95.000 | OK product_lot PLOT-2610-0226 95(= 일보 양품) · lot_stock 검사대기 · OK product_received:PLOT-2610-0226 → PR 1행 |
| 22 | MAT-030 제품 입고(P2 · 차단 시험용) | pr | `POST /mat/product-receipts` | 200 | PLOT-2610-0227 · 10 |  |
| 23 | MAT-030 제품 입고(P3 · 차단 시험용) | pr | `POST /mat/product-receipts` | 200 | PLOT-2610-0228 · 5 |  |
| 24 | QC-020 제품검사 합격 | pr | `POST /qc/product` | 200 | PLOT-2610-0226 #1 → 가용 | OK PLOT-2610-0226 가용 · judged:PLOT-2610-0226:1 → SH · SL · product_received 처리됨 |
| 25 | QC-020 제품검사 합격(P2) | pr | `POST /qc/product` | 200 | PLOT-2610-0227 #1 → 가용 |  |
| 26 | SHP-010 판정 알림 링크로 열기 | sl | `GET /shp/orders?lot=PLOT-2610-0226` | 200 |  | OK SHP-010 ?lot=PLOT-2610-0226 가 1번 줄에 그 LOT 재고를 골라 둔다 |
| 27 | SHP-010 출하 지시 등록(의뢰번호 · LOT 60) | sl | `POST /shp/orders` | 200 | SHP-2610-0214 | OK shipment_order SHP-2610-0214 지시 · 의뢰 REQ-2610-0058 의 거래처 · 납기 · OK PLOT-2610-0226 qty 95 · allocated 60 · 가용 35 · OK shipment_ordered:SHP-2610-0214 → SH · judged SL 처리됨(등록 부서) · SH 미처리 |
| 28 | SHP-020 출하 확정 | sh | `POST /shp/confirm/343/confirm` | 200 | SHP-2610-0214 | OK SHP-2610-0214 확정 · confirmed_at · OK PLOT-2610-0226 qty 95→35 · allocated 60→0 · OK stock_move 출하 1행 60 · OK shipment_ordered 처리됨(확정이 닫음) · shipment_confirmed:SHP-2610-0214 → SL · AC |
| 29 | LOT-020 역추적(출하 번호) | sl | `GET /lot/backward?shipment_no=SHP-2610-0214` | 200 |  | 화면에 SHP-2610-0214 · PLOT-2610-0226 · WO-2610-0036 · MLOT-2610-0640 · MLOT-2610-0641 · MLOT-2610-0640-01 있음 |
| 30 | LOT-010 정방향(원자재 LOT) | pr | `GET /lot/forward?lot_no=MLOT-2610-0640` | 200 |  | 화면에 MLOT-2610-0640 · MLOT-2610-0640-01 · WO-2610-0036 · PLOT-2610-0226 · SHP-2610-0214 있음 |
| 31 | MAT-010 원자재 입고(차단 시험 B · C) | pr | `POST /mat/receipts` | 200 | MLOT-2610-0642, MLOT-2610-0643 |  |
| 32 | QC-010 입고검사 불합격(C) | pr | `POST /qc/incoming` | 200 | MLOT-2610-0643 → 보류 | OK MLOT-2610-0643 보류 |
| 33 | MAT-020 불출(검사대기 LOT) | pr | `POST /mat/issues` | 422 | 1행 LOT: 검사대기 LOT 은 불출할 수 없습니다 — 입고검사(QC-010) 합격 뒤 불출합니다: MLOT-2610-0642 |  |
| 34 | MAT-020 불출(보류 LOT) | pr | `POST /mat/issues` | 422 | 1행 LOT: 보류(입고검사 불합격) LOT 은 불출할 수 없습니다: MLOT-2610-0643 |  |
| 35 | MAT-010 입고(사용 중지 품목) | pr | `POST /mat/receipts` | 422 | 1행 품목: 사용 중지 품목은 고를 수 없습니다: QA2-592946098-X |  |
| 36 | SHP-010 출하 지시(검사대기 LOT) | sl | `POST /shp/orders` | 422 | 할당할 수 없는 LOT 가 있습니다 |  |
| 37 | SHP-010 출하 지시(P2 10) | sl | `POST /shp/orders` | 200 | SHP-2610-0215 |  |
| 38 | QC-020 제품검사 재판정 불합격(P2) | pr | `POST /qc/product/670` | 200 | PLOT-2610-0227 #2 → 보류 |  |
| 39 | SHP-020 출하 확정(재판정 불합격 LOT) | sh | `POST /shp/confirm/344/confirm` | 422 | 확정할 수 없는 LOT 가 있습니다 — 검사 미판정·불합격 LOT 는 출하 확정을 막습니다 |  |
| 40 | QC-010 입고검사 재판정 합격(C) | pr | `POST /qc/incoming/760` | 200 | MLOT-2610-0643 #2 → 가용 |  |
| 41 | MAT-020 동시 불출(스레드 2 · 각 15 / 가용 20) | pr | `POST /mat/issues` | 422 |  |  |
| 42 | MAT-020 동시 불출(스레드 2 · 각 15 / 가용 20) | pr | `POST /mat/issues` | 200 |  |  |
| 43 | SHP-010 동시 할당(스레드 2 · 각 30 / 가용 35) | sl | `POST /shp/orders` | 422 |  |  |
| 44 | SHP-010 동시 할당(스레드 2 · 각 30 / 가용 35) | sh | `POST /shp/orders` | 200 | SHP-2610-0216 |  |
| 45 | SHP-010 출하 지시 수정(할당 30 → 25) | sl | `POST /shp/orders/345` | 200 | 출하 지시 SHP-2610-0216 를 고쳤습니다 |  |
| 46 | BAS-010 제품 품목 사용 중지 | pr | `POST /bas/items/3385` | 200 | 품목을 수정했습니다 |  |
| 47 | SHP-010 출하 지시(사용 중지 품목 LOT) | sl | `POST /shp/orders` | 422 | 할당할 수 없는 LOT 가 있습니다 |  |
| 48 | BAS-010 제품 품목 다시 사용 | pr | `POST /bas/items/3385` | 200 | 품목을 수정했습니다 |  |
| 49 | QC-020 출하 뒤 재판정 불합격(P1) | pr | `POST /qc/product/669` | 200 | PLOT-2610-0226 #2 → 보류 · shipped_after True |  |
| 50 | LOT-020 역추적(재판정 뒤) | sl | `GET /lot/backward?shipment_no=SHP-2610-0214` | 200 |  | 출하 확정→확정 · 수량 60.000→60.000 · 반품정정 0 · 재고 보류 · 「출하 후 불합격」 있음 |
| 51 | SHP-020 출하 확정(재판정 불합격 P1 할당분) | sh | `POST /shp/confirm/345/confirm` | 422 | 확정할 수 없는 LOT 가 있습니다 — 검사 미판정·불합격 LOT 는 출하 확정을 막습니다 |  |
| 52 | HOME-020 알림함(ds) | ds | `GET /home/notifications` | 200 |  |  |
| 53 | HOME-020 다른 부서 알림 처리 | sh | `POST /home/notifications/2286/handle` | 404 | 이 부서의 알림이 아닙니다 |  |
| 54 | HOME-020 알림 처리 | ds | `POST /home/notifications/2286/handle` | 200 | 알림을 처리했습니다 |  |
| 55 | HOME-020 이미 처리한 알림 다시 처리 | ds | `POST /home/notifications/2286/handle` | 200 | 알림을 처리했습니다 |  |
| 56 | jobs due-check | (배치) | `uv run python -m lcomfine.jobs due-check` | 0 | due-check: 대상 의뢰 1 · 새 알림 2행 (실행 시각 미확정 D-520) |  |
| 57 | jobs due-check | (배치) | `uv run python -m lcomfine.jobs due-check` | 0 | due-check: 대상 의뢰 1 · 새 알림 0행 (실행 시각 미확정 D-520) |  |
| 58 | SHP-010 출하 지시 수정(라인 전부 제거 = 취소) | sl | `POST /shp/orders/344` | 200 | 출하 지시 SHP-2610-0215 를 취소했습니다 — 할당 1줄(10.000) 해제 | 응답 200 · 상태 취소 · PLOT-2610-0227 할당 10.000→0.000 · 독립 열린 출하 행 합 0 · shipment_line 1→0 · INV-010 가용 [Decimal('10')] · 알림 행 1→1 |


## 4. 독립 재계산 대조

| 대상 | 화면 · 모듈 값 | QA2 독립 SQL | 일치 |
|---|---|---|---|
| 역추적 — 출하 SHP-2610-0214 의 원 입고 LOT | `trace.backward(shipment_no)` → {MLOT-2610-0640, MLOT-2610-0641} · LOT-020 화면 글자 | `shipment_line` → `product_lot`(`parent_lot_id` 재귀) → `work_order` → `material_issue_line`(취소된 불출 제외) → `material_lot`(`parent_lot_id` 재귀 · 뿌리) → {0640, 0641} | 일치 |
| 역추적 — 실제 불출 LOT(분할 포함) | {0640, 0640-01, 0641} | 같은 CTE 의 `issued` 집합 {0640, 0640-01, 0641} — 분할 0640-01 의 뿌리 = 0640 | 일치 |
| 역추적 — 제품 LOT PLOT-2610-0226 | `trace.backward(product_lot_no)` → {0640, 0641} | 같은 CTE · 시작점을 제품 LOT 로 | 일치 |
| 역추적 — DB 의 모든 출하(취소 제외) | 1건 | 1건 대조 · 불일치 0 | 일치 |
| 정방향 — MLOT-2610-0640 | `trace.forward` 제품 LOT {0226, 0227, 0228} · 출하 {SHP-2610-0214} · LOT-010 화면 | `material_lot`(자식 재귀) → `material_issue_line` → `work_order` → `product_lot`(취소 입고 제외) → `shipment_line` → `shipment_order`(취소 제외) | 일치 |
| 정방향 — DB 의 모든 원 입고 LOT | 2건 | 2건 대조 · 불일치 0 | 일치 |
| 가용 — PLOT-2610-0226 할당 뒤 | INV-010 가용 칸 35 | `qty 95 − allocated_qty 60 = 35` | 일치 |
| 가용 — 확정 뒤 | qty 35 · allocated 0 · 가용 35 | 확정 전 가용 35 = 확정 뒤 35(가용 불변 · D-510) | 일치 |
| 할당 합 — 전 LOT | `lot_stock.allocated_qty`(8 행) | 열린(`status = '지시'`) `shipment_line.qty` 합 — 같은 제품 LOT · 위치 | 불일치 0 |
| 가용 — INV-010 전 행 | 화면 8 행의 가용 칸 | `qty − allocated_qty`(8 행) | 값 불일치 0 · 빠진 행 0 |
| F-SHP-012 취소 — PLOT-2610-0227 | 응답 200 · 상태 취소 · 할당 10→0 · INV-010 가용 10 | 열린 출하 행 합 0 · `shipment_line` 1→0 · qty 10 그대로 | 일치 |
| 동시성 | 불출 15 × 2(가용 20) → [200, 422] · 남은 qty 5 / 할당 30 × 2(가용 35) → [200, 422] · 할당 30 | 초과 불출 · 초과 할당 0 | 일치 |

## 5. 산출물 · 다시 돌리는 법

- `tools/check_data.py` — `make check-data` · `uv run python tools/check_data.py --transcript`(+ §3 기록) · `--keep`(정리 안 함 · 디버그) · `--seed`(개발 시드 2회 멱등 · 참고 — 다른 QA 와 DB 를 함께 쓰는 동안은 돌리지 않았다). 실측: 종료코드 4 · 약 3초.
- `tests/test_qa2_static.py`(G-05 정적 4) · `tests/test_qa2_flow.py`(G-06 ~ G-11 + G-05 동적 + 개발2 수정 확인 17 — 모듈 픽스처가 흐름을 한 번 돌리고 끝에 지운다) — `uv run pytest -q tests/test_qa2_*.py` → **21 passed in 2.12s**. 기능 표식 `@pytest.mark.fn` 28 기능(WO 3 · MAT 6 · PRD 1 · INS 1 · QC 6 · INV 2 · SHP 3 · LOT 2 · HOME 2 · TRK 1 · PRP 1).
- 남은 행 확인: `psql -h /tmp lcomfine_db -tAc "select count(*) from item where item_code like 'QA2-%'"` → 0.

## 6. 관찰 (결함으로 올리지 않음)

- `shipment_confirmed`(SL · AC)는 닫는 처리 화면이 없다 — 알림함(HOME-020)에서만 처리한다. 계약(D-511)에 닫는 화면이 적혀 있지 않아 결함이 아니다.
- `jobs due-check` 출력에 「실행 시각 미확정 D-520」 이 붙어 나온다 — 배치 시각은 사람이 정할 것(goal.md §7).
- 개발2 수정 확인(테스트 `test_dev2_empty_body_is_422_and_qc_status_filter`): `POST /mat/receipts/{id}` · `/mat/issues/{id}` · `/mat/product-receipts/{id}` 빈 본문 → 422 · `GET /qc/incoming?status=보류` · `/qc/product?status=가용` 200 · `?status=없는상태` 422. F-INV-022 빈 본문은 이동 행 id 가 흐름에 없어 보지 않았다(QA1 몫).
- 전 출하 · 전 원자재 LOT 대조 건수(1 · 2)가 작은 것은 다른 QA 의 정리가 끝난 뒤 DB 에 QA2 행만 남아 있었기 때문이다. 시드 데이터가 들어온 DB 에서 다시 돌리면 그 수만큼 대조한다.
- 시드 멱등(G-21 의 「시드 2회 행 수 diff 0」)은 QA3 몫이라 여기서는 `--seed` 참고 행으로만 두고 이번에 돌리지 않았다.

---

## 7. W2 수금 (2026-10-22)

개발3 이 COL 7 화면 · `erp_upload.py` · `stats` 수금 함수를 만들었다. `check_data.py` 에 **수금 단계**(`Flow.collections`)와 정적 검사(`static_col`)를 더해 G-11 `erp_upload_error` · G-12 · G-13 · G-14 를 잰다. 앱 코드는 고치지 않았다. 흐름은 **HTTP 만** — ERP 엑셀은 openpyxl 로 만든 `(예시)` xlsx(저장소에 바이너리 없음)를 COL-010 `POST /col/uploads`(multipart · 계정 ac)에 올리고, 매핑은 COL-030 POST, 확인은 COL-020 · 030 · 040 · 050 · 070 화면 GET 과 SELECT 로 했다. 확정 출하는 W1 E2E 가 만든 것(S1 · 60 · 거래처 `QA2-<tag>-C`)을 그대로 쓰고, ERP 만 있는 거래처 `QA2-<tag>-C2` 는 BAS-020 으로 하나 더 만들었다. 만든 행(ERP 회차 3 · 행 12 · 알림 3 · 거래처 매핑 2 · 거래처 1)은 끝에 지웠다 — 남은 행 0. **열 매핑(`erp_column_map`)은 바꾸지 않았다**(시드 7 행에 거래처코드 · 일자 · 매출액 · 수금액이 있어 그대로 썼다 · 없을 때만 시드 낱말로 저장하고 끝에 되돌리는 코드가 있다 · 실행 뒤 7 행 그대로). 기준 기간은 다른 사람의 회차와 (시작, 끝)이 겹치지 않는 것을 골랐다(같은 기간 재업로드가 그 회차를 교체하기 때문 — `Flow.free_period`).

### 7.1 결함

| ID | 심각도 | 담당 | 상태 | 요약 |
|---|---|---|---|---|
| DEF-QA2-004 | 경미 | 개발3 (`routers/col.py` F-COL-031 · F-COL-032 응답 문장) | **해소(실측)** — 개발3 이 `erp_upload.remap` 반환을 `{reviewed, changed, applied, still_error}` 로, F-COL-031 · 032 JSON 을 `reinterpreted · applied · still_error · remapped(= applied)` 로 바꿨다. 재실측(같은 시나리오 · E 행 4 = 정상 2 · 날짜 오류 1 · 금액 오류 1): 응답 `reinterpreted 4 · applied 2 · still_error 2 · remapped 2` · 문장 「다시 해석한 행 4 · 그중 반영 2 · 다른 오류로 여전히 제외 2」 = DB `error is null` 2 · `error_count` 4. E2 매핑(오류 전부 미매핑)은 `2 · 2 · 0 · 2`. 검사기 기대값을 새 응답으로 맞췄다(`check_data.py` G-13 COL-030 행 · G-11 재해석 행) · `make check-data` 종료코드 1(G-15 만) · `tests/test_qa2_*.py` 31 passed | (수정 전 실측) 매핑 등록 응답 「다시 반영된 행 N」 의 N 이 **error 글자가 바뀐 행 수**(`erp_upload.remap` 반환 · 공표 §1.4 「error 가 바뀐 행 수」)라서, 미매핑과 다른 오류(날짜 · 금액)가 함께 있던 행도 센다. 실측: 반영 회차 ERP-2610-0109(E 행 4: 정상 2 · 날짜 오류 1 · 금액 오류 1)에 E 매핑 등록 → 응답 `remapped 4` · 문장 「다시 반영된 행 4」, 그러나 `error is null` 이 된 행은 **2**(엑셀 행 2 · 3) 이고 행 5 · 6 은 「일자: …」 · 「매출액: …」 으로 여전히 반영 제외. 기대: 「다시 반영된 행」 = error 가 null 이 된 행 수(2), 또는 문장을 「다시 해석한 행 4 · 그중 반영 2」 로. 데이터는 맞다(뷰 2행 · error_count 4) — 사람이 읽는 수가 다르다. 재현: `uv run python tools/check_data.py --transcript` 의 단계 68 번호 열 「map … · 재해석 4」 와 바로 뒤 DB 확인 열의 A2 error 행 {2: '', 3: '', 5: '일자…', 6: '매출액…'} · 또는 `tests/test_dev3_col.py` 의 매핑 시나리오에 날짜 오류 + 미매핑 행을 하나 넣으면 `remapped` 가 1 늘어난다 |

치명 0 · 중대 0 · 경미 1(해소 1). 미해소 0. W1 결함 3 은 전부 해소 상태 그대로.

### 7.2 게이트 판정 — W2 실측 (`uv run python tools/check_data.py --transcript` · 종료코드 **1** = G-15 W3 · 약 2.7초)

| 게이트 | 판정 | 실측 (check_data 행 — 번호 · 거래처 코드는 그 실행의 값) |
|---|---|---|
| **G-05 쓰기 경계** | **PASS** (6/6) | 라우터 **15**(col.py 포함) 쓰기 테이블 ⊆ 계약 · 위반 0 / **새 행** `erp_upload.py` 쓰기 {erp_column_map, erp_upload_batch, erp_upload_row} · col.py 직접 쓰기 {erp_customer_map} ⊆ F-COL 「쓰는 테이블」 {erp_column_map, erp_customer_map, erp_upload_batch, erp_upload_row, notification} · 계약 밖 0 · erp_upload 쓰기 함수(apply · remap · save_column_map)를 부르는 라우터 ['COL'] 만 · 다른 라우터의 erp_* 쓰기 0 · erp_upload 안의 공용 모듈 notify · numbering(§2.2) / `stats.py` 쓰기 0(기존 행) / 조회 GET **23** 화면(**COL 7 추가**: uploads · upload-history · customer-map · collections · receivables · aging · shipment-vs-collection) 전부 200 · 업무 테이블 diff 0 |
| **G-11 알림 9종** | **PASS** (13/13) | W1 8종 그대로 + **`erp_upload_error`**: 회차 ERP-2610-0108(행 4 · 오류 4) → `notification(event_key='erp_upload_error', to_role='AC')` **1행** · link `/col/upload-history?batch=108` · dedupe `erp_upload_error:ERP-2610-0108` · 문장에 「4행」 과 미매핑 코드 · 다른 부서 0 / `notify.emit` 같은 키 재호출 → 새 행 **0** · 행 1 유지(D-522) / 같은 기간 재업로드(교체) → 교체된 회차의 알림 `handled_at` 있음(닫힘) · 새 회차 ERP-2610-0109(오류 6) → AC 1행 미처리 / **매핑으로 오류 0 → 닫힘**: 기간 Q 회차 ERP-2610-0110(E2 미매핑 2행 · AC 1행) → COL-030 에서 E2 매핑 등록 → 재해석 2행 · error_count 0 · 알림 닫힘(같은 트랜잭션 · `handle_by_link`) / 오류가 남은 회차(0109 · 매핑 뒤 4)는 알림 열린 채 |
| **G-12 회차 교체** | **PASS** (4/4) | 기간 P 2026-10-01~2026-10-31: 1회차 ERP-2610-0108(행 4) → 같은 기간 재업로드 → 2회차 ERP-2610-0109 `반영` · 응답 `replaced = ERP-2610-0108` · 이전 회차 `status='교체'` · `replaced_by = 109`(= 새 회차 id) · **이전 회차 행 4 → 4 보존**(`row_count` 4 · error 그대로) / 기간 P 의 `반영` 회차 **1** · 교체 회차의 `v_dq_collections` 행 0 / COL-020 이력: 0108 행 `data-status="교체"` 「교체됨」 · 0109 행 `반영` · `?batch=109` 에 교체한 회차 번호 / **정적**: 앱 라우트 표의 `/col/*` POST = {/col/uploads, /col/customer-map, /col/customer-map/{id}, /col/customer-map/{id}/delete} = function-list F-COL-011 · 031 · 032 · 033 **딱 4** · col.py 가 직접 쓰는 수금 테이블 0 · 폼 칸 {action, period_from, period_to, erp_code, erp_name, customer_id, use_yn} — **금액 칸 · 수정 엔드포인트 없음** |
| **G-13 오류 행 · 미매핑** | **PASS** (5/5) | 2회차 6행: 2 · 3 정상(매핑 뒤) · **4** 「거래처 코드 미매핑: QA2-…-U」 · **5** 「일자: 날짜 형식이 아닙니다 '2026/13/01' (YYYY-MM-DD)」 · **6** 「매출액: 숫자가 아닙니다 'abc'」 · **7** 「거래처코드: 필수 항목이 비어 있습니다」 — error 사유 · 원문 `raw` 그대로 보존(`raw['거래처코드'] = U` · `raw['일자'] = '2026/13/01'` · `raw['매출액'] = 'abc'`) · `error_count` 4 / 반영 제외: 뷰 0109 행 **2**(E 만) · 미매핑 U 뷰 0 · COL-040(거래처 C1 · 이 달) 행 2 · U 없음 · COL-050 C1 매출 1,000 · 수금 300 · 미수 700 · U 없음 / COL-030 `data-unmapped` E · U · E2 전부 보임(매핑 전) · `unmapped_codes` E 4행(반영 회차만 — 교체 회차의 E 3행은 세지 않음) · U 1행 → E 매핑 → **반영 회차 0109 만 재해석**: error 바뀜 4행 · `error is null` 2행 · 교체 회차 0108 의 오류 4 그대로 · 목록에서 E 사라짐 · U 남음 / COL-020 `?batch=109`: 매핑 전 `data-row` [2,3,4,5,6,7] → 매핑 뒤 [4,5,6,7] / **정적**: 앱 전체 `update erp_upload_row set` 1문 컬럼 {parsed, error, updated_at, updated_by} · `update erp_upload_batch set` 3문 ⊆ {status, replaced_by, error_count, updated_at, updated_by} · `delete from erp_upload_*` 0 — raw · 기간 · 행 수 · 금액은 어디서도 바꾸지 않는다 |
| **G-14 출하 대비 수금** | **PASS** (4/4) | 월 2026-10 · 거래처 C1(확정 출하 S1 60 + ERP E 매출 1,000 · 수금 300): COL-070 화면 `data-month="2026-10" data-customer=C1` 칸 (출하 건수 1 · 수량 60.000 · 매출 1,000 · 수금 300) = **QA2 독립 SQL**(`shipment_order status='확정' · to_char(confirmed_at,'YYYY-MM')` × `erp_upload_row ← 반영 회차 · error is null · erp_customer_map use_yn='Y' · to_char(txn_date,'YYYY-MM')` — 뷰를 거치지 않음) (1, 60.000, 1000.00, 300.00) · `?customer=` 필터도 같음 / **출하만 있는 거래처(매핑 전) = MES 쪽만**: (1, 60.000, None, None) / **ERP 만 있는 거래처 C2 = ERP 쪽만**: (None, None, 500, 200) = 독립 SQL / 미매핑 U(77/77) 뷰 0 · COL-070 화면에 없음 / `stats.shipment_vs_collection` = 독립 SQL · `v_dq_collections` 월 합 = 테이블 직접 집계 · 건 단위 짝짓기 없음(월 · 거래처 합만) |
| G-15 대시보드 8 수치 | FAIL | **W3 에서 잰다** — RPT-010~080 · `dashboard.py` 없음 (그대로) |

G-06 ~ G-10 은 W1 과 같이 PASS(같은 실행에서 다시 잼). 게이트 요약: `G-05 PASS · G-06 PASS · G-07 PASS · G-08 PASS · G-09 PASS · G-10 PASS · G-11 PASS · G-12 PASS · G-13 PASS · G-14 PASS · G-15 FAIL — FAIL 행 1 → 종료코드 1`.

### 7.3 W2 단계 기록 (`--transcript` 59~73 · 번호는 그 실행의 값)

| # | 단계 | 계정 | 요청 | 응답 | 번호 · 메시지 | DB 확인 |
|---|---|---|---|---|---|---|
| 59 | COL-010 ERP 업로드 1회차(기간 P · 미매핑 E · U · 날짜 오류) | ac | `POST /col/uploads action=apply 2026-10-01~2026-10-31 (4행)` | 200 | ERP-2610-0108 1회차 · 행 4 · 오류 4 · 교체 None | OK 반영 · 1회차 · 행 4 · 오류 4(E 미매핑 3 + 날짜 1 · U 1 — 겹침) · notification erp_upload_error → ['AC'] · link /col/upload-history?batch=108 · dedupe 재호출 새 행 0 |
| 60 | COL-070 출하 대비 수금(매핑 전) | ac | `GET /col/shipment-vs-collection?ym_from=2026-10&ym_to=2026-10&customer=<C1>` | 200 |  | C1 (1, 60.000, None, None) — MES 쪽만 |
| 61 | COL-010 ERP 재업로드 2회차(같은 기간 P · 6행) | ac | `POST /col/uploads action=apply 2026-10-01~2026-10-31 (6행)` | 200 | ERP-2610-0109 2회차 · 행 6 · 오류 6 · 교체 ERP-2610-0108 | ERP-2610-0108 교체 replaced_by 109 · 행 4 · ERP-2610-0109 반영 2회차 |
| 62 | COL-020 업로드 이력 | ac | `GET /col/upload-history` | 200 |  | 0108 data-status 교체 「교체됨」 · 0109 반영 |
| 63 | COL-020 회차별 오류 행 (2회차) | ac | `GET /col/upload-history?batch=109` | 200 |  | data-row [2,3,4,5,6,7] |
| 64 | BAS-020 거래처(ERP 만 · 출하 없음) | sl | `POST /bas/customers` | 200 | customer <C2> |  |
| 65 | COL-010 ERP 업로드(기간 Q · 미매핑 E2 2행) | ac | `POST /col/uploads action=apply 2026-10-01~2026-10-15 (2행)` | 200 | ERP-2610-0110 1회차 · 행 2 · 오류 2 · 교체 None | AC 1행 미처리 |
| 66 | COL-030 거래처 코드 매핑(미매핑 목록) | ac | `GET /col/customer-map` | 200 |  | data-unmapped E · U · E2 전부 있음 · unmapped_codes [E, E2, U] |
| 67 | COL-030 거래처 코드 매핑 등록(E2 → C2) | ac | `POST /col/customer-map` | 200 | map · 재해석 2 | 0110 error_count 0 · 알림 닫힘 |
| 68 | COL-030 거래처 코드 매핑 등록(E → C1) | ac | `POST /col/customer-map` | 200 | map · 재해석 4 · 반영 2 · 여전히 오류 2 · 「다시 해석한 행 4 · 그중 반영 2 · 다른 오류로 여전히 제외 2」 (**DEF-QA2-004 해소 뒤 실측**) | A2 error 행 {2: '', 3: '', 4: '거래처 코드 미매핑: …-U', 5: "일자: 날짜 형식이 아닙니다 '2026/13/01' (YYYY-MM-DD)", 6: "매출액: 숫자가 아닙니다 'abc'", 7: '거래처코드: 필수 항목이 비어 있습니다'} · error null 2 |
| 69 | COL-040 수금 현황(거래처 C1 · 이 달) | ac | `GET /col/collections?date_from=2026-10-01&date_to=2026-10-31&customer=<C1>` | 200 |  | 행 2(E · E) · U 없음 |
| 70 | COL-050 거래처별 미수 | ac | `GET /col/receivables?asof=2026-10-31` | 200 |  | C1 (1000, 300, 700) · U 없음 |
| 71 | COL-020 회차별 오류 행 (E 매핑 뒤) | ac | `GET /col/upload-history?batch=109` | 200 |  | 뷰 2행 · U 0 · COL-040 행 [E, E] · COL-050 (1000, 300, 700) · COL-020 오류 행 [4, 5, 6, 7] |
| 72 | COL-070 출하 대비 수금(전체) | ac | `GET /col/shipment-vs-collection?ym_from=2026-10&ym_to=2026-10` | 200 |  | C1 (1, 60.000, 1000, 300) · C2 (None, None, 500, 200) · U 없음 |
| 73 | COL-070 출하 대비 수금(거래처 C1) | ac | `GET /col/shipment-vs-collection?ym_from=2026-10&ym_to=2026-10&customer=<C1>` | 200 |  | 화면 C1 (1, 60.000, 1000, 300) C2 (None, None, 500, 200) · 독립 C1 (1, 60.000, 1000.00, 300.00) C2 (None, None, 500.00, 200.00) · 모듈 같음 |

### 7.4 독립 재계산 대조 (W2)

| 대상 | 화면 · 모듈 값 | QA2 독립 SQL | 일치 |
|---|---|---|---|
| COL-070 — 2026-10 · C1(출하 + ERP) | 화면 (1, 60.000, 1,000, 300) · `stats.shipment_vs_collection` (1, 60.000, 1000.00, 300.00) | `shipment_order` 확정 · `confirmed_at` 월 → (1, 60.000) / `erp_upload_row` ⋈ `erp_upload_batch(반영)` ⋈ `erp_customer_map(use_yn='Y')` · `error is null` · `txn_date` 월 → (1000.00, 300.00) | 일치 |
| COL-070 — 2026-10 · C2(ERP 만) | 화면 (None, None, 500, 200) | 출하 0 → None / ERP (500.00, 200.00) | 일치 |
| COL-070 — 2026-10 · C1 매핑 전(출하만) | 화면 (1, 60.000, None, None) | ERP 행 전부 미매핑 오류 → 반영 0 → None | 일치 |
| 미매핑 코드 U(77/77) | COL-070 · COL-040 · COL-050 화면에 없음 | `v_dq_collections where erp_customer_code = U` → 0 | 일치 |
| `v_dq_collections` 월 합(C1) | (1000.00, 300.00) | 테이블 직접 집계 (1000.00, 300.00) | 일치 |
| 회차별 뷰 행 (tests/test_qa2_col.py) | `v_dq_collections` 회차 0108 → 0 · 0109 → 2 · 0110 → 2 | 반영이면 `error is null` 행 수 · 교체면 0 — 0108 교체 0 · 0109 2 · 0110 2 · `error_count = row_count − 정상 행` | 일치 |
| COL-050 — C1 기준일 2026-10-31 | 화면 매출 1,000 · 수금 300 · 미수 700 | Σ매출 − Σ수금 = 700 (D-803) | 일치 |
| 미매핑 목록 (tests/test_qa2_col.py) | COL-030 · `unmapped_codes` 매핑 뒤 {U} | 반영 회차 `parsed.customer_code` 중 사용 중 매핑 없는 QA2 코드 = {U} | 일치 |

### 7.5 산출물 · 다시 돌리는 법 (W2)

- `tools/check_data.py` — 수금 단계 `Flow.collections`(G-11 erp_upload_error · G-12 · G-13 · G-14 · 13 행) · `static_col`(G-12 · G-13 정적 2 행) · G-05 에 `erp_upload.py` 포함 행 1 + 조회 diff 에 COL 7 화면 · `Flow.run(only=…)` 로 일부 단계만 돌릴 수 있다 · 재지 못한 게이트는 행이 없으면 FAIL 로 채운다(`MUST_MEASURE`). `LATER` 는 G-15 만. 실측: **종료코드 1 · 약 2.7초**.
- `tests/test_qa2_col.py`(새 · 7) — 기준정보 → E2E → 수금만 돌리는 모듈 픽스처 · G-11 2 · G-12 1 · G-13 2 · G-14 1(이 파일의 두 번째 독립 SQL · `date_trunc`) · 정리 확인 1. `tests/test_qa2_static.py` +3(G-05 COL/erp_upload · G-12 정적 · G-13 정적). 표식 `@pytest.mark.fn`: F-COL-011 · 021 · 031 · 032 · 033 · 034 · 041 · 051 · 071.
- `uv run pytest -q tests/test_qa2_*.py` → **31 passed in 3.54s**(W1 21 + W2 10). 남은 행 확인: `psql -h /tmp lcomfine_db -tAc "select count(*) from erp_upload_batch where source_file like 'QA2-%'"` → 0 · `erp_customer_map where erp_code like 'QA2-%'` → 0 · `erp_column_map` → 7(시드 그대로).

### 7.6 관찰 (결함으로 올리지 않음)

- 반영 회차의 `erp_upload_error` 알림 문장은 업로드 시점의 수(「오류·미매핑 6행 / 6행」)를 그대로 둔다 — 매핑 뒤 재해석으로 오류가 4 로 줄어도 문장은 바뀌지 않고, 0 이 되면 닫힌다(D-802 대로). 알림함(HOME-020)에서 회계부가 보는 수가 현재 값과 다를 수 있다. 문장 갱신은 계약에 없어 결함이 아니다 — 개발3 참고.
- 기준 기간은 사람이 고른 날짜 둘이고 같은 (시작, 끝)만 교체 키다(D-802). 겹치지만 다른 기간(예: 10/1~10/31 과 10/1~10/15)은 둘 다 `반영` 으로 남아 둘 다 집계에 든다 — `v_dq_collections` 의 「기간이 겹치면 올라온 그대로 센다」 와 같다. QA2 흐름은 이 성질을 써서 기간 Q 회차(E2)와 기간 P 회차(E)를 같은 달에 함께 두었다.
- `remap` 은 미매핑 코드 행만이 아니라 원문 거래처코드가 그 코드인 반영 회차 행 전부를 지금 열 매핑 · 거래처 매핑으로 다시 해석한다(날짜 · 금액 오류는 그대로 남는다) — 계약 F-COL-031 「해당 오류 행을 다시 반영할 수 있다」 에 맞는다. 사람이 읽는 수가 달랐던 것(DEF-QA2-004)은 해소되어 이제 「다시 해석 · 그중 반영 · 여전히 제외」 세 수로 나온다.
- `check_data.py` 는 ERP 회차의 기준 기간을 DB 가 센 확정 출하 월(`to_char(confirmed_at,'YYYY-MM')` · 세션 시간대)에서 잡는다 — 월 경계의 밤에 돌려도 출하 월 = ERP 월이 맞다.
