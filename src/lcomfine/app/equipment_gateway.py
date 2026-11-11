"""읽기 전용 인쇄기 Ethernet 연결 확인기.

장비별 프로토콜이 확정되기 전에는 데이터를 쓰거나 명령을 전송하지 않고,
설정된 TCP endpoint에 연결만 시도한다. 실제 카운터·상태 수집은 장비
프로토콜을 받은 뒤 별도 adapter로 추가한다.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    equipment_code: str
    host: str
    port: int
    timeout: float = 0.5


def endpoints() -> dict[str, Endpoint]:
    """`LCOMFINE_EQUIPMENT_ENDPOINTS` JSON 설정을 읽는다.

    예: {"EQ01": {"host": "192.168.0.21", "port": 9100}}
    잘못된 설정은 장비 전체를 중단시키지 않고 해당 항목을 제외한다.
    """
    raw = os.getenv("LCOMFINE_EQUIPMENT_ENDPOINTS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    result: dict[str, Endpoint] = {}
    for code, value in data.items() if isinstance(data, dict) else ():
        if not isinstance(value, dict):
            continue
        host = str(value.get("host", "")).strip()
        try:
            port = int(value.get("port"))
            timeout = min(max(float(value.get("timeout", 0.5)), 0.1), 2.0)
        except (TypeError, ValueError):
            continue
        if code and host and 1 <= port <= 65535:
            result[str(code)] = Endpoint(str(code), host, port, timeout)
    return result


def probe(endpoint: Endpoint) -> dict:
    """TCP 연결만 확인한다. payload 전송·장비 제어는 하지 않는다."""
    try:
        with socket.create_connection((endpoint.host, endpoint.port), timeout=endpoint.timeout):
            return {"status": "연결됨", "detail": "TCP 연결 확인 · 프로토콜 대기"}
    except socket.timeout:
        return {"status": "응답없음", "detail": "TCP 연결 시간 초과"}
    except OSError as exc:
        return {"status": "응답없음", "detail": f"TCP 연결 실패 ({exc.__class__.__name__})"}


def probe_all() -> dict[str, dict]:
    return {code: probe(endpoint) for code, endpoint in endpoints().items()}
