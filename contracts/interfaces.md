# 공용 인터페이스 계약 (아키텍트 · v2 · 2026-10-21 Phase 0 Task 7)

> 개발 3명·QA 3명이 **동시에** 일하기 위해 접점을 먼저 못 박는다. 이대로 호출한다.
> 이 문서와 실제 코드가 다르면 **코드가 맞다** — 발견자가 이 문서를 고치고 `progress-*.md` 에 적는다.
> 시그니처를 바꿔야 하면 소유자가 `progress-devN.md` §1 에 먼저 공표한다. 아직 없는 모듈은 아래 공표 시그니처대로 W1~W4 에서 만든다.

| 모듈 | 소유자 | 상태 | 쓰는 사람 |
|---|---|---|---|
| `db.conn` · `app.nav` · `app.contracts` · `app.rbac` · `app.auth` · `app.templating` · `app.util.*` | 아키텍트 | 구현됨 | 전원 |
| `app.numbering` (채번 7) | 아키텍트 | 구현됨 | 개발1·2·3 |
| `app.notify` (알림 9) | 아키텍트 | 구현됨 | 개발1·2·3 |
| `app.trace` | 개발2 | W1 에서 만든다 | 개발1(TRK) · 개발2(LOT) |
| `app.stats` | 개발3 | W1 에서 만든다 | 개발1(TRK) · 개발3(PRP) |
| `app.erp_upload` | 개발3 | W2 에서 만든다 | 개발3(COL) |
| `app.dashboard` · `app.ai` · `app.dataquery` | 개발3 | W3 에서 만든다 | 개발3(RPT) · 개발1(SYS-040) |
| `app.sso` | 개발1 | W4 에서 만든다 | 개발1(DOC) |

## 1. DB — `lcomfine.db.conn`

```python
q(sql, params=None) -> list[dict]   # SELECT. 항상 dict 리스트
q1(sql, params=None) -> dict|None   # 첫 행
x(sql, params=None) -> int          # INSERT/UPDATE/DELETE 한 문장. rowcount
tx()                                # with conn.tx() as cur: … 여러 문장을 한 트랜잭션으로 (cur 는 dict 행)
```
- DSN 은 `LCOMFINE_PG_DSN`(기본 `postgresql:///lcomfine_db`). **DB 연결 실패는 삼키지 않는다** → `DbUnavailable` → 503 `서비스 일시 중단`. 사유 문구의 비밀번호는 `conn` 이 가린다(D-32).
- **같이 성공하거나 같이 실패해야 하는 것은 `tx()` 하나에** — 업무 행 + 채번(`numbering.next(kind, cur)`) + 알림(`notify.emit(cur, …)`) + 재고(`lot_stock`).
- 제약 위반(`IntegrityError`)과 담을 수 없는 입력값(`DataError`)은 `main.py` 가 422 로 바꾼다. 사람이 읽을 문장은 라우터가 먼저 검사해 `http.validation_error` 로 준다.

## 2. 메뉴 · 계약 — `app.nav` · `app.contracts`

```python
# app.nav — 메뉴·경로의 원본 (묶음 8 · 대메뉴 17 · 화면 67 · 공통 2)
nav.BUNDLES · nav.MENUS · nav.SCREENS(67) · nav.COMMON(login · error) · nav.ALL · nav.FLOW(흐름 띠 7 화면 ID)
nav.by_id("BAS-010") -> Screen(screen_id, name, menu_code, menu, bundle, module, slug, path, owner, kind, common)
nav.path_of("BAS-010") -> "/bas/items"           # 경로를 문자열로 다시 적지 않는다
nav.by_path(path) -> Screen | None · nav.menu("BAS") -> Menu(code, name, bundle, module, owner, screens)
nav.screens_of(module) -> list[Screen] · nav.menu_tree() -> [{"bundle": (키, 이름, 설명), "menus": [Menu]}]

# app.contracts — function-list.md · permission-matrix.md · db-schema.md
contracts.functions() -> tuple[Function] · contracts.function("F-BAS-011") -> Function
Function(id, menu_code, screen_id, name, kind, tables, roles_w, api, owner, contract, permission_exception)
  .is_write (kind ∈ WRITE_KINDS) · .read_ok (읽기 기능 또는 권한 예외) · .method · .path
contracts.functions_of(screen_id) · functions_of_menu(menu_code) · write_functions()
contracts.WRITE_KINDS = {등록 수정 삭제 처리 저장 진입} · READ_KINDS = {조회 출력}
contracts.ROLE_CODES = {부서 이름: 코드} (정본 순서 SL PR SH DS AC ST EX ADM)
contracts.permission_cells() -> [(screen_id, role_code, "W"|"R")]   # 260칸 (W 64 · R 196) — 칸 없는 조합은 빠진다
contracts.db_tables() -> {이름: Table}
```

## 3. 권한 — `app.rbac` (화면 단위 · DB 데이터)

권한 표는 DB `sys_permission(role_code, screen_id, level)` 이다(5초 캐시). 행이 없는 칸은 권한 없음. 부서·칸을 코드에 박지 않는다.

```python
rbac.User(id, login_id, name, role_code, role_name, status)   # 요청마다 DB 에서 읽은 지금 값 (D-26)
rbac.current_user(request) -> User | None    # 세션 없음 · 중지·잠금 · 로그아웃한 세션 · 상태/비밀번호가 바뀌기 전 세션 → None
rbac.require_login(request) -> User          # Depends 용. 미로그인 401
rbac.require_screen("BAS-010") -> Depends    # 화면 R 이상. 없으면 403 「이 화면을 볼 권한이 없습니다」. 공통 화면은 로그인만
rbac.require_fn("F-BAS-011") -> Depends      # 쓰기 유형 → W 칸 · 조회 유형 · 권한 예외(read_ok: F-DOC-011 F-RPT-132 F-HOME-022) → R 칸
                                             #   없으면 403 「이 기능을 실행할 권한이 없습니다」
rbac.can(user, screen_id, level="R") -> bool # R = 칸 W 또는 R · W = 칸 W (템플릿의 버튼 활성/비활성)
rbac.can_do(user, function_id) -> bool       # require_fn 과 같은 판정
rbac.visible_menu(user) -> list[dict]        # menu_tree 모양 — 볼 화면만 남긴 Menu, 빈 대메뉴·묶음은 뺀다. 미로그인 []
rbac.can_flow(user) -> [(screen_id, bool)]   # 흐름 띠 7단계의 링크 가능 여부
rbac.level(role_code, screen_id) -> "W"|"R"|None · rbac.roles() -> [Role(code, name, sort_no)] · rbac.role(code)
rbac.counts() -> {"W": n, "R": n, "전체": n} · rbac.matrix() -> [{"screen": Screen, "cells": [level, …부서 순]}]
rbac.load_user(login_id) -> User | None      # 세션 판정 없이 계정의 지금 값 (배치 · 도구 · 테스트)
rbac.invalidate()                            # sys_permission · sys_role 을 바꾼 뒤 (SYS-020)
```

## 4. 로그인 · 세션 — `app.auth`

```python
auth.authenticate(login_id, password, *, client_ip=None, via="") -> LoginResult(ok, user, reason)   # 접근 로그 `로그인`
auth.login_session(request, user) · auth.logout_session(request) · auth.revoke_session(login_id, session_id)
auth.session_expired(request) · auth.touch_session(request) · auth.home_path_for(request, user) -> "/" (HOME-010)
auth.quick_login_enabled() -> bool     # LCOMFINE_QUICK_LOGIN 켜짐 · 시드 비밀번호 있음 · env != prod
auth.quick_login_accounts() -> [{"role", "summary": {"W","R"}, "menus", "primary", "others", "active", "total"}]   # 부서 8
auth.hash_password(pw) · auth.verify_password(pw, stored)    # PBKDF2-SHA256
```
- 채널(device) 구분은 없다. 실패 횟수는 세지만 잠그지 않는다(잠금 횟수 미정 — D-20). 상태가 `정상` 인 계정만 로그인한다.

## 5. 렌더 — `app.templating`

```python
templating.render(request, "bas/items.html", ctx, *, screen_id="BAS-010", status_code=200) -> HTMLResponse
templating.placeholder(request, screen_id) -> HTMLResponse
```
- 헤더 · 좌측 메뉴 · 계약 패널을 채우고 **화면 조회 로그**(`sys_access_log` 구분 `조회`)를 남긴다. 레이아웃은 Task 8 에서 다시 쓴다.

라우터 한 개의 모양 (`app/routers/<모듈>.py` — `router = APIRouter()` 만 있으면 `main.py` 가 자동 include):

```python
@router.get(nav.path_of("BAS-010"), response_class=HTMLResponse)           # F-BAS-014 품목 조회 = 화면 GET
def items(request: Request, user: rbac.User = rbac.require_fn("F-BAS-014")):
    rows = conn.q("select … from item order by item_code")
    return templating.render(request, "bas/items.html", {"rows": rows}, screen_id="BAS-010")

@router.post("/bas/items")                                                  # F-BAS-011 품목 등록
def create_item(request: Request, item_code: str = Form(...), …, user: rbac.User = rbac.require_fn("F-BAS-011")):
    if conn.q1("select 1 from item where item_code = %s", (item_code,)):
        raise http.validation_error("이미 있는 품목 코드입니다", fields=[{"name": "품목 코드", "reason": item_code}])
    conn.x("insert into item (…, created_by) values (…, %s)", (…, user.login_id))
    audit.log_change(request, user, "F-BAS-011", f"item:{item_code}")
    return http.saved(request, "품목을 등록했습니다")
```
- 기능의 메서드·경로는 `function-list.md` 의 `API` 열과 **글자 그대로** 같아야 한다.

## 6. 오류 · 로그 · 화면 헬퍼 — `app.util.*`

```python
# app.util.http — 오류는 여기 함수로만 올린다 (api-contract.md)
http.validation_error(message, fields=[{"name": …, "reason": …}])   # 422
http.unauthorized() · http.forbidden(message, **extra) · http.not_found(message)   # 401 · 403 · 404
http.undecided("D-516", "ERP 열 구성")                               # 501 `ERP 열 구성 미확정 (D-516)`
http.saved(request, "저장했습니다", data={…})                         # 쓰기 성공 — 브라우저는 303 + 알림, 그 밖은 200 JSON

# app.util.audit
audit.log_change(request, user, "F-BAS-011", "item:<품목 코드>", "내용")   # → sys_change_log. 쓰기 성공 직후 반드시 부른다
audit.write_log(log_type=audit.LOGIN|VIEW|ERROR|SSO, login_id=…, …)       # → sys_access_log (auth · templating · main · DOC-010)

# app.util.screen — 값이 없으면 지어내지 않는다
screen.NOT_COLLECTED == "미수집" · screen.undecided("D-509") == "미확정 (D-509)" · screen.example("값") == "값 (예시)"
screen.txt(v) · screen.num(v, digits) · screen.dt(v)                 # 템플릿 필터로도 있다: {{ v|num(1) }}
```

## 7. 채번 — `app.numbering` (D-509)

```python
numbering.KINDS = ("REQ", "WO", "MLOT", "PLOT", "SHP", "ERP", "DQ")   # 상수 numbering.REQ … numbering.DQ
numbering.next(kind, cur=None, *, at=None) -> str   # 발번(카운터 +1). cur 를 주면 그 트랜잭션 안에서 — 업무 행과 함께 롤백
numbering.peek(kind, *, at=None) -> str             # 발번하지 않는 미리보기
numbering.rule(kind) -> dict | None                 # sys_number_rule 행 (없으면 화면은 `미확정 (D-509)`)
```
- 형식은 데이터다: `sys_number_rule(seq_kind, prefix, date_format, seq_digits, note)` · 카운터 `sys_number_seq(seq_kind, seq_scope, last_value)`.
  번호 = prefix + to_char(시각, date_format) + 일련번호(seq_digits 자리). 날짜 부분이 바뀌면 1 부터.
- 시드 7행은 `KIND-YYMM-nnnn` `(예시)` — 가설(D-509). KINDS 밖은 `ValueError`, 형식 행이 없으면 `RuntimeError`.
- 분할 LOT 는 채번하지 않고 원 LOT 번호에 `-01` 순번을 붙인다(D-509 · INV-020).

## 8. 알림 — `app.notify` (D-511 · D-522 · D-523)

```python
notify.EVENTS: dict[str, tuple[str, ...]]   # 이벤트 9 → 수신 부서 코드
  request_created → (PR, DS) · order_issued → (PR,) · material_received → (PR,) · product_received → (PR,)
  judged → (SH, SL) · shipment_ordered → (SH,) · shipment_confirmed → (SL, AC) · erp_upload_error → (AC,)
  due_d3_unshipped → (SL, PR)
notify.emit(cur, event, *, link, dedupe_key, text) -> int   # 수신 부서마다 1행 · (dedupe_key, to_role) 중복은 무시 · 새 행 수
notify.unread(user) -> list[dict]                           # 부서(role_code)의 미처리 알림 최신순 (id event_key link message dedupe_key created_at)
notify.handle(cur, notification_id, user) -> None           # 그 행 처리. 다른 부서 · 없는 ID → LookupError(라우터 404) · 이미 처리 → 그대로
notify.handle_by_link(cur, link, user) -> int               # 같은 부서 · 같은 link 의 미처리 알림 전부 처리 — 처리한 행 수
notify.resolve_by_link(cur, link, user) -> int                 # 알림이 가리키던 사실이 사라졌을 때(회차 교체 · 오류 0) 수신 부서와 무관하게 닫는다 (DEF-QA1-006)
notify.recipients(event) -> tuple[str, ...]                 # 모르는 이벤트 KeyError
```
- `emit` · `handle` · `handle_by_link` 은 **쓰기 트랜잭션의 커서**를 받는다 — 자체 연결을 열지 않는다. 모르는 이벤트는 `KeyError`(조용히 무시하지 않는다).
- 수신 = `role_code` · 설정은 끄기만 (자기 부서가 받는 이벤트를 끄는 것뿐 · 다른 부서 이벤트 구독은 범위 밖).
- `notification` 에 쓰는 곳은 `notify` 뿐. 개인 설정 `notification_setting(user_id, event_key, enabled=false)` 는 `unread` 에서 숨기기만 한다(행은 생긴다 · 행이 없으면 켜짐).
- 처리 화면의 쓰기 트랜잭션 안에서 `notify.handle_by_link(cur, 그 화면 경로, user)` 를 부르면 「알림을 눌러 연 화면에서 처리하면 닫힌다」.

## 9. W1~W4 에서 만드는 모듈 (공표 시그니처 — 스펙 §5 · 계획)

```python
# app.trace (개발2 · W1) — 읽기만. 어떤 테이블에도 쓰지 않는다
trace.backward(shipment_no=None, product_lot_no=None) -> dict   # 단계별 노드 목록 · 원자재 LOT 목록
trace.forward(material_lot_no) -> dict                          # 원자재 LOT → 불출 → 지시 → 제품 입고 → 출하

# app.stats (개발3 · W1) — 집계 SQL (읽기만)
stats.customer_receivable(customer_id: int) -> dict             # TRK-030 수금 칸 (W2 공표 · progress-dev3 §1.3) — {customer_id, asof, erp_codes, rows, sales_amount,
                                                                #   collected_amount, receivable_amount, last_txn_date, status ∈ "ok"|"미수집"|"미확정 (D-516)", decision}
stats.due_compliance(period) -> dict                            # TRK-020 납기 준수율 (Ruling 23 · D-804) — period "YYYY-MM" 또는 (시작일, 종료일) →
                                                                #   {period, total, on_time, late_done, late_open, in_progress, rate | None(미수집), rows, formula}
stats.erp_asof() -> date | None                                 # 반영 회차의 마지막 기간 끝 (COL · TRK-030 「ERP 업로드 기준일」)
stats.collections(date_from, date_to, customer_id=None, method=None) -> dict      # COL-040
stats.receivables(asof, include_zero=False) -> dict             # COL-050 (매출액 열 미매핑이면 미확정 (D-516))
stats.aging(asof) -> dict                                       # COL-060 — 구간 30 · 60 · 90 · over90 (HOME 회계부 「90일 초과 미수」 = len(aging(...)["over90"]))
stats.shipment_vs_collection(ym_from, ym_to, customer_id=None) -> dict           # COL-070 — MES 확정 출하 ↔ ERP 매출·수금 full outer join

# app.erp_upload (개발3 · W2)
erp_upload.read_xlsx(file: bytes) -> list[dict]                 # 첫 시트 · 1행 헤더 (D-802)
erp_upload.headers(file: bytes) -> list[str]
erp_upload.column_map() -> dict[str, str]                       # MES 필드 → 엑셀 열 이름 (erp_column_map · D-516 흡수)
erp_upload.save_column_map(cur, mapping, user) -> int
erp_upload.check_map(cmap, file_headers=None) -> None           # 필수 열 빠지면 422
erp_upload.validate(rows, cmap, customer_map=None) -> list[dict]        # 행마다 parsed 또는 error (미매핑 = 오류 행)
erp_upload.apply(cur, period_from, period_to, rows, user, *, source_file="") -> int   # 새 회차 id · 같은 기간 재업로드 = 회차 교체 · 오류 · 미매핑 있으면 notify.emit("erp_upload_error")
erp_upload.remap(cur, batch_id=None, erp_code=None, user=None) -> dict  # 매핑 뒤 반영 회차 행 재해석 — {reviewed, changed, applied(error → None), still_error} (DEF-QA2-004)
erp_upload.unmapped_codes() -> list[dict]                       # COL-030 미매핑 목록
erp_upload.mapped_fields() -> dict[str, bool]
erp_upload.error_link(batch_id) -> str                          # 알림 link = /col/upload-history?batch=<id>

# app.dashboard (개발3 · W3) — 8 함수: orders production quality inventory shipment collection order_flow summary
dashboard.<이름>(period, customer_id=None) -> {"kpis": [...], "series": {...}, "tables": {...}, "asof": date | None}

# app.ai (개발3 · W3)
ai.complete(system, user, *, kind, cur) -> str   # 키 없으면 ai.NotConfigured · 호출마다 sys_ai_call_log
ai.NotConfigured · ai.set_client(fake)           # 테스트 주입

# app.dataquery (개발3 · W3)
dataquery.ask(cur, user, question) -> dict
dataquery.validate_sql(sql, allowed_views) -> str   # SELECT 한 문장 · 허용 뷰 v_dq_* 만 · 어긋나면 422 「허용되지 않는 질의」

# app.sso (개발1 · W4)
sso.issue(cur, user) -> tuple[str, str]   # (token, jti) · 비활성 · 미매핑이면 sso.NotMapped
sso.NotMapped
sso.consume(cur, token) -> dict           # 서명 · 만료 · 1회 사용
```

## 10. 시드 · 테스트

- 공통 시드 `lcomfine.db.seed`(`make db-seed`): 부서 8(`sys_role`) · 계정 8(`sl pr sh ds ac st ex admin`, 이름 `<부서> (예시)`) · 권한 260칸(`contracts.permission_cells()` 그대로, 표에 없는 행은 지운다) · 채번 7(`(예시)` D-509) · 공통코드 3그룹(설비 2 · 불량유형 3 · 수금수단 3, 전부 `(예시)`). `notification_setting` 은 시드하지 않는다.
- 계정 비밀번호는 `get_settings().seed_password`(= `.env` 의 `LCOMFINE_SEED_PASSWORD`)뿐 — 없으면 시드가 실패한다. 코드·문서·테스트에 값을 적지 않는다. 이미 그 값이면 해시를 다시 쓰지 않는다(D-26).
- 개발자 시드는 `src/lcomfine/db/seed_dev{1,2,3}.py` 에 `main() -> int`(0 = 성공) — 공통 → 개발1 → 개발2 → 개발3 순. 없는 파일은 한 줄 남기고 건너뛴다.
- **시드는 멱등** — 두 번 돌려도 행 수가 같다(G-21). 값에는 `(예시)` 를 붙인다(`screen.example`). 회사 실데이터를 지어내지 않는다.
- 테스트 파일은 `tests/test_dev{1,2,3}_*.py` · `tests/test_qa{1,2,3}_*.py`. **기능마다 테스트 하나 이상**, `@pytest.mark.fn("F-BAS-011")` 표식 — 그 기능의 `API` 를 실제로 부르는 테스트에만 붙인다.
- 테스트가 만든 행은 테스트가 치운다(또는 `conn.tx()` 안에서 예외로 롤백). 시드 행을 지우지 않는다.
