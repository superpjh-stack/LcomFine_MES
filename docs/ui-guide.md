# 화면 정리 안내 (담당 개발용)

운영 시스템 화면이다. 본문에는 **일에 필요한 것만**, 설명은 오른쪽 **「화면 도움말」** 패널에 짧게 둔다.
공용 틀은 아키텍트 소유(`base.html` · `_macros.html` · `_charts.html` · `util/viz.py` · `style.css` · `app.js`) — 각 담당은 자기 템플릿만 고친다.

본보기 두 화면 — 이것을 보고 따라 한다:
- 업무 화면: `src/lcomfine/app/templates/wo/requests.html` (WO-010 생산의뢰서)
- 대시보드: `src/lcomfine/app/templates/rpt/production.html` (RPT-020 생산 리포트) · 공용 조각 `rpt/_d.html`

## 1. 지울 것 · 남길 것

| 지운다 (본문 · 패널 어디에도) | 남긴다 |
|---|---|
| 개발 메모 문단 (`<p class="muted">원천: … 캐시 없음 · D-512 …</p>`) | `미확정 (D-nn)` 글자 — `ui.undecided("D-nn", "한 줄 뜻")` 칩으로 (QA 가 본문 글자를 본다) |
| 함수 이름 (`numbering.next` · `stats.*`), 기능 ID (`F-WO-011`), 오류 코드 (422/404) | `data-*` 표식 전부 (`data-kpi` · `data-series` · `data-series-table` · `data-table` · `data-section` · `data-receivable` …) |
| D 번호 나열 (「D-509 · D-512 · D-805」) | 정본 L3 낱말이 들어간 제목(「의뢰 목록」 「기계별 통계」 …) |
| 「IA 전체의 수주 기준」 같은 설계 문장 | `(예시)` · `미수집` 표시 |

개발 계약(기능 ID · API · W 부서 · 계약 문장)은 `/ia` 의 **「기능 계약」 표**에만 있다.

## 2. 화면 머리

```jinja
{% import "_macros.html" as ui %}
{% call ui.screen_head(screen.name) %}
  {% if fn_allowed.get("F-WO-011") %}<a class="btn btn-primary" href="#req-form">＋ 의뢰 등록</a>{% endif %}
{% endcall %}
```
링크 단추만이면 `ui.screen_head(screen.name, [(경로, "이름", "primary")])`. 제목 아래 설명 문단은 두지 않는다.

## 3. 조회 조건 — 한 줄 필터 바

```jinja
<form class="filters" method="get" role="search" aria-label="조회 조건">
  <label class="field field--grow"><span>검색</span><input type="search" name="q" value="{{ form.q }}" placeholder="의뢰번호 · 거래처 · 제품"></label>
  {{ f.select("status", "상태", st_opts, form.status, blank="전체") }}
  {% call ui.filters_more(open=(form.customer or form.due_from)) %}   {# 자주 안 쓰는 조건은 접는다 · 값이 있으면 열린 채 #}
    …
  {% endcall %}
  <div class="filters__go"><button type="submit" class="btn btn-primary">조회</button></div>
</form>
```
입력 `name` 은 바꾸지 않는다(라우터 · 테스트가 그 이름으로 읽는다).

## 4. 등록 · 수정 폼 — 접히는 패널

```jinja
{% call ui.form_details("의뢰 등록", open=(flash and flash.kind == "warn"), allowed=fn_allowed.get("F-WO-011")) %}
<form method="post" action="/wo/requests" id="req-form">
  <div class="form-grid"> …입력… </div>
  <div class="actions"><button type="submit" class="btn btn-primary">저장</button></div>
</form>
{% endcall %}
```
- 입력 오류(422)로 돌아오면 `flash.kind == "warn"` — 열린 채로 그린다. 수정 모드(`?edit=`)는 `open=true`.
- `allowed=false`(조회만 부서)면 패널을 그리지 않는다. 단, 테스트가 「이 부서는 이 기능을 실행할 권한이 없습니다」 문장을 보는 화면(예: SHP)은 기존 `f.form_panel` 을 그대로 두거나 그 문장을 남긴다.

## 5. 오른쪽 「화면 도움말」

템플릿에 `{% block help %}` 를 채운다(2~5 항목 · 업무 말투). 안 채우면 기능 **이름** 목록이 자동으로 나온다. 「내 권한(등록·수정 가능 / 조회만)」은 항상 붙는다.

```jinja
{% block help %}
{{ ui.help_item("이 화면에서 할 일", "거래처의 발주 내용을 생산의뢰로 등록하고 …") }}
{{ ui.help_rule("의뢰번호는 저장할 때 자동으로 붙습니다.") }}
{{ ui.undecided_note("D-519", "생산 로스율 산식") }}
{{ ui.help_next("WO-020", "확정된 의뢰로 생산지시서 작성") }}
{% endblock %}
```
규칙 문장은 라우터가 실제로 막는 것만 쓴다(지어내지 않는다). 패널은 `<main>` 밖이라 본문 대조(QA)에 들어가지 않는다 — `미확정 (D-nn)` 은 패널이 아니라 **본문**에 있어야 한다.

## 6. 대시보드

순서: `d.head(screen, data)` → `d.filters(...)` → `d.kpis(data.kpis, sparks={...})` → `{% call ch.grid() %} d.chart_table(…) … {% endcall %}` → 상세 표 `d.table(...)`.

`d.chart_table(name, title, series, label_hdr, value_hdr, digits, kind, sub="", wide=false, sort=false)` — 차트 + **접힌 데이터 표**(`<details class="data-table">` · 쪽 넘김 없음 · HTML 에 그대로). `wide=true` 는 격자 2칸을 쓴다.

| 수치 | kind / 매크로 |
|---|---|
| 기간별 추세(일 · 월) | `line` (점 · 옅은 면 · None 에서 끊김) |
| 기간별 건수 · 수량 비교 | `bar` (세로 막대 · 눈금 · 값 라벨) |
| 거래처 · 품목 · 설비 순위(상위 N · 긴 이름) | `hbar` (`sort=true` 면 큰 값부터 — 표도 같은 순서) |
| 구성비(설비별 몫 · 불량유형 · 연령 구간) 2~6 조각 | `donut` (가운데 합계) · 좁으면 `stack` |
| 단계별 · 상태별 여러 줄 | `ch.stacked(rows, keys)` — data-series 묶음 **밖**에 둔다 |
| 준수율 · 가동률(%) | KPI 단위가 `%` 면 진행 막대가 자동 · 따로는 `ch.meter(label, value)` |
| 값 하나 | KPI 타일(`ch.kpi_tile` — 스파크라인은 `sparks={key: series}`) |

QA 가 기계로 보는 것 — 바꾸지 않는다: 값마다 SVG `<title>` 「라벨: 값」 한 줄 = 데이터 표 행(`<tr><td>라벨</td><td class="num">값</td></tr>`) · KPI `<div class="kpi" data-kpi>` 안 `<strong class="kpi__value num">` · 표는 `grid-wrap` 안 · 스크립트 0. 색은 토큰(`--viz-1…6` 고정 순서)만 — 템플릿에 색 값을 적지 않는다.

## 7. 색 · 톤 (D-527 — 브랜드는 엘컴화인 붉은색)

색은 `style.css` 의 토큰만 쓴다 — 템플릿에 색 값을 적지 않는다. 라이트 · 다크(시스템 설정 `prefers-color-scheme` · 토글 `[data-theme="dark"]`) 세 묶음이 같은 이름을 갖는다.

**브랜드 토큰** — 정확한 브랜드 색을 받으면 `:root` 의 `--brand` 한 줄만 고친다(다크 값은 대비를 다시 재서 함께). `tests/test_arch_layout.py::test_brand_tokens_contrast` 가 대비를 잰다.

| 토큰 | 라이트 | 다크 | 쓰는 곳 |
|---|---|---|---|
| `--brand` | `#b3122e` (흰 바탕 6.90:1) | `#f2667c` (다크 바탕 5.54:1) | 주요 단추 바탕 · 링크 · 현재 단계 · 선택 메뉴 막대 · 포커스 · 상단 3px 띠 · 로고 마크 |
| `--brand-strong` | `#8f0d24` | `#ff8a9a` | 주요 단추 hover · active |
| `--brand-soft` | `#fbe8eb` | `#3a1820` | 선택 메뉴 바탕 · 도움말 「?」 · 폼 머리 아이콘 |
| `--brand-ink` | `#ffffff` (6.90:1) | `#1a0a0e` (6.37:1) | 브랜드 바탕 위 글자 |
| `--cyan` · `--cyan-soft` | `var(--brand)` · `var(--brand-soft)` | (같음) | **옛 이름 — 별칭만.** 새 규칙 · 템플릿은 `--brand*` 를 쓴다 |

**상태색** — 브랜드 레드와 뜻이 다르다. 「나쁨」(오류 · 불합격 · 지연 · 90일 초과)은 주홍 `--bad`(라이트 `#bf4b00` · 다크 `#ff9159`)로 크림슨(H 21°)과 색상이 다르고(H 44°), **색만으로 알리지 않는다**: `.chip--bad` · `.alert--bad` · `.is-error` 행 · 422 팝업(`.popup.warn`) · 오류 화면 코드에는 연한 바탕(`--bad-soft`) · 테두리 · 「!」 표식이 CSS 로 함께 붙는다. `--ok`(초록) · `--warn`(황갈)은 그대로.

**차트 팔레트** — `--viz-1…6` 고정 순서(돌려 쓰지 않는다): 1 남색 · 2 회청 · 3 황토 · 4 보라 · 5 크림슨(브랜드 강조 한 계열) · 6 하늘. 한 계열 차트는 `--viz-1`(남색) 하나. 진행 막대(`ch.meter` tone="accent")도 남색이다.

| 슬롯 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| 라이트 | `#31559a` | `#3797ba` | `#aa7d25` | `#9772c0` | `#b3122e` | `#5b98cc` |
| 다크 | `#4469b0` | `#3ea2c6` | `#a4771c` | `#825ea9` | `#cf3f4c` | `#4a8cc1` |

dataviz `validate_palette.js` — 라이트(surface `#fff`): 명도 띠 · 채도 · 인접 CVD ΔE 18.7 · 정상 시각 ΔE 18.9 · 대비 전부 ≥ 3:1 PASS / 다크(surface `#181e29`): 인접 CVD ΔE 14.7 · 정상 시각 ΔE 15.9 · 대비 ≥ 3:1 PASS. 앞 세 슬롯은 `--pairs all` 도 통과(산점 · 작은 여러 차트는 세 계열까지).

**상태 차트** — 라벨이 상태인 조각 · 막대는 범주색 대신 상태색(`.viz-t-ok|warn|bad|muted`)을 쓴다. `_charts.html` 의 기본 표: 「납기 안 완료」 ok · 「지연 완료」 warn · 「지연」 bad · 「진행」 muted · 「불합격」 bad · 「90일 초과」 bad. 화면마다 더하거나 바꾸려면 `tone={"라벨": "bad"}` 를 `chart_panel` · `columns` · `bars_h` · `donut` · `stack` · `stacked` 에 준다. 「나쁨」 조각의 범례에는 「!」 가 붙는다. SVG `<title>` · 데이터 표 · `data-*` 는 그대로.

**쓰면 안 되는 것**
- 브랜드 레드를 바탕 · 넓은 면 · 표 글자 · 상태 표시에 쓰지 않는다(표 안 링크는 먹색 + 옅은 브랜드 밑줄). 바탕은 중립 회색 · 흰색.
- 오류 · 불합격 · 지연에 `--brand` 를, 단추 · 링크에 `--bad` 를 쓰지 않는다. 상태는 색 하나로 알리지 않는다(글자 · 「!」 · 바탕을 함께).
- 차트 범주에 상태색을, 상태 조각에 범주색을 쓰지 않는다. 일곱째 계열을 만들지 않는다(「기타」 로 접거나 표로).
- 템플릿에 hex · rgb 를 적지 않는다. 새 색이 필요하면 아키텍트에게 토큰을 요청한다.
