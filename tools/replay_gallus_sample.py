#!/usr/bin/env python3
"""Gallus EMS430 샘플 Snapshot을 읽기 전용으로 재생·검증한다."""

from __future__ import annotations

import json

from lcomfine.app.gallus_ems430 import parse_snapshot, sample_payload


def main() -> int:
    snapshot = parse_snapshot(sample_payload())
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
