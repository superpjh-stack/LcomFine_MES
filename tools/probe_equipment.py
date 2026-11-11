#!/usr/bin/env python3
"""인쇄기 Ethernet TCP 연결 확인 — payload를 보내지 않는 안전한 파일럿 도구."""

from __future__ import annotations

import argparse
import json

from lcomfine.app.equipment_gateway import Endpoint, probe


def main() -> int:
    parser = argparse.ArgumentParser(description="읽기 전용 인쇄기 TCP 연결 확인")
    parser.add_argument("--code", default="PILOT", help="설비 코드")
    parser.add_argument("--host", required=True, help="인쇄기 IP 또는 호스트")
    parser.add_argument("--port", required=True, type=int, help="인쇄기 TCP 포트")
    parser.add_argument("--timeout", type=float, default=0.5, help="연결 제한 시간(초, 최대 2초)")
    args = parser.parse_args()
    result = probe(Endpoint(args.code, args.host, args.port, min(max(args.timeout, 0.1), 2.0)))
    print(json.dumps({"equipment_code": args.code, "host": args.host, "port": args.port, **result}, ensure_ascii=False))
    return 0 if result["status"] == "연결됨" else 1


if __name__ == "__main__":
    raise SystemExit(main())
