# 화면 맵 — 중메뉴 32 + 공통 3 (아키텍트 · 2026-10-03)

> 메뉴·경로의 원본은 `src/lcomfine/app/nav.py` 다(D-08). **§1 은 그 파일의 렌더본**이라 손으로 고치지 않는다(`make contracts`).
> 이름과 순서는 설계도 §5 IA 구성도 글자 그대로이고 `make check-trace` 가 설계도와 대조한다(G-01).
> 경로·화면 ID·모듈·중메뉴별 채널은 설계도에 없어 아키텍트가 정한 `가설` 이다(D-19·D-22).

## 1. 중메뉴 32 → 경로 · 담당 · 채널 (렌더본)

<!-- BEGIN:generated screens -->
| # | 화면 ID | 묶음 | 대메뉴 | 중메뉴 | 경로 | 모듈 | 담당 | 채널 | 기능 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | BAS-01 | 기준 · 지시 | 기준정보 관리 | 품목 관리 | `/bas/items` | bas | 개발1 | 관리자 Web | F-BAS-01 ~ 04 (4) |
| 2 | BAS-02 | 기준 · 지시 | 기준정보 관리 | 고객 관리 | `/bas/customers` | bas | 개발1 | 관리자 Web | F-BAS-05 ~ 08 (4) |
| 3 | BAS-03 | 기준 · 지시 | 기준정보 관리 | 공정 관리 | `/bas/processes` | bas | 개발1 | 관리자 Web | F-BAS-09 ~ 12 (4) |
| 4 | BAS-04 | 기준 · 지시 | 기준정보 관리 | 설비 관리 | `/bas/equipment` | bas | 개발1 | 관리자 Web | F-BAS-13 ~ 16 (4) |
| 5 | BAS-05 | 기준 · 지시 | 기준정보 관리 | 불량코드 관리 | `/bas/defect-codes` | bas | 개발1 | 관리자 Web | F-BAS-17 ~ 20 (4) |
| 6 | PRT-01 | 기준 · 지시 | 인쇄 기준 관리 | 판사양 관리 | `/prt/plates` | prt | 개발1 | 관리자 Web | F-PRT-01 ~ 04 (4) |
| 7 | PRT-02 | 기준 · 지시 | 인쇄 기준 관리 | 아니록스 관리 | `/prt/anilox` | prt | 개발1 | 관리자 Web | F-PRT-05 ~ 08 (4) |
| 8 | PRT-03 | 기준 · 지시 | 인쇄 기준 관리 | 잉크조성 관리 | `/prt/inks` | prt | 개발1 | 관리자 Web | F-PRT-09 ~ 12 (4) |
| 9 | JOB-01 | 기준 · 지시 | 작업지시 관리 | 작업지시 | `/job/orders` | job | 개발1 | 관리자 Web | F-JOB-01 ~ 05 (5) |
| 10 | JOB-02 | 기준 · 지시 | 작업지시 관리 | Job-Lot-Roll 매핑 | `/job/mapping` | job | 개발1 | 관리자 Web | F-JOB-06 ~ 07 (2) |
| 11 | POP-01 | 현장 실행 | 생산 실적 (POP) | 작업 실적 | `/pop/work` | pop | 개발2 | 현장 POP | F-POP-01 ~ 03 (3) |
| 12 | POP-02 | 현장 실행 | 생산 실적 (POP) | 정지 · 폐기 | `/pop/stops` | pop | 개발2 | 현장 POP | F-POP-04 ~ 07 (4) |
| 13 | POP-03 | 현장 실행 | 생산 실적 (POP) | 롤 라벨 | `/pop/roll-labels` | pop | 개발2 | 현장 POP | F-POP-08 (1) |
| 14 | MAT-01 | 현장 실행 | 자재 · 입고 | 입고 | `/mat/receipts` | mat | 개발2 | 현장 POP, 관리자 Web | F-MAT-01 ~ 02 (2) |
| 15 | MAT-02 | 현장 실행 | 자재 · 입고 | 입고검사 | `/mat/inspections` | mat | 개발2 | 현장 POP, 관리자 Web | F-MAT-03 ~ 04 (2) |
| 16 | MAT-03 | 현장 실행 | 자재 · 입고 | 원재료 LOT | `/mat/lots` | mat | 개발2 | 관리자 Web, 현장 POP | F-MAT-05 ~ 06 (2) |
| 17 | MAT-04 | 현장 실행 | 자재 · 입고 | 자재 투입 | `/mat/inputs` | mat | 개발2 | 현장 POP | F-MAT-07 ~ 08 (2) |
| 18 | CLR-01 | 현장 실행 | 조색 기록 | 조색 기록 | `/clr/records` | clr | 개발2 | 현장 POP | F-CLR-01 ~ 05 (5) |
| 19 | RLL-01 | 현장 실행 | 후가공 · 슬리팅 롤 이력 | 후가공 | `/rll/finishing` | rll | 개발2 | 현장 POP | F-RLL-01 ~ 03 (3) |
| 20 | RLL-02 | 현장 실행 | 후가공 · 슬리팅 롤 이력 | 슬리팅 | `/rll/slitting` | rll | 개발2 | 현장 POP | F-RLL-04 ~ 05 (2) |
| 21 | RLL-03 | 현장 실행 | 후가공 · 슬리팅 롤 이력 | 롤 이력 | `/rll/history` | rll | 개발2 | 현장 POP | F-RLL-06 ~ 07 (2) |
| 22 | QUA-01 | 품질 · 출하 | 품질 검사 기록 | 검사 결과 | `/qua/inspections` | qua | 개발3 | 관리자 Web, 현장 POP | F-QUA-01 ~ 04 (4) |
| 23 | QUA-02 | 품질 · 출하 | 품질 검사 기록 | 불량 집계 | `/qua/defect-stats` | qua | 개발3 | 관리자 Web | F-QUA-05 ~ 06 (2) |
| 24 | SHP-01 | 품질 · 출하 | 출하 | 출하 | `/shp/shipments` | shp | 개발3 | 현장 POP, 관리자 Web | F-SHP-01 ~ 04 (4) |
| 25 | SHP-02 | 품질 · 출하 | 출하 | 출하 승인 | `/shp/approvals` | shp | 개발3 | 관리자 Web | F-SHP-05 (1) |
| 26 | SHP-03 | 품질 · 출하 | 출하 | COA | `/shp/coa` | shp | 개발3 | 관리자 Web | F-SHP-06 ~ 07 (2) |
| 27 | TRC-01 | 조회 · 관리 | LOT 추적 | 추적 (정방향, 역방향, LOT 검색) | `/trc/trace` | trc | 개발3 | 관리자 Web, 모바일 | F-TRC-01 ~ 03 (3) |
| 28 | STA-01 | 조회 · 관리 | 실적 현황 | 집계 (생산, 품질, 납기) | `/sta/summary` | sta | 개발3 | 관리자 Web, 모바일 | F-STA-01 ~ 03 (3) |
| 29 | STA-02 | 조회 · 관리 | 실적 현황 | 현황판 | `/sta/board` | sta | 개발3 | 현황판 | F-STA-04 (1) |
| 30 | SYS-01 | 조회 · 관리 | 시스템 관리 | 사용자 | `/sys/users` | sys | 개발1 | 관리자 Web | F-SYS-01 ~ 04 (4) |
| 31 | SYS-02 | 조회 · 관리 | 시스템 관리 | 권한 | `/sys/permissions` | sys | 개발1 | 관리자 Web | F-SYS-05 ~ 06 (2) |
| 32 | SYS-03 | 조회 · 관리 | 시스템 관리 | 로그 | `/sys/logs` | sys | 개발1 | 관리자 Web | F-SYS-07 (1) |
<!-- END:generated screens -->

- 화면 ID = `<대메뉴 코드>-nn`. 경로 = `/<모듈>/<슬러그>`. 코드에서는 `nav.path_of("BAS-01")` 로 쓴다.
- 이 표의 순서는 설계도 §5 그대로다(G-01). **화면(좌측 메뉴 · 메인 카드)은** 묶음 없이 일하는 순서(메인은 IA 화면 — 흐름 · 메뉴 · 데이터 · 계보 · 사용자 · 확인 필요, D-419)(`nav.SIDEBAR` — 메인 → 실적 현황 → 영업관리 → 작업지시 관리 → 자재 · 입고 → 조색 기록 → 생산 실적 (POP) → 후가공 · 슬리팅 롤 이력 → 품질 검사 기록 → 출하 → LOT 추적 → 기준정보 관리 → 인쇄 기준 관리 → 시스템 관리)로 그리고, 대메뉴를 누르면 중메뉴가 펼쳐진다(D-417).
- 「기능」 열은 그 화면에 묶인 `function-list.md` 의 줄이다. 기능의 엔드포인트는 전부 그 화면 경로 아래에 있다.
- 화면 GET 을 담당 개발자가 라우터에 등록하기 전에는 `_placeholder` 가 200 으로 "미구현 — 담당 개발N" 과 계약 문장을 보여 준다.

## 2. 대메뉴 12 → 권한 · 채널 (설계도 §6 그대로)

| 묶음 | 코드 | 대메뉴 | 기능 수 | 관리자 | 생산 | 품질 | 현장 | 주로 쓰는 채널 | 담당 |
|---|---|---|---|---|---|---|---|---|---|
| 기준 · 지시 | BAS | 기준정보 관리 | 20 | 입력 | 조회 | 조회 | 없음 | 관리자 Web | 개발1 |
| 기준 · 지시 | PRT | 인쇄 기준 관리 | 12 | 입력 | 입력 | 조회 | 조회 | 관리자 Web | 개발1 |
| 기준 · 지시 | JOB | 작업지시 관리 | 7 | 입력 | 입력 | 조회 | 조회 | 관리자 Web | 개발1 |
| 현장 실행 | POP | 생산 실적 (POP) | 8 | 조회 | 입력 | 조회 | 입력 | 현장 POP | 개발2 |
| 현장 실행 | MAT | 자재 · 입고 | 8 | 조회 | 입력 | 입력 (입고검사) | 입력 | 현장 POP, 관리자 Web | 개발2 |
| 현장 실행 | CLR | 조색 기록 | 5 | 조회 | 조회 | 입력 | 입력 | 현장 POP | 개발2 |
| 현장 실행 | RLL | 후가공 · 슬리팅 롤 이력 | 7 | 조회 | 입력 | 조회 | 입력 | 현장 POP | 개발2 |
| 품질 · 출하 | QUA | 품질 검사 기록 | 6 | 조회 | 조회 | 입력 | 조회 | 관리자 Web, 현장 POP | 개발3 |
| 품질 · 출하 | SHP | 출하 | 7 | 입력 (승인) | 입력 | 조회 | 입력 | 현장 POP, 관리자 Web | 개발3 |
| 조회 · 관리 | TRC | LOT 추적 | 3 | 조회 | 조회 | 조회 | 없음 | 관리자 Web, 모바일 | 개발3 |
| 조회 · 관리 | STA | 실적 현황 | 4 | 조회 | 조회 | 조회 | 조회 | 관리자 Web, 현황판, 모바일 | 개발3 |
| 조회 · 관리 | SYS | 시스템 관리 | 7 | 입력 | 없음 | 없음 | 없음 | 관리자 Web | 개발1 |

48칸 = 입력 19 · 조회 24 · 없음 5. 이 표는 **기본값**이다 — 운영값은 DB `sys_permission` 이고 시스템 관리 > 권한 화면이 바꾼다.

권한이 화면에서 뜻하는 것 (D-14):

| 칸 | 메뉴 | 화면 GET | 쓰기 기능 |
|---|---|---|---|
| `없음` | 숨김 | 403 | 403 |
| `조회` | 보임 | 200 | 403 |
| `입력` | 보임 | 200 | 범위가 `일반` 인 기능만 200 |
| `입력 (입고검사)` | 보임 | 200 | `F-MAT-03` 만 200, 나머지 쓰기는 403 |
| `입력 (승인)` | 보임 | 200 | `F-SHP-05` 만 200, 나머지 쓰기는 403 |

## 3. 공통 화면 3 과 파일 소유권 (D-22)

| 화면 | 경로 | 담당 | 비고 |
|---|---|---|---|
| 메인 | `/` | 개발1 | 권한 표 밖 — 로그인한 누구나. 아키텍트가 최소 구현(묶음별 바로가기)을 넣어 두었다 |
| 로그인 | `/login` | 아키텍트 | 화면에서 채널을 골라 로그인하면 그 채널로 세션 고정. `?device=pop\|mobile\|board` 로 열면 그 채널이 미리 골라져 있다 (D-30) |
| 오류 | `/error` | 아키텍트 | 인자 없이 열면 오류 계약 안내(200) |

| 담당 | 만지는 파일 |
|---|---|
| 아키텍트 | `app/{main,nav,rbac,auth,templating,settings,contracts}.py` · `app/util/` · `templates/{base,login,_error,_placeholder}.html` · `templates/home/_macros.html` · `static/` · `db/{schema.sql,conn.py,seed.py}` · `tools/{gate,check_routes,check_trace,gen_contracts,init_env,backup}.py` · `Makefile` · `Dockerfile` · `docker-compose.yml` · `.env.example` · `contracts/` · `CLAUDE.md` (`tools/check_schema.py` 는 QA2 가 이어받았다 — D-24) |
| 개발1 | `app/routers/{home,bas,prt,job,sys}.py` · `templates/{home,bas,prt,job,sys}/`(`home/_macros.html` 제외) · `app/numbering.py` · `db/seed_dev1.py` · `tests/test_dev1_*.py` · `progress-dev1.md` |
| 개발2 | `app/routers/{pop,mat,clr,rll}.py` · `templates/{pop,mat,clr,rll}/` · `app/{lineage,printing}.py` · `db/seed_dev2.py` · `tests/test_dev2_*.py` · `tests/test_lineage_scenario.py` · `progress-dev2.md` |
| 개발3 | `app/routers/{qua,shp,trc,sta}.py` · `templates/{qua,shp,trc,sta}/` · `app/{erp,stats}.py` · `src/lcomfine/migration/` · `db/seed_dev3.py` · `tests/test_dev3_*.py` · `contracts/migration-files.md`(제안) · `progress-dev3.md` |
| QA1 · QA2 · QA3 | `tools/check_screens.py` · `tools/check_data.py`(+ `check_schema.py` 확장) · `tools/check_security.py` · `tests/test_qa{1,2,3}_*.py` · `outputs/` |

공용 매크로·스타일이 모자라면 직접 고치지 말고 `progress-devN.md` §3 에 요청한다.

## 4. 화면 사이의 흐름 (goal.md §3.2)

```
작업지시(JOB-01) ─ Job 번호
  → 입고(MAT-01) → 입고검사(MAT-02 · 품질) ─ 합격 LOT 만 투입 가능
  → 조색 기록(CLR-01 · Job 참조)
  → 작업 실적(POP-01) 시작 → 자재 투입(MAT-04) 스캔 → 작업 실적 종료 = 인쇄 롤 + 라벨(POP-03)   [정지·폐기 POP-02]
  → 후가공(RLL-01) 롤 스캔 1개 또는 N개(splice) → 후가공 롤 + 라벨
  → 슬리팅(RLL-02) 롤 1개 → N개 + 라벨                                                        [롤 이력 RLL-03]
  → 검사 결과(QUA-01) 롤 스캔 → ΔE·판정·불량                                                  [불량 집계 QUA-02]
  → 출하(SHP-01) 등록 → 롤 스캔 → 출하 승인(SHP-02 · 관리자) → COA(SHP-03)
  → 추적(TRC-01) · 집계(STA-01) · 현황판(STA-02)
```

프로세스끼리 직접 주고받지 않는다. 앞 화면이 만든 번호(Job · 원재료 LOT · 롤 · 출하 LOT)를 다음 화면이 스캔하거나 고른다.
스캔으로 들어오는 화면은 `?no=<번호>` 로도 열린다 — 라벨의 바코드를 스캔칸에 넣으면 그 LOT/롤이 열린다(G-14).

## 5. 채널 (G-13 · D-19)

| 채널 | 여는 법 | 레이아웃 (`base.html` 의 `body.ch-*`) | 대상 화면 |
|---|---|---|---|
| 관리자 Web | 기본 | 3단(메뉴 · 본문 · 계약 패널) | §1 의 채널에 `관리자 Web` 이 있는 화면 |
| 현장 POP | 로그인 화면에서 `현장 POP` 을 고르거나 `?device=pop` · `/login?device=pop` | 터치용 확대 · 계약 패널 숨김 · 스캔칸 포커스(`_macros.scan_box`) · 알림은 큰 글씨. 알림이 떠 있어도 스캔을 받고, 닫으면 스캔칸으로 돌아온다(`app.js`) | `현장 POP` 이 있는 화면 |
| 모바일 | 로그인 화면에서 `모바일` 또는 `?device=mobile` | 한 단 · 폭 390px 에서 가로 스크롤 없음 · **본문이 메뉴보다 먼저**(메뉴는 아래, 헤더의 「메뉴」 로 내려간다) | LOT 추적 · 집계 |
| 현황판 | 로그인 화면에서 `현황판` 또는 `?device=board` | 메뉴 없음 · 큰 글씨 · 자동 새로고침(`app.js` 가 서버 응답을 확인하고 다시 그린다 — 오류 화면에서도 이어진다, D-27) · 헤더에 `마지막 갱신` | 현황판 |

채널은 레이아웃만 바꾼다. 어느 채널에서든 권한은 역할로 판정한다.

## 6. 확장 화면 3 — 설계도 밖 (D-418)

설계도의 중메뉴 32 밖이다. `nav.EXT_SCREENS` 가 원본이고 게이트(G-01 · G-03)는 세지 않는다. 계약은 `contracts/extension-list.md`.

| 화면 ID | 대메뉴 | 중메뉴 | 경로 | 모듈 | 담당 | 채널 | 권한 | 기능 |
|---|---|---|---|---|---|---|---|---|
| SAL-01 | 영업관리 | 수주 관리 | `/sal/orders` | sal | 개발1 | 관리자 Web | 작업지시 관리 칸을 따른다 | X-SAL-01 ~ 04 (4) |
| SAL-02 | 영업관리 | 수주 현황 | `/sal/status` | sal | 개발1 | 관리자 Web | 작업지시 관리 칸을 따른다 | X-SAL-05 (1) |
| SAL-03 | 영업관리 | 거래처 이력 | `/sal/customers` | sal | 개발1 | 관리자 Web | 작업지시 관리 칸을 따른다 | X-SAL-06 (1) |

화면 사이의 흐름(§4)에서는 수주(SAL-01)가 작업지시(JOB-01)의 앞에 온다 — 수주 화면의 「이 수주로 작업지시 등록」 이 `JOB-01?sales_order_no=` 로 열리고 고객 · 품목 · 수량 · 납기가 채워진다.
