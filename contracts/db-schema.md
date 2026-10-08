# DB 스키마 계약 (아키텍트 · 2026-10-03)

> 원본은 `src/lcomfine/db/schema.sql` 이다(D-08). **§4 는 그 파일과 실제 DB 에서 찍어 낸 렌더본**이라 손으로 고치지 않는다 —
> `schema.sql` 을 고치고 `make db-schema && make contracts`. `make check-schema` 가 이 문서 ↔ 실제 DB 를 컬럼 단위로 대조한다(G-04).
> 데이터가 있는 DB(여럿이 같이 쓰는 DB · 운영 DB)는 `make db-schema` 로 지우지 않고 **`ALTER` 로 같은 모양을 만든 뒤** `make contracts` 를 돌린다 —
> 새 컬럼은 `schema.sql` 에서도 그 테이블의 맨 끝에 적는다(`ADD COLUMN` 이 맨 끝에 붙으므로 컬럼 순서가 같아야 한다).
> 스키마를 고치는 사람은 아키텍트뿐이다. 개발자는 `progress-devN.md` §3 에 요청을 남긴다(D-22).
> 컬럼은 설계도 「프로세스별 입력과 출력」 표의 **입력** 낱말에서 끌어왔다. 모자란 곳의 구조 컬럼은 `가설`(D-18)이고 규격 값은 넣지 않았다.

DB `lcomfine_db` (PostgreSQL 17 · unix socket `/tmp`) · 테이블 **30** (D1~D8 23 + SYS 7) · 뷰 2 · 그 밖에 설계도 밖 확장 테이블 EXT 1(`sales_order`, D-418 — 30 에 세지 않는다).

## 1. 저장소 → 테이블

| 저장소 (설계도 §2) | 쓰는 프로세스 | 테이블 | 설계도의 입력 낱말 → 어디에 |
|---|---|---|---|
| D1 기준정보 | P1 | `item` `customer` `process` `equipment` `defect_code` `plate_spec` `anilox` `ink_formula` `ink_formula_component` | 품목 · 고객 · 공정 · 설비 · 불량코드 · 판사양 · 아니록스 · 잉크조성 → 각 테이블 |
| D2 작업지시 | P2 | `job` `job_lot` | Job 등록 → `job` · Job-Lot-Roll 매핑 → `job_lot`(D-10) |
| D3 원재료 LOT | P3 | `material_lot` | 입고 등록 → 행 생성 · 입고검사 결과 → `insp_status` `insp_at` `insp_by` `insp_note` |
| D4 조색 기록 | P4 | `color_record` `color_record_mix` | 색상값 → `color_l/a/b` · 배합비 → `color_record_mix.ratio_pct` |
| D5 생산 실적 | P5 | `work_result` `work_stop` `work_scrap` `material_input` | 작업 시작·종료 → `started_at` `ended_at` · 정지 → `work_stop` · 폐기 → `work_scrap` · 자재 투입 스캔 → `material_input` |
| D6 Roll·계보 | P5(인쇄 롤) · P6 | `roll` `roll_genealogy` | 가공 실적 → `roll` 의 설비·길이·폭·일시 · 슬리팅 분할 → 슬리팅 롤 N + `슬리팅` 행 · splice → `splice` 행 |
| D7 품질 검사 | P7 | `inspection` `inspection_defect` | ΔE → `delta_e` · 불량 유형·위치 → `inspection_defect` · 불량 롤 번호 → `inspection.roll_id` |
| D8 출하 | P8 | `shipment` | 출하 등록 → 행 생성 · 출하 승인 → `approved_at` `approved_by` · 롤 스캔 → 계보의 `출하` 행(D-12) |
| SYS 공통 | 공통(D-15) | `sys_role` `sys_user` `sys_permission` `sys_access_log` `sys_number_rule` `sys_number_seq` `sys_migration_log` | 로그인 · 역할별 권한 · 접근 로그 · 채번 · 이관 기록 |
| EXT 확장 (설계도 밖 · D-418) | 영업관리 `sal` | `sales_order` | 수주 등록 → 행 생성 · 취소 → `status`. 설계도 테이블 30 에 들어가지 않는다(`check_schema` 가 따로 센다). 작업지시가 `job.sales_order_id` 로 가리킨다 |

이름이 설계도에 적혀 있어 그대로 쓴 테이블 — `material_lot` · `roll` · `roll_genealogy` · `shipment`.
`roll` 은 인쇄·후가공·슬리팅 롤을 한 테이블에 담고 `process_type` 으로 가른다.

## 2. 쓰기 경계 (G-05 의 기대값)

프로세스는 아래 표의 테이블에만 쓴다. `tools/check_data.py`(QA2)가 라우터별 쓰기 SQL 과 조회 전후 행 수로 확인한다.

| 프로세스 | 라우터 | 쓸 수 있는 테이블 | 쓰면 안 되는 대표 사례 |
|---|---|---|---|
| P1 기준정보 · 인쇄 기준 | `bas` `prt` | D1 9개 | — |
| P2 작업지시 | `job` | `job` `job_lot` | 원재료 LOT·롤을 미리 묶는 것 |
| P3 자재 입고 | `mat`(입고·입고검사·원재료 LOT) | `material_lot` | — |
| P4 조색 기록 | `clr` | `color_record` `color_record_mix` | — |
| P5 생산 실적 (인쇄) | `pop` · `mat`(자재 투입) | `work_result` `work_stop` `work_scrap` `material_input` + `roll`(인쇄 롤) `roll_genealogy`(`투입`) | `job.status` 바꾸기 · `material_lot` 잔량 깎기 |
| P6 후가공 · 슬리팅 | `rll` | `roll` `roll_genealogy`(`후가공` `splice` `슬리팅`) | `work_result` 에 쓰기 |
| P7 품질 검사 | `qua` | `inspection` `inspection_defect` | 롤에 판정을 적는 것(판정은 최신 검사에서 읽는다) |
| P8 출하 | `shp` | `shipment` + **`roll_genealogy` 의 `출하` 행 — `lineage.ship_roll`·`lineage.unlink_shipment` 로만** | `roll` 에 상태를 적는 것 · `roll_genealogy` 직접 INSERT |
| **P9 LOT 추적** | `trc` | **없음** | 추적 결과를 담는 테이블 |
| **P10 실적 현황** | `sta` | **없음** | 집계 결과를 담는 테이블 |
| 공통 | `sys` · `main` | `sys_*` | — |
| 배치(이관) | `lcomfine.migration` | 그 명령의 대상 테이블 + `sys_migration_log` | — |
| 확장 영업관리 (D-418) | `sal` | `sales_order` 뿐 | `job` 에 쓰기 — 수주 연결(`job.sales_order_id`)은 P2(F-JOB-01·02)가 쓴다 |

- **P8 의 예외**는 설계도의 모순에서 나온다 — §2 표는 P8 → D8 뿐인데 §3 은 출하 화살표도 `roll_genealogy` 한 줄이다. G-06 이 10행을 요구하므로 §3 을 따랐다(D-12).
- `sys_access_log`(화면 조회 로그)와 `sys_number_seq`(채번 카운터)는 공통 코드가 쓴다. P9·P10 화면을 열면 접근 로그가 한 줄 늘지만 그것은 라우터의 쓰기가 아니다 — **G-05 의 행 수 대조 대상은 D1~D8 의 23개 테이블**이다(D-15).
- 그래서 저장하지 않고 계산하는 값이 셋 있다: 롤 상태(`v_roll_state`) · 원재료 LOT 잔량(`v_material_lot_stock`) · Job 의 진행 여부(D5 에 실적이 있는가).

## 3. `roll_genealogy` — 만들기 전에 종이 위에서 따져 본 것

### 3.1 모양

한 행 = 화살표 하나. 부모 둘 중 하나, 자식 둘 중 하나만 채운다. 네 컬럼 모두 FK 라서 없는 LOT·롤·출하를 가리킬 수 없다.

| 관계 `relation` | 부모 | 자식 | 만드는 기능 |
|---|---|---|---|
| `투입` | `parent_material_lot_id` | `child_roll_id` (인쇄 롤) | F-POP-02 작업 종료 — 그 실적의 `material_input` 마다 한 줄 |
| `후가공` | `parent_roll_id` | `child_roll_id` (후가공 롤) | F-RLL-01 — 부모 1개 |
| `splice` | `parent_roll_id` | `child_roll_id` (후가공 롤) | F-RLL-02 — 부모 N개(N줄) |
| `슬리팅` | `parent_roll_id` | `child_roll_id` (슬리팅 롤) | F-RLL-04 — 자식 N개(N줄) |
| `출하` | `parent_roll_id` | `child_shipment_id` | F-SHP-02 출하 롤 스캔 |

### 3.2 G-06 — 설계도 §3 예시는 정확히 10행인가

설계도 그림의 「계보 선: 부모 → 자식」 화살표는 10개다. 같은 예시를 이 표에 넣으면:

| # | 부모 | 자식 | relation |
|---|---|---|---|
| 1 | 원재료 LOT ① | 인쇄 Roll ① | 투입 |
| 2 | 원재료 LOT ① | 인쇄 Roll ② | 투입 |
| 3 | 원재료 LOT ② | 인쇄 Roll ② | 투입 |
| 4 | 인쇄 Roll ① | 후가공 Roll | splice |
| 5 | 인쇄 Roll ② | 후가공 Roll | splice |
| 6 | 후가공 Roll | 슬리팅 Roll ① | 슬리팅 |
| 7 | 후가공 Roll | 슬리팅 Roll ② | 슬리팅 |
| 8 | 후가공 Roll | 슬리팅 Roll ③ | 슬리팅 |
| 9 | 슬리팅 Roll ① | 출하 LOT | 출하 |
| 10 | 슬리팅 Roll ② | 출하 LOT | 출하 |

투입 3 + splice 2 + 슬리팅 3 + 출하 2 = **10**. 슬리팅 Roll ③ 은 부모로 나오는 행이 없다 → `v_roll_state` 가 `재고`.
- 행이 더 생기지 않는 이유: 출하 롤 목록을 따로 담는 테이블이 없고(계보 한 줄이 곧 "실렸다"), 투입 스캔은 D5 `material_input` 에 있다가 롤이 만들어질 때 한 번만 옮겨진다.
- 행이 덜 생기지 않는 이유: LOT ① 이 두 롤에 들어간 것은 작업 실적 2건의 투입 스캔 2건이고(D-13) 유니크 키가 `(부모 LOT, 자식 롤)` 이라 같은 LOT 이 다른 롤의 부모가 되는 것은 막지 않는다.
- 화면 조작 순서: 입고 2 → 입고검사 합격 2 → Job → (작업 시작 → 투입 스캔 LOT① → 종료) → (작업 시작 → 투입 스캔 LOT①·② → 종료) → splice(롤 2 스캔) → 슬리팅 분할 3 → 출하 등록 → 롤 스캔 2 → 승인.
- 이 10행·추적·제약은 `tests/test_arch_genealogy.py` 가 SQL 로 직접 넣어 확인한다(스키마가 감당하는지만 — API 로 만드는 것은 개발2 의 `tests/test_lineage_scenario.py`).

### 3.3 G-07 — 양방향 추적이 조회 하나로 되는가

역방향(출하 LOT → 원재료 LOT). 자식 쪽 키로 들어가 부모 쪽으로 올라간다. 깊이·분기 수를 가정하지 않는다.

```sql
with recursive up as (
    select g.* from roll_genealogy g where g.child_shipment_id = %(shipment_id)s      -- 롤에서 시작하면 g.child_roll_id = %(roll_id)s
    union
    select g.* from roll_genealogy g join up on g.child_roll_id = up.parent_roll_id
)
select * from up;            -- parent_material_lot_id 가 채워진 행이 닿은 원재료 LOT
```

예시로 따라가면 출하 2행(9·10) → 슬리팅 2행(6·7) → splice 2행(4·5) → 투입 3행(1·2·3) = 9행, 원재료 LOT ①·② 둘 다 닿는다. 8번(③)은 출하되지 않았으므로 안 나온다.

정방향(원재료 LOT → 출하 LOT). 부모 쪽 키로 들어가 자식 쪽으로 내려간다.

```sql
with recursive down as (
    select g.* from roll_genealogy g where g.parent_material_lot_id = %(material_lot_id)s   -- 롤에서 시작하면 g.parent_roll_id = %(roll_id)s
    union
    select g.* from roll_genealogy g join down on g.parent_roll_id = down.child_roll_id
)
select * from down;          -- child_shipment_id 가 채워진 행이 닿은 출하 LOT. 자식으로만 나오고 부모로는 안 나오는 롤 = 재고
```

LOT ① 에서 시작하면 투입 2행(1·2) → splice 2행(4·5) → 슬리팅 3행(6·7·8) → 출하 2행(9·10) = 9행. 3번(LOT ②의 투입)은 안 나온다. 슬리팅 ③ 은 자식으로만 나온다 → `재고`.

- `union`(중복 제거)이라 같은 행이 두 길로 닿아도(후가공 Roll 은 ①·② 두 길에서 닿는다) 한 번만 나온다. 행 전체가 같아야 중복이므로 깊이 열을 붙이면 중복 제거가 풀린다 — 깊이가 필요하면 바깥에서 `min(depth)` 로 묶는다.
- 순환이 없으므로(§3.4) 재귀는 반드시 끝난다. 추적 결과를 담는 테이블은 없다 — 매번 이 조회를 돈다(G-05·G-07).
- 인덱스: `child_roll_id` · `child_shipment_id` · `parent_roll_id` · `(parent_material_lot_id, child_roll_id)`.

### 3.4 순환 금지

- 순환에 낄 수 있는 것은 롤 → 롤 행뿐이다. 원재료 LOT 은 부모만, 출하는 자식만 될 수 있다(CHECK `roll_genealogy_shape_chk`).
- 자기 자신: CHECK `roll_genealogy_self_chk` (`parent_roll_id <> child_roll_id`).
- 긴 순환: 트리거 `roll_genealogy_guard` 가 롤 → 롤 행을 넣기 전에 **자식에서 내려가 부모에 닿는지** 재귀 조회로 본다. 닿으면 거부한다. 지금까지의 행에 순환이 없으면 새 행을 넣어도 순환이 없다(귀납).
- 동시성: 두 트랜잭션이 A→B 와 B→A 를 동시에 넣으면 서로의 행을 못 본다. 트리거가 `pg_advisory_xact_lock` 으로 계보 삽입을 직렬화한다.
- 계보 행의 부모·자식·관계는 UPDATE 할 수 없다(같은 트리거). 고치려면 지우고 다시 넣는다.

### 3.5 같은 트리거가 막는 나머지

| 상황 | 막는 곳 | 앱이 내는 오류 |
|---|---|---|
| 이미 출하된 롤 재출하 | 부분 유니크 인덱스 `roll_genealogy_ship_once_uq` | 422 |
| 출하된 롤을 다음 공정의 부모로 | 트리거 | 422 |
| 다음 공정에 쓰인(소진) 롤 출하 | 트리거 | 422 |
| 같은 화살표 중복 | 유니크 인덱스 2개 | 422 |
| 관계와 자식 롤의 공정 구분이 어긋남 (`슬리팅` 인데 자식이 인쇄 롤) | 트리거 | 422 |
| `등록` 이 아닌 출하에 롤 담기 · 다른 Job 의 롤 담기(D-16) | 트리거 | 422 |

DB 가 막는 것은 **마지막 방어선**이다. `lineage` 가 먼저 검사해 사람이 읽을 문장으로 422 를 낸다. 놓쳐도 `main.py` 가 제약 위반(`IntegrityError`)을 422 로 바꾼다(500 이 되지 않는다).
DB 가 막지 않고 `lineage` 만 막는 것: 소진된 롤을 **다른 작업에서** 다시 부모로 쓰기(슬리팅은 한 부모에 자식이 여럿이라 DB 로는 구분할 수 없다) · 불합격/검사 대기 LOT 투입 · 불합격 롤 출하(D-17).

## 4. 테이블 · 컬럼 (렌더본 — 손으로 고치지 않는다)

<!-- BEGIN:generated tables -->
#### D1 기준정보 — 테이블 9

### `item` — D1 · 품목 — 제품과 원재료를 한 테이블에 구분으로 담는다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| item_id | bigint | N | 내부 키 |
| item_code | text | N | 품목 코드 (업무 키 · 이관 upsert 기준) |
| item_name | text | N | 품목명 |
| item_type | text | N | 구분: 제품 | 원재료 |
| spec | text | Y | 규격 (글자 그대로 — 값은 받은 적 없음, D-18) |
| unit | text | Y | 단위 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `customer` — D1 · 고객

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| customer_id | bigint | N | 내부 키 |
| customer_code | text | N | 고객 코드 |
| customer_name | text | N | 고객명 |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `process` — D1 · 공정

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| process_id | bigint | N | 내부 키 |
| process_code | text | N | 공정 코드 |
| process_name | text | N | 공정명 |
| process_type | text | N | 공정 구분: 인쇄 | 후가공 | 슬리팅 | 기타 |
| sort_no | integer | Y | 표시 순서 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `equipment` — D1 · 설비 — 기준정보까지만. 설비 상태·수집값 컬럼은 두지 않는다 (G-12)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| equipment_id | bigint | N | 내부 키 |
| equipment_code | text | N | 설비 코드 |
| equipment_name | text | N | 설비명 |
| process_id | bigint | Y | 이 설비가 속한 공정 |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `defect_code` — D1 · 불량코드 — P7 의 "불량 유형" 이 가리키는 곳

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| defect_code_id | bigint | N | 내부 키 |
| defect_code | text | N | 불량 코드 |
| defect_name | text | N | 불량명 (불량 유형) |
| defect_group | text | Y | 분류 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `plate_spec` — D1 · 판사양 (인쇄 기준)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| plate_spec_id | bigint | N | 내부 키 |
| plate_code | text | N | 판 코드 |
| plate_name | text | N | 판명 |
| item_id | bigint | Y | 대상 품목(제품) |
| color_count | integer | Y | 도수 (가설 컬럼 D-18) |
| spec_note | text | Y | 사양 메모 (글자 그대로) |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `anilox` — D1 · 아니록스 (인쇄 기준)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| anilox_id | bigint | N | 내부 키 |
| anilox_code | text | N | 아니록스 코드 |
| anilox_name | text | N | 명칭 |
| line_count | numeric(10,2) | Y | 선수 (가설 컬럼 D-18) |
| cell_volume | numeric(10,3) | Y | 셀 용적 (가설 컬럼 D-18) |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `ink_formula` — D1 · 잉크조성 (인쇄 기준) — 조색의 기준이 되는 표준 조성

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| ink_formula_id | bigint | N | 내부 키 |
| ink_code | text | N | 잉크 코드 |
| ink_name | text | N | 잉크명 |
| color_name | text | Y | 색 이름 |
| target_l | numeric(7,2) | Y | 기준 색상값 L (가설 컬럼 D-18) |
| target_a | numeric(7,2) | Y | 기준 색상값 a |
| target_b | numeric(7,2) | Y | 기준 색상값 b |
| note | text | Y | 비고 |
| use_yn | text | N | 사용 여부 Y | N |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `ink_formula_component` — D1 · 잉크조성의 조성 행 (성분·비율)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| ink_formula_component_id | bigint | N | 내부 키 |
| ink_formula_id | bigint | N | 잉크조성 |
| seq_no | integer | N | 행 순번 |
| component_name | text | N | 성분명 |
| ratio_pct | numeric(6,3) | N | 비율 (%) |

#### D2 작업지시 — 테이블 2

### `job` — D2 · 작업지시(Job) — Job-Lot-Roll 키의 맨 위

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| job_id | bigint | N | 내부 키 |
| job_no | text | N | 작업지시 번호 (numbering.next('JOB') · 형식 D-05) |
| item_id | bigint | N | 품목(제품) |
| customer_id | bigint | N | 고객 |
| plate_spec_id | bigint | Y | 판사양 |
| anilox_id | bigint | Y | 아니록스 |
| ink_formula_id | bigint | Y | 잉크조성 |
| equipment_id | bigint | Y | 계획 설비 |
| order_qty | numeric(14,3) | N | 지시 수량 |
| qty_unit | text | N | 수량 단위 |
| due_date | date | N | 납기 (실적 현황 납기 집계의 기준) |
| status | text | N | 등록 | 완료 | 취소 (진행 여부는 저장하지 않고 D5 에서 읽는다) |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |
| sales_order_id | bigint | Y | 수주 (설계도 밖 확장 D-418 · 수주 없이 낸 지시는 NULL) |

### `job_lot` — D2 · 생산 LOT — "Job-Lot-Roll 매핑" 의 Lot 단 (D-10). Job 1 : 생산 LOT N

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| job_lot_id | bigint | N | 내부 키 |
| job_id | bigint | N | 작업지시 |
| lot_no | text | N | 생산 LOT 번호 (numbering.next('JOB_LOT')) |
| planned_roll_count | integer | Y | 계획 롤 수 |
| planned_length_m | numeric(14,3) | Y | 계획 길이 (m) |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

#### D3 원재료 LOT — 테이블 1

### `material_lot` — D3 · 원재료 LOT — 입고 1건 = LOT 1개. 계보의 맨 앞 (설계도 §3 그림의 이름 그대로)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| material_lot_id | bigint | N | 내부 키 |
| lot_no | text | N | 원재료 LOT 번호 (numbering.next('MAT_LOT') · 라벨 바코드) |
| item_id | bigint | N | 원재료 품목 |
| supplier_name | text | Y | 공급처 (마스터 없음 — 글자, D-18) |
| supplier_lot_no | text | Y | 공급사 LOT 번호 |
| received_qty | numeric(14,3) | N | 입고 수량 |
| qty_unit | text | N | 수량 단위 |
| received_at | timestamp with time zone | N | 입고 일시 |
| received_by | text | N | 입고 등록자 login_id |
| insp_status | text | N | 입고검사 결과: 대기 | 합격 | 불합격 (합격만 투입 가능) |
| insp_at | timestamp with time zone | Y | 입고검사 일시 |
| insp_by | text | Y | 입고검사자 login_id |
| insp_note | text | Y | 입고검사 비고 |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

#### D4 조색 기록 — 테이블 2

### `color_record` — D4 · 조색 기록 — Job 의 색별·차수별 색상값

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| color_record_id | bigint | N | 내부 키 |
| job_id | bigint | N | 작업지시 (Job 키) |
| ink_formula_id | bigint | Y | 기준 잉크조성 |
| color_name | text | N | 색 이름 |
| seq_no | integer | N | 차수 (재조색마다 +1) |
| color_l | numeric(7,2) | Y | 색상값 L (가설: Lab, D-18) |
| color_a | numeric(7,2) | Y | 색상값 a |
| color_b | numeric(7,2) | Y | 색상값 b |
| note | text | Y | 비고 |
| recorded_at | timestamp with time zone | N | 기록 일시 |
| recorded_by | text | N | 기록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `color_record_mix` — D4 · 조색 기록의 배합비 행 (성분·비율)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| color_record_mix_id | bigint | N | 내부 키 |
| color_record_id | bigint | N | 조색 기록 |
| seq_no | integer | N | 행 순번 |
| component_name | text | N | 성분명 |
| ratio_pct | numeric(6,3) | N | 배합비 (%) |

#### D5 생산 실적 — 테이블 4

### `work_result` — D5 · 작업 실적(인쇄) — 시작·종료. 실적 1건 = 인쇄 롤 1개 (D-13)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| work_result_id | bigint | N | 내부 키 (경로의 work_id) |
| job_id | bigint | N | 작업지시 (Job 키) |
| job_lot_id | bigint | Y | 생산 LOT |
| process_id | bigint | Y | 공정 |
| equipment_id | bigint | Y | 설비 |
| status | text | N | 진행 | 정지 | 완료 |
| started_at | timestamp with time zone | N | 작업 시작 |
| ended_at | timestamp with time zone | Y | 작업 종료 |
| output_qty | numeric(14,3) | Y | 실적 수량 (종료 때 입력 · 생산 집계의 값) |
| qty_unit | text | Y | 수량 단위 |
| worker | text | N | 작업자 login_id |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `work_stop` — D5 · 정지 기록 — 정지 시작과 재개

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| work_stop_id | bigint | N | 내부 키 (경로의 stop_id) |
| work_result_id | bigint | N | 작업 실적 |
| stop_reason | text | N | 정지 사유 (마스터 없음 — 글자, D-18) |
| stopped_at | timestamp with time zone | N | 정지 시각 |
| resumed_at | timestamp with time zone | Y | 재개 시각 (비어 있으면 정지 중) |
| created_by | text | N | 등록자 login_id |

### `work_scrap` — D5 · 폐기 기록

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| work_scrap_id | bigint | N | 내부 키 |
| work_result_id | bigint | N | 작업 실적 |
| scrap_qty | numeric(14,3) | N | 폐기 수량 |
| qty_unit | text | Y | 수량 단위 |
| defect_code_id | bigint | Y | 폐기 사유(불량코드) |
| reason | text | Y | 사유 메모 |
| scrapped_at | timestamp with time zone | N | 폐기 시각 |
| created_by | text | N | 등록자 login_id |

### `material_input` — D5 · 자재 투입 스캔 — 작업 종료 때 인쇄 롤의 계보 `투입` 행이 된다 (D-13)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| material_input_id | bigint | N | 내부 키 |
| work_result_id | bigint | N | 작업 실적 |
| material_lot_id | bigint | N | 원재료 LOT (합격만) |
| input_qty | numeric(14,3) | Y | 투입량 |
| qty_unit | text | Y | 수량 단위 |
| scanned_at | timestamp with time zone | N | 스캔 시각 |
| scanned_by | text | N | 스캔한 사람 login_id |

#### D6 Roll·계보 — 테이블 2

### `roll` — D6 · 롤 — 인쇄·후가공·슬리팅 롤을 한 테이블에 공정 구분으로. 상태 컬럼은 없다 (v_roll_state)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| roll_id | bigint | N | 내부 키 |
| roll_no | text | N | 롤 번호 (numbering.next('ROLL') · 라벨 바코드) |
| process_type | text | N | 공정 구분: 인쇄 | 후가공 | 슬리팅 |
| job_id | bigint | N | 작업지시 (Job 키) |
| job_lot_id | bigint | Y | 생산 LOT (Lot 키) |
| work_result_id | bigint | Y | 인쇄 롤을 만든 작업 실적 (D5 키 · 인쇄 롤만) |
| equipment_id | bigint | Y | 가공 실적: 설비 |
| length_m | numeric(14,3) | Y | 가공 실적: 길이 m (가설 컬럼 D-18) |
| width_mm | numeric(10,2) | Y | 가공 실적: 폭 mm (슬리팅 분할 폭) |
| slit_seq | integer | Y | 슬리팅 분할 순번 (1..N) |
| produced_at | timestamp with time zone | N | 생산(가공) 일시 |
| produced_by | text | N | 작업자 login_id |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |

### `roll_genealogy` — D6 · 계보 — 한 행 = 설계도 §3 그림의 화살표 하나 (부모 → 자식). 추적은 이 표를 따라가는 조회다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| genealogy_id | bigint | N | 내부 키 |
| parent_material_lot_id | bigint | Y | 부모: 원재료 LOT (parent_roll_id 와 둘 중 하나) |
| parent_roll_id | bigint | Y | 부모: 롤 |
| child_roll_id | bigint | Y | 자식: 롤 (child_shipment_id 와 둘 중 하나) |
| child_shipment_id | bigint | Y | 자식: 출하 LOT |
| relation | text | N | 관계: 투입 | 후가공 | splice | 슬리팅 | 출하 |
| qty | numeric(14,3) | Y | 그 화살표로 넘어간 양 (투입량 등 · 없으면 비움) |
| created_at | timestamp with time zone | N | 기록 일시 |
| created_by | text | N | 기록자 login_id |

#### D7 품질 검사 — 테이블 2

### `inspection` — D7 · 검사 결과 — 롤 1개에 여러 번. 최신 검사가 그 롤의 판정이다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| inspection_id | bigint | N | 내부 키 |
| roll_id | bigint | N | 검사한 롤 ("불량 롤 번호" 가 가리키는 롤) |
| job_id | bigint | N | 작업지시 (롤에서 복사한 Job 키, D-16) |
| delta_e | numeric(7,2) | Y | ΔE (색차) |
| result | text | N | 판정: 합격 | 불합격 |
| inspected_at | timestamp with time zone | N | 검사 일시 |
| inspected_by | text | N | 검사자 login_id |
| note | text | Y | 비고 |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `inspection_defect` — D7 · 검사의 불량 행 (불량 유형·위치) — 불량 유형별 집계의 원천

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| inspection_defect_id | bigint | N | 내부 키 |
| inspection_id | bigint | N | 검사 결과 |
| defect_code_id | bigint | N | 불량 유형 (불량코드) |
| position | text | Y | 불량 위치 (형식 미정 — 글자, D-18) |
| note | text | Y | 비고 |

#### D8 출하 — 테이블 1

### `shipment` — D8 · 출하 LOT — 계보의 맨 끝. 담긴 롤은 roll_genealogy 의 `출하` 행이다 (별도 목록 테이블 없음)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| shipment_id | bigint | N | 내부 키 |
| shipment_no | text | N | 출하 LOT 번호 (numbering.next('SHIPMENT')) |
| job_id | bigint | N | 작업지시 (Job 키 — 출하 LOT 1 = Job 1, D-16) |
| customer_id | bigint | N | 고객 |
| ship_date | date | N | 출하일 (납기 집계에서 납기와 비교) |
| status | text | N | 등록 | 승인 | 취소 |
| registered_at | timestamp with time zone | N | 출하 등록 일시 |
| registered_by | text | N | 출하 등록자 login_id |
| approved_at | timestamp with time zone | Y | 출하 승인 일시 |
| approved_by | text | Y | 출하 승인자 login_id (관리자) |
| coa_no | text | Y | COA 번호 (승인 때 numbering.next('COA'), D-17) |
| coa_issued_at | timestamp with time zone | Y | COA 발행 일시 |
| note | text | Y | 비고 |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

#### SYS 공통(시스템) — 테이블 7

### `sys_role` — SYS · 역할 — 설계도 §6 의 4역할. 역할을 늘리려면 행을 넣는다 (D-06)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| role_code | text | N | 역할 코드 (ADMIN · PROD · QC · FIELD) |
| role_name | text | N | 역할명 (관리자 · 생산 · 품질 · 현장) |
| sort_no | integer | N | 표시 순서 (권한 표의 열 순서) |
| use_yn | text | N | 사용 여부 Y | N |

### `sys_user` — SYS · 사용자 계정

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| user_id | bigint | N | 내부 키 |
| login_id | text | N | 로그인 ID |
| user_name | text | N | 이름 |
| password_hash | text | N | 비밀번호 해시 (PBKDF2 · 화면에 내보내지 않는다) |
| role_code | text | N | 역할 |
| status | text | N | 정상 | 잠금 | 중지 |
| fail_count | integer | N | 연속 로그인 실패 횟수 |
| last_login_at | timestamp with time zone | Y | 마지막 로그인 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |
| session_epoch | integer | N | 세션 판 번호 — 상태·비밀번호가 바뀌면 트리거가 +1. 로그인 때의 값과 다른 세션은 무효 (D-26) |
| revoked_sessions | jsonb | N | 로그아웃한 세션 ID → 로그아웃 시각(epoch 초). 쿠키 수명이 지난 것은 다음 로그아웃 때 지운다 (D-26) |

### `sys_permission` — SYS · 권한 표 — 역할 × 대메뉴 한 칸이 한 행 (4 × 12 = 48). 코드가 아니라 데이터다 (G-17 · D-14)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| role_code | text | N | 역할 |
| menu_code | text | N | 대메뉴 코드 (nav.py 의 BAS · PRT · … · SYS) |
| level | text | N | 입력 | 조회 | 없음 |
| write_scope | text | N | 입력의 범위: 일반 | 입고검사 | 승인 (쉼표로 여럿). 입력이 아니면 빈 글자 |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |

### `sys_access_log` — SYS · 접근 로그 — 로그인 성공·실패, 화면 조회, 데이터 변경, 오류 (G-18)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| log_id | bigint | N | 내부 키 |
| logged_at | timestamp with time zone | N | 일시 (언제) |
| log_type | text | N | 구분: 로그인 | 조회 | 변경 | 오류 |
| login_id | text | Y | 누가 (실패한 로그인은 입력한 ID) |
| role_code | text | Y | 그때의 역할 |
| method | text | Y | HTTP 메서드 |
| path | text | Y | 경로 |
| screen_id | text | Y | 화면 ID (nav.py) |
| function_id | text | Y | 기능 ID (function-list.md) |
| target | text | Y | 무엇을 (테이블·업무 번호) |
| result | text | N | 성공 | 실패 |
| detail | text | Y | 내용 |
| client_ip | text | Y | 접속 IP |

### `sys_number_rule` — SYS · 채번 형식 — 번호 종류별 한 행. 형식은 코드가 아니라 이 행이다 (D-05). 행은 개발1 시드가 넣는다

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| seq_kind | text | N | 번호 종류: JOB | JOB_LOT | MAT_LOT | ROLL | SHIPMENT | COA |
| prefix | text | N | 접두 글자 |
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

### `sys_migration_log` — SYS · 이관 배치 실행 기록 — 실행마다 한 행 (G-15 · D-23)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| migration_log_id | bigint | N | 내부 키 |
| command | text | N | 명령 (load-master 등) |
| target | text | Y | 대상 테이블 |
| source_file | text | Y | Import 파일명 |
| read_count | integer | N | 읽은 행 수 |
| loaded_count | integer | N | 적재한 행 수 |
| error_count | integer | N | 오류 행 수 |
| error_detail | text | Y | 오류 내용 |
| started_at | timestamp with time zone | N | 시작 |
| finished_at | timestamp with time zone | Y | 끝 |
| run_by | text | Y | 실행한 사람 |

#### EXT 확장(설계도 밖 · D-418) — 테이블 1

### `sales_order` — EXT · 수주 — 설계도 밖 확장(D-418). 영업이 받은 수주 한 건. 작업지시가 이 행을 가리킨다(job.sales_order_id)

| 컬럼 | 타입 | NULL | 설명 |
|---|---|---|---|
| sales_order_id | bigint | N | 내부 키 |
| order_no | text | N | 수주 번호 (numbering.next('SALES_ORDER') · 형식 가설 D-418) |
| customer_id | bigint | N | 고객 |
| item_id | bigint | N | 품목(제품) |
| order_qty | numeric(14,3) | N | 수주 수량 |
| qty_unit | text | N | 수량 단위 |
| order_date | date | N | 수주일 |
| due_date | date | N | 납기 (고객 요청) |
| customer_po | text | Y | 고객 발주 번호 (받은 글자 그대로) |
| status | text | N | 등록 | 취소 (진행은 저장하지 않고 Job·실적·출하에서 읽는다) |
| note | text | Y | 비고 |
| created_at | timestamp with time zone | N | 등록 일시 |
| created_by | text | N | 등록자 login_id |
| updated_at | timestamp with time zone | Y | 수정 일시 |
| updated_by | text | Y | 수정자 login_id |
<!-- END:generated tables -->

## 5. 뷰 (읽기 전용 — 저장하지 않고 계산한다)

| 뷰 | 컬럼 | 계산 |
|---|---|---|
| `v_roll_state` | `roll_id` `roll_no` `process_type` `job_id` `state` `shipment_id` | `출하`(출하 행이 있다) > `소진`(자식 롤이 있다) > `재고`(자식이 없다) |
| `v_material_lot_stock` | `material_lot_id` `lot_no` `item_id` `insp_status` `received_qty` `input_qty` `remaining_qty` `input_count` | 잔량 = 입고 수량 − `material_input.input_qty` 합 |

## 6. 키 연결 (G-08) — 롤 번호 하나로 어디까지 가는가

| 찾는 것 | 길 |
|---|---|
| 작업지시 | `roll.job_id` → `job` (생산 LOT 은 `roll.job_lot_id` → `job_lot`) |
| 조색 기록 | `roll.job_id` = `color_record.job_id` |
| 생산 실적 | 인쇄 롤: `roll.work_result_id` → `work_result`(→ `work_stop` `work_scrap` `material_input`). 후가공·슬리팅 롤: 계보를 거슬러 올라간 인쇄 롤의 실적 — **이 길을 화면에서 보여 주는 것은 롤 이력(F-RLL-06 `GET /rll/history?no=`, 개발2)의 책임이다**: 후가공·슬리팅 롤 번호로 열면 `lineage.trace_backward` 로 닿은 모든 조상 인쇄 롤의 실적이 나온다(D-210). LOT 추적 화면(F-TRC-01·02)은 계보만 보인다(D-401) |
| 검사 결과 | `inspection.roll_id` (최신 `inspected_at` 이 그 롤의 판정) |
| 출하 | `roll_genealogy` 의 `parent_roll_id = 롤` · `child_shipment_id` → `shipment` (자손 롤의 출하는 정방향 추적) |
| 원재료 LOT | 역방향 추적 |

`job_id` 는 D2·D4·D5·D6·D7·D8 의 모든 머리 테이블에 있다. D7·D8 의 `job_id` 는 롤에서 복사한 키이고(D-16), `inspection` 은 복합 FK `(roll_id, job_id)` 로 복사가 틀릴 수 없게 했다.

## 7. 상태값

| 컬럼 | 값 | 누가 바꾸는가 |
|---|---|---|
| `job.status` | `등록` → `완료` / `취소` | P2 만 (F-JOB-02·03) |
| `material_lot.insp_status` | `대기` → `합격` / `불합격` | P3 (F-MAT-03 · 품질만) |
| `work_result.status` | `진행` ⇄ `정지` → `완료` | P5 (F-POP-01·02·04·05) |
| `shipment.status` | `등록` → `승인` / `취소` | P8 (F-SHP-01·03·05) |
| `inspection.result` | `합격` / `불합격` | P7 |
| `sys_user.status` | `정상` / `잠금` / `중지` | 공통 (F-SYS-02·03). 바뀌면 트리거 `sys_user_session_epoch_trg` 가 `session_epoch` 를 올려 그 계정의 살아 있는 세션을 끊는다(비밀번호 해시가 바뀔 때도 — D-26) |
| 롤 상태 | `재고` / `소진` / `출하` | 아무도 — 계보에서 계산 (`v_roll_state`) |

Job 이 참조하는 판사양·아니록스·잉크조성은 각각 하나다. 다색 인쇄에서 색마다 다른 아니록스·잉크를 지정하는 구조는 현업의 작업지시서 양식을 받은 뒤 정한다(D-18).
