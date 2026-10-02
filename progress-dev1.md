# progress-dev1 — 개발1 (기준·지시·시스템 / 기능 46)

> §1 공표(다른 사람이 그대로 쓰는 것) · §2 진행 · §3 요청(스키마·계약·공용 파일). 실측한 것만 적는다.

## 1. 공표 — 채번 `app/numbering.py` (2026-10-03 · 구현됨, 지금 불러도 된다)

**형식은 가설이다(D-05 · D-101).** 현업 채번 규칙을 받으면 `sys_number_rule` 행만 바꾼다 — 코드와 호출부는 그대로다.

```
번호 = prefix + to_char(기준 시각, date_format) + 일련번호(seq_digits 자리, 0 채움)
```

| 종류 `kind` | 어디에 | prefix | date_format | seq_digits | 예 (2026-10-03 의 첫 번호) |
|---|---|---|---|---|---|
| `JOB` | `job.job_no` | `J` | `YYMMDD-` | 3 | `J261003-001` |
| `JOB_LOT` | `job_lot.lot_no` | `L` | `YYMMDD-` | 3 | `L261003-001` |
| `MAT_LOT` | `material_lot.lot_no` | `M` | `YYMMDD-` | 3 | `M261003-001` |
| `ROLL` | `roll.roll_no` | `R` | `YYMMDD-` | 4 | `R261003-0001` |
| `SHIPMENT` | `shipment.shipment_no` | `S` | `YYMMDD-` | 3 | `S261003-001` |
| `COA` | `shipment.coa_no` | `C` | `YYMMDD-` | 3 | `C261003-001` |

- 6행은 이미 DB 에 들어 있다(`uv run python -m lcomfine.db.seed_dev1` — 멱등, 이미 있는 행은 건드리지 않는다).
- 글자는 영문 대문자·숫자·`-` 뿐이다(Code 128 바코드에 그대로 찍힌다). 구분 기호 `-` 는 `date_format` 안의 글자다.
- 카운터(`sys_number_seq`)의 범위는 **날짜 부분의 값**(`261003-`)이다 → 날짜가 바뀌면 001 부터. `date_format` 이 빈 글자면 통산 일련번호.
- 일련번호가 자릿수를 넘으면(예: 하루 1000번째 Job) 자르지 않고 자릿수가 늘어난다(`J261003-1000`). 겹치지 않는 것이 먼저다.
- **첫 글자로 번호 종류를 가정하지 않는다.** 접두는 데이터라 바뀔 수 있다. 스캔값이 무엇인지는 테이블을 찾아서 판정한다(`lineage.resolve`).

사용법 (시그니처는 `contracts/interfaces.md` §3 그대로 — 바꾸지 않았다):

```python
from lcomfine.app import numbering

# 업무 행과 함께 성공/실패해야 하면 tx 의 커서를 준다 — 롤백되면 카운터도 되돌아간다(번호가 비지 않는다)
with conn.tx() as cur:
    roll_no = numbering.next("ROLL", cur=cur)          # numbering.ROLL 상수도 있다
    cur.execute("insert into roll (roll_no, …) values (%s, …)", (roll_no, …))

numbering.next("MAT_LOT")            # cur 없이 — 자체 트랜잭션으로 발번하고 곧바로 커밋
numbering.next("JOB", at=some_dt)    # 날짜 부분의 기준 시각을 준다(이관·테스트). 기본 now()
numbering.peek("JOB")                # 발번하지 않고 다음 번호만 (화면 미리보기)
numbering.rule("JOB")                # sys_number_rule 행(dict) 또는 None → 화면은 `미확정 (D-05)`
```

- 종류가 `KINDS` 밖이면 `ValueError`. 형식 행이 없으면 `RuntimeError`(500 — 설정 누락은 사용자 입력 오류가 아니다).
- 동시성: `insert … on conflict do update … returning` 한 문장으로 카운터 행을 잠그고 올린다. 같은 (종류, 날짜)를 동시에 부르면 뒤쪽이 앞 트랜잭션의 커밋/롤백을 기다린다.
  → **`cur=` 를 준 트랜잭션은 짧게 끝낸다**(발번 뒤 오래 붙잡으면 같은 종류의 다른 발번이 그동안 기다린다).
- 테스트에서 발번하면 `sys_number_seq` 카운터가 올라간다(행 수는 (종류, 날짜)당 1행이라 그대로). 테스트가 `cur=` 로 부르고 롤백하면 카운터도 원래대로다.
- 번호를 다른 곳에서 조립하지 않는다(G-08). 테스트용 행도 가능하면 `numbering.next` 로 번호를 받는다. 직접 지어 넣는 번호는 위 형식과 겹치지 않게(예: `T2-…`).

검증: `uv run pytest -q tests/test_dev1_numbering.py`

## 2. 진행 (2026-10-03 실측)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 채번 | `app/numbering.py` 구현(스텁 아님) · `sys_number_rule` 6행 · 8 스레드 × 25회 = 200번 동시 발번에서 겹침 0 · 빠짐 0 · `cur=` 발번은 호출자 트랜잭션과 함께 롤백 | `uv run pytest -q tests/test_dev1_numbering.py` → 8 passed |
| 시드 | 채번 형식 6 + 품목 5 · 고객 2 · 공정 3 · 설비 3 · 불량코드 4 · 판사양 2 · 아니록스 2 · 잉크조성 2(조성 행 3). 이름 전부 `(예시)`. **2회 실행 출력 동일(diff 0)** | `uv run python -m lcomfine.db.seed_dev1` ×2 |
| 화면 | 담당 중메뉴 13 + 메인 — placeholder **0**, 관리자로 전부 200. (전체로도 HTTP 200 35/35 · placeholder 0 · 권한 위반 0) | `make check-routes` → PASS |
| 기능 ↔ 라우트 | 담당 46기능의 API(메서드·경로)가 전부 등록 · 담당 모듈 아래 계약에 없는 엔드포인트 0 | `uv run pytest -q tests/test_dev1_home.py -k routed` — **`make check-trace` 는 지금 0/94 로 나온다(도구 문제, §3-1)** |
| 기능 ↔ 테스트 표식 | 담당 46기능 전부 `@pytest.mark.fn` 표식 있음(46/46). 전체는 91/100(남은 9 는 다른 담당) | `make check-trace` 의 「기능 100 ↔ 테스트」 행 · 담당분은 표식 정규식으로 따로 셈 |
| 권한 | 담당 46기능 × 시드 4역할 전수 — 권한 표에서 못 하는 역할은 403(조회 역할의 쓰기 · 없음 역할의 조회·쓰기), 미로그인 401. 권한 판정이 입력값 검증보다 먼저 | `uv run pytest -q tests/test_dev1_home.py` → 51 passed |
| 권한 표 편집 | 한 칸 수정이 다음 요청부터 반영(없음 → 조회 → 입력 → 없음) · 괄호 범위 · 관리자의 시스템 관리 칸 내리기 422 | `uv run pytest -q tests/test_dev1_sys.py -k permission` |
| 접근 로그 | 로그 화면에 로그인 성공·실패, 화면 조회, 데이터 변경이 보임. 쓰기 32기능 전부 성공 직후 `audit.log_change` | `uv run pytest -q tests/test_dev1_sys.py -k logs` · 쓰기 테스트마다 `change_logs(...) == 1` |
| 작업지시서 | `GET /job/orders/{job_no}/print` — `printing.barcode_svg` 의 Code 128 바코드(값 = Job 번호 그대로) + 품목·고객·판사양·아니록스·잉크조성(조성 행)·수량·납기·생산 LOT | `uv run pytest -q tests/test_dev1_job.py -k print` · 포트 8021 에서 화면 확인 후 서버 내림 |
| pytest (담당) | **127 passed** — numbering 8 · bas 27 · prt 19 · job 10 · sys 12 · home 51 | `uv run pytest -q tests/test_dev1_*.py` |
| pytest (전체, 참고) | 251 passed (내가 돌린 시점. 다른 담당의 테스트가 계속 늘고 있다) | `uv run pytest -q` |
| 테스트가 남긴 것 | `T1-…` 기준정보 0 · `t1…` 계정 0 · 임시 역할 0(`sys_role` 4 · `sys_permission` 48) · 1999년 카운터 0 | `psql` 로 접두 조회 |

만든 파일 — `app/numbering.py` · `app/routers/{home,bas,prt,job,sys}.py` · `templates/bas/master.html` · `templates/prt/inks.html` ·
`templates/job/{orders,print,mapping}.html` · `templates/sys/{users,permissions,logs}.html` · `templates/home/main.html` ·
`db/seed_dev1.py` · `tests/test_dev1_{helpers,numbering,bas,prt,job,sys,home}.py`. 결정은 `decisions.md` D-101~D-106.

구조 메모
- 기준정보 5종과 인쇄 기준 3종은 전부 마스터 4기능이라 `routers/bas.py` 의 `Master` + `register()` 한 벌이 처리한다(`prt.py` 가 가져다 쓴다). 화면도 `bas/master.html` 한 벌. 잉크조성만 조성 행 갈고리 3개.
- 삭제를 막는 참조는 DB 의 FK 카탈로그에서 읽는다 — 스키마에 FK 가 늘면 따라간다(D-102).
- 수정 화면은 별도 경로를 만들지 않고 화면 GET 의 `?edit=<id>`(마스터·사용자) · `?no=<Job 번호>`(작업지시·매핑)로 연다 — 계약에 없는 엔드포인트를 만들지 않으려는 것이다(고아 라우트 0).
- 테스트 도우미는 `tests/test_dev1_helpers.py`(테스트 함수 없음) — `conftest.py` 는 내 파일이 아니라 만들지 않았다.

확인하지 못한 것
- 실제 브라우저에서의 조작(클릭·폼 제출·인쇄 미리보기)은 하지 않았다. 한 것은 TestClient/curl 로 303 흐름과 알림, 헤드리스 크롬으로 정적 렌더 캡처(레이아웃)까지다.
- `make gate` 의 G-08·G-11·G-12·G-14·G-18 은 QA 검사기가 없어 `미검증` 으로 나온다 — 내 쪽 근거는 위 표의 테스트뿐이다.
- 워커 프로세스가 여럿일 때 권한 변경의 전파(다른 워커는 캐시 5초)는 재 보지 않았다.

## 2-D. 웨이브 D 2차 — 작은 마무리 수정 (2026-10-03 · 실측)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 진행 중인 실적이 있는 Job 의 마감 (D-107) | 종료되지 않은 실적(`진행`·`정지`)이 있으면 `POST /job/orders/{job_no}` 의 `status=완료` 가 **422**, 사유에 열린 실적마다 한 줄(`작업 실적 <번호>` · 상태 · 시작 · 작업자). 개발2 실측의 순서(열린 실적 → 마감 → 종료 → 마감된 Job 에 인쇄 롤)를 그대로 밟으면 첫 걸음에서 막히고, 실적 종료(F-POP-02 실제 API)는 그대로 200 · 롤은 `등록` Job 에 생기며 · 그 뒤 마감 200 | `uv run pytest -q tests/test_dev1_job.py -k "close or closed"` → 3 passed |
| 마감의 잠금 | Job 행 `for update` 뒤 같은 트랜잭션에서 세고 바꾼다 — 커밋 전인 실적 삽입이 있으면 기다렸다가 422. 잠금을 빼면 그 테스트가 실패하는 것을 확인(변이 1), 규칙을 빼면 3건 실패(변이 2) | `tests/test_dev1_job.py::test_close_waits_for_a_work_result_being_inserted` · 변이는 `job.lock_job`/`job.open_works` 를 프로세스 안에서 바꿔 치기해 실행(파일은 그대로) |
| 취소 (F-JOB-03) | 규칙 변경 없음 — 실적이 `진행`·`정지`·`완료` 어느 상태든 한 건이면 422(롤이 없어도). 세는 것과 바꾸는 것을 한 트랜잭션으로 묶었다 | `uv run pytest -q tests/test_dev1_job.py -k cancel` |
| 사용자 화면 문구 (D-108) | "다음에 로그인할 때부터" → 「역할·이름은 다음 요청부터 · 잠금·중지·비밀번호 초기화는 그 계정의 세션을 곧바로 끊음 · 자기 비밀번호 초기화는 자기 세션도 끊음」. 임시 계정으로 문구대로 동작함을 확인(역할 올림·내림·이름이 같은 세션의 다음 요청에 반영 / 잠금 → 두 세션 모두 401, `정상` 복귀 뒤에도 401 / 비밀번호 초기화 401 / 중지 401 / 자기 초기화 뒤 브라우저 GET 은 `/login` 303) | `uv run pytest -q tests/test_dev1_sys.py -k "session"` → 2 passed |
| 임시 `.req` 인라인 스타일 | `bas/master.html` · `job/orders.html` · `sys/users.html` 에서 제거. 공용 `static/style.css` 60·65행이 같은 규칙(`label{position:relative}` · `label>.req{position:absolute;top:0;right:2px}`). 헤드리스 Chromium(포트 8021)으로 5화면(`/bas/items` · `/prt/inks` · `/job/orders` · `/sys/users` · `/sys/users?edit=admin`) — 필수 칸 16개 전부 `position:absolute` · 같은 줄의 입력칸 높이 어긋남 0 · 페이지 안 `.req` 인라인 규칙 0. 서버는 내렸다 | 측정 스크립트(스크래치) + 캡처 육안 |
| pytest (담당 + 아키텍트) | **166 passed** — dev1 132(numbering 8 · bas 27 · prt 19 · job 13 · sys 14 · home 51) + arch 34 | `uv run pytest -q tests/test_dev1_*.py tests/test_arch_*.py` |
| 회귀 (QA1) | 1101 passed · 1 failed — 실패는 이미 알려진 `test_qa1_rbac.py::test_forbidden_comes_before_validation`(QA1 자기 모순) | `uv run pytest -q tests/test_qa1_functions.py tests/test_qa1_rbac.py tests/test_qa1_errors.py` |
| 회귀 (계보 시나리오) | **53 passed** — 마감 규칙과 충돌 없음(이 시나리오들은 실적이 열린 채 Job 을 마감하지 않는다) | `uv run pytest -q tests/test_dev2_pop.py tests/test_lineage_scenario.py tests/test_qa2_lineage.py` |
| 테스트가 남긴 것 | `T1-…` 품목·Job·원재료 LOT·롤·실적·투입 0 · `t1…` 계정 0 · `sys_user` 4(전부 `정상`) · `sys_role` 4 · `sys_permission` 48 | `psql` 로 접두 조회 |

기존 테스트 가운데 새 규칙과 부딪힌 것은 **내 테스트 1건**뿐이다 — `test_update_order_rules` 가 열린 실적(SQL 로 넣은 `진행`)이 있는 채 마감 200 을 기대했다 → 실적을 `완료` 로 넣도록 고쳤다(기대값 200 은 그대로, 전제만 규칙에 맞춤).

확인하지 못한 것 (이번 회전)
- `make gate`/`gate-full` · `tools/check_*.py` 는 돌리지 않았다(개발3 과 겹침). `tools/check_data.py` 2356행이 `prod` 로 Job 을 마감하는데 **실적이 없는 Job** 이라 새 규칙에 걸리지 않는다고 **읽어서** 판단했다 — 실행 확인은 다음 `gate-full`.
- 작업 시작(F-POP-01)과 마감이 수 ms 차로 엇갈리는 경우(§3-8)는 재현하지 않았다.
- 마감 422 의 브라우저 화면(알림 팝업의 사유 줄)은 보지 않았다 — JSON 응답과 화면 HTML(진행 중 건수 · `완료` 선택 불가)까지 확인.

## 2-E. 웨이브 D 3차 — DEF-QA2-004 의 같은 꼴 ⓐ·ⓒ (`routers/job.py`) · 2026-10-03 실측 (수정 담당이 혼자 돌며 개발1 파일을 고침)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| ⓐ 생산 LOT 붙이기·계획 수정 × 취소·마감 | 창 있었다(상태를 트랜잭션 밖에서 읽고 `job_lot` 을 넣음 — 취소를 잠금 직후에 세워 두면 FK 를 기다렸다가 200). `share_job`(`for share`) + 재확인으로 닫음 → 기다렸다가 422 · `job_lot` 0 | `uv run pytest -q tests/test_dev1_job.py -k mapping_waits` → 2 passed |
| ⓒ 품목·수량 변경 × 작업 시작 | 창 있었다(`work_count` 를 트랜잭션 밖에서 읽음 — 작업 시작을 잠금 직후에 세워 두면 UPDATE 가 기다렸다가 200). `lock_job` 뒤 `work_count` 재확인으로 닫음 → 422 · 수량·비고 그대로 | `tests/test_dev1_job.py::test_item_and_quantity_change_waits_for_a_work_start_in_flight_and_then_refuses` |
| 수정·마감 × 취소 · 취소 × 취소 | 같은 꼴 — 취소된 Job 이 고쳐지거나 되살아남 · 둘 다 200. `lock_job` 이 상태를 돌려주고 `취소` 면 422 | `-k "cancel_in_flight or two_cancels"` → 2 passed |
| 규칙·문장 | 바꾸지 않았다 — 순차 요청의 결과는 전과 같다(`tests/test_dev1_job.py` 18 passed) | `uv run pytest -q tests/test_dev1_job.py` |
| 변이 | `share_job` 상수 반환 · `work_count` 0 반환 · `lock_job` 상태 무시 — 각각 해당 테스트 실패 | 스크래치 변이 스크립트 (파일은 그대로) |
| 테스트 도우미 | 「앞 요청을 잠금 직후에 세워 두기」 는 `test_dev2_helpers.pause_after` 를 가져다 쓴다(한 벌만 둔다 — 개발2 파일 import) | — |

## 3. 요청 (스키마 · 계약 · 공용 파일)

1. **[도구 · 아키텍트] `tools/check_trace.py` 가 라우트를 하나도 못 본다 → G-02 「기능 94 ↔ 라우트」 가 항상 0/94.**
   설치된 FastAPI 0.142.2 는 `app.include_router(r)` 한 라우터를 `app.routes` 에 풀어 넣지 않고 `_IncludedRouter`(속성 `original_router`) 한 덩어리로 둔다.
   도구는 `for rt in app.routes` 로만 돌아서 `path`·`methods` 가 없는 덩어리를 건너뛴다. 「고아 라우트 0」 도 같은 이유로 **검사 없이 PASS** 다.
   고칠 곳(제안): 라우트를 펴서 센다 —
   ```python
   def all_routes(routes):
       for rt in routes:
           inner = getattr(rt, "original_router", None)
           if inner is not None:
               yield from all_routes(inner.routes)
           else:
               yield rt
   ```
   이렇게 펴서 같은 식으로 세어 본 값(2026-10-03 내 실측): **이어진 기능 94/94**(개발1 46/46) · placeholder 0. `tests/test_dev1_home.py::test_every_dev1_function_is_routed` 가 담당분을 같은 방법으로 확인한다.
   `tools/gate.py` · `tools/check_routes.py` 에 `app.routes` 를 직접 도는 곳이 더 있으면 같이 본다(`check_routes` 는 경로를 `nav` 에서 읽어 영향 없음 — PASS 확인).
2. **(해결됨 — D-26 · 화면 문구는 D-108 로 갱신)** **[공용 · 아키텍트] 중지·잠금된 계정의 살아 있는 세션이 계속 통한다.** `rbac.current_user` 가 세션 쿠키의 사용자·역할만 읽고 DB 를 다시 보지 않는다.
   실측: 임시 관리자 계정으로 로그인 → 관리자가 그 계정을 삭제(상태 `중지`) → **같은 세션으로 `GET /sys/users` 200**(새 로그인은 401). 역할 변경도 다음 로그인부터다.
   사용자 삭제(F-SYS-03)·수정(F-SYS-02)의 효과가 즉시 나게 하려면 `rbac.require_login`(또는 세션 미들웨어)에서 계정 상태·역할을 확인해야 한다 — `rbac.py`·`auth.py` 는 내 파일이 아니라 손대지 않았다. 화면에는 "다음 로그인부터 적용" 이라고 적어 두었다(D-105).
3. **(필수 표시는 해결됨 — 공용 CSS 반영 · 인라인 제거. 버튼 줄·삭제 확인의 공용화는 남아 있다)** **[공용 CSS · 아키텍트] 필수 표시 `*` 가 한 줄을 차지한다.** `.form-grid label` 이 세로 flex 라 `ui.field(required=true)` 의 `<em class="req">` 가 별도 줄이 되고 그 칸만 아래로 밀린다.
   내 템플릿 3곳(`bas/master.html` · `job/orders.html` · `sys/users.html`)에는 임시로 인라인 스타일(`label>.req{position:absolute…}`)을 넣었다. `static/style.css` 에 반영되면 지운다.
   같이 공용화하면 좋은 것: 버튼 줄(`.row-actions`/`.form-actions`) · 삭제 확인(`form[data-confirm]` — 지금은 템플릿마다 인라인 스크립트 4줄).
4. **[계약 · 아키텍트] `contracts/interfaces.md` §3 에 조립식 한 줄** — `번호 = prefix + to_char(기준 시각, date_format) + 일련번호(seq_digits 자리)`, 카운터 범위 = 날짜 부분의 값, 자릿수 초과 시 늘어남. 지금은 이 파일 §1 과 D-101 에만 있다. 시그니처는 계약 그대로라 호출부는 바뀌지 않는다.
5. **[계약 · 아키텍트] F-BAS-03 문장의 「참조(Job·원재료 LOT·판사양·잉크조성)」** — 스키마의 `ink_formula` 에는 품목을 가리키는 컬럼이 없다. 코드는 DB 의 FK 를 따라가므로 지금 품목 삭제를 막는 것은 `job` · `material_lot` · `plate_spec` 이다. 계약 문장에서 잉크조성을 빼거나, 잉크조성에 품목 FK 가 필요하면 스키마에 더한다(더하면 코드는 그대로 따라간다).
6. **[계약 · 아키텍트] 내 결정 D-101~D-106 을 `function-list.md` 문장에 반영할지** — 특히 D-103(작업 실적 뒤 잠기는 항목 · `완료` ↔ `등록` 되돌리기) · D-104(`등록` 상태 Job 에만 매핑) · D-106(잠김 방지 범위). 계약에 문장이 없던 곳을 최소로 정한 것이다.
7. **[계약 · 아키텍트] F-JOB-02 문장에 D-107 한 줄** — 넣을 문장: 「**진행 중인(종료되지 않은 — `진행`·`정지`) 작업 실적이 있는 Job 은 `완료` 로 마감할 수 없다 — 422, 사유에 열려 있는 실적이 보인다. 작업을 종료한 뒤 마감한다(D-107).**」 F-JOB-03 은 문장 그대로 맞다(진행 중 실적만 있어도 「실적이 있으면 422」).
   같이 볼 곳: `db-schema.md` §7 의 `job.status` 줄(「`등록` → `완료`」 에 조건 한마디) · D-208 끝 줄 「막지 않은 것」 은 이 결정으로 닫혔다.
8. **(해결됨 — 웨이브 D 3차 · D-211, 같은 꼴은 `job.py` 쪽도 D-109)** **[개발2 · `routers/pop.py` 작업 시작] Job 상태를 트랜잭션 밖에서 읽는다.** `work_start` 가 `job_of()` 로 상태를 본 뒤 따로 연 트랜잭션에서 실적을 넣는다 — 그 사이(수 ms)에 마감·취소가 끝나면 `완료`·`취소` Job 에 열린 실적이 생길 수 있다(재현하지 않았다 · 내 쪽 잠금으로는 못 막는 방향).
   실적을 넣는 트랜잭션 안에서 `select status from job where job_id = %s for share` 로 다시 보면 닫힌다(`lineage` 의 D-208 판정과 같은 방식).

(해결됨) 작업지시서 바코드 — 시작할 때는 `app/printing.py` 가 스텁일 수 있어 "준비되면 연결" 로 적을 예정이었으나, 화면을 만들 때 개발2 의 `printing.barcode_svg` 가 이미 구현돼 있어 바로 연결했다. 남은 요청 없음.
