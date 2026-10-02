# QA1 리포트 — 기능 · 계약 (G-01~G-03 · 오류 계약 §2.5 · G-17 권한 48칸)

> 2026-10-03 · 웨이브 C · QA1. **고치지 않았다** — `src/` · 남의 테스트·도구 · `contracts/` 는 그대로다.
> 만든 것: `tools/check_screens.py` · `tests/test_qa1_{support,functions,rbac,errors}.py` · 이 문서.
> 기대값은 설계도(§5 IA · §6 권한 표)와 goal.md(§2 게이트 · §2.5 · §6)에서 직접 끌어왔다. 앱의 `nav` · `contracts` · `rbac` 와
> `tools/design_doc.py` 가 스스로 적은 값을 기대값으로 쓰지 않았다(검사기에 파서를 따로 두었다).

## 0. 요약

| 게이트 | 판정 | 실측 | 명령 |
|---|---|---|---|
| G-01 메뉴 12 · 32 | **PASS** (다른 방법으로 재확인) | 설계도 자체 파싱 대메뉴 12 · 중메뉴 32 · 기능 94 = 계약의 (대메뉴, 중메뉴) 쌍 32 = 계약에서 끌어낸 화면 경로 32 | `uv run pytest -q tests/test_qa1_functions.py -k "design_doc or one_line"` |
| G-02 기능 94 + 6 | **PASS** | 검사 7 전부 PASS — 기능 94 전부 실호출(요청 121 · 404·405 0) · 읽기 40/40 · 쓰기 54/54(쓰는 테이블 SQL 확인) · 실행 중인 앱의 OpenAPI = 계약(고아 0 · 누락 0) · 배치 6/6 | `uv run python tools/check_screens.py` |
| G-03 화면 32 + 공통 3 | **PASS** | 검사 7 전부 PASS — 브라우저 GET 200 32/32 · placeholder 0 · **방금 만든 값이 32 화면에 보임 32/32** · 공통 3 200 | 〃 |
| G-17 권한 48칸 | **PASS** | 검사 10 전부 PASS — 요청 686 건 · **위반 0**. 괄호 조건 2개 일치. 권한 표는 데이터(새 역할 한 행으로 확인). 검사 뒤 48칸 = 입력 19 · 조회 24 · 없음 5 | 〃 |
| §2.5 오류 계약 (6행) | **FAIL** | 422 행 FAIL(결함 001 · 002 · 004 · 005 · 007) · 401 행 FAIL(003 · 006) · 403 · 503 · 501 · 500 행 PASS | `uv run pytest -q tests/test_qa1_errors.py` → 130 passed · **26 failed** |

| 결함 | 치명 | 중대 | 경미 | 계 |
|---|---|---|---|---|
| `DEF-QA1-nnn` | **0** | **4** (001 · 002 · 003 · 004) | **3** (005 · 006 · 007) | 7 |

- `tests/test_qa1_*.py` 는 1,102건이다 — functions 200 passed · rbac 746 passed · errors 130 passed + **26 failed**. 실패 26건은 전부 아래 결함을 드러내는 것이고 `skip`·`xfail` 을 쓰지 않았다(§3 의 대응표). 그래서 **G-21(pytest 전건)은 이 결함들이 고쳐질 때까지 FAIL** 이다.
- 권한(G-17)과 기능 1:1(G-02) · 화면(G-03)에서는 결함을 찾지 못했다. 결함은 전부 **오류 계약** 쪽이다 — 틀린 입력이 500 이 되는 것 2종, 중지된 계정의 세션, POP 스캔 오류 화면.
- 「확인 필요」 7건(§4)은 결함으로 세지 않았다 — 설계도·goal.md 에 기대값이 없거나 `가설` 로 정한 것이다.

## 1. `tools/check_screens.py` — 무엇을 어떻게 쟀나

`check_trace`(라우트 표를 읽는다) · `check_routes`(관리자로 화면 35개를 TestClient 로 연다)와 겹치지 않게 했다.

1. **실제 서버를 포트 8021 에 띄워 HTTP 로** 두드린다(끝나면 내린다 — 포트가 쓰이고 있으면 TestClient 로 내려가고 그 사실을 첫 줄에 적는다).
2. **한 Job 을 화면이 부르는 API 로 끝까지** 흘린다: 기준정보 5 · 인쇄 기준 3 → 작업지시 · 매핑 → 입고 2 · 입고검사 → 조색 · 배합비 → 인쇄 3회(투입 스캔 · 정지 · 재개 · 폐기) → splice 2:1 · 슬리팅 1:3 · 1:1 후가공 → 검사 → 출하 · 승인 · COA → 정방향·역방향 추적 → 집계 · 현황판 → 사용자 · 권한 · 로그. 기능 94개를 전부 부른다(요청 121).
3. 쓰기 54개는 응답 200 `{ok: true, message}` 뿐 아니라 **계약의 「쓰는 테이블」 을 SQL 로 다시 읽어** 그 키의 행이 생겼는지(또는 지워졌는지) 본다. 읽기 40개와 화면 32개는 **방금 만든 번호가 HTML 에 있는지** 본다.
4. 설계도 §3 예시가 그대로 나온다: 이 흐름이 남긴 계보 = 투입 4 · splice 2 · 후가공 1 · 슬리팅 3 · 출하 2 = 12행(예시 10행 + 1:1 후가공 롤 한 벌 2행). 역방향 추적 화면에 원재료 LOT ①·② 가 둘 다 나온다(완료 기준).
5. 권한은 설계도 §6 의 칸 글자에서 기대값을 만들고 역할 4 × (화면 32 · 메뉴 48칸 · 읽기 40 · 쓰기 54) + 미로그인 94 를 **전수**로 두드린다. 쓰기는 **없는 키·빈 본문**으로 보낸다 — 권한이 없으면 403, 있으면 404·422 가 나와야 하고 어느 쪽도 아무것도 쓰지 않는다.
6. 테스트 데이터는 `Q1-<6자>-…` 접두이고 끝나면 지운다. 시드 역할의 48칸과 시드 계정 4개의 행은 바꾸지 않는다.

`uv run python tools/check_screens.py` 출력 (원문 · 2026-10-03):

```
G-02 기능 · G-03 화면 · G-17 RBAC (tools/check_screens.py) — 방식: server (포트 8021) · 테스트 데이터 접두 Q1-D2A529
--------------------------------------------------------------------------------------------------------------
G-02  계약 100줄 = 설계도 §5 의 대메뉴별 수 (자체 파싱)                 PASS  화면 94 + 배치 6 · 20·12·7·8·8·5·7·6·7·3·4·7 (설계도 20·12·7·8·8·5·7·6·7·3·4·7)
G-02  기능 94 실호출 — 로그인 세션으로 API 를 불러 404·405 가 아니다       PASS  호출한 기능 94/94 · 요청 121 · 404·405 0
G-02  읽기 기능 40 — 200 이고 방금 만든 값이 화면에 있다                 PASS  통과 40/40
G-02  쓰기 기능 54 — 200 이고 계약의 「쓰는 테이블」 에 행이 생긴다 (SQL 확인)  PASS  통과 54/54
G-02  흐름이 남긴 계보 — 설계도 §3 예시 10행 + 1:1 후가공 2행            PASS  투입 4 · splice 2 · 후가공 1 · 슬리팅 3 · 출하 2 = 12행 (기대 12)
G-02  등록된 API = 계약 94 (고아 0 · 누락 0) — 실행 중인 앱의 OpenAPI  PASS  서버의 /openapi.json: 경로·메서드 106 · 계약에 없는 것 0 · 계약인데 없는 것 0
G-02  이관 배치 6 — 명령을 실제로 돌린다 (Q1 사본 폴더)                  PASS  통과 6/6
G-03  중메뉴 32 의 화면 경로가 계약에서 나온다 (설계도 중메뉴 수와 같다)          PASS  계약의 화면 경로 32 · 설계도 중메뉴 32
G-03  중메뉴 32 화면 — 브라우저(Accept: text/html) GET 200       PASS  200 32/32
G-03  placeholder(미구현) 0                                PASS  placeholder 0
G-03  실 데이터 연동 — 방금 API 로 만든 값이 32 화면에 보인다              PASS  연동 확인 32/32
G-03  공통 3 (메인 · 로그인 · 오류) 200                          PASS  / 200 · /login 200 · /error 200
G-03  역할 4 모두 메인 200                                    PASS  관리자 200 · 현장 200 · 생산 200 · 품질 200
G-03  없는 주소 404 오류 화면                                   PASS  HTTP 404
G-17  설계도 §6 = 48칸 (입력 19 · 조회 24 · 없음 5)               PASS  48칸 = 입력 19 · 조회 24 · 없음 5
G-17  DB sys_permission = 설계도 48칸 (칸마다 대조)              PASS  다른 칸 0
G-17  화면 GET — 없음 403 · 그 밖 200 (역할 4 × 화면 32)          PASS  요청 128 · 위반 0
G-17  메뉴 숨김 — 없음 칸의 화면 링크 0 (48칸)                       PASS  요청 48 · 위반 0
G-17  읽기 기능 — 없음 403 · 그 밖 허용 (역할 4 × 40)               PASS  요청 160 · 위반 0
G-17  쓰기 기능 전수 — 조회·없음 403 · 입력 허용 (역할 4 × 54)          PASS  요청 216 · 위반 0
G-17  미로그인 — 기능 94 전부 401 · 브라우저 GET 303                PASS  요청 134 · 위반 0
G-17  괄호 조건 2 — 품질은 입고검사만 · 관리자는 출하 승인만                 PASS  품질×자재·입고 쓰기 3: 허용 ['F-MAT-03'] 나머지 403 · 관리자×출하 쓰기 4: 허용 ['F-SHP-05'] 나머지 403 · 위반 0
G-17  권한 표는 데이터 — 새 역할 한 행 + 칸 변경이 코드 수정 없이 반영          PASS  행 없는 칸(TRC) 조회 403 · → 조회로 바꾼 직후 200 · BAS 조회 칸의 쓰기 403 · → 입력으로 바꾼 직후 쓰기 422 · MAT 입력(입고검사) 의 입고검사 등록 422 · 같은 칸의 입고 등록 403 · SHP 입력(승인) 의 승인 404 · 같은 칸의 출하 등록 403 · SHP 입력(일반,승인) 의 출하 등록 422 · SQL 로 없음 → 403 까지 5.2초
G-17  검사 뒤 권한 표 원상 — 48행 = 입력 19 · 조회 24 · 없음 5 · 역할 4  PASS  sys_permission 48행 = 입력 19 · 조회 24 · 없음 5 · sys_role 4 (검사 전 48행) · 남은 Q1 행 0
--------------------------------------------------------------------------------------------------------------
권한 전수: 요청 686 건 (화면 128 · 메뉴 48 · 읽기 160 · 쓰기 216 · 미로그인 134) · 위반 0 건
확인 필요 (D-14 해석 · 게이트 판정에 넣지 않음): 괄호 없는 `입력` 칸의 역할이 다른 역할의 괄호 기능을 부른 4 건 — 생산 × F-MAT-03 입고검사 결과 등록 → 403 / 생산 × F-SHP-05 출하 승인 → 403 / 현장 × F-MAT-03 입고검사 결과 등록 → 403 / 현장 × F-SHP-05 출하 승인 → 403
참고 (G-18 은 QA3 판정): 쓰기 기능 54 개의 성공한 호출 81 건 가운데 `변경` 로그가 남지 않은 기능 0
G-02 판정: PASS (검사 7 · 실패 0)
G-03 판정: PASS (검사 7 · 실패 0)
G-17 판정: PASS (검사 10 · 실패 0)
```

`tools/gate.py` 의 `per_gate()` 에 이 출력을 넣어 본 결과: `G-02 ('PASS', '검사 7 전부 PASS')` · `G-03 ('PASS', '검사 7 전부 PASS')` · `G-17 ('PASS', '검사 10 전부 PASS')` — 행 형식이 맞는다. `gate.py` 는 고치지 않았다.

검사기가 헐겁지 않다는 확인: `rbac.can_do` 를 (테스트 프로세스 안에서만) 무엇이든 허용하게 바꾸면 전수 검사가 쓰기 216 중 위반 **132**(403 이어야 할 128 + D-14 4), 읽기 160 중 위반 20 을 낸다 — `uv run pytest -q tests/test_qa1_rbac.py -k sweep_detects`.

## 2. 결함

### DEF-QA1-001 · 중대 · 글자 입력에 NUL(0x00)이 섞이면 500 — 미로그인 `/login` 포함

- **재현**
  ```bash
  uv run uvicorn lcomfine.app.main:app --app-dir src --port 8021 &
  curl -s -o /dev/null -w '%{http_code}\n' -d 'login_id=a%00b&password=x' http://127.0.0.1:8021/login      # 로그인 없이
  PW=$(grep '^LCOMFINE_SEED_PASSWORD=' .env | cut -d= -f2-)
  curl -s -o /dev/null -c q1.jar -d 'login_id=admin' --data-urlencode "password=$PW" http://127.0.0.1:8021/login
  curl -s -b q1.jar 'http://127.0.0.1:8021/bas/items?code=a%00b'
  curl -s -o /dev/null -w '%{http_code}\n' -b q1.jar 'http://127.0.0.1:8021/trc/trace/backward?no=a%00b'
  # 또는
  uv run pytest -q tests/test_qa1_errors.py -k nul_byte
  ```
- **실측** `500` · `{"code":"internal_error","message":"예상하지 못한 오류","reason":"DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes"}`.
  모듈 12개에 40건을 보내 **38건이 500**: `POST /login`(미로그인) · `/bas/items?code` · `/bas/customers?name` · `/prt/plates?code` · `/prt/inks?name` · `/job/orders?no`·`?q` · `/job/mapping?no` · `/job/orders/{…}/print` · `/sys/users?login_id`·`?edit` · `/sys/logs?login_id` · `/pop/work?no`·`?roll` · `/pop/roll-labels?no` · `POST /pop/work/start` · `/mat/lots?no` · `/mat/receipts?supplier` · `/mat/inspections?insp_status` · `/mat/lots/{…}/label` · `POST /mat/receipts` · `POST /mat/inspections` · `/clr/records?job_no` · `POST /clr/records` · `/rll/history?no` · `/rll/finishing?rolls` · `/rll/slitting?parent` · `POST /rll/finishing` · `/qua/inspections?no` · `/qua/defect-stats/rolls?defect_code` · `POST /qua/inspections` · `/shp/shipments?no` · `/shp/coa?customer` · `/shp/coa/{…}/print` · `POST /shp/shipments` · `/trc/trace?q` · `/trc/trace/forward?no` · `/trc/trace/backward?no`. 422 로 막힌 것은 개발1 의 POST 2건(`POST /bas/items` · `POST /job/mapping`)뿐이다.
  500 마다 접근 로그에 `오류` 한 줄이 남는다 — 로그인 없이도 로그를 불릴 수 있다.
- **기대** 422 `validation_error` (goal.md §2.5 1행 — 입력값 오류는 422 · `contracts/api-contract.md` §3 「놓친 경우에도 500 이 되지 않게」).
- **담당** 아키텍트 — `app/main.py` 가 `psycopg.errors.IntegrityError` 만 422 로 바꾸고 `psycopg.DataError` 는 500 으로 흘린다(한 곳에서 막을 수 있다 · `api-contract.md` §3 도 함께). 라우터 쪽: 개발2 `routers/pop.py` 의 `text_of`(mat·clr·rll 공용) · 개발3 `routers/{qua,shp,trc}.py` · 개발1 의 조회 인자(`bas.contains` 를 타는 GET).
- **드러내는 테스트** `test_nul_byte_input_is_not_500[login|bas|prt|job|sys|pop|mat|clr|rll|qua|shp|trc]` (12건).

### DEF-QA1-002 · 중대 · 컬럼이 담을 수 없는 큰 수 → 500

- **재현**
  ```bash
  curl -s -o /dev/null -c f.jar -d 'login_id=field' --data-urlencode "password=$PW" http://127.0.0.1:8021/login
  curl -s -b f.jar -d 'item_code=EX-RM-01&received_qty=1e15' http://127.0.0.1:8021/mat/receipts
  uv run pytest -q tests/test_qa1_errors.py -k out_of_range
  ```
- **실측** `500` · `NumericValueOutOfRange: numeric field overflow — A field with precision 14, scale 3 must round to an absolute value less than 10^11`. 트랜잭션은 되돌려져 행은 생기지 않는다.

  | 기능 | 요청 | 실측 |
  |---|---|---|
  | F-MAT-01 입고 등록 | `received_qty=1e15` | 500 |
  | F-MAT-07 자재 투입 스캔 | `input_qty=1e15` | 500 |
  | F-POP-06 폐기 등록 | `scrap_qty=1e15` | 500 |
  | F-POP-02 작업 종료 | `output_qty=1e15` · `width_mm=1e9` · `length_m=1e15` | 500 ×3 |
  | F-CLR-01 조색 기록 등록 | `color_l=1000000` · `seq_no=99999999999`(`integer out of range`) | 500 ×2 |
  | F-CLR-03 조색 기록 수정 | `color_l=1000000` | 500 |
  | F-RLL-01 후가공 실적 등록 | `length_m=1e15` · `width_mm=1e9` | 500 ×2 |
  | F-RLL-04 슬리팅 분할 등록 | `widths_mm=1e9` | 500 |
  | F-QUA-01 검사 결과 등록 | `delta_e=99999.999` (상한 검사 `< 100000` 은 통과하고 numeric(7,2) 반올림에서 넘침) | 500 |
  | F-JOB-01 · F-JOB-06 · F-PRT-05 (개발1) | `order_qty=1e15` · `planned_roll_count=99999999999` · `line_count=1e12` | **422** (통과) |

- **기대** 422 (goal.md §2.5 1행).
- **담당** 개발2 — `routers/pop.py` 의 `decimal_of` · `int_of` 에 상한이 없다(mat · clr · rll 이 같이 쓴다. 개발1 의 `bas.decimal_of` 는 `int_digits` 로 막는다). 개발3 — `routers/qua.py` 의 `_delta_e`. (DEF-001 의 핸들러를 넣으면 같이 422 가 되지만 사람이 읽을 문장은 라우터가 줘야 한다.)
- **드러내는 테스트** `test_out_of_range_number_is_422_not_500[mat|pop|clr|rll|qua]` (5건 · `[job]` `[prt]` 는 통과).

### DEF-QA1-003 · 중대 · 중지·잠금한 계정의 살아 있는 세션이 계속 통한다 (역할 변경도 반영되지 않는다)

- **재현** `uv run pytest -q tests/test_qa1_errors.py -k stopped_account_live_session`
  — 관리자가 계정을 만든다(F-SYS-01) → 그 계정으로 로그인해 세션을 연다 → 관리자가 그 계정을 삭제(= 상태 `중지`, F-SYS-03)한다 → 열어 둔 세션으로 다시 요청한다.
- **실측** 중지 뒤에도 `GET /sys/users` **200**, `POST /bas/items`(빈 본문) **422** — 권한 판정을 통과해 본문 검증까지 간다(유효한 본문이면 쓴다). `sys_user.status` 는 `중지` 이고 새 로그인은 401 로 막힌다.
  같은 뿌리로 재 본 것: 상태를 `잠금` 으로 바꿔도 기존 세션 200 · 역할을 관리자 → 현장으로 바꿔도 기존 세션은 `GET /sys/users` 200(새로 로그인하면 403).
  세션은 서명 쿠키이고 요청마다 DB 를 다시 보지 않는다(`rbac.current_user`). `.env` 에 `LCOMFINE_SESSION_IDLE_MINUTES` 가 없어(D-20) 자동 로그아웃이 없고, 쿠키 수명은 Starlette 기본 14일이다 — 막은 계정이 최장 14일 동안 그 권한으로 움직인다.
- **기대** 401 (goal.md §2.5 「인증 실패 401」 · 계약 F-SYS-03 「행을 지우지 않고 상태 `중지`」 는 그 계정을 못 쓰게 한다는 뜻이다).
- **담당** 아키텍트 — `app/rbac.py`(`current_user` · `require_login`) · `app/auth.py`. 개발1 이 `progress-dev1.md` §3-2 와 D-105 에 같은 요청을 남겼고 `progress.md` 「지금 해야 할 것」 2 에 올라 있다 — 이 리포트는 그것을 실측으로 확인한 것이다.
- **드러내는 테스트** `test_401_stopped_account_live_session_is_cut` (1건).

### DEF-QA1-004 · 중대 · 현장 POP 화면 2개(검사 결과 · 출하)에서 없는 번호를 스캔하면 오류 화면으로 빠져 다음 스캔이 막힌다

- **재현**
  ```bash
  curl -s -o /dev/null -c qc.jar -d 'login_id=qc' --data-urlencode "password=$PW" http://127.0.0.1:8021/login
  curl -s -H 'Accept: text/html' -b qc.jar 'http://127.0.0.1:8021/qua/inspections?no=Q1-NONE&device=pop' | grep -c data-scan      # 0
  curl -s -H 'Accept: text/html' -b f.jar  'http://127.0.0.1:8021/shp/shipments?no=Q1-NONE&device=pop'   | grep -c data-scan      # 0
  uv run pytest -q tests/test_qa1_errors.py -k pop_scan_get
  ```
- **실측** 둘 다 `422` 이지만 응답이 공용 오류 화면(`_error.html` · 702 / 725 바이트)이다 — 스캔칸(`data-scan`) 0개, 버튼은 「메인으로」 「로그인」 뿐. 스캐너는 키보드라(D-04) 다음 바코드가 갈 곳이 없다.
  비교: 같은 조작을 개발2 의 POP 화면 7개(`/pop/work` · `/pop/roll-labels` · `/mat/inspections` · `/mat/lots` · `/rll/finishing` · `/rll/slitting` · `/rll/history`)에서 하면 **그 화면이 422 로 다시 그려지고** 스캔칸과 사유가 함께 있다(D-201) — 7건 PASS.
- **기대** goal.md §2.5 1행 「POP 은 큰 글씨로, 다음 스캔을 막지 않는다」. 두 화면의 채널은 설계도 §6 「주로 쓰는 채널」 에 `현장 POP` 이 들어 있다(품질 검사 기록 · 출하).
- **담당** 개발3 — `routers/qua.py`(`inspections` 의 `?no=`) · `routers/shp.py`(`shipments` 의 `?no=`). 개발2 의 `scan_failure` 방식(D-201)을 쓰면 된다. 공용 규약은 아키텍트 — `api-contract.md` §2 표에 「브라우저 GET 의 422」 줄이 없다(`progress.md` 「지금 해야 할 것」 2 의 세 번째 항목).
- **같은 뿌리 (POP 채널이 아니라 등급을 올리지 않음)** `/trc/trace/forward?no=` · `/trc/trace/backward?no=` · `/job/orders?no=` · `/job/mapping?no=` · `/mat/inputs?work_id=` 도 브라우저에서 없는 번호면 오류 화면이다(입력하던 화면으로 돌아가지 않는다).
- **드러내는 테스트** `test_pop_scan_get_422_keeps_the_scan_box[/qua/inspections?no]` · `[/shp/shipments?no]` (2건 · 나머지 7건 통과).

### DEF-QA1-005 · 경미 · Referer 없는 폼 POST 의 422 가 POST 전용 주소로 303 → 405 (알림을 볼 수 없다)

- **재현**
  ```bash
  curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' -H 'Accept: text/html' -b f.jar -c f.jar -d 'job_no=Q1-NONE' http://127.0.0.1:8021/pop/work/start
  curl -s -o /dev/null -w '%{http_code}\n' -H 'Accept: text/html' -b f.jar http://127.0.0.1:8021/pop/work/start
  uv run pytest -q tests/test_qa1_errors.py -k without_referer
  ```
- **실측** `303 → /pop/work/start` → 그 주소의 GET 은 `405`. `POST /shp/shipments/{번호}/rolls` 도 같다. (`/mat/inputs` · `/rll/slitting` · `/qua/inspections` 는 같은 주소에 화면이 있어 200.) Referer 가 있으면 스캔하던 화면으로 돌아가고 알림·스캔칸이 함께 있다 — `test_pop_scan_post_422_returns_to_the_scan_screen` PASS.
- **기대** `api-contract.md` §2 「422(폼 POST): 303 → 원래 화면 + 알림」. 브라우저는 보통 Referer 를 보내므로 경미.
- **담당** 아키텍트 — `app/main.py` `_back_with_flash`(Referer 가 없으면 `request.url.path` 로 보낸다).
- **드러내는 테스트** `test_form_post_422_without_referer_lands_on_a_real_page` (1건).

### DEF-QA1-006 · 경미 · API 문서(`/docs` · `/redoc` · `/openapi.json`)가 로그인 없이 열린다

- **재현** `for p in /docs /redoc /openapi.json; do curl -s -o /dev/null -w "$p %{http_code}\n" http://127.0.0.1:8021$p; done` · `uv run pytest -q tests/test_qa1_errors.py -k api_docs`
- **실측** 셋 다 `200` — 엔드포인트 106개와 입력 항목 이름이 전부 보인다.
- **기대** 인증 없이 열리는 것은 `/health` · `/static/*` · 로그인 화면뿐이다(`api-contract.md` §2 · goal.md §2.5 「인증 실패 401」).
- **담당** 아키텍트 — `app/main.py` 의 `FastAPI(...)`. (QA3 의 보안 범위와 겹칠 수 있다. 닫아도 `check_screens.py` 는 `app.openapi()` 로 내려가 같은 검사를 한다.)
- **드러내는 테스트** `test_401_api_docs_are_not_open_to_anonymous[/docs|/redoc|/openapi.json]` (3건).

### DEF-QA1-007 · 경미 · 검사 결과 수정·삭제의 경로 키가 숫자가 아니면 404 가 아니라 422 + 영문 문구

- **재현** `curl -s -b qc.jar -X POST http://127.0.0.1:8021/qua/inspections/abc/delete` · `uv run pytest -q tests/test_qa1_errors.py -k non_numeric_path_key`
- **실측** `422` `{"fields":[{"name":"inspection_id","reason":"Input should be a valid integer, unable to parse string as an integer"}]}`. 같은 조작을 한 다른 7개(`/bas/items/abc` · `/bas/items/abc/delete` · `/prt/inks/abc/delete` · `/pop/work/abc/finish` · `/pop/stops/abc/resume` · `/clr/records/abc/delete` · `/clr/records/abc/mix`)는 `404 대상을 찾을 수 없습니다`.
- **기대** `api-contract.md` §1 「경로에 박힌 키가 없으면 404」 — 화면마다 같아야 하고 문구는 한국어여야 한다.
- **담당** 개발3 — `routers/qua.py` 의 `inspection_id: int`. (같은 종류의 영문 문구: `POST /login` 에 비밀번호가 빠지면 `422 … "Field required"` — 아키텍트 `main.py`. 상태코드는 맞다.)
- **드러내는 테스트** `test_404_non_numeric_path_key[/qua/inspections/abc]` · `[/qua/inspections/abc/delete]` (2건 · 나머지 7건 통과).

## 3. 실패하는 테스트 ↔ 결함

| 테스트 (`tests/test_qa1_errors.py`) | 건수 | 결함 |
|---|---|---|
| `test_nul_byte_input_is_not_500[…]` | 12 | DEF-QA1-001 |
| `test_out_of_range_number_is_422_not_500[mat·pop·clr·rll·qua]` | 5 | DEF-QA1-002 |
| `test_401_stopped_account_live_session_is_cut` | 1 | DEF-QA1-003 |
| `test_pop_scan_get_422_keeps_the_scan_box[/qua/inspections?no · /shp/shipments?no]` | 2 | DEF-QA1-004 |
| `test_form_post_422_without_referer_lands_on_a_real_page` | 1 | DEF-QA1-005 |
| `test_401_api_docs_are_not_open_to_anonymous[…]` | 3 | DEF-QA1-006 |
| `test_404_non_numeric_path_key[/qua/inspections/abc · …/delete]` | 2 | DEF-QA1-007 |
| 계 | **26** | |

`test_qa1_functions.py`(200) · `test_qa1_rbac.py`(746) 에는 실패가 없다.

## 4. 확인 필요 (결함으로 세지 않았다)

| # | 무엇 | 실측 | 왜 결함이 아닌가 / 누가 정하나 |
|---|---|---|---|
| C-1 | **D-14 의 해석** — 괄호 없는 `입력` 칸의 생산·현장이 입고검사 결과 등록(F-MAT-03) · 출하 승인(F-SHP-05)을 못 한다 | 생산·현장 × 두 기능 = 4쌍 전부 403. 실제 LOT·출하로도 403 이고 상태가 안 바뀐다(`test_denied_writes_change_nothing`) | 설계도 §6 은 생산·현장의 자재·입고와 출하를 괄호 없이 `입력` 이라고만 적었다 — 문면만 보면 그 대메뉴의 입력 전부다. D-14 는 「괄호 기능은 괄호가 붙은 역할만」 으로 좁혔다. goal.md G-17 이 요구하는 것(품질은 입고검사**만** · 관리자는 **승인**)은 둘 다 충족한다. 나머지 4쌍은 설계도가 말하지 않는다 → 현업 확인(D-14 에도 같은 질문이 있다) |
| C-2 | SQL 로 `sys_permission` 을 직접 바꾸면 **5.2초 뒤** 반영 | 화면 기능(F-SYS-06)으로 바꾸면 다음 요청부터 · SQL 직접은 5.2초(`rbac.CACHE_SECONDS = 5`) | D-106 에 적힌 동작이다. 워커 프로세스가 여럿이면 다른 워커는 화면으로 바꿔도 최대 5초 늦는다 — 단일 프로세스로만 쟀다 |
| C-3 | `use_yn='N'`(미사용) 역할의 계정이 로그인되고 그 역할의 칸이 그대로 적용된다 | 검사 전용 역할(`use_yn='N'`)의 계정 로그인 303 · 조회 칸 화면 200 | 역할의 「미사용」 이 무엇을 뜻하는지 계약에 없다(권한 화면의 열에서만 빠진다 — D-106) |
| C-4 | 슬리팅 **분할 수에 상한이 없다** | `count=200` → 200 · 슬리팅 롤 200개 · 0.07초 | 계약은 「N 이 1 미만이면 422」 만 말한다. 스캐너가 키보드라(D-04) 분할 수 칸에 바코드가 들어가면 그 수만큼 롤을 만들고(한 트랜잭션 · 계보 advisory lock 을 쥔 채), 롤을 지우는 기능은 없다 → 상한을 둘지 현업·아키텍트 확인 |
| C-5 | 정지 시각을 작업 시작보다 **앞선 시각**으로 줄 수 있다 | `stopped_at=0001-01-01T00:00:00` → 200 | D-202 는 「미래는 422」 만 정했다 |
| C-6 | 작업 종료(F-POP-02)는 없는 실적 + 빈 본문이면 404 가 아니라 422 | 본문(실적 수량)을 먼저 본다. 본문이 유효하면 404 | 422 와 404 의 순서는 계약에 없다. 키가 있는 다른 기능 34개는 빈 본문으로도 404 |
| C-7 | `/erp/{kind}` 가 GET·POST 를 한 함수로 받아 OpenAPI 가 `Duplicate Operation ID erp_call…` 경고를 낸다 | `/openapi.json` 을 만들 때 경고 1건 | 동작에는 영향 없다(아키텍트 `main.py`) |

## 5. 통과 항목 — 실측과 명령

### 5.1 G-01 · G-02 · G-03 (`uv run pytest -q tests/test_qa1_functions.py` → 200 passed)

| 항목 | 실측 | 테스트 |
|---|---|---|
| 설계도 §5 | 대메뉴 12 · 중메뉴 32 · 기능 94 · 대메뉴별 20·12·7·8·8·5·7·6·7·3·4·7 | `test_design_doc_counts` |
| 계약 100줄 | 화면 94 + 배치 6 · (대메뉴, 중메뉴) 쌍 = 설계도의 32쌍 · ID·API 중복 0 · 쓰기 54 · 읽기 40 | `test_contract_is_one_line_per_function` |
| 기능 94 실호출 | 94/94 — 404·405 0 · 쓰기 54 는 쓰는 테이블 SQL 확인 · 읽기 40 은 만든 값이 화면에 있음 | `test_function_works_through_its_api[F-…]` ×94 |
| 쓰기 성공의 모양 | 200 `{ok: true, message}` 81건 전부 · 브라우저 폼은 303 + 알림 한 번(두 번째 열면 없음) | 흐름의 각 단계 · `test_browser_write_success_is_303_with_one_time_flash` |
| 변경 로그 | 쓰기 54 기능의 성공한 호출 81건 전부 `sys_access_log` 에 `변경` · 그 기능 ID · 그 사용자로 한 줄 (G-18 판정은 QA3) | `test_write_function_leaves_change_log[F-…]` ×54 |
| 계보 | 투입 4 · splice 2 · 후가공 1 · 슬리팅 3 · 출하 2 = 12행 (설계도 §3 예시 10 + 1:1 후가공 2) | `test_flow_leaves_the_design_doc_genealogy` |
| 이관 배치 6 | `validate` rc 0 · 적재 0 · 로그 0 / `load-master` 품목 4 · 고객 2 · 공정 3 · 설비 2 · 불량코드 2, 재실행 뒤 같음, 로그 10 / `load-print-std` 1·1·1·조성 2 / `load-jobs` Job 2 · 생산 LOT 2 / `load-history` rc 0(빈 파일 5) · `미확정 (D-01)` 표기 / `report` rc 0 | `test_batch_command_runs[B-MIG-…]` ×6 |
| 화면 32 | 브라우저 GET 200 · placeholder 0 · 만든 값이 보임 32/32 | `test_screen_is_200_and_shows_real_data[…]` ×32 |
| 화면 ↔ API 1:1 | 쓰기 54 마다 그 API 로 보내는 POST 폼이 화면에 있다 · 읽기 40 마다 링크나 GET 폼이 있다 · 계약에 없는 POST 폼 0(로그아웃 제외) | `test_every_function_is_reachable_from_a_screen` · `test_no_form_posts_outside_the_contract` |
| 스캔 화면 | POP 채널로 연 10개 화면에 `data-scan autofocus` 입력칸이 정확히 하나 | `test_scan_screens_have_a_focused_scan_box` |
| 빈 항목 데이터 | 판사양·아니록스·잉크·설비 없는 Job · 길이·폭 없는 롤 · 검사 없는 출하로 12개 화면·출력물 200 · 매핑 `미수집` · COA 목록 `미발행` · COA `미수집` | `test_screens_render_with_sparse_data` |
| 공통 3 · 404 | `/` 200(역할 4) · `/login` 200 · `/error` 200 · 없는 주소 404 `대상을 찾을 수 없습니다` | `test_common_screens` · `test_every_role_opens_main` |

### 5.2 G-17 권한 48칸 전수 (`uv run pytest -q tests/test_qa1_rbac.py` → 746 passed)

기대값: 설계도 §6 표 — 48칸 = 입력 19 · 조회 24 · 없음 5. 쓰기 54 × 역할 4 = 216쌍의 기대는 **허용 84 · 403 128 · D-14 해석 4**.

| 항목 | 요청 수 | 위반 | 테스트 |
|---|---|---|---|
| DB `sys_permission` = 설계도 (칸마다 등급·괄호) | 48칸 | 0 | `test_db_cell_equals_design_doc` ×48 |
| 화면 GET — 없음 403 `접근 권한이 없습니다` · 그 밖 200 | 4 × 32 = 128 | 0 | `test_screen_get` ×128 |
| 메뉴 숨김 — 없음 대메뉴의 링크 0 · 그 밖은 전부 있음 (메인) | 48칸 | 0 | `test_menu_hidden_only_when_none` ×48 |
| 〃 (화면 안의 좌측 메뉴) | 43칸 | 0 | `test_menu_of_other_screens_also_hides_none` ×43 |
| 읽기 기능 40 × 역할 4 — 없음 403 | 160 | 0 | `test_read_function` ×160 |
| **쓰기 기능 54 × 역할 4** — 조회·없음 403 · 입력 허용(404·422) | 216 | 0 | `test_write_function` ×216 |
| 괄호 조건 2 — 품질 × 자재·입고: F-MAT-03 만 허용, F-MAT-01·07 403 / 관리자 × 출하: F-SHP-05 만 허용, F-SHP-01·02·03 403 | 7 | 0 | `test_bracket_conditions` |
| 미로그인 — 기능 94: JSON 401 `로그인이 필요합니다` · 브라우저 GET 303 `/login?next=…` · 브라우저 POST 401 화면 | 94 × 2 = 188 | 0 | `test_anonymous_is_401` ×94 |
| 실제 대상 + 유효한 본문으로 거부 — 403 이고 DB 가 그대로 | 18 | 0 | `test_denied_writes_change_nothing` |
| 순서 401 → 403 → 422 | 4 | 0 | `test_forbidden_comes_before_validation` |
| 권한 표는 데이터 | — | 0 | `test_permission_table_is_data` · `test_new_role_is_not_in_code` |

- 「입력 = 쓰기 가능」: 허용 84쌍 **전부** 권한 판정 통과(404·422)를 확인했다. 그중 **62쌍**은 흐름에서 실제 쓰기 200 + 행 확인까지 했다(기능 54개는 전부 포함). 나머지 22쌍은 같은 기능을 다른 허용 역할이 쓴 것으로만 확인했다.
- 「권한 표는 데이터」: 코드에 없는 역할 한 행(`sys_role`)을 넣고 그 역할의 계정으로 — 행 없는 칸 403 · 메뉴 숨김 → F-SYS-06 으로 `조회` → 다음 요청 200 · 메뉴 표시 → `BAS` 조회 칸의 쓰기 403 → `입력` 으로 바꾼 직후 422(통과) → `MAT 입력(입고검사)` 는 입고검사만 통과 · 입고 등록 403 → `SHP 입력(승인)` 은 승인만 통과 · 출하 등록 403 → `입력(일반,승인)` 은 둘 다 → SQL 로 `없음` 으로 바꾸면 5.2초 뒤 403. 그 역할 코드는 `src/` 어디에도 없다.
- **원상 확인**: 권한 표를 바꾼 것은 검사 전용 역할의 칸뿐이고 시드 역할 4개의 48칸은 한 번도 바꾸지 않았다. 마지막 실측 — `psql -h /tmp -d lcomfine_db -Atc "select level, count(*) from sys_permission group by 1"` → `없음 5 · 입력 19 · 조회 24`, `sys_role` 4, `sys_user` = admin · prod · qc · field, `Q1-` 행 0.

### 5.3 오류 계약 §2.5 (`uv run pytest -q tests/test_qa1_errors.py` → 130 passed · 26 failed)

| goal.md §2.5 의 행 | 판정 | 실측 (통과한 것) | 실패 |
|---|---|---|---|
| **422** 필수값 누락 | PASS | 경로에 키가 없는 쓰기 24개 전부 빈 본문 → 422 `validation_error` + 항목별 사유 (`test_422_missing_required` ×24) | — |
| **422** 코드 중복 | PASS | 마스터 8종 + 로그인 ID → 422, 행 수 그대로 (`test_422_duplicate_code` ×8 · `test_422_duplicate_login_id`) | — |
| **422** 없는 LOT/롤 스캔 | PASS (JSON) | POST 11종 · GET 스캔 진입 13종 전부 422 + 그 번호 (`test_422_scan_of_unknown_number_post` · `…_get` ×13) | 브라우저 화면은 DEF-004 |
| **422** 이미 출하된 롤 재출하 | PASS | 다른 출하·같은 출하에 다시 → 422, 출하 화살표 1개 그대로. 출하·소진 롤을 후가공·슬리팅·splice·출하에 → 422 (`test_422_reship_of_shipped_roll` · `test_422_shipped_or_consumed_roll_cannot_be_reused`) | — |
| **422** 자기 자신을 부모로 하는 계보 | PASS | 화면: 같은 롤 두 번 splice → 422 / `lineage.link` 자기 자신·순환 → 422, 행 0 / `lineage` 를 거치지 않은 SQL 은 DB CHECK 가 막고 핸들러가 422 로 바꾼다 (`test_422_self_parent_*` ×3) | — |
| **422** 기능별 계약 문장 | PASS | 사용 중 삭제 8종 · 코드 변경 · Job(실적 뒤 취소·수량 변경, 취소된 Job) · POP(취소 Job, 투입 0건 종료, 이미 종료, 정지/재개/폐기) · 자재(대기·불합격 LOT 투입, 투입 뒤 판정 변경) · 조색(합 ≠ 100, 같은 차수) · 검사(승인된 롤 수정·삭제) · 출하(다른 Job 롤, 불합격 롤, 승인된 출하, 롤 0개 승인, 이미 승인, 승인 뒤 취소, 미승인 COA) · 시스템(자기 삭제, 잠김 방지) | — |
| **422** 형식이 틀린 입력 | **FAIL** | — | DEF-001 · DEF-002 · DEF-007 |
| **POP** 은 다음 스캔을 막지 않는다 | **FAIL** | 중복·없는 LOT 스캔 422 뒤 다음 스캔 200 (`test_422_duplicate_scan_then_next_scan_works`) · 폼 POST 422 → 스캔하던 화면으로 303, 알림 + 스캔칸 5종 (`test_pop_scan_post_422_returns_to_the_scan_screen`) · 스캔 GET 422 가 같은 화면 7/9 | DEF-004 (2/9) · DEF-005 |
| **401** 인증 실패 | **FAIL** | 틀린 비밀번호·없는 ID → 401 + 세션 없음 + 로그 `로그인/실패` · 브라우저는 로그인 화면 401 · 위조 쿠키 401 · 로그아웃 뒤 401 · 중지 계정 로그인 401 · 브라우저 GET 303 `/login?next=…` · 기능 94 전부 401 | DEF-003 · DEF-006 |
| **403** 권한 없음 | PASS | `{"code":"forbidden","message":"접근 권한이 없습니다"}` · 오류 화면에도 같은 문장 · 전수는 §5.2 | — |
| **503** DB 연결 실패 | PASS | 접속 문자열을 없는 소켓으로 바꾸면 화면 32 전부 503 `서비스 일시 중단` · 기능 94 전부 503 `db_unavailable` · 역할 4 의 메인·현황판 503 · 로그인 503 · `/health` 503 `db.ok=false` · 정적 파일 200 · 되돌리면 200 (`test_503_*` ×3). **200 으로 멀쩡한 화면 0 · 500 0** | — |
| **501** ERP · 미확정 연계 | PASS | `/erp/status` · `/erp/orders` · `POST /erp/shipments` → 501 `ERP 연계 미확정 (D-02)` + `decision: D-02` · 화면에도 `미확정 (D-02)` · 미로그인 401 (`test_501_erp_is_undecided` ×4) | — |
| **500** 처리되지 않은 예외 | PASS | 시험용 경로에서 `RuntimeError` → 500 `예상하지 못한 오류`(JSON·화면) + `sys_access_log` 에 `오류/실패` 2줄(`500 RuntimeError: …`) (`test_500_unhandled_exception_is_logged`). 405 는 405 | — |
| 404 경계 (`api-contract.md` §1) | PASS | 경로에 키가 있는 기능 35개(쓰기 30 · 읽기 5)에 없는 키 → 404 `대상을 찾을 수 없습니다` (`test_404_missing_path_key` ×35) | DEF-007 (숫자가 아닌 키) |

## 6. 아키텍트 요청 (QA1 이 고치지 않은 남의 파일)

1. **`tools/gate.py` 연결은 맞다** — 고칠 것 없음. `per_gate()` 가 `check_screens` 의 G-02 · G-03 · G-17 행을 읽는다(§1). G-01 은 `check_screens` 가 행을 내지 않는다(`gate.py` 가 이 검사기에서 읽는 게이트가 셋뿐이다) — G-01 재확인은 pytest 쪽에 있다.
2. **`tools/check_routes.py` 의 계정 고르기** — 역할마다 `min(login_id)` 인 `정상` 계정으로 로그인한다. 품질 역할에 `qc` 보다 앞서는 로그인 ID 의 계정이 하나라도 있으면(다른 QA 가 만든 `q3c-…` 계정으로 실제로 겪었다) 시드 비밀번호로 로그인이 안 되어 품질 화면 전부가 401 이 되고 `G-03` · `G-21` 이 거짓 FAIL 이 된다. 재현: 품질 역할로 `q1-zz0000-u1` 계정을 만든 뒤 `uv run python tools/check_routes.py` → rc 1 · 「품질 → … 기대 200, 실제 401」 · 계정을 지우면 다시 PASS. `check_screens.py` 는 「그 역할에서 가장 먼저 만들어진 정상 계정」 으로 고른다.
3. `contracts/api-contract.md` — §3 에 `psycopg.DataError`(NUL · 범위 초과)도 422 라는 줄(DEF-001·002) · §2 표에 「브라우저 GET 의 422」 줄(DEF-004 · D-201).
4. `app/main.py` — `_back_with_flash` 의 Referer 없는 경우(DEF-005) · `FastAPI(docs_url=…)`(DEF-006) · `/erp/{kind}` 의 operation id 경고(C-7).

## 7. 재지 못한 것

- **실제 PostgreSQL 중단** — 규칙대로 멈추지 않았다. 503 은 테스트 프로세스의 접속 문자열을 없는 소켓으로 바꿔서 쟀다(연결 자체가 안 되는 경우). 쿼리 도중 끊기는 경우 · 접속 대기 시간이 긴 경우는 재지 않았다.
- **POP 의 브라우저 동작** — 「다음 스캔을 막지 않는다」 는 서버 응답(422 뒤 다음 요청이 되는가 · 돌아간 화면에 스캔칸과 알림이 있는가)까지만 봤다. 알림을 닫은 뒤 포커스가 돌아오는지, 알림이 떠 있는 동안의 스캔 글자가 버려지는지는 브라우저가 있어야 한다(QA3 · `progress.md` 의 `static/app.js` 항목).
- **워커 프로세스가 여럿일 때의 권한 캐시** — 단일 프로세스(서버 1 · TestClient)로만 쟀다(C-2).
- **`use_yn='Y'` 인 새 역할이 권한 화면의 열로 늘어나는지** — 공유 DB 에서 다른 QA 의 48칸 집계를 흔들 수 있어 `use_yn='N'` 역할로만 했다. 같은 이유로 **시드 역할의 실제 칸을 바꿔 보는 검사는 하지 않았다**(F-SYS-06 은 검사 전용 역할의 칸으로 같은 코드 경로를 탄다).
- **허용 84쌍 가운데 22쌍의 실제 쓰기 200** — 권한 통과(404·422)까지만 봤다(§5.2).
- **동시성** — 같은 롤을 동시에 출하·소진하는 경우, 같은 실적을 동시에 종료하는 경우는 재지 않았다(QA2 의 계보 범위와 겹친다).
- **`LCOMFINE_ENV=prod` 에서 500 응답이 원인 문구를 숨기는지** — dev 로만 돌렸다(dev 에서는 응답에 예외 문구가 나온다 — 설계된 동작).
- **이관 배치의 오류 경로**(틀린 파일 · 없는 참조 코드) — 정상 경로와 멱등만 봤다(G-15 는 QA3).
- **G-18 접근 로그 화면의 내용 · G-13 채널 레이아웃 · G-14 바코드 디코드** — QA3 범위라 「로그가 남는다 · `<svg` 가 있다 · `ch-pop` 이 붙는다」 까지만 봤다.

## 8. 남긴 것 · 치운 것

- 치운 것: `Q1-` 접두의 기준정보 · Job · 원재료 LOT · 실적 · 롤 · 계보 · 검사 · 출하 · 조색 · 이관 로그 · 계정 · 검사 전용 역할과 그 칸 · 그 대상의 `변경` 로그 → 남은 행 0 (`uv run python tools/check_screens.py --purge` 로도 지울 수 있다).
- 남은 것: 시드 계정으로 낸 접근 로그(`로그인` · `조회`)와 DEF-001 · 002 를 재현하며 생긴 `오류` 로그(실제 500 의 흔적이라 지우지 않았다) · 채번 카운터(`sys_number_seq`)의 소비분. 시드 행은 바꾸지 않았다.
- 서버: 포트 8021 만 썼고 내렸다(`lsof -iTCP:8021 -sTCP:LISTEN` → 0줄). git 커밋 없음.
