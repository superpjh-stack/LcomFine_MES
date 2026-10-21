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
| 개발1 테스트 | **65 passed** (test_dev1_common · bas 12 · std 23 · wo 10 · home 5 · sys 9 · trk 3 · jobs 2) | `uv run pytest tests/test_dev1_*.py -q` |
| 개발1 placeholder | 화면 23 등록 · 남은 2 = DOC-010 · DOC-020 (W4) | `make gate` G-03 「개발1 2」 |
| 빌드 전제 | pytest 189 passed · /health 200 | `make gate` (읽기 전용 · 19:47) |
| 배치 | `due-check` — 대상 의뢰 · 새 알림 행 수를 찍는다. 같은 날 재실행 0행 | `uv run python -m lcomfine.jobs due-check` · tests/test_dev1_jobs.py |
| 시드 | `seed_dev1.run()` 두 번 → item 4 · customer 2 · location 2 그대로 (전부 `(예시)`) | `uv run python -c "from lcomfine.db import seed_dev1; seed_dev1.run()"` |
| 결정 | D-601~D-607 (가설) | decisions.md |

- 쓰기는 전부 `rbac.require_fn` · 화면 GET 은 `rbac.require_screen` · 출력 GET(F-STD-054 · F-WO-024)은 `require_fn`. 성공은 `http.saved` 직후 `audit.log_change`.
- 경로 키가 숫자가 아니거나 없으면 404, 폼으로 고른 값이 틀리면 422(F-WO-021 의 없는 의뢰만 계약대로 404). 템플릿에 스크립트 없음.
- 「참조가 있으면 사용 중지」는 `routers/bas.py` 의 `remove_or_disable` 한 곳(FK 를 DB 카탈로그에서 읽는다). 개발1 라우터 공용 폼 헬퍼도 bas.py 에 있다.

## 3. 요청 (스키마 · 계약 · 공용 파일)

1. **notify (아키텍트)** — F-HOME-031 「개인 추가 알림만 켜고 끈다」: 설정은 저장되지만 `notify.unread` 는 `to_role = 사용자 부서` 행만 보여서, 다른 부서로 가는 이벤트를 켜도 알림함에 나타나지 않는다. `unread` 가 `notification_setting.enabled = true` 인 이벤트의 다른 부서 행(dedupe_key 로 한 줄)도 함께 보이게 할지 판정을 요청한다. 화면에는 이 사실을 안내 문장으로 적었다.
2. **stats (개발3) / 계약 문장** — TRK 3 화면은 계약상 「집계 SQL 은 `stats` 뿐」이지만 W1 지시대로 `routers/trk.py` 안의 조회 SQL 로 보인다(D-607). `stats` 에 의뢰별 진행(`progress`) 을 옮길지, 계약 문장을 「TRK 는 조회 SQL」로 고칠지 정해 달라. 수금 칸은 `stats.customer_receivable` 공표(W2) 뒤 붙인다.
3. **개발2 / 개발3 화면 조건** — HOME 카드가 거는 조회 인자: QC-010 · QC-020 `?status=검사대기`, MAT-020 · PRD-010 · SHP-010 · SHP-020 · COL-020 · COL-030 은 인자 없이 연다. 각 화면이 그 인자를 받아 거르면 「조건이 걸린 채 열린다」가 완성된다.
4. **위치 확인 (아키텍트)** — goal.md §3.2 는 `app/jobs.py`, w1-dev1 · Makefile 은 `python -m lcomfine.jobs` → `src/lcomfine/jobs.py` 로 만들었다. interfaces.md §10 은 개발 시드 `main() -> int`, w1-common 은 `run()` — 둘 다 두었다. CLAUDE.md 는 아직 v1(설계도 · 대메뉴 12) 내용이다.
