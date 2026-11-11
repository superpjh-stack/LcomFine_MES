"""임시 Ethernet telemetry 수집기.

현재 가정: Gallus 장비가 Ethernet TCP 연결로 줄바꿈 구분 JSON을 push한다.
실제 프로토콜이 달라지면 `decode_json_line`만 장비용 Decoder로 교체한다.
수집기는 읽기만 한다.
"""

from __future__ import annotations

import json
import socket
from typing import Any

from .gallus_ems430 import parse_snapshot

MAX_FRAME_BYTES = 64 * 1024


def decode_json_line(line: bytes | str) -> dict[str, Any]:
    """JSON 한 프레임을 검증해 dict로 변환한다."""
    raw = line.encode() if isinstance(line, str) else line
    if len(raw) > MAX_FRAME_BYTES:
        raise ValueError("telemetry frame이 너무 큽니다")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("UTF-8 JSON telemetry frame이 아닙니다") from exc
    if not isinstance(value, dict):
        raise ValueError("telemetry frame의 최상위 값은 object여야 합니다")
    return value


def snapshot_from_line(line: bytes | str) -> dict:
    return parse_snapshot(decode_json_line(line))


def collect_once(host: str, port: int, *, timeout: float = 1.0) -> dict:
    """장비에 연결해 첫 줄을 읽는다. 연결 후 어떠한 payload도 보내지 않는다."""
    with socket.create_connection((host, port), timeout=min(max(timeout, 0.1), 5.0)) as sock:
        sock.settimeout(min(max(timeout, 0.1), 5.0))
        buffer = bytearray()
        while len(buffer) <= MAX_FRAME_BYTES:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            if b"\n" in buffer:
                line = bytes(buffer).split(b"\n", 1)[0].strip()
                return snapshot_from_line(line)
    raise TimeoutError("JSON telemetry frame을 받지 못했습니다")
