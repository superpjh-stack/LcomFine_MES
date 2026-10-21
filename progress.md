# 진행 상태 (v2 · 2026-10-21 정본 기준)

검증된 것만 적는다. 여기 없는 숫자는 화면에 지어내지 않는다. 형식: `| 항목 | 실측 | 검증 방법 |`.
옛 판(설계도 기준 · 대메뉴 12)의 기록은 `progress-v1.md` 에 있다 — v2 의 실측이 아니다.

## 지금 해야 할 것: Phase 0 (아키텍트)

`goal.md` §3.1 Phase 0 — 정본 추출 · 계약 7종 · 스키마 · 시드(부서 8 · 권한 260 · 계정 8 · 채번 7 · 공통코드 3그룹) · 게이트 도구 · placeholder 67 · 새 CSS · 로그인/레이아웃.
Phase 0 끝 = G-01 · G-04 PASS, G-02 는 계약 존재, G-03 은 placeholder 67 로 FAIL(정상). 그다음 W1 핵심 흐름(개발 3 병렬).

## 2026-10-21 Phase 0 실측

| 항목 | 실측 | 검증 방법 |
|---|---|---|
| 정본 추출 | `contracts/ia.json` · `contracts/ia-overrides.json`(D-505) 커밋됨 | `git log --oneline -- contracts/ia.json` |
| 기대값 | 묶음 8 · 대메뉴 17 · 화면 67 · 흐름 7 · 권한 260(W 64 · R 196) | `goal.md` §2.0 명령 (`design_doc.effective()`) |
| 문서 체계 | `goal.md` · `CLAUDE.md` · `decisions.md`(D-501~D-520) · `progress.md` 새로 · 옛 대장 `decisions-v1.md` · `progress-v1.md` · 옛 설계도 `docs/archive/` | `git log -1 --stat` |
| 계약 7종 | 미검증 | `ls contracts/` |
| 스키마 | 미검증 | `make check-schema` (G-04) |
| 시드 | 미검증 | `make db-seed` ×2 · 행 수 diff (G-21) |
| nav · 경로 | 미검증 | `make check-trace` (G-01) |
| placeholder | 미검증 | `make check-routes` (G-03) |
| pytest | 미검증 | `uv run pytest -q` |
| 게이트 판정표 | 미검증 | `make gate` |
