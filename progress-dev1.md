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

- 쓰기는 전부 `rbac.require_fn` · 화면 GET 은 `rbac.require_screen` · 출력 GET(F-STD-054 · F-WO-024)은 `require_fn`. 성공은 `http.saved` 직후 `audit.log_change`.
- 경로 키가 숫자가 아니거나 없으면 404, 폼으로 고른 값이 틀리면 422(F-WO-021 의 없는 의뢰만 계약대로 404). 템플릿에 스크립트 없음.
- 「참조가 있으면 사용 중지」는 `routers/bas.py` 의 `remove_or_disable` 한 곳(FK 를 DB 카탈로그에서 읽는다). 개발1 라우터 공용 폼 헬퍼도 bas.py 에 있다.

## 3. 요청 (스키마 · 계약 · 공용 파일)

1. **notify (아키텍트)** — F-HOME-031 「개인 추가 알림만 켜고 끈다」: 설정은 저장되지만 `notify.unread` 는 `to_role = 사용자 부서` 행만 보여서, 다른 부서로 가는 이벤트를 켜도 알림함에 나타나지 않는다. `unread` 가 `notification_setting.enabled = true` 인 이벤트의 다른 부서 행(dedupe_key 로 한 줄)도 함께 보이게 할지 판정을 요청한다. 화면에는 이 사실을 안내 문장으로 적었다.
   **종결(Ruling 24)** — 「자기 부서가 수신하는 이벤트의 끄기만 · 다른 부서 이벤트 구독은 범위 밖(D-511)」. HOME-030 에서 다른 부서 칸·안내 문장을 뺐다(§2). 남은 모순 하나만 적어 둔다: F-HOME-031 계약은 「부서 기본 알림을 끄려 하면 422」와 「자기 부서가 수신하는 이벤트의 끄기만」을 함께 적고 있어, 지금 화면은 끄기도 422 로 막는다(켜고 끌 것이 없다 · `notify.unread` 의 `enabled=false` 숨김은 이 화면으로 만들 수 없다). 끄기를 허용할지는 아키텍트가 문장 하나로 정해 주면 바로 맞춘다. → 아키텍트 판정: 정본 모순으로 **D-526(차단)**. 지금 구현 그대로 두고 HOME-030 본문에 「개인 추가 알림의 범위는 미확정 (D-526)」 한 줄을 보인다(`test_notification_settings_view` 가 검사).
2. **stats (개발3) / 계약 문장** — TRK 3 화면은 계약상 「집계 SQL 은 `stats` 뿐」이지만 W1 지시대로 `routers/trk.py` 안의 조회 SQL 로 보인다(D-607). `stats` 에 의뢰별 진행(`progress`) 을 옮길지, 계약 문장을 「TRK 는 조회 SQL」로 고칠지 정해 달라. 수금 칸은 `stats.customer_receivable` 공표(W2) 뒤 붙인다.
   **종결(Ruling 23)** — 납기 준수율은 W2 에 `stats.due_compliance(period)` 로, 그때까지 `routers/trk.py` 의 조회 SQL(function-list F-TRK-021 · interfaces.md §9).
3. **개발2 / 개발3 화면 조건** — HOME 카드가 거는 조회 인자: QC-010 · QC-020 `?status=검사대기`, MAT-020 · PRD-010 · SHP-010 · SHP-020 · COL-020 · COL-030 은 인자 없이 연다. 각 화면이 그 인자를 받아 거르면 「조건이 걸린 채 열린다」가 완성된다.
4. **위치 확인 (아키텍트)** — goal.md §3.2 는 `app/jobs.py`, w1-dev1 · Makefile 은 `python -m lcomfine.jobs` → `src/lcomfine/jobs.py` 로 만들었다. interfaces.md §10 은 개발 시드 `main() -> int`, w1-common 은 `run()` — 둘 다 두었다. CLAUDE.md 는 아직 v1(설계도 · 대메뉴 12) 내용이다.
   **종결(Ruling 25)** — goal.md §3.2 · §5 가 `src/lcomfine/jobs.py` 로 고쳐졌다(커밋 1fd01fd). CLAUDE.md 도 v2 로 바뀌었다.
