# 공용 인터페이스 계약 (아키텍트 · 2026-10-03 · 웨이브 D 에서 구현에 맞춰 갱신)

> 7명이 **동시에** 일하기 위해 접점을 먼저 못 박는다. 개발 3명·QA 3명은 이대로 호출한다.
> §1~§2·§8 은 아키텍트가, §3~§7 의 공용 모듈은 각 소유자가 **구현했다**(웨이브 B). 웨이브 D 에서 개발이 더한 것(D-101 · D-205 · D-206 · D-301 · D-302)을 이 문서에 옮겼다.
> 이 문서와 실제 코드가 다르면 **코드가 맞다** — 발견자가 이 문서를 고치고 `progress-*.md` 에 적는다.
> 시그니처를 바꿔야 하면 소유자가 `progress-devN.md` §1 에 먼저 공표한다.

| 모듈 | 소유자 | 상태 | 쓰는 사람 |
|---|---|---|---|
| `db.conn` · `app.nav` · `app.contracts` · `app.rbac` · `app.auth` · `app.templating` · `app.util.*` | 아키텍트 | 구현됨 | 전원 |
| `app.numbering` | **개발1** | 구현됨 | 개발1·2·3 |
| `app.lineage` | **개발2** | 구현됨 | 개발2·3 |
| `app.printing` | **개발2** | 구현됨 | 개발1(작업지시서 바코드)·2·3(COA 바코드) |
| `app.erp` | **개발3** | 구현됨(전부 501) | — |
| `app.stats` | **개발3** | 구현됨 | 개발3 · QA2(대조) |

## 1. DB — `lcomfine.db.conn`

```python
q(sql, params=None) -> list[dict]   # SELECT. 항상 dict 리스트
q1(sql, params=None) -> dict|None   # 첫 행
x(sql, params=None) -> int          # INSERT/UPDATE/DELETE 한 문장. rowcount
tx()                                # 컨텍스트 매니저 — with conn.tx() as cur: … 여러 문장을 한 트랜잭션으로
```
- DSN 은 `LCOMFINE_PG_DSN`(기본 `postgresql:///lcomfine_db`). **DB 연결 실패는 삼키지 않는다** → `DbUnavailable` → 503 `서비스 일시 중단`.
- 롤 생성 + 계보 행, 출하 승인 + COA 채번처럼 **같이 성공하거나 같이 실패해야 하는 것은 `tx()` 하나**에 넣는다. `numbering.next(..., cur=cur)` · `lineage.*(cur, …)` 가 그 커서를 받는다.
- 제약 위반(`psycopg.errors.IntegrityError`)과 DB 가 담을 수 없는 입력값(`psycopg.DataError` — NUL 글자 · 자릿수 초과)은 잡지 않아도 `main.py` 가 422 로 바꾼다. 다만 사람이 읽을 문장을 주려면 먼저 검사해 `http.validation_error` 를 낸다.

## 2. 메뉴 · 계약 · 권한 · 렌더 (아키텍트 구현)

```python
# app.nav — 메뉴·경로의 원본
nav.GROUPS(4) · nav.MENUS(12) · nav.SCREENS(32) · nav.COMMON(3)
nav.path_of("BAS-01") -> "/bas/items"          # 경로를 문자열로 다시 적지 않는다
nav.by_id("BAS-01") -> Screen(screen_id, name, menu_code, menu, group, module, path, owner, channels)
nav.menu("BAS") -> Menu(code, name, group, fn_count, module, owner, channels, screens)

# app.contracts — function-list.md 의 100줄
contracts.function("F-BAS-01") -> Function(id, menu, screen_name, name, kind, process, stores, tables, channels, roles, scope, api, owner, text)
contracts.functions_of("BAS-01") -> list[Function]

# app.rbac — 권한 표 48칸 (DB)
rbac.require_screen("BAS-01")   # 화면 GET 의존성. 그 대메뉴 칸이 없음이면 403, 미로그인 401
rbac.require_fn("F-BAS-01")     # 기능 의존성. 쓰기 기능이면 쓰기 판정(범위 포함), 읽기 기능이면 조회 판정
user.can("F-BAS-01") -> bool    # 템플릿에서 버튼 활성/비활성
user.login_id · user.user_name · user.role_code · user.role_name   # 쿠키가 아니라 **요청마다 DB 에서 읽은 지금 값** (D-26)
rbac.current_user(request) -> User | None   # 세션이 없거나 무효(중지·잠금 · 로그아웃한 세션 · 상태/비밀번호가 바뀌기 전의 세션)면 None → 401
rbac.invalidate()               # sys_permission · sys_role 을 바꾼 뒤 (F-SYS-06)
rbac.matrix() · rbac.roles() · rbac.cell(role_code, menu_code) -> Cell(level, scopes)

# app.templating
templating.render(request, "bas/items.html", ctx, screen_id="BAS-01") -> HTMLResponse
```

라우터 한 개의 모양 (`app/routers/<모듈>.py` — `router = APIRouter()` 만 있으면 `main.py` 가 자동 include):

```python
@router.get(nav.path_of("BAS-01"), response_class=HTMLResponse)          # F-BAS-04 품목 조회 = 화면 GET
def items(request: Request, user: rbac.User = rbac.require_fn("F-BAS-04")):
    rows = conn.q("select … from item order by item_code")
    return templating.render(request, "bas/items.html", {"rows": rows}, screen_id="BAS-01")

@router.post(nav.path_of("BAS-01"))                                       # F-BAS-01 품목 등록
def create_item(request: Request, item_code: str = Form(...), …, user: rbac.User = rbac.require_fn("F-BAS-01")):
    if conn.q1("select 1 from item where item_code = %s", (item_code,)):
        raise http.validation_error("이미 있는 품목 코드입니다", fields=[{"name": "품목 코드", "reason": item_code}])
    conn.x("insert into item (…, created_by) values (…, %s)", (…, user.login_id))
    audit.log_change(request, user, "F-BAS-01", f"item:{item_code}")
    return http.saved(request, "품목을 등록했습니다")
```

- 화면 GET 을 등록하면 그 경로의 placeholder 는 저절로 빠진다. 기능의 `API` 열과 **메서드·경로가 글자 그대로** 같아야 `check-trace` 가 그 기능을 "이어졌다" 고 센다.
- 화면 GET 이 조회 기능이 아닌 중메뉴(롤 라벨 `POP-03` · 출하 승인 `SHP-02` · 집계 `STA-01`)는 `rbac.require_screen(화면 ID)` 로 연다.
- `templating.render` 가 헤더·좌측 메뉴·우측 계약 패널·채널 레이아웃을 채우고 **화면 조회 로그**를 남긴다. 템플릿은 `{% extends "base.html" %}` 뒤 `search` · `grid` · `actions` 블록(또는 `body` 통째)을 채운다.
- 공용 매크로 `{% import "home/_macros.html" as ui %}` — `ui.grid` · `ui.scan_box` · `ui.field` · `ui.select` · `ui.write_button` · `ui.print_button` · `ui.undecided` · `ui.notes`. 같은 것을 각자 다시 만들지 않는다.
- `ui.scan_box(action, name='barcode', label='바코드 스캔', hidden={}, method='post', placeholder='', button='처리')` — 스캔칸 옆에 **보이는 입력칸**(예: 투입량)이 필요하면 call 블록으로 넣는다:
  `{% call ui.scan_box(path, name='lot_no', label='원재료 LOT 번호') %}<label>투입량<input type="number" name="input_qty" step="any"></label>{% endcall %}`. 화면에 `data-scan` 은 하나만.
  알림이 떠 있어도 스캔을 받고 닫으면 스캔칸으로 포커스가 돌아오는 것은 `static/app.js` 가 한다 — 템플릿에 스크립트를 따로 넣지 않는다(`api-contract.md` §2).
- 스캔 진입 GET(`?no=` 등)에서 없는 번호는 **그 화면을 422 로 다시 그린다**(`templating.render(…, status_code=422)` — 스캔칸 유지, D-201 · `api-contract.md` §2). JSON 요청이면 `http.validation_error` 를 그대로 올린다.

## 3. 채번 — `app.numbering` (개발1)

```python
KINDS = ("JOB", "JOB_LOT", "MAT_LOT", "ROLL", "SHIPMENT", "COA")
numbering.next(kind, *, cur=None, at=None) -> str   # 발번 (카운터 +1). cur 를 주면 그 트랜잭션 안에서
numbering.peek(kind, *, at=None) -> str             # 발번하지 않고 다음 번호만
numbering.rule(kind) -> dict | None                 # sys_number_rule 행. 없으면 None → 화면은 `미확정 (D-05)`
```
- 형식은 `sys_number_rule`(접두 · 날짜 형식 · 자릿수) 행, 카운터는 `sys_number_seq`. **번호를 다른 곳에서 조립하지 않는다**(G-08).
- **조립식 (D-101)**: `번호 = prefix + to_char(기준 시각, date_format) + 일련번호(seq_digits 자리, 0 채움)`. 구분 기호는 따로 두지 않고 `prefix`·`date_format` 안에 글자로 넣는다(예 `YYMMDD-`).
  카운터 범위(`sys_number_seq.seq_scope`) = **날짜 부분의 값** — 날짜 부분이 바뀌면 1 부터, 날짜 형식이 비면 통산. 일련번호가 자릿수를 넘으면 자르지 않고 늘린다.
  기준 시각은 `at`(기본 지금), 날짜 부분은 DB 의 `to_char` 가 만든다.
- 동시에 불러도 같은 번호가 두 번 나오지 않는다 — 카운터 행을 잠그고 올린다. `cur=` 로 받은 트랜잭션이 롤백되면 발번도 같이 되돌아간다(번호가 비지 않는다).
- 형식 행이 없는 종류를 `next`/`peek` 하면 `RuntimeError`(500) — 번호를 지어내지 않는다. `rule(kind)` 가 `None` 이면 화면은 `미확정 (D-05)`.
- 가설 형식과 `sys_number_rule` 시드 6행(`J`·`L`·`M`·`R`·`S`·`C` + `YYMMDD-` + 3자리, 롤만 4자리)은 `progress-dev1.md` §1 · `db/seed_dev1.py`(D-101). 번호는 바코드로 찍히므로 영문 대문자·숫자·`-` 만 쓴다.
  **다른 모듈은 번호의 첫 글자로 종류를 판정하지 않는다** — `lineage.resolve` 가 테이블에서 찾는다.

| 종류 | 어디에 | 발번하는 기능 |
|---|---|---|
| `JOB` | `job.job_no` | F-JOB-01 |
| `JOB_LOT` | `job_lot.lot_no` | F-JOB-06 |
| `MAT_LOT` | `material_lot.lot_no` | F-MAT-01 |
| `ROLL` | `roll.roll_no` | F-POP-02 · F-RLL-01·02·04 (`lineage` 안에서) |
| `SHIPMENT` | `shipment.shipment_no` | F-SHP-01 |
| `COA` | `shipment.coa_no` | F-SHP-05 |

## 4. 계보 — `app.lineage` (개발2)

노드는 `(종류, id)` — 종류는 `lineage.MATERIAL_LOT` · `lineage.ROLL` · `lineage.SHIPMENT`. **`roll_genealogy` 에 쓰는 곳은 이 모듈뿐이다.**
상수 — 관계 `lineage.INPUT`(투입) · `FINISHING`(후가공) · `SPLICE` · `SLITTING`(슬리팅) · `SHIPPING`(출하) / 공정 구분 `PRINT_ROLL` · `FINISHING_ROLL` · `SLIT_ROLL` /
롤 상태 `IN_STOCK`(재고) · `CONSUMED`(소진) · `SHIPPED`(출하) / 방향 `FORWARD` · `BACKWARD` (D-205).

```python
# 쓰기 — 전부 conn.tx() 의 커서를 받는다. 검증 실패는 422
lineage.link(cur, parent, child, relation, *, by, qty=None) -> int            # 화살표 한 줄. genealogy_id
lineage.assert_usable(cur, parents) -> None                                    # 롤은 재고, 원재료 LOT 은 합격이어야 한다
lineage.make_print_roll(cur, *, work_result_id, by, length_m=None, width_mm=None) -> dict          # F-POP-02
lineage.make_finishing_roll(cur, *, parent_roll_ids, by, job_id=None, equipment_id=None, length_m=None, width_mm=None) -> dict   # F-RLL-01·02
lineage.slit_roll(cur, *, parent_roll_id, count, by, equipment_id=None, widths_mm=None, length_m=None) -> list[dict]             # F-RLL-04
lineage.ship_roll(cur, *, shipment_id, roll_id, by) -> int                     # F-SHP-02 (개발3 이 부른다)
lineage.unlink_shipment(cur, shipment_id, *, by) -> int                        # F-SHP-03 (개발3 이 부른다)

# 읽기 — 어떤 테이블에도 쓰지 않는다
lineage.resolve(no) -> Node | None            # 번호(스캔값) → 원재료 LOT · 롤 · 출하 LOT
lineage.search(text, limit=50) -> list[Node]  # 번호 일부 검색 (F-TRC-03)
lineage.roll_state(roll_id) -> str            # 재고 | 소진 | 출하
lineage.parents_of(node) / children_of(node) -> list[Edge]     # 한 단계 (F-RLL-06)
lineage.trace_backward(node) -> Trace         # 출하 LOT·롤 → 원재료 LOT (F-TRC-02)
lineage.trace_forward(node) -> Trace          # 원재료 LOT·롤 → 출하 LOT (F-TRC-01)

Node(kind, id, no, label, state, job_no) · .ref == (kind, id)      # label: 원재료 LOT | 인쇄 | 후가공 | 슬리팅 | 출하 LOT
Edge(genealogy_id, parent: Node, child: Node, relation, qty, depth)   # depth: 출발점에서 그 화살표까지의 **가장 가까운 길**(1부터)
Trace(start: Node, direction, edges) · .nodes() · .rolls() · .material_lots() · .shipments() · .stock_rolls()
```
- `relation` 은 `투입` · `후가공` · `splice` · `슬리팅` · `출하`. 후가공 롤의 부모가 2개 이상이면 전부 `splice`.
- `trace_*` 는 **재귀 조회 하나**다(`db-schema.md` §3.3). 깊이·분기 수를 가정하지 않고, 경로를 다른 곳에 저장하지 않는다.
- `Trace.edges` 는 화살표 중복 없이(같은 행이 두 길로 닿아도 한 번), 출발점에서 가까운 순서로.
- 422 로 막아야 하는 것: 자기 자신을 부모로 · 순환 · 같은 화살표 중복 · 이미 출하된 롤 재출하 · 소진된 롤 재사용 · 불합격/검사 대기 LOT 투입 · 다른 Job 의 롤 출하 · 최신 검사가 불합격인 롤 출하.
- 출하의 판정(다른 Job · 최신 검사 불합격 · `등록` 이 아닌 출하)은 **`link` 안에** 있다 — `ship_roll` 은 잠금 + `assert_usable` + `link`. `link(…, '출하')` 를 직접 불러도 같은 규칙이다(D-205).
- `make_finishing_roll` 의 `job_id`(splice 의 `job_no`)는 **부모 롤의 Job 중 하나**여야 하고 취소·완료된 Job 이면 422 다(F-RLL-02 · D-208). 후가공·슬리팅 롤이 붙을 Job 이 `등록` 이 아니면 `make_finishing_roll` · `slit_roll` 이 422 를 낸다(D-208).
- `resolve(no)` 는 앞뒤 공백을 떼고, 소문자로 들어오면 대문자로도 찾는다(스캔 화면마다 같은 번호가 같게 풀려야 한다 — 스캔값 조회는 이 함수로 한다, D-201). 취소된 출하 LOT 도 찾힌다(상태 `취소`).
- 없는 노드의 `trace_*` · `roll_state` 는 404 다 — 스캔값은 호출자가 `resolve` 로 먼저 찾고 `None` 이면 422 를 낸다.
- 동시성: `assert_usable` 이 부모 롤 행을 `for no key update` 로, `ship_roll`·`unlink_shipment` 가 그 출하 행을 `for share` 로 잠근다. 잠금은 쓰기가 아니다(G-05).
- `tests/test_lineage_scenario.py` — 설계도 §3 예시를 API 로 만들어 `roll_genealogy` 10행(G-06).

## 5. 출력 — `app.printing` (개발2)

```python
printing.barcode_svg(value, *, height=48, show_text=True) -> Markup   # Code 128 인라인 SVG. 작업지시서·COA 도 쓴다
printing.code128_symbols(value) -> list[int]                          # 심벌 값(시작 + 데이터 + 체크섬). 세트 B, 숫자가 4자리 이상 이어지면 세트 C
printing.code128_modules(value) -> str                                # 막대 `1` · 공백 `0` 의 모듈 문자열(시작~정지, 좌우 여백 제외) — 디코더로 검증할 때 쓴다
printing.material_lot_label(lot_no) -> Label                          # F-MAT-06
printing.roll_label(roll_no) -> Label                                 # 인쇄 롤이면 `인쇄 롤 라벨`(F-POP-08), 아니면 `롤 라벨`(F-RLL-07)
printing.render_label(label) -> Markup                                # 라벨 한 장의 인쇄용 HTML — 출력 방식이 바뀌면 여기만
Label(kind, number, lines=[(항목명, 값), …])
```
- 프린터 규격 미정(D-04) → 지금의 어댑터는 브라우저 인쇄(`ui.print_button`). 외부 CDN·이미지 0.
- 바코드가 담는 값은 번호 글자 그대로다. 그 값을 스캔칸에 넣으면 그 LOT/롤이 열려야 한다(G-14). 빈 값·세트 B 밖의 글자는 `ValueError` — 조용히 지우거나 바꾸지 않는다.
- 심벌은 Code 128, 모듈 폭 2px · 좌우 여백 10 모듈(D-206). COA 의 바코드 값은 COA 번호가 아니라 **출하 LOT 번호**다(D-305).

## 6. ERP — `app.erp` (개발3)

```python
erp.adapter() -> ErpAdapter          # 지금은 UndecidedErp
ErpAdapter.status() · .send(kind, payload) · .receive(kind)   # 전부 501 `ERP 연계 미확정 (D-02)`
```
`/erp/{kind}`(GET·POST, 로그인 필요)가 이 어댑터를 부른다(`main.py`). 조용한 폴백 0(G-16).

## 7. 집계 — `app.stats` (개발3) · 산식 (D-25)

```python
stats.production(date_from, date_to, item_id=None) -> list[dict]
stats.quality(date_from, date_to, item_id=None) -> list[dict]
stats.delivery(date_from, date_to, item_id=None, *, today=None) -> list[dict]     # today: 「오늘」 을 고정해 다시 계산할 때 (기본 = 실행한 날)
stats.defect_by_type(date_from, date_to, item_id=None) -> list[dict]
stats.defect_rolls(date_from, date_to, defect_code=None, item_id=None) -> list[dict]   # F-QUA-06 — 집계와 같은 조건의 불량 행 내역. 행 수 = defect_count 합
stats.totals(kind, rows) -> dict | None   # kind: production | quality | delivery. 품목별 행을 더한 한 줄 — SQL 을 다시 돌리지 않는다. 행이 없으면 None
stats.period(date_from, date_to, *, today=None) -> (date, date)   # 화면의 기간 인자. 둘 다 비우면 이번 달 1일 ~ 오늘, 시작 > 끝이면 422 (D-302)
stats.board(today=None) -> dict      # {today, production, quality, delivery, totals} — 위 함수를 (today, today) 로 그대로 부른다 (D-302)
```
기간은 양 끝 날짜를 포함한다. 품목은 `job.item_id`. **어떤 테이블에도 쓰지 않는다.** QA2 는 아래 문장만 보고 SQL 을 따로 짠다(G-10).
「날짜가 기간 안」 = `timestamptz::date between date_from and date_to` — 날짜는 DB 세션 시간대 기준이다(D-301).

| 함수 | 대상 행 | 품목별로 내는 값 |
|---|---|---|
| `production` | `work_result` 중 `status='완료'` 이고 `ended_at` 의 날짜가 기간 안 (D5 → D2) | `work_count` = 행 수 · `output_qty` = `output_qty` 합 · `scrap_qty` = 그 실적들의 `work_scrap.scrap_qty` 합 |
| `quality` | `inspection` 중 `inspected_at` 의 날짜가 기간 안 (D7 → D2) | `inspection_count` = **검사 행 수**(롤마다 최신만 세지 않는다) · `fail_count` = `result='불합격'` 수 · `fail_rate` = fail ÷ count · `avg_delta_e` = `delta_e` 평균(비어 있는 것 제외) · `delta_e_count` = ΔE 가 적힌 검사 수(전체 평균의 가중치) |
| `delivery` | `job` 중 `due_date` 가 기간 안이고 `status<>'취소'` (D2 ← D8) | `job_count` · `on_time` · `late` · `pending` · `on_time_rate` = on_time ÷ (on_time + late) |
| `defect_by_type` | `inspection_defect` — 그 검사의 `inspected_at` 날짜가 기간 안 (D7) | 불량코드별 `defect_code_id` · `defect_count` = 불량 행 수 · `roll_count` = 서로 다른 롤 수 |

납기 판정 — 그 Job 의 **승인된** 출하(`shipment.status='승인'`) 가운데 가장 이른 `ship_date` 를 본다.
`on_time`: 그 날짜 ≤ `due_date`. `late`: 그 날짜 > `due_date`, 또는 승인된 출하가 없고 `due_date` < 오늘. `pending`: 승인된 출하가 없고 `due_date` ≥ 오늘.
분모가 0 이면 비율은 `None` 이다(0 으로 지어내지 않는다). 대상 행이 없으면 빈 리스트 → 화면은 `미수집`.
합(`output_qty` · `scrap_qty`)은 더할 값이 없으면 `0`, 평균은 ΔE 가 적힌 검사가 없으면 `None`. 비율은 반올림하지 않은 `분자 / 분모`, `totals` 의 비율은 더한 값으로 다시 나눈다(비율의 평균이 아니다).
`scrap_qty` 는 그 실적들의 폐기 전부다(폐기 시각이 기간 밖이어도 센다). 납기 = 오늘 인 Job 은 아직 `pending` 이다. 현황판의 납기는 **오늘이 납기인** Job 이다(D-301 · D-302).
수량의 단위가 품목 안에서 섞여 있어도 그대로 더한다 — 단위 환산 규칙을 받은 적이 없다(D-402).

## 8. 오류 · 로그 · 화면 헬퍼 (아키텍트 구현)

```python
# app.util.http — 오류는 여기 함수로만 올린다 (api-contract.md)
http.validation_error(message, fields=[{"name": …, "reason": …}])   # 422
http.forbidden() · http.not_found() · http.unauthorized()            # 403 · 404 · 401
http.undecided("D-02", "ERP 연계")                                   # 501 `ERP 연계 미확정 (D-02)`
http.saved(request, "저장했습니다", data={…})                         # 쓰기 성공 — 브라우저는 303 + 알림, 그 밖은 200 JSON

# app.util.audit — 데이터 변경 로그 (G-18). 쓰기 성공 직후 반드시 부른다
audit.log_change(request, user, "F-BAS-01", "item:<품목 코드>", "내용")

# app.util.screen — 값이 없으면 지어내지 않는다
screen.NOT_COLLECTED == "미수집" · screen.undecided("D-05") == "미확정 (D-05)" · screen.example("값") == "값 (예시)"
screen.txt(v) · screen.num(v, digits) · screen.dt(v)                 # 템플릿 필터로도 있다: {{ v|num(1) }}
```

## 9. 시드 · 테스트

- 공통 시드(역할 4 · 권한 48칸 · 계정 4)는 `lcomfine.db.seed`. 개발자 시드는 `src/lcomfine/db/seed_dev{1,2,3}.py` 에 `main() -> int`(0 = 성공)를 두면 `make db-seed` 가 공통 → 개발1 → 개발2 → 개발3 순으로 돌린다.
- 시드가 넣는 것: 개발1 = 채번 형식 6행 + `(예시)` 기준정보·인쇄 기준(D-101) · 개발2 = 원재료 LOT 4건(합격 2 · 대기 1 · 불합격 1, D-207) · **개발3 = 행을 넣지 않는다**(D-307 — 검사·출하는 롤을 가리키고 롤은 화면 흐름만 만든다. 새 DB 의 D7·D8 이 0행인 것이 정상이다).
  Job · 작업 실적 · 롤 · 계보 · 조색 기록도 시드가 넣지 않는다.
- 공통 시드는 시드 계정의 비밀번호가 이미 `LCOMFINE_SEED_PASSWORD` 와 같으면 해시를 다시 쓰지 않는다 — 다시 쓰면 그 계정의 살아 있는 세션이 끊긴다(D-26).
- **시드는 멱등이어야 한다** — 두 번 돌려도 행 수가 같다(G-09). 업무 코드 기준 `on conflict` 로 넣는다. 값에는 `(예시)` 를 붙인다(`screen.example`). 회사 실데이터를 지어내지 않는다.
- 시드 계정: `admin`(관리자) · `prod`(생산) · `qc`(품질) · `field`(현장). 비밀번호는 `get_settings().seed_password`(= `LCOMFINE_SEED_PASSWORD`) — 코드·문서에 값을 적지 않는다.
- 테스트 파일은 `tests/test_dev{1,2,3}_*.py` · `tests/test_qa{1,2,3}_*.py`. **기능마다 테스트 하나 이상**, 그 테스트에 `@pytest.mark.fn("F-BAS-01")` 를 붙인다 — `check-trace` 는 이 표식만 센다(본문에 ID 가 적혀 있는 것은 세지 않는다, G-02). 표식은 그 기능의 `API` 를 실제로 부르는 테스트에만 붙인다.
- 이관 배치는 `src/lcomfine/migration/__init__.py` 에 `COMMANDS: dict[str, Callable]` 를 둔다 — 키는 `function-list.md` 의 `cli <명령>` 과 같은 글자(`validate` `load-master` `load-print-std` `load-jobs` `load-history` `report`). `python -m lcomfine.migration <명령> --dir <폴더>` 로 돈다.
- 테스트가 만든 행은 테스트가 치운다(또는 `conn.tx()` 안에서 예외로 롤백). 시드 행을 지우지 않는다.
