# 이관 파일 규격 — 표준 Import 파일 16개 (개발3 제안 · 2026-10-03)

> **제안본이다.** `decisions.md` D-23 에 따라 개발3 이 제안하고 아키텍트가 확정한다. 확정 전까지 전부 `가설` 이다(D-303).
> 기존 설치형 MES 의 실제 메뉴·데이터 접근 경로를 본 적이 없다(D-01). 그래서 **이 시스템의 테이블에 맞춘 표준 파일**을 정했다 —
> 기존 MES 에서 이 모양으로 뽑아 주면 적재한다. 접근 경로가 정해지면 `src/lcomfine/migration/files.py` 의 리더 한 곳만 바꾼다.
> 코드 쪽 원본은 `lcomfine.migration.files.SPECS` 이고 **§3 은 그 렌더본**이다(손으로 고치지 않는다 — `tests/test_dev3_migration.py` 가 대조한다).

## 1. 공통 규칙

| 항목 | 규칙 |
|---|---|
| 형식 | UTF-8 CSV (BOM 있어도 된다) · 쉼표 구분 · 첫 줄은 열 이름 · 열 순서는 자유 · 빈 줄은 건너뛴다 |
| 파일 이름 | `<대상 테이블>.csv` — Import 폴더 바로 아래에 둔다 (`--dir <Import 폴더>`) |
| 열 이름 | §3 의 글자 그대로. **규격에 없는 열이나 빠진 필수 열이 있으면 그 파일 전체를 적재하지 않는다**(오타를 조용히 넘기지 않는다). 선택 열은 통째로 빼도 된다 |
| 빈 칸 | 선택 열의 빈 칸은 NULL 로 적재한다(기본값이 적힌 열은 그 값). 필수 열의 빈 칸은 그 행의 오류 |
| 날짜 | `YYYY-MM-DD` |
| 숫자 | 자릿수 구분 쉼표 없이 (`1000.5`) |
| 코드 참조 | 다른 테이블을 가리키는 칸은 **업무 코드**(품목 코드 · Job 번호 …)로 적는다. 적재할 때 내부 키로 바꾼다. 없는 코드면 그 행의 오류 |
| 업무 키 | 파일마다 §3 의 「업무 키」. 같은 키가 DB 에 있으면 그 행을 **갱신**, 없으면 **추가**(upsert) → 다시 돌려도 행 수가 같다(G-15). 한 파일 안에서 키가 겹치면 뒤 행이 오류 |
| 오류 행 | 형식이 틀리거나 참조 코드가 없거나 DB 제약에 걸린 행은 **그 행만** 건너뛰고 계속한다. 건너뛴 행은 출력과 `sys_migration_log.error_detail` 에 줄 번호·키·사유로 남는다. 고쳐서 넣지 않는다 |
| 적재한 사람 | 적재한 행의 `created_by` · `updated_by` 는 `migration` |
| 삭제 | 하지 않는다. 파일에서 빠진 행은 DB 에 그대로 남는다 |

## 2. 명령과 파일

```
uv run python -m lcomfine.migration <명령> --dir <Import 폴더> [--by <실행자>]
```

| 기능 | 명령 | 읽는 파일 (적재 순서) | 쓰는 테이블 | 종료코드 |
|---|---|---|---|---|
| B-MIG-01 Import 파일 검증 | `validate` | 16개 전부 | **없음** (`sys_migration_log` 에도 쓰지 않는다) | 오류가 있으면 1 |
| B-MIG-02 기준정보 적재 | `load-master` | `item` → `customer` → `process` → `equipment` → `defect_code` | 그 5개 + `sys_migration_log` | 오류 행·없는 파일이 있으면 1 |
| B-MIG-03 인쇄 기준 적재 | `load-print-std` | `plate_spec` → `anilox` → `ink_formula` → `ink_formula_component` | 그 4개 + `sys_migration_log` | 〃 |
| B-MIG-04 작업지시 적재 | `load-jobs` | `job` → `job_lot` | 그 2개 + `sys_migration_log` | 〃 |
| B-MIG-05 과거 이력 적재 | `load-history` | `material_lot` · `roll` · `roll_genealogy` · `inspection` · `shipment` | `sys_migration_log` 만 — **데이터 행은 적재하지 않는다 (D-01)** | 데이터 행이 있으면 1 |
| B-MIG-06 이관 결과 리포트 | `report` | (`--dir` 를 주면 적재 가능한 파일의 업무 키) | **없음** | 최신 실행에 오류 행이 있거나 대조가 어긋나면 1 |

- 순서는 `validate` → `load-master` → `load-print-std` → `load-jobs` → `load-history` → `report`. 뒤 명령의 코드 참조는 앞 명령이 적재한 행(또는 화면에서 등록한 행)을 가리킨다.
- `validate` 의 코드 참조는 "DB 에 이미 있다" 또는 "같은 폴더의 앞선 파일에서 검사를 통과했다" 면 통과다.
- `validate` 는 필수 파일 11개가 없으면 오류다. 선택 파일(과거 이력 5개)은 없어도 된다.
- `load-history`: 파일이 없으면 `파일 없음 (선택)`, 머리 줄만 있으면 `빈 파일` 로 0건을 기록하고 종료코드 0. 데이터 행이 있으면 형식만 검사하고
  `과거 이력 적재 범위 미확정 (D-01) — n행을 적재하지 않았다` 를 오류로 남긴다(종료코드 1). 적재한 척하지 않는다.
- `report --by <실행자>` 는 그 실행자의 기록만 본다. 대조 = (명령, 파일)별 **최신 실행**의 적재 수 ≤ 대상 테이블의 현재 행 수.
  `--dir` 를 주면 파일의 업무 키가 테이블에 실제로 있는지도 본다(없는 키를 낱낱이 적는다).
- `(예시)` 파일 한 벌이 `src/lcomfine/migration/examples/` 에 있다(코드 접두 `IMP-` — 개발1 시드의 `EX-` 와 겹치지 않는다). 실데이터가 아니다.
  `validate` 는 쓰지 않으므로 언제 돌려도 된다. `load-*` 를 이 폴더로 돌리면 `IMP-` 행이 DB 에 남는다(다시 돌려도 행 수는 같다).

## 3. 파일별 열 규격 (렌더본 — 손으로 고치지 않는다)

<!-- BEGIN:generated files -->
### `item.csv` → `item` — 품목

명령 `load-master` · 업무 키 `item_code` · 필수 파일

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `item_code` | Y | 글자 | `item_code` | 품목 코드 |
| `item_name` | Y | 글자 | `item_name` | 품목명 |
| `item_type` | Y | 선택 `제품 / 원재료` | `item_type` | 구분 |
| `spec` |  | 글자 | `spec` | 규격 (글자 그대로) |
| `unit` |  | 글자 | `unit` | 단위 |
| `use_yn` |  | Y / N · 비우면 `Y` | `use_yn` | 사용 여부 Y/N (비우면 Y) |

### `customer.csv` → `customer` — 고객

명령 `load-master` · 업무 키 `customer_code` · 필수 파일

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `customer_code` | Y | 글자 | `customer_code` | 고객 코드 |
| `customer_name` | Y | 글자 | `customer_name` | 고객명 |
| `note` |  | 글자 | `note` | 비고 |
| `use_yn` |  | Y / N · 비우면 `Y` | `use_yn` | 사용 여부 Y/N (비우면 Y) |

### `process.csv` → `process` — 공정

명령 `load-master` · 업무 키 `process_code` · 필수 파일

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `process_code` | Y | 글자 | `process_code` | 공정 코드 |
| `process_name` | Y | 글자 | `process_name` | 공정명 |
| `process_type` | Y | 선택 `인쇄 / 후가공 / 슬리팅 / 기타` | `process_type` | 공정 구분 |
| `sort_no` |  | 정수 | `sort_no` | 표시 순서 |
| `use_yn` |  | Y / N · 비우면 `Y` | `use_yn` | 사용 여부 Y/N (비우면 Y) |

### `equipment.csv` → `equipment` — 설비 (기준정보까지 — 상태·수집값은 받지 않는다)

명령 `load-master` · 업무 키 `equipment_code` · 필수 파일

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `equipment_code` | Y | 글자 | `equipment_code` | 설비 코드 |
| `equipment_name` | Y | 글자 | `equipment_name` | 설비명 |
| `process_code` |  | 글자 | `process_id` ← `process.process_code` | 이 설비가 속한 공정의 코드 |
| `note` |  | 글자 | `note` | 비고 |
| `use_yn` |  | Y / N · 비우면 `Y` | `use_yn` | 사용 여부 Y/N (비우면 Y) |

### `defect_code.csv` → `defect_code` — 불량코드

명령 `load-master` · 업무 키 `defect_code` · 필수 파일

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `defect_code` | Y | 글자 | `defect_code` | 불량 코드 |
| `defect_name` | Y | 글자 | `defect_name` | 불량명 (불량 유형) |
| `defect_group` |  | 글자 | `defect_group` | 분류 |
| `use_yn` |  | Y / N · 비우면 `Y` | `use_yn` | 사용 여부 Y/N (비우면 Y) |

### `plate_spec.csv` → `plate_spec` — 판사양

명령 `load-print-std` · 업무 키 `plate_code` · 필수 파일

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `plate_code` | Y | 글자 | `plate_code` | 판 코드 |
| `plate_name` | Y | 글자 | `plate_name` | 판명 |
| `item_code` |  | 글자 | `item_id` ← `item.item_code` | 대상 품목(제품)의 코드 |
| `color_count` |  | 정수 · 0 초과 | `color_count` | 도수 |
| `spec_note` |  | 글자 | `spec_note` | 사양 메모 |
| `use_yn` |  | Y / N · 비우면 `Y` | `use_yn` | 사용 여부 Y/N (비우면 Y) |

### `anilox.csv` → `anilox` — 아니록스

명령 `load-print-std` · 업무 키 `anilox_code` · 필수 파일

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `anilox_code` | Y | 글자 | `anilox_code` | 아니록스 코드 |
| `anilox_name` | Y | 글자 | `anilox_name` | 명칭 |
| `line_count` |  | 숫자 | `line_count` | 선수 |
| `cell_volume` |  | 숫자 | `cell_volume` | 셀 용적 |
| `note` |  | 글자 | `note` | 비고 |
| `use_yn` |  | Y / N · 비우면 `Y` | `use_yn` | 사용 여부 Y/N (비우면 Y) |

### `ink_formula.csv` → `ink_formula` — 잉크조성

명령 `load-print-std` · 업무 키 `ink_code` · 필수 파일

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `ink_code` | Y | 글자 | `ink_code` | 잉크 코드 |
| `ink_name` | Y | 글자 | `ink_name` | 잉크명 |
| `color_name` |  | 글자 | `color_name` | 색 이름 |
| `target_l` |  | 숫자 | `target_l` | 기준 색상값 L |
| `target_a` |  | 숫자 | `target_a` | 기준 색상값 a |
| `target_b` |  | 숫자 | `target_b` | 기준 색상값 b |
| `note` |  | 글자 | `note` | 비고 |
| `use_yn` |  | Y / N · 비우면 `Y` | `use_yn` | 사용 여부 Y/N (비우면 Y) |

### `ink_formula_component.csv` → `ink_formula_component` — 잉크조성의 조성 행

명령 `load-print-std` · 업무 키 `ink_code + seq_no` · 필수 파일

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `ink_code` | Y | 글자 | `ink_formula_id` ← `ink_formula.ink_code` | 잉크 코드 |
| `seq_no` | Y | 정수 · 0 초과 | `seq_no` | 행 순번 |
| `component_name` | Y | 글자 | `component_name` | 성분명 |
| `ratio_pct` | Y | 숫자 · 0 초과 · 100 이하 | `ratio_pct` | 비율 (%) — 0 초과 100 이하 |

### `job.csv` → `job` — 작업지시(Job)

명령 `load-jobs` · 업무 키 `job_no` · 필수 파일

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `job_no` | Y | 글자 | `job_no` | 작업지시 번호 (기존 MES 의 번호 그대로) |
| `item_code` | Y | 글자 | `item_id` ← `item.item_code` | 품목(제품) 코드 |
| `customer_code` | Y | 글자 | `customer_id` ← `customer.customer_code` | 고객 코드 |
| `plate_code` |  | 글자 | `plate_spec_id` ← `plate_spec.plate_code` | 판 코드 |
| `anilox_code` |  | 글자 | `anilox_id` ← `anilox.anilox_code` | 아니록스 코드 |
| `ink_code` |  | 글자 | `ink_formula_id` ← `ink_formula.ink_code` | 잉크 코드 |
| `equipment_code` |  | 글자 | `equipment_id` ← `equipment.equipment_code` | 계획 설비 코드 |
| `order_qty` | Y | 숫자 · 0 초과 | `order_qty` | 지시 수량 — 0 초과 |
| `qty_unit` | Y | 글자 | `qty_unit` | 수량 단위 |
| `due_date` | Y | 날짜 YYYY-MM-DD | `due_date` | 납기 YYYY-MM-DD |
| `status` |  | 선택 `등록 / 완료 / 취소` · 비우면 `등록` | `status` | 상태 (비우면 등록) |
| `note` |  | 글자 | `note` | 비고 |

### `job_lot.csv` → `job_lot` — 생산 LOT (Job-Lot-Roll 매핑의 Lot 단)

명령 `load-jobs` · 업무 키 `lot_no` · 필수 파일

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `lot_no` | Y | 글자 | `lot_no` | 생산 LOT 번호 |
| `job_no` | Y | 글자 | `job_id` ← `job.job_no` | 작업지시 번호 |
| `planned_roll_count` |  | 정수 · 0 초과 | `planned_roll_count` | 계획 롤 수 |
| `planned_length_m` |  | 숫자 | `planned_length_m` | 계획 길이 (m) |
| `note` |  | 글자 | `note` | 비고 |

### `material_lot.csv` → `material_lot` — 원재료 LOT

명령 `load-history` · 업무 키 `lot_no` · 선택 파일 · **적재 보류 (D-01)**

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `lot_no` | Y | 글자 | `lot_no` | 원재료 LOT 번호 |
| `item_code` | Y | 글자 | `item_id` ← `item.item_code` | 원재료 품목 코드 |
| `supplier_name` |  | 글자 | `supplier_name` | 공급처 |
| `supplier_lot_no` |  | 글자 | `supplier_lot_no` | 공급사 LOT 번호 |
| `received_qty` | Y | 숫자 · 0 초과 | `received_qty` | 입고 수량 |
| `qty_unit` | Y | 글자 | `qty_unit` | 수량 단위 |
| `received_at` | Y | 날짜 YYYY-MM-DD | `received_at` | 입고일 YYYY-MM-DD |
| `insp_status` | Y | 선택 `대기 / 합격 / 불합격` | `insp_status` | 입고검사 결과 |

### `roll.csv` → `roll` — 롤

명령 `load-history` · 업무 키 `roll_no` · 선택 파일 · **적재 보류 (D-01)**

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `roll_no` | Y | 글자 | `roll_no` | 롤 번호 |
| `process_type` | Y | 선택 `인쇄 / 후가공 / 슬리팅` | `process_type` | 공정 구분 |
| `job_no` | Y | 글자 | `job_id` ← `job.job_no` | 작업지시 번호 |
| `lot_no` |  | 글자 | `job_lot_id` ← `job_lot.lot_no` | 생산 LOT 번호 |
| `equipment_code` |  | 글자 | `equipment_id` ← `equipment.equipment_code` | 설비 코드 |
| `length_m` |  | 숫자 | `length_m` | 길이 (m) |
| `width_mm` |  | 숫자 · 0 초과 | `width_mm` | 폭 (mm) |
| `slit_seq` |  | 정수 · 0 초과 | `slit_seq` | 슬리팅 분할 순번 |
| `produced_at` | Y | 날짜 YYYY-MM-DD | `produced_at` | 생산일 YYYY-MM-DD |

### `roll_genealogy.csv` → `roll_genealogy` — 계보 (화살표 하나 = 한 줄)

명령 `load-history` · 업무 키 `parent_no + child_no` · 선택 파일 · **적재 보류 (D-01)**

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `parent_no` | Y | 글자 | `parent_no` | 부모 번호 — 원재료 LOT 번호 또는 롤 번호 |
| `child_no` | Y | 글자 | `child_no` | 자식 번호 — 롤 번호 또는 출하 LOT 번호 |
| `relation` | Y | 선택 `투입 / 후가공 / splice / 슬리팅 / 출하` | `relation` | 관계 |
| `qty` |  | 숫자 | `qty` | 넘어간 양 |

### `inspection.csv` → `inspection` — 검사 결과

명령 `load-history` · 업무 키 `roll_no + inspected_at` · 선택 파일 · **적재 보류 (D-01)**

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `roll_no` | Y | 글자 | `roll_id` ← `roll.roll_no` | 검사한 롤 번호 |
| `delta_e` |  | 숫자 | `delta_e` | ΔE — 0 이상 |
| `result` | Y | 선택 `합격 / 불합격` | `result` | 판정 |
| `inspected_at` | Y | 날짜 YYYY-MM-DD | `inspected_at` | 검사일 YYYY-MM-DD |
| `note` |  | 글자 | `note` | 비고 |

### `shipment.csv` → `shipment` — 출하 LOT

명령 `load-history` · 업무 키 `shipment_no` · 선택 파일 · **적재 보류 (D-01)**

| 열 | 필수 | 형식 | 적재 컬럼 | 설명 |
|---|---|---|---|---|
| `shipment_no` | Y | 글자 | `shipment_no` | 출하 LOT 번호 |
| `job_no` | Y | 글자 | `job_id` ← `job.job_no` | 작업지시 번호 |
| `customer_code` | Y | 글자 | `customer_id` ← `customer.customer_code` | 고객 코드 |
| `ship_date` | Y | 날짜 YYYY-MM-DD | `ship_date` | 출하일 YYYY-MM-DD |
| `status` | Y | 선택 `등록 / 승인 / 취소` | `status` | 상태 |
| `coa_no` |  | 글자 | `coa_no` | COA 번호 |
<!-- END:generated files -->

## 4. 실행 기록 — `sys_migration_log`

적재 명령(`load-*`)은 **실행 × 파일마다 한 줄**을 남긴다(D-303 — 테이블의 `target` · `source_file` 이 하나씩이다).

| 컬럼 | 값 |
|---|---|
| `command` | `load-master` · `load-print-std` · `load-jobs` · `load-history` |
| `target` · `source_file` | 대상 테이블 · 파일 이름 (`item` · `item.csv`) |
| `read_count` | 읽은 데이터 행 수 (머리 줄 · 빈 줄 제외) |
| `loaded_count` | upsert 한 행 수 (추가 + 갱신) |
| `error_count` | 건너뛴 행 수 + 파일 전체의 오류(파일 없음 · 머리 줄 오류) |
| `error_detail` | 오류 한 건이 한 줄 — `<줄 번호>행 [<업무 키>]: <열>: <사유>`. 100줄이 넘으면 `… 외 n건` |
| `started_at` · `finished_at` · `run_by` | 시작 · 끝 · 실행자(`--by`, 기본 OS 계정) |

## 5. 정해지지 않은 것 — 아키텍트·현업 확인

| # | 무엇 | 지금의 처리 |
|---|---|---|
| 1 | **과거 이력의 범위** — 어느 테이블까지 옮기는가, 계보(`roll_genealogy`)를 옮기는가, 기존 MES 에 롤 부모-자식 기록이 있는가 (D-01) | 파일 5개의 열 규격만 정했다. 데이터 행은 적재하지 않는다 |
| 2 | 과거 이력의 일시 — 지금 규격은 날짜(`YYYY-MM-DD`)다. 시각까지 필요한가 | 규격만 (적재 보류) |
| 3 | 과거 이력의 계보를 적재한다면 `lineage.link` 를 거쳐야 한다(계보에 쓰는 곳은 `lineage` 뿐). 과거 검사의 불량 행(`inspection_defect`) 파일도 필요하다 | 규격에 없다 — 범위가 정해지면 더한다 |
| 4 | 기존 MES 의 번호(Job · LOT)와 이 시스템의 채번(D-05)이 겹칠 수 있는가 | 번호는 파일 글자 그대로 넣는다. 채번 카운터는 건드리지 않는다 |
| 5 | 품목 구분이 `제품`/`원재료` 둘로 충분한가, 판사양·아니록스·잉크조성의 규격 값 열(D-18) | 스키마의 가설 컬럼 그대로 |
| 6 | 파일 인코딩 — 기존 MES 가 CP949 로만 뽑는다면 | UTF-8 만 받는다. 아니면 파일 오류 `UTF-8 로 읽을 수 없다` |
