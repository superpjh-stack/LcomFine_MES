# progress-dev2 — 개발2 (현장 실행 / 기능 28)

> §1 공표(다른 사람이 그대로 쓰는 것) · §2 진행 · §3 요청(스키마·계약·공용 파일). 실측한 것만 적는다.

## 1. 공표

### 1.1 계보 `app/lineage.py` (2026-10-03 · 구현됨, 지금 불러도 된다)

시그니처는 `contracts/interfaces.md` §4 **그대로다 — 바꾸지 않았다.** 더한 것은 상수와 편의 속성뿐이다.

```python
from lcomfine.app import lineage
from lcomfine.db import conn

# 노드는 (종류, id). 종류 상수: lineage.MATERIAL_LOT · lineage.ROLL · lineage.SHIPMENT
# 관계 상수: lineage.INPUT(투입) · FINISHING(후가공) · SPLICE(splice) · SLITTING(슬리팅) · SHIPPING(출하)
# 롤 상태: lineage.IN_STOCK(재고) · CONSUMED(소진) · SHIPPED(출하)

# ── 읽기 (어떤 테이블에도 쓰지 않는다 — 자체 연결로 SELECT 만) ──
node = lineage.resolve("R261003-0001")        # 스캔값 → Node | None. 원재료 LOT·롤·출하 LOT 세 테이블에서 찾는다
if node is None:                              #   (첫 글자로 종류를 가정하지 않는다. 앞뒤 공백 제거 · 소문자면 대문자로도 찾는다)
    raise http.validation_error("없는 번호입니다", fields=[{"name": "번호", "reason": no}])   # 스캔값이 없으면 422 는 호출자가
t = lineage.trace_backward(node.ref)          # 또는 (node.kind, node.id). 출하 LOT·롤 → 원재료 LOT
t.material_lots()                             # 닿은 원재료 LOT [Node]  ← 역방향 추적의 답
t = lineage.trace_forward(node.ref)           # 원재료 LOT·롤 → 출하 LOT
t.shipments()                                 # 닿은 출하 LOT [Node]    ← 정방향 추적의 답
t.stock_rolls()                               # 자식 없이 남은 롤 [Node] (state == '재고')
t.edges                                       # [Edge] 가까운 순(depth 1 부터) · genealogy_id 중복 없음
t.nodes() · t.rolls()                         # 출발점 포함, 지나간 노드(중복 없음) · 그중 롤
lineage.search("261003", limit=50)            # 번호 일부 → [Node] (F-TRC-03). 빈 검색어는 []
lineage.parents_of(node.ref) / lineage.children_of(node.ref)   # 한 단계 [Edge]
lineage.roll_state(roll_id)                   # '재고' | '소진' | '출하' (없는 롤 404)

Node(kind, id, no, label, state, job_no)      # label: 원재료 LOT | 인쇄 | 후가공 | 슬리팅 | 출하 LOT
                                              # state: 롤=재고/소진/출하 · 원재료 LOT=대기/합격/불합격 · 출하=등록/승인/취소
                                              # job_no: 롤·출하의 Job 번호 (원재료 LOT 은 None) · node.ref == (kind, id)
Edge(genealogy_id, parent: Node, child: Node, relation, qty, depth)
Trace(start: Node, direction, edges)          # direction: 'forward' | 'backward'

# ── 쓰기 (전부 conn.tx() 의 커서를 받는다 — 검증 실패는 422 HTTPException) ──
with conn.tx() as cur:                                            # 개발3 · 출하 롤 스캔 F-SHP-02
    gid = lineage.ship_roll(cur, shipment_id=sid, roll_id=node.id, by=user.login_id)
with conn.tx() as cur:                                            # 개발3 · 출하 취소 F-SHP-03
    n = lineage.unlink_shipment(cur, sid, by=user.login_id)       # 지운 계보 행 수. 그 뒤 같은 tx 에서 shipment.status='취소'
```

- **`ship_roll` 이 막는 것(전부 422, 사람이 읽을 문장)**: 없는 출하 LOT · 없는 롤 · 이미 출하된 롤(`이미 출하된 롤입니다`) · 소진된 롤 · `등록` 이 아닌 출하 · 다른 Job 의 롤(D-16) · 최신 검사가 `불합격` 인 롤(D-17, 미검사 롤은 통과).
  스캔값 → `roll_id` 는 호출자가 `resolve()` 로 바꾼다(`node.kind != lineage.ROLL` 이면 호출자가 422).
- **`unlink_shipment`**: 승인된 출하면 422. 계보 행만 지운다 — `shipment.status` 는 호출자(P8)가 같은 `tx` 에서 바꾼다. `by` 는 계보에 남지 않으므로(행이 지워진다) `audit.log_change` 로 남긴다.
- `ship_roll` · `unlink_shipment` 는 그 `shipment` 행을 `for share` 로, 롤 행을 `for no key update` 로 **잠근다**(쓰지는 않는다). 승인·취소가 동시에 들어와도 한쪽이 기다린다.
- `trace_*` 는 `with recursive` 조회 **하나**다. 깊이·분기 수를 가정하지 않는다. 결과를 저장하지 않는다. 없는 노드를 주면 404, 원재료 LOT 의 역방향·출하 LOT 의 정방향은 빈 `edges`.
- 취소된 출하 LOT 은 `resolve`/`search` 로 찾히지만(상태 `취소`) 계보 행이 없으므로 추적하면 `edges` 가 비어 있다.
- DB 지킴이 트리거가 올리는 `psycopg.errors.IntegrityError` 는 잡지 않는다 — `main.py` 가 422 로 바꾼다(`tests/test_dev2_lineage.py` 에서 확인).
- 개발2 가 쓰는 나머지: `lineage.link` · `assert_usable` · `make_print_roll` · `make_finishing_roll` · `slit_roll` — 시그니처는 계약 그대로.

검증: `uv run pytest -q tests/test_lineage_scenario.py tests/test_dev2_lineage.py`

### 1.2 출력 `app/printing.py` (2026-10-03 · 구현됨, 지금 불러도 된다)

시그니처는 `contracts/interfaces.md` §5 **그대로다.** 개발1(작업지시서)·개발3(COA)이 쓰는 것은 `barcode_svg` 하나다.

```python
from lcomfine.app import printing

svg = printing.barcode_svg(job_no)                         # Markup — Code 128 인라인 SVG. 템플릿에 {{ svg }} 로 넣는다
svg = printing.barcode_svg(coa_no, height=40, show_text=False)   # height = 막대 높이(px) · show_text = 막대 아래 번호 글자
```

- 라우터에서 만들어 컨텍스트로 넘긴다: `templating.render(request, "job/print.html", {"barcode": printing.barcode_svg(job["job_no"])}, …)` → 템플릿 `{{ barcode }}`(이미 `Markup` 이라 `|safe` 불필요).
- 바코드가 담는 값은 **넘긴 글자 그대로**다(앞뒤에 아무것도 안 붙인다) → 스캔값을 `lineage.resolve()` · `?no=` 에 그대로 넣으면 된다.
- 찍을 수 있는 글자는 ASCII 32~126(세트 B). 숫자가 4자리 이상 이어지면 세트 C 로 폭을 줄인다. **빈 값·한글 등은 `ValueError`** — 번호가 없는 문서(예: 미승인 출하의 COA)는 부르기 전에 걸러야 한다.
- 외부 CDN·이미지·라이브러리 0. SVG 폭은 `(모듈 수 + 좌우 여백 20) × 2px` — `R261003-0001` 은 330px. CSS 로 `svg.barcode { width: …; height: auto }` 처럼 늘려도 비율이 유지된다.
- 라벨 3종은 개발2 화면이 쓴다: `printing.material_lot_label(lot_no)` · `printing.roll_label(roll_no)` → `Label(kind, number, lines)` → `printing.render_label(label)`(라벨 한 장의 HTML 조각, 스타일 포함). 없는 번호는 422.
- 라벨 인쇄 화면 경로(링크 걸 때): 원재료 LOT `/mat/lots/{lot_no}/label` · 인쇄 롤 `/pop/roll-labels/{roll_no}/print` · 롤 `/rll/history/{roll_no}/label`.
- 스캔 진입 경로(바코드 값을 `?no=` 로): 원재료 LOT `/mat/lots?no=` · 롤 `/rll/history?no=`.

검증: `uv run pytest -q tests/test_dev2_printing.py` — 표 106심벌 구조 · 손계산 체크섬 · 번호 23종 SVG → 모듈 → 디코드(체크섬 검증) → 원래 번호 · **실제 디코더 `zbarimg` 로 6종 판독**(이 장비에 깔려 있어 실행됨. 없으면 그 6건만 skip).

### 1.3 개발2 엔드포인트의 폼 필드 · JSON 응답 (QA · 다른 개발이 부를 때)

전부 `application/x-www-form-urlencoded` 폼. 쓰기 성공은 JSON `{"ok": true, "message": …, …아래 값}`(브라우저는 303 + 알림). 번호는 스캔값 그대로(앞뒤 공백·소문자 허용).

| 기능 | API | 폼 필드 (`*` 필수) | 성공 응답에 더 담기는 값 |
|---|---|---|---|
| F-MAT-01 입고 등록 | `POST /mat/receipts` | `item_code*`(원재료 품목 코드) `received_qty*` `qty_unit` `supplier_name` `supplier_lot_no` `note` | `lot_no` `insp_status`(대기) `label_url` |
| F-MAT-03 입고검사 결과 | `POST /mat/inspections` | `lot_no*` `result*`(합격\|불합격) `note` | `lot_no` `insp_status` |
| F-MAT-07 자재 투입 스캔 | `POST /mat/inputs` | `work_id*` `lot_no*` `input_qty` `qty_unit` | `input_id` `work_id` `lot_no` |
| F-POP-01 작업 시작 | `POST /pop/work/start` | `job_no*` `lot_no`(생산 LOT) `equipment_code` `note` | `work_id` `job_no` |
| F-POP-02 작업 종료 | `POST /pop/work/{work_id}/finish` | `output_qty*` `qty_unit` `length_m` `width_mm` | `work_id` `roll_no` `label_url` |
| F-POP-04 정지 | `POST /pop/stops` | `work_id*` `stop_reason*` `stopped_at`(ISO, 비우면 지금) | `stop_id` `work_id` |
| F-POP-05 재개 | `POST /pop/stops/{stop_id}/resume` | — | `stop_id` `work_id` |
| F-POP-06 폐기 | `POST /pop/stops/scrap` | `work_id*` `scrap_qty*` `qty_unit` `defect_code` `reason` | `scrap_id` `work_id` |
| F-CLR-01 조색 기록 등록 | `POST /clr/records` | `job_no*` `color_name*` `seq_no`(비우면 다음 차수) `color_l` `color_a` `color_b` `ink_code` `note` | `id` `job_no` `color_name` `seq_no` |
| F-CLR-02 배합비 | `POST /clr/records/{id}/mix` | `component_name`·`ratio_pct` 반복(같은 순서) — 합 100 | `id` `rows` |
| F-CLR-03 수정 | `POST /clr/records/{id}` | `color_name*` `color_l` `color_a` `color_b` `note` | `id` |
| F-CLR-04 삭제 | `POST /clr/records/{id}/delete` | — | `id` |
| F-RLL-01 후가공 | `POST /rll/finishing` | `roll_no*`(부모 1개) `equipment_code` `length_m` `width_mm` | `roll_no` `relation`(후가공) `parents` `label_url` |
| F-RLL-02 splice | `POST /rll/finishing/splice` | `roll_no*` 반복(2개 이상 · 쉼표로 이어도 됨) `job_no`(부모 Job 이 다를 때 — **부모 롤들의 Job 중 하나 · `등록` 상태**, D-208) `equipment_code` `length_m` `width_mm` | `roll_no` `relation`(splice) `parents` `label_url` |
| F-RLL-04 슬리팅 | `POST /rll/slitting` | `roll_no*`(부모 1개) `count*` `widths_mm`(쉼표로 N개) `length_m` `equipment_code` | `parent` `rolls`[N] `label_urls`[N] |

웨이브 D 에서 더해진 422 (전부 `validation_error`, 항목 사유 포함) —
- **닫힌 Job (D-208)**: F-RLL-01 · F-RLL-02 · F-RLL-04 는 새 롤이 붙을 Job(부모 롤의 Job, splice 는 `job_no`)이 `취소`·`완료` 면 422 `<상태> 상태의 Job 에는 롤을 만들 수 없습니다`. splice 의 `job_no` 가 부모 롤들의 Job 이 아니면 422 `부모 롤의 Job 이 아닙니다 — …`. `lineage.make_finishing_roll` · `lineage.slit_roll` 을 직접 불러도 같다.
- **숫자 범위 (D-209)**: 수량·길이는 정수부 11자리(소수 3자리), 폭은 8자리(소수 2자리), 색상값은 5자리(소수 2자리), 차수·분할 수는 `integer` 범위. 넘으면 422 `<칸 이름>이(가) 너무 큽니다`. 소수 자릿수를 넘는 값은 반올림해 담는다.
- **롤 이력 (D-210)**: `GET /rll/history?no=<후가공·슬리팅 롤>` 의 「생산 실적」 은 계보를 거슬러 올라간 조상 인쇄 롤의 실적 표(`id="works"`)다.

조회 화면의 인자 — `/mat/receipts?date_from&date_to&item_code&supplier` · `/mat/inspections?no&insp_status` · `/mat/lots?no&lot&item_code&insp_status` ·
`/mat/inputs?work_id` · `/pop/work?no(Job 번호)&day&roll` · `/pop/stops?work_id` · `/pop/roll-labels?no` · `/clr/records?job_no&date_from&date_to&edit` ·
`/rll/finishing?add&rolls&made` · `/rll/slitting?no&parent` · `/rll/history?no`.
스캔 진입(`no` · `add`)에서 번호가 없으면 **JSON 은 422, 브라우저는 같은 화면을 422 로 다시 그린다**(D-201).

### 1.4 현장 화면 공용 조각 `templates/pop/_ui.html`

개발2 의 화면이 같이 쓰는 매크로다(`{% import "pop/_ui.html" as pui %}`). 다른 담당의 POP 화면(검사 결과 · 출하)이 같은 동작을 원하면 가져다 써도 된다 — 고치지는 않는다(D-22).
`pui.assets()`(결과 배너·상태 표시 스타일 + 알림이 떠 있어도 다음 스캔을 받는 스크립트) · `pui.result(flash, scan_error)`(방금 처리한 결과를 본문에 큰 글씨로) · `pui.state(낱말)` · `pui.keep(device)`.

## 2. 진행 (2026-10-03 · 실측)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| R1 `app/lineage.py` | 스텁 0 — 쓰기 7 · 읽기 7 함수 구현. 시그니처는 계약 그대로 | `grep -c NotImplementedError src/lcomfine/app/lineage.py` → 0 |
| R1 `app/printing.py` | 스텁 0 — Code 128(세트 B·C) 인라인 SVG · 라벨 3종 · `render_label` | `grep -c NotImplementedError src/lcomfine/app/printing.py` → 0 |
| G-06 설계도 §3 예시 (API) | `roll_genealogy` **10행** = 투입 3 · splice 2 · 슬리팅 3 · 출하 2. 10행 전부 `created_by='field'`(로그인한 현장 계정이 화면 API 로 만든 행). **출하 2행도 개발3 API**(`POST /shp/shipments` · `…/{shipment_no}/rolls`)로 만든다 | `uv run pytest -q tests/test_lineage_scenario.py` → 9 passed |
| G-07 양방향 추적 | 역방향: 출하 LOT → 원재료 LOT ①·② (화살표 9) · 정방향: LOT ① → 인쇄 ①② → 후가공 → 슬리팅 ①②③ → 출하 LOT (화살표 9, ③ 은 `재고`) · 임의 계보 3종(seed 11·23·47, 6단 이상 · 슬리팅/splice/후가공 섞음)에서 넓이 우선 탐색과 노드·화살표·깊이 일치 | 같은 파일의 `test_g07_*` 5건 |
| 소진·출하 롤 재사용 | 후가공·splice·슬리팅·출하 스캔 전부 422, 계보 행 수 그대로. 같은 롤을 두 작업이 동시에 쓰면 뒤쪽이 기다렸다가 422 | `tests/test_lineage_scenario.py::test_g07_consumed_and_shipped_rolls_cannot_be_reused` · `tests/test_dev2_lineage.py::test_same_roll_used_by_two_jobs_at_once_only_one_wins` |
| DB 트리거 → 422 | `lineage` 의 사전 검사를 끄고 출하된 롤을 슬리팅 → 응답 422, `fields[0].reason` 에 트리거 문장 `이미 출하된 롤은 다음 공정에 쓸 수 없다`, 롤·계보 0행 추가 | `tests/test_dev2_lineage.py::test_db_guard_integrity_error_surfaces_as_422` |
| 읽기 함수 쓰기 0 | `resolve`·`search`·`trace_*`·`parents_of`·`children_of`·`roll_state` 가 내보낸 SQL 12개가 전부 `select`/`with`, 쓰기 경로(`conn.x`·`conn.tx`) 호출 0, 추적 1회 = `with recursive` 1개 | `tests/test_dev2_lineage.py::test_read_functions_do_not_write` |
| 바코드 | 표 106심벌 구조 · 손계산 체크섬 2건 · 번호 23종 SVG → 모듈 → 디코드(체크섬 검증) → 원래 번호 · **실제 디코더 `zbarimg` 6종 판독** | `uv run pytest -q tests/test_dev2_printing.py` → 63 passed (skip 0 — 이 장비에 `zbarimg` 있음) |
| 바코드 (브라우저 화면) | 라벨 화면 캡처 PNG 4장을 `zbarimg` 로 판독 → 원재료 LOT 라벨 1 · 인쇄 롤 라벨 1 · 슬리팅 롤 라벨 3 · 후가공 롤 라벨 1 전부 `CODE-128:<번호>` | 포트 8022 헤드리스 브라우저 캡처 → `zbarimg -q <png>` (캡처는 저장소 밖 임시 폴더, 남기지 않음) |
| R2 화면 | 개발2 중메뉴 11 placeholder **0** (전체 0) · 개발2 라우트 29 = 기능 28 + 화면 GET 1(`/pop/roll-labels`) | `make check-routes` → `placeholder 잔여 0 건` · `PASS` |
| G-02 (개발2 몫) | 28기능 ↔ 라우트 **28/28** · 개발2 테스트 파일의 표식 **28/28** · 고아 라우트 0 (전체: 94/94 · 100/100) | `make check-trace` → G-02 PASS |
| pytest (개발2) | **152 passed** — printing 63 · mat 31 · pop 16 · clr 9 · rll 14 · lineage 10 · scenario 9 | `uv run pytest -q tests/test_dev2_*.py tests/test_lineage_scenario.py` |
| pytest (전체) | 369 passed (다른 담당 테스트 포함 — 내 마지막 실행 시점) | `uv run pytest -q` |
| 채널 유지 | `?device=pop` 으로 연 화면에서 쓰기 → 303 의 주소에 `device=pop` 이 붙어 POP 레이아웃 유지(로그인 때 채널을 고정했으면 세션이 유지한다) | `tests/test_dev2_pop.py::test_pop_channel_survives_the_redirect_after_a_write` |
| 권한 | 조회 역할의 쓰기 403: POP(관리자·품질) · MAT(관리자·품질의 입고/투입) · CLR(관리자·생산) · RLL(관리자·품질). 괄호 권한: 입고검사 결과 등록은 품질만(생산·현장·관리자 403). 미로그인 401 | 각 `tests/test_dev2_*.py` 의 `test_read_only_roles_cannot_write` · `test_inspection_result_is_quality_only` · `test_anonymous_is_401` |
| 접근 로그 | 쓰기 15기능마다 `sys_access_log` 구분 `변경` 1행(기능 ID · 대상) | 각 테스트의 `change_logs(...) == 1` |
| 시드 멱등 | `seed_dev2` 2회 — `material_lot` 4 → 4 (새로 0건), `sys_number_seq` 6 → 6, 그 밖의 D3~D6 테이블 0 → 0. (전체 행 수 합은 다른 담당이 같은 DB 에서 돌고 있어 그 사이에도 변했다 — 개발2 가 쓰는 테이블만 대조했다) | `uv run python -m lcomfine.db.seed_dev2` ×2 + 테이블별 `count(*)` |
| 뒷정리 | 테스트 뒤 `T2-` 접두 품목·Job 0행, `roll`·`roll_genealogy`·`work_result`·`material_input`·`color_record` 0행(시드 LOT 4건만 남음) | `psql -d lcomfine_db -Atc "select count(*) from item where item_code like 'T2-%'"` → 0 |
| 브라우저 한 바퀴 (개발2 화면) | 포트 8022 · POP 채널(`/login?device=pop`) · 현장 계정으로: 입고 2 → (입고검사는 API) → 작업지시서 스캔 → 작업 시작 → 투입 스캔(대기 LOT = 큰 글씨 26px 배너 + 22px 알림 → **알림을 닫지 않고 다음 스캔** → 알림이 닫히고 스캔칸이 값을 받음) → 작업 종료(인쇄 롤 + 라벨) → 롤 2개 스캔 → splice → 슬리팅 3분할(라벨 3장) → 롤 이력(부모 2 · 자식 3) → 조색 기록 + 배합비 → 정지. 콘솔 오류 0(422 응답 로그 제외) · 라벨 화면의 외부 자원 요청 0 · 작업 실적 화면은 폭 1024px 에서 가로 스크롤 없음 | `uv run uvicorn … --port 8022` + 헤드리스 브라우저. 끝나고 서버를 내렸고 전제 데이터는 지웠다. **QA3 의 G-22 를 대신하지 않는다** |
| 용어 · 범위 | 개발2 파일에 다른 사업 용어 0건 · PLC/비전/AI 0건 | `grep -rnE "솥\|인분\|검식\|절임\|숙성\|염도\|김치\|급식" <개발2 파일>` → 0 |

만든 것 — `app/lineage.py` · `app/printing.py` · `routers/{pop,mat,clr,rll}.py` · `templates/pop/{_ui,work,stops,roll_labels,label_print}.html` ·
`templates/mat/{receipts,inspections,lots,inputs}.html` · `templates/clr/records.html` · `templates/rll/{finishing,slitting,history}.html` ·
`db/seed_dev2.py` · `tests/test_dev2_{helpers,printing,lineage,mat,pop,clr,rll}.py` · `tests/test_lineage_scenario.py` · `decisions.md` D-201~D-207.

확인하지 못한 것 —
- **실물 스캐너·라벨 프린터**(D-04): 바코드는 `zbarimg`(소프트웨어 디코더)로만 읽어 봤다. 실제 스캐너의 판독 거리·인쇄 해상도에서의 판독은 확인하지 않았다.
- **G-06 의 Job**: 시나리오의 Job·품목·고객·설비는 전제 데이터로 SQL 로 넣는다(개발1 의 `POST /job/orders` 를 부르지 않는다). 계보 10행 자체는 전부 API 다.
- 브라우저 확인은 헤드리스 Chromium 한 종류, POP 채널만. 터치 조작(손가락)·모바일 폭은 보지 않았다.
- `make gate` 의 G-06·G-07·G-08·G-14 는 `미검증` 으로 나온다 — 판정기(`check_data.py` · `check_security.py`)가 아직 없다(QA2·QA3).

## 2-D. 웨이브 D — QA 결함 수정 (2026-10-03 · 실측)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| DEF-QA2-001 롤 이력의 생산 실적 | 후가공·슬리팅 롤의 롤 이력에 **조상 인쇄 롤의 실적 표**(`lineage.trace_backward` → 인쇄 롤 → `work_result`). QA 검사 행 「후가공·슬리팅 롤 번호 → 그 롤의 생산 실적」 **PASS** — 슬리팅 롤 2/2 · 후가공 롤 2/2 (고치기 전 0/2 · 0/2) | `uv run python tools/check_data.py --only G-08` · `tests/test_qa2_lineage.py::test_g08_roll_history_shows_production_result_for_finishing_and_slit_rolls` · `tests/test_dev2_rll.py::test_history_of_finishing_and_slit_rolls_shows_the_ancestor_print_work_results` |
| DEF-QA2-002 splice 의 Job | `job_no` = 부모 롤들의 Job 중 하나 · `등록` 상태(D-208). 취소된 Job 지정 → **422 · 취소 Job 의 롤 0개**, 부모와 무관한 `등록` Job 지정 → 422, 부모의 Job 이지만 `완료` → 422. 422 뒤 롤 수·계보 행 수·부모 상태 그대로. QA 검사 행 「취소된 Job 에 롤이 생기지 않는다」 **PASS** | 같은 검사기 · `…::test_g08_splice_cannot_put_a_roll_under_a_cancelled_job` · `tests/test_dev2_rll.py::test_splice_job_must_be_an_open_job_of_the_parents` |
| 같은 구멍 — 1:1 후가공 · 슬리팅 | **있었다.** `완료` Job 의 재고 롤로 후가공·슬리팅 → 판정을 끈 상태(고치기 전의 동작)에서 200 · 200, 고친 뒤 422 · 422. `lineage.make_finishing_roll` · `slit_roll` 안에서 막는다(Job 행 `for share`) | `tests/test_dev2_rll.py::test_finishing_and_slitting_are_blocked_for_closed_jobs` (`완료` · `취소` 둘 다, 다시 `등록` 이면 200) |
| DEF-QA1-002 숫자 범위 | mat(입고 수량 · 투입량) · pop(실적 수량 · 길이 · 폭 · 폐기 수량) · clr(색상값 · 차수) · rll(길이 · 폭 · 슬리팅 폭 · 분할 수) 전부 **내 입력 도우미에서** 422 `<칸>이(가) 너무 큽니다`(공용 `DataError` 처리에 닿기 전). 상한 값(`99999999999.999` · `99999999.99` · `99999.99` · `2147483647`)은 담긴다 | `uv run pytest -q tests/test_qa1_errors.py -k out_of_range` → mat · pop · clr · rll 통과 · 각 `tests/test_dev2_*.py` 의 `…out_of_range…`/검증 테스트 |
| G-08 | **PASS — 검사 9 · 실패 0** (고치기 전 9 중 2 FAIL) | `uv run python tools/check_data.py --only G-08` |
| G-05 · G-06 · G-07 회귀 | PASS 9/9 · 6/6 · 8/8 — 임의 계보 5개 · 추적 313건 불일치 0 · Job 간 splice 3회 그대로 통과 · 막기 28/28 | `uv run python tools/check_data.py --only G-05,G-06,G-07` |
| pytest (개발2) | **160 passed** — printing 63 · mat 34 · pop 17 · clr 9 · rll 18 · lineage 10 · scenario 9 (웨이브 B 의 152 + 새 8) | `uv run pytest -q tests/test_dev2_*.py tests/test_lineage_scenario.py` |
| pytest (QA2) | `tests/test_qa2_*.py` 63건 중 62 통과 — 남은 1건 `test_g04_schema_checker_passes` 는 아키텍트가 작업 중인 `sys_user` 컬럼 2개(`session_epoch` · `revoked_sessions`)가 계약 렌더본에 아직 없어서다(내 변경과 무관 — 내 수정 직전 실행에서는 통과) | `uv run pytest -q tests/test_qa2_*.py` · `uv run python tools/check_schema.py` |
| 뒷정리 | `T2-` 품목 0 · Job 0 (테스트·임시 확인 뒤) | `psql -h /tmp -d lcomfine_db -Atc "select count(*) from item where item_code like 'T2-%'"` |

고친 파일 — `app/lineage.py`(`_assert_job_open` · `make_finishing_roll` · `slit_roll`) · `routers/pop.py`(`decimal_of` · `int_of` + 컬럼 범위 상수) · `routers/{mat,clr,rll}.py` ·
`templates/rll/{history,finishing,slitting}.html` · `tests/test_dev2_{rll,pop,mat,clr}.py` · `decisions.md` D-208~D-210. `templates/pop/_ui.html` 은 건드리지 않았다.

확인하지 못한 것 (웨이브 D) —
- 브라우저로 열어 보지 않았다. 롤 이력의 실적 표 · 후가공 화면의 Job 선택칸 · 슬리팅 화면의 닫힌 Job 안내는 TestClient 의 HTML 로만 확인했다(POP 폭에서의 표 넘침 여부 미확인).
- 전체 `uv run pytest -q` · `make gate` · `check_security.py` · `check_screens.py` 는 돌리지 않았다(병렬 작업 규칙). 돌린 것은 위 표의 명령과 `tests/test_qa1_{functions,errors}.py` · `tests/test_dev3_*.py` · `tests/test_arch_*.py` · `tests/test_dev1_job.py`(456 passed)다.
- Job 행 잠금(`for share`)이 실제 동시 요청(마감과 슬리팅이 같은 순간)에서 기다리는지는 재지 않았다 — 순차 요청만 쟀다.

## 2-E. 웨이브 D 3차 — DEF-QA2-004 (작업 시작 × Job 취소·마감 경합) · 2026-10-03 실측 (수정 담당이 혼자 돌며 개발2 파일을 고침)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 작업 시작의 잠금 (D-211) | `routers/pop.py` `assert_job_open` — 실적 INSERT 와 같은 트랜잭션에서 Job 행 `for share` + 상태 재확인. 취소·마감(`for update`)과 겹치면 둘 중 하나만 200 | `uv run pytest -q tests/test_dev2_pop.py -k "in_flight or racing"` → 6 passed · QA `tests/test_qa2_lineage.py::test_g08_work_start_racing_…` 2 passed |
| 반복 | QA 테스트(40회 × 2) 30번 + QA·개발 경합 테스트(130쌍) 25번 = 55번 전부 통과(경합 5,650쌍) · 실서버 8021 에 400쌍(취소·마감을 0~8ms 늦춘 것 포함) — 둘 다 200 인 것 0 · 5xx 0 · 두 순서 다 나옴(시작이 먼저 77·76 / 취소·마감이 먼저 23·24) | 반복 셸 루프 · 스크래치 스크립트(실서버) · 서버는 내렸다 |
| 교착 | `pg_stat_database.deadlocks` 0 → 0 (전 과정) · 503 0 | `psql -Atc "select deadlocks from pg_stat_database where datname='lcomfine_db'"` |
| 같은 꼴 ⓑ 후가공·splice·슬리팅 × 마감 | 창 없음(D-208 의 `for share` 가 롤을 만드는 트랜잭션 안) — 마감을 잠금 직후에 세워 두고 보낸 롤 등록 3종이 기다렸다가 422, 롤·계보·부모 상태 그대로 | `tests/test_dev2_rll.py::test_finishing_and_slitting_wait_for_a_close_in_flight_and_then_refuse` |
| 같은 꼴 ⓓ 자재 투입·작업 종료 × 취소 | 창 없음 — 둘 다 커밋된 실적이 전제이고 실적 1건이라도 있는 Job 의 취소는 잠근 뒤 세어 422(D-107 · `test_dev1_job.py -k cancel`). 코드를 읽어 판단, 별도 경합 테스트는 두지 않았다 | 코드 읽기 |
| 변이 | `pop.assert_job_open` 을 프로세스 안에서 빈 함수로 바꾸면 QA 2건 + 개발 6건 실패 | 스크래치 변이 스크립트 (파일은 그대로) |
| 배합비 사유 (D-209 보강) | 422 사유에 「소수 셋째 자리까지 저장한다(넘는 자리는 반올림)」 + 반올림된 행마다 「입력 → 저장되는 값」 · 입력칸 `step="0.001"` · 판정 규칙 그대로 | `uv run pytest -q tests/test_dev2_clr.py` → 9 passed |
| 테스트 도우미 | `test_dev2_helpers.pause_after` — 실제 함수의 첫 호출이 끝난 직후(잠금을 쥔 채) 세워 두는 도구. 개발1 테스트도 가져다 쓴다(한 벌만) | — |

## 3. 요청 (스키마 · 계약 · 공용 파일)

스키마 변경 요청은 없다. 아래는 아키텍트 소유 파일에 대한 것이다 — 전부 우회해 두었고 막힌 것은 없다.

| # | 대상 (소유) | 요청 | 지금의 우회 |
|---|---|---|---|
| 1 | `static/app.js` (아키텍트) | 알림 팝업을 「확인」 버튼으로 닫으면 **스캔칸으로 포커스가 돌아오지 않는다**. `closePopup()` → `focusScan()` 이 "지금 포커스가 BUTTON 이면 빼앗지 않는다" 조건에 걸린다(방금 누른 「확인」 버튼이 아직 `activeElement`). 브라우저에서 재현: 스캔 성공 → 「확인」 클릭 → `document.activeElement !== [data-scan]`. 또 팝업이 떠 있는 동안 스캐너가 다음 번호를 쏘면 글자는 버려지고 Enter 가 팝업만 닫는다. → `closePopup` 에서 무조건 `scan.focus()`, 팝업이 열린 채 글자 키가 오면 닫고 스캔칸으로 넘기기를 공용으로 넣어 달라 | `templates/pop/_ui.html` 의 `pui.assets()` 스크립트가 개발2 화면에서 두 가지를 다 처리한다(브라우저로 확인). 개발3 의 POP 화면(검사 결과·출하)에는 적용되지 않는다 |
| 2 | `main.py` · `contracts/api-contract.md` §2 (아키텍트) | 브라우저 **GET** 의 422 는 오류 화면(`_error.html`)으로 간다 — 스캔으로 여는 GET 화면(`?no=`)에서는 스캔칸이 사라져 "다음 스캔을 막지 않는다" 와 어긋난다. 계약에 「스캔 진입 GET 의 422 는 그 화면을 422 로 다시 그린다」를 적어 달라(D-201) | 개발2 화면은 `routers/pop.py` 의 `scan_failure()` 로 그렇게 한다. JSON 응답은 계약 그대로 422 |
| 3 | `templates/home/_macros.html` (아키텍트) | `ui.scan_box` 에 보이는 입력칸을 더 넣을 수 없다(hidden 만). 자재 투입은 스캔칸 옆에 「투입량」이 필요하다 → `{% call %}` 슬롯이나 `extra` 인자 | `mat/inputs.html` 한 곳만 같은 모양(`.scan-box` + `data-scan autofocus`)의 폼을 직접 썼다 |
| 4 | `static/style.css` (아키텍트) | 개발2 화면이 쓰는 스타일(결과 배너 `.scan-result` · 상태 표시 `.st` · 작업 카드 `.work-card` · `.form-actions` 등)이 `pop/_ui.html` 안에 인라인으로 있다. 공용으로 올릴지 판단해 달라(개발1 도 `.form-actions` 를 템플릿 안에 따로 두었다) | 인라인 `<style>` |
| 5 | `contracts/interfaces.md` §4·§5 (아키텍트) | 코드에 더한 것을 계약에 반영: `Node.ref` · `Trace.rolls()` · 상수(`lineage.PRINT_ROLL`/`FINISHING_ROLL`/`SLIT_ROLL` · `FORWARD`/`BACKWARD`) · `printing.code128_symbols(value)` · `printing.code128_modules(value)` · `Edge.depth` = 가장 가까운 길 · `link` 이 출하 판정(다른 Job · 불합격 · 등록 아님)을 한다는 것 · 없는 노드의 `trace_*`/`roll_state` 는 404 | 이 파일 §1 에 공표 |
| 6 | `contracts/function-list.md` (아키텍트) | 계약 문장에 없어 더한 규칙을 확인: F-POP-02 「정지 중인 실적은 재개 뒤 종료」 · F-MAT-07 「진행 상태만(정지 중 422)」 · F-RLL-02 「부모 Job 이 다르면 `job_no`」 · F-MAT-03 「같은 판정 재등록은 허용」 (D-202~D-204) | `decisions.md` 에 `가설` 로 올렸다 |
| 7 | 개발3 `routers/shp.py` · `qua.py` (참고) | `/shp/shipments?no=` 등 스캔 진입 GET 에서 없는 번호는 브라우저 오류 화면으로 간다(요청 2 와 같은 문제). 고치려면 `routers/pop.py` 의 `scan_failure` 와 `pop/_ui.html` 을 가져다 쓸 수 있다 | — |
| 8 | `contracts/function-list.md` (아키텍트 · 웨이브 D) | 계약 문장 반영: **F-RLL-02** 「`job_no` 는 부모 롤들의 Job 중 하나여야 하고, 취소·완료 Job 이면 422. 부모와 무관한 Job 지정도 422」(확정) · **F-RLL-01 · F-RLL-04** 「부모 롤의 Job 이 취소·완료면 422」(가설, D-208) · **F-RLL-06** 「후가공·슬리팅 롤은 계보를 거슬러 올라간 조상 인쇄 롤의 실적을 함께 보인다」(D-210 — `db-schema.md` §6 의 책임 화면) · 숫자 입력 범위(D-209)는 `api-contract.md` 의 422 표에 한 줄 | 코드·테스트는 이미 그렇게 돈다. `decisions.md` D-208~D-210 |
| 9 | `contracts/interfaces.md` §4 (아키텍트) | `make_finishing_roll` · `slit_roll` 의 422 에 「부모와 무관한 `job_id` · 롤이 붙을 Job 이 `등록` 이 아님」 추가, 상수 `lineage.JOB_OPEN` | 이 파일 §1.3 에 공표 |
| 10 | `routers/job.py` F-JOB-02 (개발1 · 아키텍트 판단) | 작업 실적이 `진행`·`정지` 인 Job 을 `완료` 로 마감할 수 있다 → 그 실적을 종료하면(F-POP-02) 마감된 Job 에 인쇄 롤이 생긴다(실측 200). F-POP-02 쪽에서 막으면 열린 실적을 닫을 길이 없다 — 「열린 실적이 있는 Job 은 마감 422」 가 맞아 보인다 | 막지 않았다(D-208 끝 줄) |
