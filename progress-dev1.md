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

### 1.4 공통코드 (SYS-030 · F-SYS-031) — 다른 라우터가 읽는 그룹 글자 (W3 공표)

| 그룹 코드(`sys_common_code.group_code`) | 뜻 | 지금 읽는 곳 (실측 `grep -rn sys_common_code src/lcomfine`) |
|---|---|---|
| `설비` | 설비 코드 | `routers/wo.py`(지시 설비 선택 · 작업 순서) · `routers/prd.py`(생산일보 설비) · `routers/inv.py` · `stats.py` |
| `불량유형` | 검사일보 `defects` 의 키 | `routers/ins.py` |
| `수금수단` | ERP 행 `parsed.method` | `routers/col.py`(COL-040 수단 필터 = 공통코드 ∪ 반영 행의 수단 글자 · D-802) |

- 그룹 글자는 `routers/sys.py` `CODE_GROUPS = ("설비", "불량유형", "수금수단")` 과 같다(정본 3 — 다른 그룹은 422). 읽는 쪽은 `select code, code_name from sys_common_code where group_code = '<그룹>' and use_yn = 'Y' order by sort_no, code` 모양이면 된다 — 사용 중지(`use_yn = 'N'`)는 새 선택에서 빼고, 이미 저장된 값은 그대로 보인다(wo · ins 가 그렇게 한다).
- 기본 행은 공통 시드 `seed.py` `COMMON_CODES`(설비 2 · 불량유형 3 · 수금수단 3 · 전부 `(예시)`). `seed_dev1.run()` 은 **빈 그룹에만** `(예시)` 코드 하나(`EX-EQ` · `EX-DF` · `EX-PM`)를 더한다(D-609). 삭제는 참조가 있으면 사용 중지(D-606).

### 1.5 `app.sso` (W4 · D-514 · D-610) — 문서관리 SSO 토큰의 한 곳

```python
sso.issue(cur, user, *, now=None) -> tuple[str, str]   # (token, jti) · 쓰기 트랜잭션 커서 · sso_token 1행 · 사용자 상태·매핑을 DB 에서 다시 읽는다
sso.consume(cur, token, *, now=None) -> dict            # {jti, user_id, account_id, login_id, issued_at, expires_at, used_at} · 1회 사용
sso.refusal(cur, user_id) -> (사유 | None, 매핑 행 | None)  # 발급을 막는 사유 — DOC-010 안내 화면과 issue 가 같은 판정
sso.NotMapped(reason)   # 발급 거부 — 비활성(정상 아님) · 매핑 없음 · 매핑 사용 중지
sso.Invalid(reason)     # 검증 거부 — 형식 · 서명 · 만료 · 이미 사용 · 발급 기록 없음 · 비활성 · 매핑 사용 중지/변경
sso.NotConfigured       # LCOMFINE_SSO_SECRET 없음 — 발급 · 검증 모두 안 함
sso.TTL_SECONDS = 60 · sso.REQUEST_MAPPING = "관리자에게 계정 연결을 요청하세요" · sso.configured()
```
- interfaces.md §9 의 공표 시그니처에 `now`(시각 주입 · UTC aware) · `Invalid` · `NotConfigured` · `refusal` 을 더했다(§3 요청 9).
- 토큰 글자는 `sso_token` · 로그 어디에도 남지 않는다. 문서관리 시스템 쪽 검증 규칙은 `consume` 이 그대로 재현한다(연계 상대에게 이 함수의 규칙을 넘긴다).
- SSO 로그(`sys_access_log` 구분 SSO): `screen_id = DOC-010` · `function_id = F-DOC-011` · `result` 성공/실패 · `detail` 사유 · 성공은 `target = sso_token:<jti>` — §3-6 메모대로라 SYS-040 SSO 탭이 그대로 보인다.

## 2. 진행 (W1 · 2026-10-21)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 담당 기능 (W1 범위 HOME · BAS · STD · WO · SYS · TRK) | **62 / 62** 라우트 + `@pytest.mark.fn` — HOME 5 · BAS 12 · STD 23 · WO 10 · SYS 9 · TRK 3 | `uv run python tools/check_trace.py` — 고아 ①③ 목록에 F-HOME/BAS/STD/WO/SYS/TRK 0 (남은 27 중 개발1 은 DOC 6 · W4) |
| 개발1 테스트 | **66 passed** (test_dev1_common 2 · bas 12 · std 23 · wo 10 · home 5 · sys 9 · trk 3 · jobs 2) + QA3 `test_nul_input_names_the_field` PASS → 67 | `uv run pytest -q tests/test_dev1_*.py tests/test_qa3_robustness.py::test_nul_input_names_the_field` |
| 개발1 placeholder | 화면 23 등록 · 남은 2 = DOC-010 · DOC-020 (W4) | `make gate` G-03 「개발1 2」 |
| 빌드 전제 | pytest 189 passed · /health 200 | `make gate` (읽기 전용 · 19:47) |
| 배치 | `due-check` — 대상 의뢰 · 새 알림 행 수를 찍는다. 같은 날 재실행 0행 | `uv run python -m lcomfine.jobs due-check` · tests/test_dev1_jobs.py |
| 시드 | `seed_dev1.run()` 두 번 → item 4 · customer 2 · location 2 그대로 (전부 `(예시)`) | `uv run python -c "from lcomfine.db import seed_dev1; seed_dev1.run()"` |
| 결정 | D-601~D-607 (가설) | decisions.md |

| **W1 QA 수정 · DEF-QA3-002** (경미) | 글자 입력의 NUL(0x00) 을 라우터가 먼저 422 로 막고 항목을 짚는다 — `routers/bas.py` 공용 헬퍼 `s(v, label)`(label 필수) · `need` · `ref_id` · `qty` · `integer` · `day` · `yn` · `choice` · `like(v, label="검색어")` · `kv_text` 전부 같은 검사 · 응답 `bad(label, "글자에 NUL(0x00)을 넣을 수 없습니다")`(개발2 와 같은 문장). 개발1 라우터의 `s()` 호출 76 곳(bas 21 · std 25 · wo 16 · sys 6 · trk 8)에 폼 화면의 한국어 라벨을 붙였다 — 무라벨 호출 0 | `uv run pytest -q tests/test_qa3_robustness.py::test_nul_input_names_the_field` PASS · `tests/test_dev1_common.py::test_nul_input_names_the_field_dev1`(표본 10 · 조회 인자 1 · F-BAS-011/021/031 · F-STD-021 · F-WO-011 · F-SYS-011/031) PASS · `grep -nE "(?<![\w.])s\(\w+\)" routers/{bas,std,wo,sys,trk}.py` → `def s(` 만 |
| **W1 QA 수정 · Ruling 24 (F-HOME-031)** | HOME-030 은 자기 부서가 수신하는 이벤트만 보인다(전부 「부서 기본」 · 끌 수 없음). 「개인 추가」 칸과 「다른 부서로 가는 이벤트를 켜도 알림함에 나타나지 않는다」 안내 문장을 뺐다. 저장: 다른 부서 이벤트 키가 오면 저장하지 않고 422 「다른 부서로 가는 알림은 구독할 수 없습니다 — 범위 밖 (D-511)」 · 부서 기본 끄기 422 · 메일·메신저 501 · 누락 422 · 범위 밖이 된 `notification_setting` 행(다른 부서 이벤트)은 저장 때 지운다(응답 `removed_out_of_scope`). 수신 이벤트가 없는 부서(전산 관리자)는 칸·저장 버튼 없음 | `tests/test_dev1_home.py::test_notification_settings_save` · `::test_notification_settings_view` PASS |

### 2-W2. 진행 (W2 수금 — 개발3 공표 `stats` 를 TRK · HOME 에 붙임 · 2026-10-22)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| **TRK-030 수금·미수 칸** (F-TRK-031) | `stats.customer_receivable(cid)` 하나로 채운다 — `status` `미수집` → `ui.empty("미수집")` · `미확정 (D-516)` → `ui.undecided("D-516")`(매출 · 미수 잔액 칸 · 수금 합은 수치) · `ok` → 매출 · 수금 · 미수 잔액 · 마지막 거래일 · **ERP 업로드 기준일(asof)** 표(+ 상단 KPI 「미수 잔액」). 자체 `erp_asof` SQL 을 지웠다(`routers/trk.py` 에 `erp_upload_batch` 조회 0 — asof 는 `customer_receivable["asof"]` = `stats.erp_asof()`). 패널 `data-receivable="<status>" data-asof="<asof>"` | `tests/test_dev1_trk.py::test_customer_receivable_from_erp_upload` — (예시) xlsx(openpyxl · 기간 1985-01) → `POST /col/uploads` → 화면에 1,500 · 1,200 · 1985-01-20 · asof · 끝에 회차 · 행 · 알림 · 매핑 삭제(`Erp.close`) · `grep -n erp_upload_batch src/lcomfine/app/routers/trk.py` → 0 |
| **TRK-020 납기 준수율** (F-TRK-021) | 수치 = `stats.due_compliance(period)` · `period` 조회 인자 `YYYY-MM`(`<input type="month">` · 기본 이번 달) · `rate` None → `미수집`(0 % 로 적지 않는다) · 산식 문장 `compliance.formula`(가설 D-804) 를 수치 옆에 · 형식이 틀리면 422 「조회 기간: YYYY-MM 형식으로 입력해 주세요 — <값>」. KPI `data-compliance="<소수1>|미수집" data-period="YYYY-MM"`. **진행 · 단계 조회(`progress`)와 D-3 · D-7 · 지연 구분은 라우터 SQL 그대로**(개발3 이 공표하지 않음 · D-607) | `tests/test_dev1_trk.py::test_due_compliance_from_stats` — 1986-03 납기 의뢰 1 → `data-compliance` = `stats.due_compliance("1986-03")["rate"]` · 1987-01 → `미수집` · `1986-3` · `abcd-ef` · `1986/03` → 422 |
| **HOME-010 회계부 카드** (F-HOME-011) | 「90일 초과 미수」 = `len(stats.aging(stats.erp_asof())["over90"])` · 반영 회차 없음 → `미수집`(note 「반영된 ERP 업로드 회차가 없다」) · `aging["undecided"]` → `미확정 (D-516)` 글자 · 링크 `nav.path_of("COL-060")` · note 에 기준일. 「업로드 오류 행」 카드 note 에 `erp_upload_error` 미처리 알림 건수(「미처리 알림 n건」) — 알림 카드를 따로 두지 않았다(오류 행 · 미매핑 거래처 카드와 같은 사실 · D-608). `Card.fn` = 집계가 `stats` 에 있는 카드의 (건수 \| 미확정 글자 \| None, note) | `tests/test_dev1_home.py::test_ac_over90_card_from_stats_aging` — 1984-09-01 매출 500 (기준일 1985-01-31 에서 152일) 올리면 그 거래처가 over90 에 들고 카드 수치 = `len(over90)` · 없을 때 `미수집` |
| 개발1 테스트 | **69 passed**(W1 66 + W2 3: trk 5 · home 6 · common 2 · bas 12 · std 23 · wo 10 · sys 9 · jobs 2) · QA · arch 화면 묶음 48 passed · 테스트 뒤 `erp_upload_batch` 0 · `erp_customer_map` T% 0 · `notification(erp_upload_error)` 0 | `uv run pytest -q tests/test_dev1_*.py` · `uv run pytest -q tests/test_qa1_screens.py tests/test_qa1_contract_text.py tests/test_qa2_static.py tests/test_qa3_security.py tests/test_qa3_robustness.py tests/test_arch_smoke.py tests/test_arch_layout.py` |
| 추적 | G-01 전부 PASS · G-02 고아 ① 16 = DOC 6(W4) + RPT 10(W3) — TRK · HOME 0 | `uv run python tools/check_trace.py` |
| 고친 파일 | `src/lcomfine/app/routers/{trk,home}.py` · `templates/trk/{due,customers}.html` · `templates/home/index.html` · `tests/test_dev1_{common,trk,home}.py` · `decisions.md`(D-608) · 이 파일. `stats.py` · 계약 · `main.py` · `rbac` 는 읽기만 | `git status` |

### 2-W3. 진행 (W3 — SYS-040 로그 탭 보강 · SYS-030 공통코드 그룹 3 · 2026-10-22)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| **SYS-040 탭 6** (F-SYS-041) | `access` · `change` 그대로 + `erp`(`erp_upload_batch` — 회차 번호 · 기준 기간 · 회차 · 반영/교체 · 교체한 회차 번호(`replaced_by` 의 `batch_no`) · 올린 파일 · 읽은 행 · 오류·미매핑 행 · 올린 사람 · 머리 회차/반영/교체/읽은 행/오류 행) · `ai`(`sys_ai_call_log` — 머리 건수 · 실패 · 평균 ms · 행 용도 · 모델 · 성공/실패 · ms · 실패 사유 · 사용자) · `dq`(`data_query_log` — 머리 건수 · 거부 · 평균 ms · 행 로그 번호 · 질문 · 생성 SQL · 허용/거부 · 행 수 · 사유 · 부서 · 사용자 · **거부 포함**) · `sso`(`sys_access_log` 구분 SSO — 머리 건수 · 실패 · 행 사용자 · 부서 · 성공 여부 · 경로 · 대상 · 내용 · IP · W4 전엔 `미수집`). 열 = db-schema 컬럼만 · 표 밑에 원본 표 · 컬럼 이름. 필터 사용자 · 기간 · 구분 하나(탭별 선택지 밖 422). 머리 수치는 같은 필터. 행 0 → `미수집`. 머리 `data-log-tab · data-n · data-live/replaced/errors · data-failed · data-avg-ms · data-rejected`. **쓰기 0**(`routers/sys.py` SYS-040 절에 insert/update/delete 0) | `tests/test_dev1_sys.py::test_logs_six_tabs_200_and_empty_is_uncollected` · `::test_logs_erp_tab_shows_batches_and_replacement`(1979 회차 2 · 교체 1 · 상태 그대로) · `::test_logs_ai_tab_counts_failures_and_avg_ms`(성공 100 + 실패 300 → `data-n="2" data-failed="1" data-avg-ms="200"`) · `::test_logs_dq_tab_includes_rejected_queries`(허용 1 · 거부 1 · 필터) · `::test_logs_sso_tab_uncollected_until_w4` · `::test_logs_tabs_permission_cells`(pr · sl · ac · ex × 탭 6 → 403) |
| **SYS-030 공통코드 그룹 3** (F-SYS-032) | DB 에 설비 2 · 불량유형 3 · 수금수단 3(공통 시드 · 전부 `(예시)`). `seed_dev1.run()` 두 번 → `code_group 3 · code_added 0` 그대로(빈 그룹에만 더한다). 읽는 쪽 그룹 글자 공표 §1.4 | `tests/test_dev1_sys.py::test_code_groups_seeded_and_idempotent` · `uv run python -c "from lcomfine.db import seed_dev1; print(seed_dev1.run()); print(seed_dev1.run())"` |
| 개발1 테스트 | **77 passed**(W2 69 + W3 8: sys 17 · trk 5 · home 6 · common 2 · bas 12 · std 23 · wo 10 · jobs 2) · QA · arch 화면 묶음 56 passed · 테스트 뒤 내 접두(`T…-log`) 행 `sys_ai_call_log` · `data_query_log` · `erp_upload_batch` · `sys_access_log(SSO)` 0 — 개발3 의 행은 건드리지 않는다 | `uv run pytest -q tests/test_dev1_*.py` · `uv run pytest -q tests/test_qa1_screens.py tests/test_qa1_contract_text.py tests/test_qa2_static.py tests/test_qa3_security.py tests/test_qa3_robustness.py tests/test_arch_smoke.py tests/test_arch_layout.py tests/test_arch_gate.py` |
| 추적 | G-01 PASS · G-02 고아 ① ③ 16 = DOC 6(W4) + RPT 10(개발3 W3) — SYS 0 | `uv run python tools/check_trace.py` |
| **W3 QA1 수정 · DEF-QA1-008** (경미) | 접속 탭 구분 `log_type` 을 `choice(…, ACCESS_LOG_TYPES)` 로 — 값 집합은 db-schema §6 `sys_access_log.log_type`(로그인 · 조회 · 변경 · 오류 · SSO) · 밖이면 422(erp · dq · sso 와 같은 규칙 · D-609). 변경 탭의 기능 ID 도 계약(`contracts.functions()`)에 없는 ID 면 422. AI 탭 「호출 용도」는 값 집합이 개발3 몫(`ai.py` 의 kind 글자)이라 글자 그대로 둔다. QA1 의 `tests/test_qa1_rpt.py::test_sys_040_filter_outside_choices_is_422` 는 이제 통과하므로 strict xfail 표식을 QA1 이 떼어야 한다(XPASS) | `tests/test_dev1_sys.py::test_logs_access_and_change_filter_outside_choices_422` · `uv run pytest -q tests/test_dev1_sys.py` → **17 passed** · `tests/test_dev1_*.py` → 77 passed |
| 고친 파일 | `src/lcomfine/app/routers/sys.py`(SYS-040 절 · 모듈 docstring) · `templates/sys/logs.html` · `db/seed_dev1.py` · `tests/test_dev1_sys.py` · `decisions.md`(D-609) · 이 파일. `main.py` · `nav.py` · `schema.sql` · 계약 · 개발3 파일은 읽기만 · 커밋 없음 | `git status --short` |

### 2-W4. 진행 (W4 문서 SSO — DOC 2 화면 · `sso` · 2026-10-22)

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 화면 · 기능 | 화면 2 등록(DOC-010 `/doc/go` · DOC-020 `/doc/account-map`) · 기능 6(F-DOC-011 `POST /doc/go` · 012 `GET /doc/go` · 021 `POST /doc/account-map` · 022 `POST /doc/account-map/{id}` · 023 `…/{id}/delete` · 024 `GET /doc/account-map`) — 화면 GET `require_screen` · 쓰기 `require_fn`(F-DOC-011 은 권한 예외 R) · 성공 `http.saved`/응답 직후 `audit.log_change` | `make check-trace` → G-02 고아 ①②③ **0** · 이어진 기능 **136/136** · 표식 136/136 / `make check-routes` → G-03 **placeholder 0** · 260/260 · 276/276 403 |
| SSO 토큰 (D-514 · D-610) | HMAC-SHA256 · 60초 · jti · 1회 사용(`update … where used_at is null returning`) · 재사용 · 만료(시각 주입 +60초) · 서명 변조 · 본문 변조 · 형식 깨짐(빈 글자 · 점 개수 · 한글 · NUL · 길이) 거부 · 동시 consume 2 스레드 → 하나만 성공 · 비활성(중지 · 잠금) · 미매핑 · 사용 중지 매핑 발급 거부 · 발급 뒤 비활성/매핑 변경이면 미사용 토큰 consume 거부 | `tests/test_dev1_doc.py` F-DOC-011 8 개 |
| 비활성 연동 | SYS-010 `POST /sys/users/{id}/delete`(F-SYS-013) → 그 세션 `POST /doc/go` 401(발급 0행) · 옛 `User` 객체로 `sso.issue` 해도 DB 상태를 읽어 NotMapped · 이미 받은 토큰 consume 거부. `routers/sys.py` 는 고치지 않았다(DB 에서 읽으니 자동) | `::test_inactive_user_refused_and_unused_token_rejected` |
| 설정 없음 | 주소 없음 → GET 안내 `미확정 (D-517)` · POST 422 「문서관리 SSO 주소(LCOMFINE_DOC_SSO_URL) 미확정 (D-517) — 토큰을 발급하지 않았습니다」 · 토큰 0행 · SSO 로그 실패 1행. 비밀 없음 → 같은 422 + `sso.NotConfigured`. 로컬 `.env` 에 주소가 없어 지금 화면은 `미확정 (D-517)`(실측) | `::test_no_url_or_no_secret_is_undecided_d517` |
| 토큰 평문 0 | HTML 응답에 토큰은 hidden 칸 1 번뿐 · 주소/Location 에 없음 · `Cache-Control: no-store` · JSON 응답 · `sys_access_log` · `sys_change_log` 에 없음 | `::test_go_issues_token_in_hidden_form_once` |
| DOC-020 | 1:1 422(사용자 · 계정 ID · 사용 중지 매핑 포함 · 항목 이름) · 누락 · NUL 422(`문서관리 계정 ID`) · 엑셀 일괄(오류 행 4/5 행마다 사유 · 0행 등록 → 정상 파일 2건) · 수정(계정 ID · 사용 여부 · 사용자 변경 422 · 404) · 삭제(발급 기록 있으면 사용 중지) · 미연결 목록 · 사번 동일 방식 `미확정 (D-517)` · 403(DOC-020 은 ADM 만) | `tests/test_dev1_doc.py` F-DOC-021×2 · 022 · 023 · 024 |
| 시드 | `seed_dev1.run()` 두 번 → `doc_map 8 · doc_map_added 8 → 0`(시드 계정 8 → `doc-<id> (예시)`) | `uv run python -c "from lcomfine.db import seed_dev1; print(seed_dev1.run()); print(seed_dev1.run())"` |
| 개발1 테스트 | **91 passed**(W3 77 + doc 14) · 전체 **418 passed** | `uv run pytest -q tests/test_dev1_*.py` · `uv run pytest -q` |
| 게이트 (읽기 전용) | PASS 21 · FAIL 1(G-18 — `tools/check_security.py` 가 아직 「W4 미구현」 고정 FAIL · §3 요청 8) · 미검증 G-23 · BLOCKED G-24 | `make gate` (13:11) |
| **W4 QA1 수정 · DEF-QA1-010** (경미 · 아키텍트 판정 1안 = 정본대로) | 메뉴(base.html `target="_blank"` · 아키텍트) 한 번 클릭 → 새 창의 `GET /doc/go` → **발급할 수 있을 때만**(주소 · 비밀 · 매핑 · 활성) 진입 폼 `<form method="post" action="/doc/go" data-auto-submit>`(app.js 자동 제출 · target 없음 = 같은 창) → 자동 POST 폼(`go_post.html` · `data-auto-submit`) → 문서관리. 준비 안 됨(미매핑 · 사용 중지 매핑 · 주소 없음 · 비밀 없음)이면 안내만 — 진입 폼 · 자동 제출 없음. 안내 문장을 실제 동작대로 고침(`templates/doc/go.html`) | `uv run pytest -q tests/test_dev1_doc.py tests/test_qa1_doc.py` → **26 passed · 2 failed** — `test_qa1_doc.py::test_doc_010_menu_click_opens_new_window` PASS · 실패 2(`::test_doc_010_l3_logic_text_and_sso_log` · `::test_doc_contract_row_and_no_other_misses`)는 `tools/check_screens.py` 1478행의 옛 기대 「POST /doc/go 폼 `target=_blank`」 — 이번 판정(같은 창)과 반대라 QA1 이 그 조건을 `data-auto-submit` 으로 바꿔야 한다(QA1 파일 · 건드리지 않음) / 새 `tests/test_dev1_doc.py::test_go_page_auto_submit_only_when_ready`(F-DOC-012) PASS · 개발1 **92 passed** |
| 결정 | D-610(토큰 모양 · 응답 · 설정 없음 422) · D-611(1:1 · 수정 · 삭제 · 엑셀 규칙) — 가설 | decisions.md |
| 고친 파일 | 새 `src/lcomfine/app/sso.py` · `routers/doc.py` · `templates/doc/{go,go_post,account_map}.html` · `tests/test_dev1_doc.py` / 고침 `db/seed_dev1.py` · `tests/test_dev1_common.py`(cleanup 에 sso_token · doc_account_map) · `decisions.md` · 이 파일. 커밋 없음 | `git status --short` |

- 공용 테스트 도구 `tests/test_dev1_common.py::Erp` — (예시) xlsx 를 지금 열 매핑(시드 7)의 열 이름으로 만들어 `POST /col/uploads` · `POST /col/customer-map` 로 올리고 `close()` 가 **자기 회차 id 만** 지운다(기간 1985년 — 개발3 의 1990~1993 과 겹치지 않는다). 필수 항목 매핑이 없을 때만 기본 항목 이름을 저장하고 되돌린다.

- 쓰기는 전부 `rbac.require_fn` · 화면 GET 은 `rbac.require_screen` · 출력 GET(F-STD-054 · F-WO-024)은 `require_fn`. 성공은 `http.saved` 직후 `audit.log_change`.
- 경로 키가 숫자가 아니거나 없으면 404, 폼으로 고른 값이 틀리면 422(F-WO-021 의 없는 의뢰만 계약대로 404). 템플릿에 스크립트 없음.
- 「참조가 있으면 사용 중지」는 `routers/bas.py` 의 `remove_or_disable` 한 곳(FK 를 DB 카탈로그에서 읽는다). 개발1 라우터 공용 폼 헬퍼도 bas.py 에 있다.

## 3. 요청 (스키마 · 계약 · 공용 파일)

1. **notify (아키텍트)** — F-HOME-031 「개인 추가 알림만 켜고 끈다」: 설정은 저장되지만 `notify.unread` 는 `to_role = 사용자 부서` 행만 보여서, 다른 부서로 가는 이벤트를 켜도 알림함에 나타나지 않는다. `unread` 가 `notification_setting.enabled = true` 인 이벤트의 다른 부서 행(dedupe_key 로 한 줄)도 함께 보이게 할지 판정을 요청한다. 화면에는 이 사실을 안내 문장으로 적었다.
   **종결(Ruling 24)** — 「자기 부서가 수신하는 이벤트의 끄기만 · 다른 부서 이벤트 구독은 범위 밖(D-511)」. HOME-030 에서 다른 부서 칸·안내 문장을 뺐다(§2). 남은 모순 하나만 적어 둔다: F-HOME-031 계약은 「부서 기본 알림을 끄려 하면 422」와 「자기 부서가 수신하는 이벤트의 끄기만」을 함께 적고 있어, 지금 화면은 끄기도 422 로 막는다(켜고 끌 것이 없다 · `notify.unread` 의 `enabled=false` 숨김은 이 화면으로 만들 수 없다). 끄기를 허용할지는 아키텍트가 문장 하나로 정해 주면 바로 맞춘다. → 아키텍트 판정: 정본 모순으로 **D-526(차단)**. 지금 구현 그대로 두고 HOME-030 본문에 「개인 추가 알림의 범위는 미확정 (D-526)」 한 줄을 보인다(`test_notification_settings_view` 가 검사).
2. **stats (개발3) / 계약 문장** — TRK 3 화면은 계약상 「집계 SQL 은 `stats` 뿐」이지만 W1 지시대로 `routers/trk.py` 안의 조회 SQL 로 보인다(D-607). `stats` 에 의뢰별 진행(`progress`) 을 옮길지, 계약 문장을 「TRK 는 조회 SQL」로 고칠지 정해 달라. 수금 칸은 `stats.customer_receivable` 공표(W2) 뒤 붙인다.
   **종결(Ruling 23)** — 납기 준수율은 W2 에 `stats.due_compliance(period)` 로, 그때까지 `routers/trk.py` 의 조회 SQL(function-list F-TRK-021 · interfaces.md §9).
   **W2 반영(2026-10-22)** — 준수율 수치는 `stats.due_compliance(period)` 로, TRK-030 수금 칸 · ERP 업로드 기준일은 `stats.customer_receivable` · `stats.erp_asof()` 로 옮겼다(§2-W2). `routers/trk.py` 에 남은 집계 SQL = 의뢰별 **진행 · 단계**(`progress` · D-3/D-7/지연 구분 · 거래처·제품별 건수)만 — 개발3 이 그 함수를 공표하지 않았다. 옮기려면 개발3 이 `stats.request_progress(...)`(단계 6 수량 · 날짜) 를 공표하거나, 계약 문장을 「TRK 의 단계 조회는 라우터 SQL」로 고치면 된다(아키텍트 판정 대기 · 지금은 D-607 그대로).
3. **개발2 / 개발3 화면 조건** — HOME 카드가 거는 조회 인자: QC-010 · QC-020 `?status=검사대기`, MAT-020 · PRD-010 · SHP-010 · SHP-020 · COL-020 · COL-030 은 인자 없이 연다. 각 화면이 그 인자를 받아 거르면 「조건이 걸린 채 열린다」가 완성된다.
4. **위치 확인 (아키텍트)** — goal.md §3.2 는 `app/jobs.py`, w1-dev1 · Makefile 은 `python -m lcomfine.jobs` → `src/lcomfine/jobs.py` 로 만들었다. interfaces.md §10 은 개발 시드 `main() -> int`, w1-common 은 `run()` — 둘 다 두었다. CLAUDE.md 는 아직 v1(설계도 · 대메뉴 12) 내용이다.
   **종결(Ruling 25)** — goal.md §3.2 · §5 가 `src/lcomfine/jobs.py` 로 고쳐졌다(커밋 1fd01fd). CLAUDE.md 도 v2 로 바뀌었다.
5. **개발3 (`ai.py` · `dataquery.py` · W3)** — SYS-040 의 AI 호출 · 데이터 질의 탭은 `sys_ai_call_log` · `data_query_log` 의 **db-schema 열 그대로** 읽는다. 쓰는 쪽이 채우는지 확인 바란다: `sys_ai_call_log.kind`(호출 용도 글자 — 탭의 「호출 용도」 필터는 이 값과 글자 일치) · `model` · `ok` · `ms` · `error`(키 없음 포함 · **키 값은 적지 않는다**) · `user_id`(사용자 필터는 `sys_user.login_id` 로 잇는다 — 비면 사용자 칸 `—`) / `data_query_log.query_no`(`numbering.next("DQ")`) · `user_id` · `role_code` · `question` · `sql_text`(AI 실패면 null) · `ok`(검증 거부 · 실패 = false — 탭은 「거부」로 보이고 거부 수를 센다) · `row_count` · `error`(거부·실패 사유 — 탭의 「거부·실패 사유」 열) · `ms`. 열을 더하거나 뜻을 바꾸면 `db-schema.md` 와 함께 알려 주면 탭을 맞춘다. 쓰기는 개발3 몫 — SYS-040 은 어느 표에도 쓰지 않는다.
6. **개발1 W4 메모 (자기 몫)** — SSO 탭은 `sys_access_log` 의 `log_type = 'SSO'` 행(D-514 · G-18)을 보인다. F-DOC-011 이 남길 때 `result`(성공/실패) · `login_id` · `screen_id = 'DOC-010'` · `function_id = 'F-DOC-011'` · `detail`(거부 사유 — 토큰 값은 적지 않는다)을 채우면 탭의 필터 · 머리 수치가 그대로 맞는다.
7. **종결(DEF-QA1-010 · 아키텍트 1안)** — `static/app.js` 에 `form[data-auto-submit]` 자동 제출이 들어갔고 메뉴는 `target="_blank"`. DOC-010 은 준비됨일 때만 자동 제출(§2-W4). ~~요청 원문: `static/app.js` (아키텍트) — DOC-010 자동 POST: `form[data-auto-submit]` 를 문서가 읽힌 뒤 한 번 `submit()` 하는 보조를 더해 달라(템플릿에 스크립트를 넣지 않는다). 그 전에는 사람이 「문서관리 열기」를 누른다 — 토큰은 그대로 POST hidden 이라 주소창에 남지 않는다(D-610).~~
8. **`tools/check_security.py` G-18 (QA3)** — 지금 「W4 — DOC-010 SSO 미구현」 고정 FAIL 이다. 기대값대로 실검사로 바꿔 달라: 재사용 · 만료(`sso.consume(cur, token, now=…)`) · 비활성 · 미매핑 거부 · `POST /doc/go` 의 토큰이 주소/Location/JSON 에 없음(GET 은 발급하지 않음) · 호출마다 SSO 로그(`login_id` · `logged_at` · `result`) · 주소 없으면 `미확정 (D-517)`(GET 안내 · POST 422 · 토큰 0행). 테스트에서 주소는 `LCOMFINE_DOC_SSO_URL` 환경변수 + `settings.reset_cache()` 로 넣는다(`tests/test_dev1_doc.py` 의 `p` fixture).
9. **계약 (아키텍트)** — 코드가 맞다: (a) `interfaces.md` §9 `app.sso` 줄에 `now` · `sso.Invalid` · `sso.NotConfigured` · `sso.refusal` (§1.5). (b) `db-schema.md` `sso_token` 표가 `created_by · updated_at · updated_by` 를 적었지만 `schema.sql` 은 `created_at` 하나다(토큰은 고치지 않는 이력) — 표를 schema 대로. (c) `api-contract.md` §2 예외에 「F-DOC-011 브라우저 성공 = 같은 화면 200 POST 폼 · JSON 에 토큰 없음」 · 「주소/비밀 없음 = 422 `미확정 (D-517)`」(D-610) 한 줄.
