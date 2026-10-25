# 엘컴화인 MES 전사 경영 Cockpit 구현 계획

**Goal:** RPT-010~080을 일간·주간·월간 경영 흐름으로 확장하고, 목표관리·위험/조치관리·단계적 ERP 재무연계를 별도 MGT 관리영역으로 구현한다.

**Architecture:** 기존 FastAPI + Jinja2 + PostgreSQL 구조와 RPT 실시간 조회 원칙을 유지한다. 업무 실적 집계는 `dashboard.py`, 경영 지표 결합과 위험 규칙은 신규 `management.py`, 재무 업로드와 활성 회차 집계는 신규 `financial.py`에 둔다. RPT는 읽기만 하고 MGT-010~040만 관리 테이블을 쓴다.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, psycopg 3, PostgreSQL 17, openpyxl, pytest, 인라인 SVG.

**Spec:** `docs/superpowers/specs/2026-10-26-executive-dashboard-cockpit-design.md`

## 전역 제약

- 정본 HTML은 수정하지 않는다. 새 요구사항은 `ia-overrides.json`과 결정 대장에 기록한다.
- RPT-010~080 GET은 업무·관리 테이블을 쓰지 않는다.
- 삭제된 RPT-090~130 ID를 재사용하지 않는다.
- 신규 화면은 MGT-010~040, 신규 대메뉴는 `MGT 경영관리`다.
- D-519 로스율과 D-520 병목 기준은 확정 전 계산하지 않는다.
- ERP 원가·매출 자료가 없으면 금액 지표는 `연계 전`이다.
- 출하와 수금은 월·거래처 단위로 비교하며 개별 건을 추정 매칭하지 않는다.
- 쓰기 성공은 `audit.log_change`, 기능 권한은 `require_fn`, 입력 오류는 422다.
- 기능마다 `@pytest.mark.fn` 테스트를 둔다. 테스트 삭제·skip·게이트 완화는 금지한다.
- DB를 지우는 `make db-reset`은 사용하지 않는다. 실제 스키마 반영은 명시적 ALTER 이관으로 수행한다.

## Task 1: 결정·IA·기능·권한 계약 확장

**Files**

- Modify: `decisions.md`
- Modify: `contracts/ia-overrides.json`
- Modify: `src/lcomfine/app/nav.py`
- Modify: `contracts/function-list.md`
- Modify: `contracts/permission-matrix.md`
- Modify: `contracts/screen-map.md`
- Modify: `goal.md`, `CLAUDE.md`
- Modify: `tests/test_arch_design_doc.py`, `tests/test_arch_contracts.py`, `tests/test_arch_layout.py`

**Steps**

- [x] 실패 테스트: MGT 메뉴 1, 화면 4, 경로 4, 권한 칸 19, 신규 기능의 화면·라우트 표식 기대값을 추가한다.
- [x] `uv run pytest tests/test_arch_design_doc.py tests/test_arch_contracts.py tests/test_arch_layout.py -q`로 실패를 확인한다.
- [x] 신규 확정 결정에 Cockpit, 목표, 위험·조치, ERP 재무연계, MGT 분리를 기록한다.
- [x] overrides에 신규 MGT 메뉴·화면을 추가하도록 추출기 지원을 보강하고, `nav.py`를 같은 순서·이름으로 갱신한다.
- [x] 기능 계약을 확정한다: 각 화면 GET 1개, 목표·임계치 생성/새 버전/중지, 조치 배정/변경/강제 종료, 재무 업로드/반영 기능.
- [x] 권한: MGT-010 ST·ADM W / EX·AC R, MGT-020 ST·ADM W / EX R, MGT-030 전 부서 W, MGT-040 AC·ADM W / ST·EX R.
- [x] `make check-trace`의 G-01과 계약·표식 검사를 통과시킨다. MGT 라우트 15개는 Task 3·4·9에서 실제 동작과 함께 등록하며 그 전까지 G-02의 계획된 FAIL로 남긴다.
- [ ] Commit: `Cockpit 1: MGT 계약 · 화면 · 기능 · 권한`

## Task 2: 스키마와 무손실 이관

**Files**

- Modify: `src/lcomfine/db/schema.sql`
- Modify: `contracts/db-schema.md`
- Create: `tools/migrate_executive_cockpit.sql`
- Modify: `src/lcomfine/db/seed.py`
- Create: `tests/test_arch_management_schema.py`

**Schema**

- `management_metric`
- `management_target`, `management_target_version`
- `management_threshold`
- `management_issue`, `management_action`
- `financial_import_batch`, `financial_fact`

**Steps**

- [x] 실패 테스트: 테이블·FK·check·unique·이력 불변·활성 회차 유일성을 검증한다.
- [x] `uv run pytest tests/test_arch_management_schema.py -q` 실패를 확인한다.
- [x] `schema.sql`과 `db-schema.md`에 8개 테이블과 MGT 쓰기 경계를 추가한다.
- [x] 현재 DB에는 `CREATE TABLE IF NOT EXISTS` 중심의 재실행 가능한 이관을 적용한다. 기존 업무 테이블은 변경하지 않고 테이블 수 46→54를 확인한다.
- [x] 지표 시드는 코드·레이블·단위·방향성만 넣고 목표값·임계치는 지어내지 않는다.
- [x] `make check-schema`와 스키마 테스트를 통과시킨다.
- [ ] Commit: `Cockpit 2: 경영관리 · 재무 스키마와 이관`

## Task 3: 목표·임계치 서비스와 MGT-010/020

**Files**

- Create: `src/lcomfine/app/management.py`
- Create: `src/lcomfine/app/routers/mgt.py`
- Create: `src/lcomfine/app/templates/mgt/targets.html`
- Create: `src/lcomfine/app/templates/mgt/thresholds.html`
- Create: `tests/test_dev_mgt_targets.py`

**Interfaces**

- `management.target_for(metric_key, period, scope) -> dict | None`
- `management.compare(metric, actual, target) -> dict`
- `management.create_target_version(cur, target_id, payload, user) -> int`
- `management.thresholds(metric_key, period, scope) -> list[dict]`

**Steps**

- [ ] 실패 테스트: 목표 생성, 겹치는 유효 목표 422, 새 버전 이력, 중지, 목표 없음, 실제 0, 세 방향성 판정을 작성한다.
- [ ] 권한 테스트: R은 GET만, W만 쓰기, 감사로그는 성공당 1행·실패 0행을 검증한다.
- [ ] 최소 서비스와 MGT-010/020 화면을 구현한다.
- [ ] `uv run pytest tests/test_dev_mgt_targets.py -q`와 `make check-security`를 실행한다.
- [ ] Commit: `Cockpit 3: 목표 · 임계치 관리`

## Task 4: 위험·조치 서비스와 MGT-030

**Files**

- Modify: `src/lcomfine/app/management.py`
- Modify: `src/lcomfine/app/routers/mgt.py`
- Create: `src/lcomfine/app/templates/mgt/issues.html`
- Create: `tests/test_dev_mgt_issues.py`

**Interfaces**

- `management.evaluate(metric_key, observed, context, asof) -> dict | None`
- `management.upsert_issue(cur, finding) -> int`
- `management.assign_action(cur, issue_id, payload, user) -> int`
- `management.transition_action(cur, action_id, status, user) -> None`

**Steps**

- [ ] 실패 테스트: 임계치 경계, 중복 방지, 재발 시 최근값 갱신, 필수 조치 완료+규칙 해소 후 해결, 강제 종료 사유를 작성한다.
- [ ] 부서 범위 테스트: 담당 부서는 자기 조치만, ST·EX·ADM은 전사 조회, ST·ADM은 재배정 가능하도록 검증한다.
- [ ] MGT-030 목록·상세·배정·상태 변경을 구현한다.
- [ ] 규칙 없는 지표에는 위험을 생성하지 않는 테스트를 통과시킨다.
- [ ] Commit: `Cockpit 4: 위험 · 조치 관리`

## Task 5: 공통 KPI 비교 읽기 모델과 시각 컴포넌트

**Files**

- Modify: `src/lcomfine/app/dashboard.py`
- Modify: `src/lcomfine/app/templates/_charts.html`
- Modify: `src/lcomfine/app/templates/rpt/_d.html`
- Modify: `src/lcomfine/app/static/style.css`
- Modify: `tests/test_dev3_rpt.py`, `tests/test_qa1_rpt.py`

**Steps**

- [ ] 실패 테스트: KPI가 `value`, `target`, `attainment`, `previous`, `delta`, `status`, `availability`를 제공하는지 검증한다.
- [ ] 일간=전일, 주간=직전 7일, 월간=전월 동기간 비교를 독립 계산한다.
- [ ] `미수집`, 0, `목표 없음`, `미확정`, `연계 전`을 서로 다른 표식으로 렌더링한다.
- [ ] 목표선·상태색·전기 화살표가 있는 KPI 타일을 추가하되 SVG title과 데이터 표 동일성 계약을 유지한다.
- [ ] 390px 페이지 가로 스크롤 방지 정적·브라우저 검증을 추가한다.
- [ ] Commit: `Cockpit 5: KPI 목표 · 전기 비교 공통 UI`

## Task 6: RPT-080 전사 경영 Cockpit

**Files**

- Modify: `src/lcomfine/app/dashboard.py`
- Modify: `src/lcomfine/app/routers/rpt.py`
- Modify: `src/lcomfine/app/templates/rpt/summary.html`
- Modify: `tests/test_dev3_rpt.py`, `tests/test_qa2_rpt.py`

**Steps**

- [ ] 실패 테스트: 상단 KPI, 7단계 흐름, 위험 Top 5, 영역 링크와 동일 필터 보존을 작성한다.
- [ ] 일간·주간·월간별 모집단과 비교 기간을 독립 SQL로 검증한다.
- [ ] `수주→생산대기→생산→검사→제품재고→출하→수금` 단계의 건수·수량·체류시간을 구현한다.
- [ ] 재무 회차가 없을 때 금액 칸만 `연계 전`이고 운영 KPI는 유지되는지 검증한다.
- [ ] GET 전후 업무·관리 테이블 행 수 불변을 확인한다.
- [ ] Commit: `Cockpit 6: RPT-080 전사 경영 흐름`

## Task 7: RPT-010~040 강화

**Files**

- Modify: `src/lcomfine/app/dashboard.py`
- Modify: `src/lcomfine/app/templates/rpt/{orders,production,quality,inventory}.html`
- Modify: `tests/test_dev3_rpt.py`, `tests/test_qa2_rpt.py`

**Steps**

- [ ] 수주: 목표 누적, 납기 위험, 거래처·품목 구성과 미착수 드릴다운을 테스트·구현한다.
- [ ] 생산: 계획 대 실적, 지연 지시, 설비 가동·정지와 D-519 보존을 테스트·구현한다.
- [ ] 품질: 합격률, 불량 파레토, 반복 불량, 보류 LOT와 LOT 추적 링크를 테스트·구현한다.
- [ ] 재고: 현재·가용·할당, 체류 에이징, 실사 차이와 금액·안전재고 `연계 전`을 테스트·구현한다.
- [ ] 각 SVG와 데이터 표가 동일한 수치를 같은 순서로 제공하는지 검증한다.
- [ ] Commit: `Cockpit 7: 수주 · 생산 · 품질 · 재고 대시보드`

## Task 8: RPT-050~070 강화

**Files**

- Modify: `src/lcomfine/app/dashboard.py`
- Modify: `src/lcomfine/app/templates/rpt/{shipment,collection,order_flow}.html`
- Modify: `tests/test_dev3_rpt.py`, `tests/test_qa2_rpt.py`

**Steps**

- [ ] 출하: 목표 누적, 7·14·30일 부하, 납기 위험과 가용재고 차단 원인을 구현한다.
- [ ] 수금: 출하·수금·미수, 연령, ERP 기준일, 거래처 위험을 구현하고 월·거래처 단위 비교를 독립 검증한다.
- [ ] 주문흐름: 단계 체류, 타임라인, 미착수 다음 단계와 D-520 보존을 구현한다.
- [ ] 모든 드릴다운이 기간·거래처·업무 키를 보존하는지 검증한다.
- [ ] Commit: `Cockpit 8: 출하 · 수금 · 주문흐름 대시보드`

## Task 9: ERP 재무자료 업로드와 MGT-040

**Files**

- Create: `src/lcomfine/app/financial.py`
- Modify: `src/lcomfine/app/routers/mgt.py`
- Create: `src/lcomfine/app/templates/mgt/financial_imports.html`
- Create: `tests/test_dev_mgt_financial.py`
- Modify: `src/lcomfine/app/dashboard.py`

**Upload contract**

- 필수 식별 열: 기간, 거래처 코드, 품목 코드
- 선택 금액 열: 수주매출, 출하매출, 표준원가, 실제원가
- 존재하는 금액 열만 활성화하고 없는 지표는 `연계 전`으로 유지한다.

**Steps**

- [ ] 실패 테스트: 미리보기, 형식 오류 행 제외, 코드 미매핑, 같은 기간 새 회차 교체, 이전 회차 보존, 활성 회차 유일성을 작성한다.
- [ ] 문자열 수식 주입 방지와 업로드 파일 비저장을 검증한다.
- [ ] `financial.py`와 MGT-040을 구현한다.
- [ ] 활성 회차가 있을 때만 RPT 금액·원가·마진 지표를 켠다.
- [ ] 원가가 없으면 이익을 계산하지 않는 테스트를 통과시킨다.
- [ ] Commit: `Cockpit 9: ERP 재무 회차 · 금액 · 원가 연계`

## Task 10: 게이트·E2E·완료 감사

**Files**

- Modify: `tools/check_trace.py`, `tools/check_routes.py`, `tools/check_schema.py`, `tools/check_data.py`, `tools/check_security.py`, `tools/gate.py`
- Create/Modify: `tests/test_qa1_mgt.py`, `tests/test_qa2_cockpit.py`, `tests/test_qa3_mgt.py`
- Modify: `outputs/qa1-기능계약.md`, `outputs/qa2-흐름데이터.md`, `outputs/qa3-보안운영.md`
- Modify: `progress.md`

**Steps**

- [ ] 계약·화면·기능·권한·스키마 기대값을 새 규모로 갱신한다.
- [ ] QA1: MGT 기능/오류/권한과 RPT SVG=표 계약을 전수 검증한다.
- [ ] QA2: 목표 입력→RPT 비교→위험 생성→조치 완료→해결, 재무 업로드→금액 KPI 활성화를 HTTP만으로 검증한다.
- [ ] QA3: 8부서 권한, 부서 범위, 감사로그, 이상 업로드, DB 장애, XSS/수식 주입을 검증한다.
- [ ] 1280px·390px 및 라이트·다크 화면을 브라우저로 확인한다.
- [ ] `uv run pytest -q`, `make gate`, 마지막에 `make gate-full`을 실행한다.
- [ ] 기존 G-01~G-24와 신규 Cockpit 검증 항목을 요구사항별로 대조한다.
- [ ] `progress.md`에 실제 통과 수치와 명령만 기록한다.
- [ ] Commit: `Cockpit 완료: 목표 · 위험 · 재무연계 · 대시보드 8 검증`

## 실행 순서와 중단 기준

Task 1→5는 순차 실행한다. Task 6 이후 RPT 화면은 파일 충돌을 피하기 위해 6→7→8 순서로 진행한다. Task 9는 Task 2 이후 서비스 개발을 병행할 수 있지만 `dashboard.py` 결합은 Task 8 뒤에 한다. Task 10은 모든 작업자가 멈춘 상태에서 단독 실행한다.

같은 실패가 세 번 반복되면 접근을 바꾸고, 외부 기준이 필요한 D-519·D-520·원가 배부 규칙은 `미확정` 상태로 남긴다. 이 미확정 항목은 다른 완료 항목을 거짓으로 PASS 처리하는 근거가 될 수 없다.
