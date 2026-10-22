# 화면 맵 — 화면 66 + 공통 4 (아키텍트 · 2026-10-21)

> 메뉴 · 경로의 원본은 `src/lcomfine/app/nav.py` 다. **§1 은 그 파일의 렌더본**이라 손으로 고치지 않는다
> (`uv run python tools/gen_contracts.py --only screens`). 화면 ID · 이름 · 유형 · 묶음은 정본 그대로이고 게이트가
> `contracts/ia.json` + `ia-overrides.json` 과 대조한다. 경로(slug) · 담당은 정본에 없어 아키텍트가 정한 `가설` 이다(D-507).
> 화면별 기능은 `function-list.md`, 부서별 칸은 `permission-matrix.md`.

## 1. 화면 66 → 경로 · 담당 (렌더본)

<!-- BEGIN:generated screens -->
| ID | 화면 | 유형 | 경로 | 대메뉴 | 묶음 | 담당 |
|---|---|---|---|---|---|---|
| HOME-010 | 내 할 일 | 조회 | `/` | HOME 내 업무 | ⓪ 내 업무 | 개발1 |
| HOME-020 | 알림함 | 조회 | `/home/notifications` | HOME 내 업무 | ⓪ 내 업무 | 개발1 |
| HOME-030 | 알림 설정 | 설정 | `/home/notification-settings` | HOME 내 업무 | ⓪ 내 업무 | 개발1 |
| BAS-010 | 품목 관리 | 목록·등록 | `/bas/items` | BAS 기준정보 | ① 기준 | 개발1 |
| BAS-020 | 거래처 관리 | 목록·등록 | `/bas/customers` | BAS 기준정보 | ① 기준 | 개발1 |
| BAS-030 | 창고·위치 관리 | 목록·등록 | `/bas/warehouses` | BAS 기준정보 | ① 기준 | 개발1 |
| STD-010 | 제조사양기준서 | 목록·등록 | `/std/spec-sheets` | STD 인쇄 기준 | ① 기준 | 개발1 |
| STD-020 | 표준관리 | 목록·등록 | `/std/standards` | STD 인쇄 기준 | ① 기준 | 개발1 |
| STD-030 | 판관리 | 목록·등록 | `/std/plates` | STD 인쇄 기준 | ① 기준 | 개발1 |
| STD-040 | 시안등록 | 등록 | `/std/artworks` | STD 인쇄 기준 | ① 기준 | 개발1 |
| STD-050 | 표준견본서 | 등록·출력 | `/std/sample-sheets` | STD 인쇄 기준 | ① 기준 | 개발1 |
| STD-060 | 예외제품관리 | 목록·등록 | `/std/exception-items` | STD 인쇄 기준 | ① 기준 | 개발1 |
| WO-010 | 생산의뢰서 | 등록 | `/wo/requests` | WO 작업지시 | ② 수주·지시 | 개발1 |
| WO-020 | 생산지시서 | 등록·출력 | `/wo/orders` | WO 작업지시 | ② 수주·지시 | 개발1 |
| WO-030 | 생산순서관리 | 처리 | `/wo/sequence` | WO 작업지시 | ② 수주·지시 | 개발1 |
| WO-040 | 공정상태 | 조회 | `/wo/status` | WO 작업지시 | ② 수주·지시 | 개발1 |
| MAT-010 | 원자재 입고 | 등록 | `/mat/receipts` | MAT 자재·입고 | ③ 자재·생산 | 개발2 |
| MAT-020 | 불출 | 등록 | `/mat/issues` | MAT 자재·입고 | ③ 자재·생산 | 개발2 |
| MAT-030 | 제품 입고 | 등록 | `/mat/product-receipts` | MAT 자재·입고 | ③ 자재·생산 | 개발2 |
| MAT-040 | 입고·불출 내역 | 조회 | `/mat/history` | MAT 자재·입고 | ③ 자재·생산 | 개발2 |
| PRD-010 | 생산일보 | 등록 | `/prd/daily` | PRD 생산일보 | ③ 자재·생산 | 개발2 |
| PRD-020 | 생산일보출력 | 출력 | `/prd/daily/print` | PRD 생산일보 | ③ 자재·생산 | 개발2 |
| PRD-030 | 생산일보현황 | 조회 | `/prd/status` | PRD 생산일보 | ③ 자재·생산 | 개발2 |
| PRD-040 | 생산지시서 대비 생산 로스율 | 리포트 | `/prd/loss-rate` | PRD 생산일보 | ③ 자재·생산 | 개발2 |
| INS-010 | 검사일보 | 등록 | `/ins/daily` | INS 검사일보 | ③ 자재·생산 | 개발2 |
| INS-020 | 검사일보출력 | 출력 | `/ins/daily/print` | INS 검사일보 | ③ 자재·생산 | 개발2 |
| INS-030 | 검사일보현황 | 조회 | `/ins/status` | INS 검사일보 | ③ 자재·생산 | 개발2 |
| INS-040 | 생산지시서 대비 검사 로스율 | 리포트 | `/ins/loss-rate` | INS 검사일보 | ③ 자재·생산 | 개발2 |
| QC-010 | 입고검사 | 등록 | `/qc/incoming` | QC 품질 검사 | ④ 품질·재고 | 개발2 |
| QC-020 | 제품검사 판정 | 등록 | `/qc/product` | QC 품질 검사 | ④ 품질·재고 | 개발2 |
| QC-030 | 검사 이력 | 조회 | `/qc/history` | QC 품질 검사 | ④ 품질·재고 | 개발2 |
| INV-010 | LOT별 재고 조회 | 조회 | `/inv/stock` | INV 재고 | ④ 품질·재고 | 개발2 |
| INV-020 | 재고 이동 | 등록 | `/inv/moves` | INV 재고 | ④ 품질·재고 | 개발2 |
| INV-030 | 재고 조정·실사 | 등록 | `/inv/adjustments` | INV 재고 | ④ 품질·재고 | 개발2 |
| SHP-010 | 출하 지시 | 등록 | `/shp/orders` | SHP 출하 | ⑤ 출하·수금 | 개발3 |
| SHP-020 | 출하 확정 | 처리 | `/shp/confirm` | SHP 출하 | ⑤ 출하·수금 | 개발3 |
| SHP-030 | 출하 이력 | 조회 | `/shp/history` | SHP 출하 | ⑤ 출하·수금 | 개발3 |
| COL-010 | ERP 수금현황 업로드 | 등록 | `/col/uploads` | COL 수금리포트 | ⑤ 출하·수금 | 개발3 |
| COL-020 | 업로드 이력 | 조회 | `/col/upload-history` | COL 수금리포트 | ⑤ 출하·수금 | 개발3 |
| COL-030 | 거래처 코드 매핑 | 목록·등록 | `/col/customer-map` | COL 수금리포트 | ⑤ 출하·수금 | 개발3 |
| COL-040 | 수금 현황 조회 | 조회 | `/col/collections` | COL 수금리포트 | ⑤ 출하·수금 | 개발3 |
| COL-050 | 거래처별 미수 조회 | 조회 | `/col/receivables` | COL 수금리포트 | ⑤ 출하·수금 | 개발3 |
| COL-060 | 미수 연령 조회 | 조회 | `/col/aging` | COL 수금리포트 | ⑤ 출하·수금 | 개발3 |
| COL-070 | 출하 대비 수금 조회 | 조회 | `/col/shipment-vs-collection` | COL 수금리포트 | ⑤ 출하·수금 | 개발3 |
| TRK-010 | 주문 진행 조회 | 조회 | `/trk/orders` | TRK 통합 조회 | ⑥ 추적·분석 | 개발1 |
| TRK-020 | 납기 현황 | 조회 | `/trk/due` | TRK 통합 조회 | ⑥ 추적·분석 | 개발1 |
| TRK-030 | 거래처 종합 조회 | 조회 | `/trk/customers` | TRK 통합 조회 | ⑥ 추적·분석 | 개발1 |
| LOT-010 | 정방향 추적 | 조회 | `/lot/forward` | LOT LOT 추적 | ⑥ 추적·분석 | 개발2 |
| LOT-020 | 역방향 추적 | 조회 | `/lot/backward` | LOT LOT 추적 | ⑥ 추적·분석 | 개발2 |
| PRP-010 | 월별 가동률 | 리포트 | `/prp/utilization` | PRP 생산 보고서 | ⑥ 추적·분석 | 개발3 |
| PRP-020 | 기계별통계 | 리포트 | `/prp/machines` | PRP 생산 보고서 | ⑥ 추적·분석 | 개발3 |
| PRP-030 | 생산완료집계 | 리포트 | `/prp/completion` | PRP 생산 보고서 | ⑥ 추적·분석 | 개발3 |
| RPT-010 | 수주 리포트 | 리포트 | `/rpt/orders` | RPT 대시보드 | ⑥ 추적·분석 | 개발3 |
| RPT-020 | 생산 리포트 | 리포트 | `/rpt/production` | RPT 대시보드 | ⑥ 추적·분석 | 개발3 |
| RPT-030 | 품질 리포트 | 리포트 | `/rpt/quality` | RPT 대시보드 | ⑥ 추적·분석 | 개발3 |
| RPT-040 | 재고·창고 리포트 | 리포트 | `/rpt/inventory` | RPT 대시보드 | ⑥ 추적·분석 | 개발3 |
| RPT-050 | 출하 리포트 | 리포트 | `/rpt/shipment` | RPT 대시보드 | ⑥ 추적·분석 | 개발3 |
| RPT-060 | 수금 리포트 | 리포트 | `/rpt/collection` | RPT 대시보드 | ⑥ 추적·분석 | 개발3 |
| RPT-070 | 주문 흐름 리포트 | 리포트 | `/rpt/order-flow` | RPT 대시보드 | ⑥ 추적·분석 | 개발3 |
| RPT-080 | 경영 요약 | 리포트 | `/rpt/summary` | RPT 대시보드 | ⑥ 추적·분석 | 개발3 |
| DOC-010 | 문서관리 바로가기 | 외부 연계(SSO) | `/doc/go` | DOC 문서관리 | ⑦ 지원 | 개발1 |
| DOC-020 | 문서관리 계정 매핑 | 목록·등록 | `/doc/account-map` | DOC 문서관리 | ⑦ 지원 | 개발1 |
| SYS-010 | 사용자 관리 | 목록·등록 | `/sys/users` | SYS 시스템 | ⑦ 지원 | 개발1 |
| SYS-020 | 역할·권한 | 설정 | `/sys/roles` | SYS 시스템 | ⑦ 지원 | 개발1 |
| SYS-030 | 공통코드 | 설정 | `/sys/codes` | SYS 시스템 | ⑦ 지원 | 개발1 |
| SYS-040 | 로그 | 조회 | `/sys/logs` | SYS 시스템 | ⑦ 지원 | 개발1 |
<!-- END:generated screens -->

- 경로 = `/<대메뉴 코드 소문자>/<slug>`(HOME-010 내 할 일만 `/`). 코드에서는 `nav.path_of("WO-010")` 으로 쓴다 — 문자열로 다시 적지 않는다.
- 이 표의 순서는 정본의 묶음 ⓪~⑦ · ORDER 순서 그대로이고, 좌측 메뉴와 메인 카드도 이 순서로 그린다(스펙 §3.1).
- 기능의 엔드포인트는 전부 그 화면 경로 아래에 있다(`function-list.md` 의 API 열 · `contracts._validate`).
- 화면 GET 을 담당 개발자가 라우터에 등록하기 전에는 placeholder 가 「미구현 — 담당 개발N」과 계약 문장을 보여 준다.

## 2. 공통 경로 — 권한 표 밖

| 경로 | 화면 | 담당 | 비고 |
|---|---|---|---|
| `/login` | 로그인 | 아키텍트 | 누구나. 로그인하면 HOME-010 내 할 일(`/`)로 간다 |
| `/error` | 오류 | 아키텍트 | 인자 없이 열면 오류 계약 안내(200) — `api-contract.md` |
| `/ia` | IA 참고 화면 | 아키텍트 | 로그인한 누구나. 계약(nav · 권한 표 · 기능 목록)에서 그린 사이트맵 · 권한 매트릭스 — 정본 글은 옮기지 않고 수는 DB · 계약에서 센다(goal.md §3.4) |
| `/health` | 상태 확인 | 아키텍트 | 인증 없음. DB 연결 여부만 |

## 3. 파일 소유권 — 한 파일은 한 사람만 만진다 (goal.md §3.2 · §3.3)

| 담당 | 대메뉴 (화면 수) | 만지는 파일 |
|---|---|---|
| **개발1** 기준·지시·시스템 | HOME 내 업무(3) · BAS 기준정보(3) · STD 인쇄 기준(6) · WO 작업지시(4) · SYS 시스템(4) · TRK 통합 조회(3) · DOC 문서관리(2, W4) — **25** | `app/routers/{home,bas,std,wo,sys,trk,doc}.py` · `templates/{home,bas,std,wo,sys,trk,doc}/` · `jobs.py`(배치 `due-check`) · `sso.py`(W4) · `db/seed_dev1.py` · `tests/test_dev1_*.py` · `progress-dev1.md` |
| **개발2** 자재·생산·품질·재고 | MAT 자재·입고(4) · PRD 생산일보(4) · INS 검사일보(4) · QC 품질 검사(3) · INV 재고(3) · LOT LOT 추적(2) — **20** | `app/routers/{mat,prd,ins,qc,inv,lot}.py` · `templates/{mat,prd,ins,qc,inv,lot}/` · `trace.py`(정·역방향 LOT 추적 — **가장 먼저 공표**) · `db/seed_dev2.py` · `tests/test_dev2_*.py` · `progress-dev2.md` |
| **개발3** 출하·수금·분석 | SHP 출하(3) · PRP 생산 보고서(3) · COL 수금리포트(7, W2) · RPT 대시보드(8, W3) — **21** | `app/routers/{shp,prp,col,rpt}.py` · `templates/{shp,prp,col,rpt}/` · `stats.py` · `erp_upload.py` · `dashboard.py` · `db/seed_dev3.py` · `tests/test_dev3_*.py` · `progress-dev3.md` |
| **QA1** 기능·계약 | G-01~G-04 · 기능 목록 1:1 · 오류 계약 · 화면별 계약 문장 대조 | `tools/check_screens.py` · `tests/test_qa1_*` · `outputs/qa1-기능계약.md` |
| **QA2** 흐름·데이터 | G-05~G-15 | `tools/check_data.py` · `tests/test_qa2_*` · `outputs/qa2-흐름데이터.md` |
| **QA3** 보안·운영 | G-16~G-24 | `tools/check_security.py` · `tests/test_qa3_*` · `outputs/qa3-보안운영.md` · `outputs/e2e/` |
| **아키텍트** | 공통 화면(§2) | `src/lcomfine/db/schema.sql` · `nav.py` · `main.py` · `contracts/*` · `rbac` · `templating` · `notify` · `numbering` (+ `conn` · `audit` · `http` · `settings` · `static/` · `templates/base.html` · `tools/gate.py` · `tools/gen_function_list.py` · `tools/gen_permissions.py` · `tools/gen_contracts.py` · `tools/check_trace.py` · `tools/check_routes.py` · `tools/check_schema.py` · `tools/backup.py` · `tests/test_arch_*.py` · `Makefile`) |

합계 **25 + 20 + 21 = 66**. 소유 밖 파일이 필요하면 `progress-devN.md` §3 에 요청한다. 공용 함수 · 시그니처는 먼저 정한 사람이 `progress-devN.md` §1 에 공표하고, 시그니처 원본은 `contracts/interfaces.md`.
