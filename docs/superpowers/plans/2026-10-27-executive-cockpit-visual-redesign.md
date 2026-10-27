# 엘컴화인 MES 경영 Cockpit 그래프 중심 리디자인 구현 계획

**목표:** 승인된 C+A 통합안을 기준으로 RPT-080을 대형 모니터용 경영 Cockpit으로 전면 재구성하고, 같은 그래프·KPI 언어를 RPT-010~070에 확장한다.

**설계 정본:** `docs/superpowers/specs/2026-10-27-executive-cockpit-visual-redesign-design.md`

**기술 경계:** FastAPI + Jinja2 + PostgreSQL + 기존 인라인 SVG를 유지한다. 외부 차트 라이브러리를 추가하지 않는다. RPT GET은 계속 읽기 전용이며 기존 라우트·권한·산식·MGT 쓰기 계약을 바꾸지 않는다.

## 공통 구현 규칙

- 테스트를 먼저 추가해 실패를 확인한 뒤 구현한다.
- 실제 0과 `미수집`을 구분한다.
- `목표 없음`, `미확정`, `연계 전`을 서로 다른 상태로 표시한다.
- 모든 그래프는 SVG title과 데이터 표의 라벨·값·순서가 일치해야 한다.
- 브랜드 레드는 강조에만 사용하고 정상·주의·위험 상태색과 구분한다.
- 3840×2160, 2560×1440, 1920×1080, 1280px, 390px을 검증한다.
- D-519 로스율과 D-520 병목 기준은 계산하지 않는다.
- 각 단계가 끝날 때 관련 테스트와 `git diff --check`를 실행한다.

## Task 1: 리디자인 시각 계약과 테스트 기반

**수정 파일**

- `tests/test_dev3_rpt.py`
- `tests/test_qa1_rpt.py`
- `tests/test_qa2_rpt.py`
- 신규 `tests/test_qa2_cockpit_visual.py`

**작업**

- [ ] RPT-080 Hero KPI 최대 4개, 목표 종합 달성률, 재무 상태 계약을 테스트한다.
- [ ] 7단계 흐름의 `key`, `value`, `secondary`, `conversion`, `dwell`, `risk_count`, `status`, `href`를 테스트한다.
- [ ] 위험 Top 5의 단계·담당·관측값·링크를 테스트한다.
- [ ] 누적 추세, 납기 전망, Pareto 데이터 모양을 테스트한다.
- [ ] `미수집`, 실제 0, `목표 없음`, `미확정`, `연계 전`의 별도 마크업을 테스트한다.
- [ ] 기존 테스트가 새 계약에서 실패하는 것을 확인한다.

## Task 2: 공통 경영 읽기 모델 확장

**수정 파일**

- `src/lcomfine/app/dashboard.py`
- `src/lcomfine/app/financial.py`

**작업**

- [ ] KPI 비교 모델에 화면 표시용 상태와 링크를 추가한다.
- [ ] 목표가 설정된 KPI만으로 목표 종합 달성률을 계산한다.
- [ ] 영역별 목표 기여 데이터를 만든다.
- [ ] 재무 회차가 없거나 필드가 없을 때 금액별 `연계 전`을 반환한다.
- [ ] 이익은 출하매출과 실제원가가 모두 있을 때만 계산한다.
- [ ] 7단계 흐름의 대표 값·전환율·체류시간·위험 수를 독립 집계한다.
- [ ] 위험 Top 5와 납기 7일 전망, 품질 Pareto 읽기 모델을 만든다.
- [ ] RPT GET 전후 관리·업무 테이블 행 수 불변을 테스트한다.

## Task 3: 그래프·KPI 공통 컴포넌트

**수정 파일**

- `src/lcomfine/app/templates/_charts.html`
- `src/lcomfine/app/templates/rpt/_d.html`
- `src/lcomfine/app/static/style.css`

**작업**

- [ ] `cockpit_hero_kpis`를 구현한다.
- [ ] `attainment_ring`을 구현한다. 목표가 없을 때 링을 그리지 않는다.
- [ ] `contribution_waterfall`을 구현한다.
- [ ] `executive_risk_list`를 구현한다.
- [ ] `process_flow`를 구현한다.
- [ ] `comparison_chart`, `forecast_bars`, `pareto_chart`를 구현한다.
- [ ] 모든 그래프에 동일 데이터 표와 SVG title을 제공한다.
- [ ] 키보드 포커스와 상태 텍스트를 구현한다.
- [ ] 라이트·다크 토큰, 고정폭 숫자, 작은 반경 체계를 정리한다.

## Task 4: RPT-080 대형 모니터 Cockpit

**수정 파일**

- `src/lcomfine/app/routers/rpt.py`
- `src/lcomfine/app/templates/rpt/summary.html`
- `src/lcomfine/app/static/style.css`

**작업**

- [ ] 제목·기간·거래처·일간/주간/월간 제어부를 한 줄 Cockpit 헤더로 재구성한다.
- [ ] Hero KPI 4개를 첫 행에 배치한다.
- [ ] 목표 달성 링·기여 waterfall과 위험 Top 5를 60:40으로 배치한다.
- [ ] 7단계 연결형 프로세스 그래프를 구현한다.
- [ ] 누적 추세·납기 전망·불량 Pareto를 비대칭 3열로 배치한다.
- [ ] 모든 링크에 기간·거래처 필터를 보존한다.
- [ ] 일일 데이터가 적을 때 반복되는 `미수집` 카드 대신 통합 빈 상태를 제공한다.
- [ ] 도움말을 새 읽기 순서에 맞게 갱신한다.

## Task 5: RPT-010~040 그래프 중심 재구성

**수정 파일**

- `src/lcomfine/app/templates/rpt/orders.html`
- `src/lcomfine/app/templates/rpt/production.html`
- `src/lcomfine/app/templates/rpt/quality.html`
- `src/lcomfine/app/templates/rpt/inventory.html`
- `src/lcomfine/app/dashboard.py`

**작업**

- [ ] 수주에 목표 대비 누적 추세, 거래처·품목 구성, 납기위험을 배치한다.
- [ ] 생산에 계획·실적 비교, 설비 가동·정지, 지연 지시를 배치한다.
- [ ] 품질에 합격·불합격 추세, 불량 Pareto, 반복 불량·보류 LOT를 배치한다.
- [ ] 재고에 현재·가용·할당 구성, 체류 에이징, 실사 차이를 배치한다.
- [ ] 상세 표는 그래프 아래로 이동하고 기본 화면의 시각 밀도를 낮춘다.

## Task 6: RPT-050~070 그래프 중심 재구성

**수정 파일**

- `src/lcomfine/app/templates/rpt/shipment.html`
- `src/lcomfine/app/templates/rpt/collection.html`
- `src/lcomfine/app/templates/rpt/order_flow.html`
- `src/lcomfine/app/dashboard.py`

**작업**

- [ ] 출하에 목표 누적, 7·14·30일 부하, 납기위험·차단 원인을 배치한다.
- [ ] 수금에 출하·매출·수금 추세, 미수 연령, 거래처 위험과 ERP 기준일을 배치한다.
- [ ] 주문흐름에 단계 체류, 의뢰 타임라인, 미착수 다음 단계를 배치한다.
- [ ] D-520 병목은 미확정 상태와 단계 소요일을 함께 유지한다.
- [ ] 모든 업무 링크가 기간·거래처·업무 키를 보존하는지 확인한다.

## Task 7: 대형 모니터·반응형·접근성 QA

**수정 파일**

- `src/lcomfine/app/static/style.css`
- `tests/test_arch_layout.py`
- `tests/test_qa1_rpt.py`
- `tests/test_qa2_cockpit_visual.py`

**작업**

- [ ] 1920px 이상에서 Hero, 성과·위험, 7단계 흐름이 첫 화면에 들어오는지 확인한다.
- [ ] 1280px에서 7단계를 4+3행으로 재배치한다.
- [ ] 390px에서 세로 흐름과 접힌 데이터 표를 제공한다.
- [ ] 가로 넘침, 글자 겹침, CTA 줄바꿈이 없도록 정적·브라우저 검증한다.
- [ ] 라이트·다크와 정상·주의·위험 대비를 확인한다.
- [ ] 키보드 탭 순서, 포커스 링, 표 접근성을 확인한다.
- [ ] 불필요한 애니메이션과 `prefers-reduced-motion` 위반이 없는지 확인한다.

## Task 8: 전체 회귀·실기동·완료 감사

**수정 파일**

- `progress.md`
- 필요 시 QA 보고서와 게이트 기대값

**작업**

- [ ] 관련 RPT·Cockpit 테스트를 실행한다.
- [ ] `UV_CACHE_DIR=/tmp/lcomfine-uv-cache uv run pytest -q`를 통과시킨다.
- [ ] `UV_CACHE_DIR=/tmp/lcomfine-uv-cache make gate-full`을 통과시킨다.
- [ ] Docker 이미지를 재빌드하고 `/health` 200을 확인한다.
- [ ] 실제 브라우저에서 3840×2160, 1920×1080, 1280px, 390px을 캡처·검토한다.
- [ ] 리디자인 전후의 정보 위계와 첫 화면 가독성을 대조한다.
- [ ] `progress.md`에 실제 통과 수치만 기록한다.
- [ ] 최종 커밋을 남기고 작업 트리가 깨끗한지 확인한다.

## 완료 조건

- 경영진이 대형 모니터 첫 화면에서 목표·재무 성과, 즉시 위험, 7단계 흐름을 동시에 읽을 수 있다.
- RPT-010~070이 같은 KPI·그래프·상태 언어를 사용한다.
- 기존 URL·권한·쓰기 경계·산식 계약이 유지된다.
- 전체 테스트와 `gate-full`이 FAIL·미검증·BLOCKED 0이다.
