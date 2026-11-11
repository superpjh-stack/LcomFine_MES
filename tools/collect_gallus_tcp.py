#!/usr/bin/env python3
"""가정한 Gallus Ethernet JSON telemetry의 첫 프레임을 읽는 파일럿 도구."""

from __future__ import annotations

import argparse
import json

from lcomfine.app.equipment_collector import collect_once


def main() -> int:
    parser = argparse.ArgumentParser(description="읽기 전용 Gallus TCP JSON telemetry 수집")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--timeout", type=float, default=1.0)
    args = parser.parse_args()
    print(json.dumps(collect_once(args.host, args.port, timeout=args.timeout), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
