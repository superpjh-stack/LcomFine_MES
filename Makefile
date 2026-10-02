# 엘컴화인 MES — 게이트 실행. 판정은 이 명령의 출력으로만 한다. (명령은 전부 `uv run …` — 시스템 python 을 쓰지 않는다)
.PHONY: setup db-schema db-seed db-reset contracts run test check-routes check-trace check-schema check-data check-security gate gate-full backup restore-check

DB := lcomfine_db
PORT ?= 8020

setup:           # uv(Python 3.12) · 로컬 .env(난수 비밀) · DB 생성
	uv python pin 3.12 && uv sync
	uv run python tools/init_env.py
	@psql -d postgres -Atc "select 1 from pg_database where datname='$(DB)'" | grep -q 1 || createdb $(DB)
	@echo "DB $(DB) 준비됨 — 다음: make db-reset && make gate"

db-schema:       # 스키마를 지우고 다시 만든다 (데이터가 전부 사라진다 — 한 번에 한 사람만)
	psql -q -d $(DB) -v ON_ERROR_STOP=1 -c 'set client_min_messages = warning; drop schema public cascade; create schema public;'
	psql -q -d $(DB) -v ON_ERROR_STOP=1 -f src/lcomfine/db/schema.sql
	@psql -d $(DB) -Atc "select '테이블 '||count(*) filter (where table_type='BASE TABLE')||' · 뷰 '||count(*) filter (where table_type='VIEW') from information_schema.tables where table_schema='public'"

db-seed:         # 공통 → 개발1 → 개발2 → 개발3 (seed_devN.py 가 있는 것만). 두 번 돌려도 행 수가 같아야 한다
	uv run python -m lcomfine.db.seed

db-reset: db-schema db-seed

contracts:       # 렌더본 다시 찍기: db-schema.md §4 ← schema.sql + DB · screen-map.md §1 ← nav.py
	uv run python tools/gen_contracts.py

run:             # 8000 은 다른 사업이 쓴다
	uv run uvicorn lcomfine.app.main:app --app-dir src --port $(PORT) --reload

test:
	uv run pytest -q

check-routes:    # G-03 — 32 화면 + 공통 3 HTTP 200 · placeholder 수 · 권한 없음 403
	uv run python tools/check_routes.py

check-trace:     # G-01 · G-02 — 설계도 ↔ nav.py ↔ function-list.md ↔ 라우트 ↔ 테스트
	uv run python tools/check_trace.py

check-schema:    # G-04 — 계약 ↔ 실제 DB
	uv run python tools/check_schema.py

check-data:      # G-05~G-12 — QA2 가 만든다
	@test -f tools/check_data.py || { echo "미구현 — tools/check_data.py 없음 (QA2)"; exit 1; }
	uv run python tools/check_data.py

check-security:  # G-13~G-20 — QA3 가 만든다
	@test -f tools/check_security.py || { echo "미구현 — tools/check_security.py 없음 (QA3)"; exit 1; }
	uv run python tools/check_security.py

gate:            # G-01~G-22 판정표 (읽기 전용). 시드 멱등(G-09)까지 재려면 `make gate-full` — **종료 판정은 gate-full 로 한다**(gate 의 G-09 는 늘 미검증)
	@uv run python tools/gate.py

gate-full:       # 시드를 한 번 더 돌려 행 수 diff 를 잰다 — 다른 사람이 시드·스키마를 돌리는 중에는 쓰지 않는다
	@uv run python tools/gate.py --run-seeds

backup:          # G-20 — pg_dump → backups/<DB>-<일시>.dump + 덤프 시점의 테이블별 행 수(.json). backups/ 는 gitignore. 운영 DB 는 읽기만 한다
	uv run python tools/backup.py backup

restore-check:   # G-20 — 가장 최근 덤프를 **별도의 임시 DB** 에 복구해 테이블별 행 수를 대조하고 임시 DB 를 지운다 ($(DB) 를 덮어쓰지 않는다)
	uv run python tools/backup.py restore-check
