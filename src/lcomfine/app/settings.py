"""환경 설정 — `LCOMFINE_*` 환경변수 단일 소스.

설계도에 수치가 없는 값(자동 로그아웃 시간 등)은 **코드에 기본값을 지어내지 않는다.** 값이 없으면 `None` 이고
그 기능을 적용하지 않는다. 비밀(세션 비밀·시드 비밀번호)은 저장소 밖 `.env`(gitignore)에만 둔다 (G-19).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PREFIX = "LCOMFINE_"
ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = ROOT / ".env"
UNDECIDED = "미확정"


def load_dotenv(path: Path = ENV_FILE) -> int:
    """`.env` 를 읽어 **아직 없는** 환경변수만 채운다(셸 값이 우선). 파일이 없으면 0."""
    if not path.exists():
        return 0
    n = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n


load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(PREFIX + name)
    if v is None or v.strip() == "":
        return default
    return v.strip()


def _env_int(name: str) -> int | None:
    v = _env(name)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError as exc:
        raise ValueError(f"{PREFIX}{name} 는 정수여야 한다: {v!r}") from exc


@dataclass(frozen=True)
class Settings:
    env: str                           # dev | prod
    pg_dsn: str
    port: int                          # 8020 — 8000 은 다른 사업이 쓴다
    session_secret: str                # 비면 기동할 때마다 난수
    session_cookie: str
    session_idle_minutes: int | None   # 설계도에 수치 없음 → 값이 없으면 만료시키지 않는다 (D-20)
    seed_password: str | None          # 시드 계정 비밀번호 — 환경변수로만 (G-19)
    board_refresh_seconds: int         # 현황판 자동 새로고침 주기. 기본 30 (가설 D-19)
    grid_page_size: int                # 목록 한 쪽 행 수

    @property
    def session_idle_label(self) -> str:
        if self.session_idle_minutes is None:
            return f"{UNDECIDED} (D-20)"
        return f"{self.session_idle_minutes}분"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        env=_env("ENV", "dev") or "dev",
        pg_dsn=_env("PG_DSN", "postgresql:///lcomfine_db") or "postgresql:///lcomfine_db",
        port=_env_int("PORT") or 8020,
        session_secret=_env("SESSION_SECRET", "") or "",
        session_cookie=_env("SESSION_COOKIE", "lcomfine_session") or "lcomfine_session",
        session_idle_minutes=_env_int("SESSION_IDLE_MINUTES"),
        seed_password=_env("SEED_PASSWORD"),
        board_refresh_seconds=_env_int("BOARD_REFRESH_SECONDS") or 30,
        grid_page_size=_env_int("GRID_PAGE_SIZE") or 10,
    )


def reset_cache() -> None:
    """테스트용 — 환경변수를 바꾼 뒤 부른다."""
    get_settings.cache_clear()
