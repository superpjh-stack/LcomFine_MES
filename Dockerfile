# 엘컴화인 MES — 앱 이미지 (decisions.md D-03: 운영 환경 미정 → 어디든 올릴 수 있게만 한다. 실제 배포·물리 구성도는 범위 밖)
#
#   docker compose up -d --build        # 앱 + PostgreSQL (docker-compose.yml)
#
# · 비밀(세션 비밀 · 시드 비밀번호 · DB 비밀번호)은 이미지에 넣지 않는다 — 실행할 때 환경변수로 준다 (G-19). `.env` 는 .dockerignore 다.
# · 앱은 `contracts/function-list.md` 를 읽어 기능·권한을 판정하므로 `contracts/` 가 이미지에 들어간다.
# · `postgresql-client` 는 백업 도구(`tools/backup.py` — pg_dump · pg_restore)용이다. 서버와 주 버전이 같아야 한다(둘 다 17).
FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    LCOMFINE_ENV=prod \
    LCOMFINE_PORT=8020

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv==0.12.1

WORKDIR /app

# 의존성 층 — 소스가 바뀌어도 다시 받지 않는다
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# 앱 (프로젝트는 편집 가능 설치 — 패키지가 /app/src 에 그대로 있어야 `contracts/` 를 찾는다)
COPY src ./src
COPY contracts ./contracts
COPY tools/backup.py tools/sample_data.py tools/docker_init.py ./tools/
#   docker_init.py — 빈 DB 면 schema.sql 적용 + 시드 (compose 의 seed 서비스 · 호스트에 저장소가 없어도 된다 — D-31)
#   (예시) 샘플 100행: docker compose exec app /app/.venv/bin/python tools/sample_data.py   (지우기: --clean)
RUN uv sync --frozen --no-dev

RUN useradd --system --home-dir /app --shell /usr/sbin/nologin lcomfine \
 && mkdir -p /app/backups \
 && chown -R lcomfine /app/backups
USER lcomfine

EXPOSE 8020
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('LCOMFINE_PORT','8020'), timeout=4).status == 200 else 1)"]

# 워커는 하나 — 권한 표 캐시(rbac, 5초)와 세션 비밀이 프로세스마다 따로라 여러 워커는 검증하지 않았다 (D-106 · D-26)
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn lcomfine.app.main:app --host 0.0.0.0 --port ${LCOMFINE_PORT:-8020}"]
