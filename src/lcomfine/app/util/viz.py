"""대시보드 차트 기하 — 아키텍트 소유. `templates/_charts.html` 매크로가 Jinja 전역(`viz_*`)으로 부른다.

숫자를 만들지 않는다: 값은 받은 그대로(`value`) 두고, 화면 위치(백분율)만 계산한다. 차트의 `<title>` · 표 글자는 템플릿이
`num` 필터로 같은 값에서 찍는다(QA 가 SVG title = 표 행을 대조한다).
- 값 None = 미수집 → 막대·점을 그리지 않는다(위치 계산에서 빠진다) · 음수 → 0 선 아래 · 전부 None/0 → 눈금 폭 1.
- 좌표는 SVG `viewBox="0 0 100 100"` · `preserveAspectRatio="none"` 기준의 백분율(가로 = 칸 · 세로 = 위에서 아래).
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

_DAY = re.compile(r"^\d{4}-(\d{2})-(\d{2})$")


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(Decimal(str(v)))
    except Exception:  # 숫자가 아닌 값은 그리지 않는다(표에는 글자 그대로 남는다)
        return None


def _nice_step(span: float, n: int) -> float:
    raw = span / max(n, 1)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def compact(v: float) -> str:
    """눈금 글자 — 1,000 이상은 천(K) · 백만(M) 으로 줄인다. 값 칸(표 · title)에는 쓰지 않는다."""
    a = abs(v)
    if a >= 1_000_000:
        s, unit = v / 1_000_000, "M"
    elif a >= 10_000:
        s, unit = v / 1_000, "K"
    else:
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"
    return (f"{s:,.0f}" if float(s).is_integer() else f"{s:,.1f}") + unit


def short_label(label: Any) -> str:
    """축 글자만 짧게 — `2026-10-01` → `10-01` (월 `2026-10` 은 그대로). 표 · title 은 원래 라벨 그대로."""
    s = "" if label is None else str(label)
    if m := _DAY.match(s):
        return f"{m.group(1)}-{m.group(2)}"
    return s


def scale(values: list[Any], ticks: int = 4) -> dict:
    """세로축 — 0 을 반드시 포함하는 깔끔한 눈금. {lo, hi, ticks:[{v, y, text}], y0}."""
    vals = [x for x in (_f(v) for v in values) if x is not None]
    lo, hi = min(vals + [0.0]), max(vals + [0.0])
    if hi == lo:
        hi = lo + 1
    step = _nice_step(hi - lo, ticks)
    hi_n = math.ceil(hi / step - 1e-9) * step
    lo_n = math.floor(lo / step + 1e-9) * step
    span = (hi_n - lo_n) or 1.0

    def y(v: float) -> float:
        return round((hi_n - v) / span * 100, 3)

    tk, v = [], lo_n
    while v <= hi_n + step / 2:
        tk.append({"v": v, "y": y(v), "text": compact(v)})
        v += step
    return {"lo": lo_n, "hi": hi_n, "ticks": tk, "y0": y(0.0), "y": y}


def _label_every(n: int, max_labels: int) -> int:
    return max(1, math.ceil(n / max_labels))


def columns(series: list[dict], *, max_labels: int = 6, value_labels: str = "auto") -> dict:
    """세로 막대 · 선 — 칸(cols)마다 {label, short, value, x(가운데) , w(칸 폭), bx·bw(막대), top·h(막대), show_x, show_v, none, neg}.
    value_labels: auto = 12칸 이하면 전부 · 넘으면 최댓값과 마지막 값만 / all / none."""
    n = len(series)
    sc = scale([p.get("value") for p in series])
    w = 100.0 / n if n else 100.0
    bw = min(w * 0.62, 9.0)
    every = _label_every(n, max_labels)
    vals = [_f(p.get("value")) for p in series]
    present = [i for i, v in enumerate(vals) if v is not None]
    vmax_i = max(present, key=lambda i: vals[i]) if present else None
    last_i = present[-1] if present else None
    items = []
    for i, p in enumerate(series):
        v = vals[i]
        x = round(w * i + w / 2, 3)
        it = {"label": p.get("label"), "short": short_label(p.get("label")), "value": p.get("value"), "x": x, "w": round(w, 3),
              "bx": round(x - bw / 2, 3), "bw": round(bw, 3), "none": v is None, "neg": v is not None and v < 0,
              "show_x": (i % every == 0) or i == n - 1 and n <= max_labels, "top": sc["y0"], "h": 0.0, "y": sc["y0"]}
        if v is not None:
            yv = sc["y"](v)
            it.update(top=min(yv, sc["y0"]), h=round(abs(yv - sc["y0"]), 3), y=yv)
        if value_labels == "all":
            it["show_v"] = v is not None
        elif value_labels == "none":
            it["show_v"] = False
        else:
            it["show_v"] = v is not None and (n <= 12 or i in (vmax_i, last_i))
        items.append(it)
    segs, cur = [], []
    for it in items:
        if it["none"]:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(f"{it['x']},{it['y']}")
    if cur:
        segs.append(cur)
    return {"n": n, "cols": items, "ticks": sc["ticks"], "y0": sc["y0"], "segments": [" ".join(s) for s in segs],
            "area": [f"{s[0].split(',')[0]},{sc['y0']} " + " ".join(s) + f" {s[-1].split(',')[0]},{sc['y0']}" for s in segs if len(s) > 1]}


def bars_h(series: list[dict], *, sort: bool = False) -> dict:
    """가로 막대(순위) — 행마다 {label, value, x0, w(백분율), none, neg}. 음수가 있으면 0 선이 왼쪽에서 비켜난다."""
    rows = list(series)
    if sort:
        rows.sort(key=lambda p: (_f(p.get("value")) is None, -(_f(p.get("value")) or 0)))
    vals = [x for x in (_f(p.get("value")) for p in rows) if x is not None]
    lo, hi = min(vals + [0.0]), max(vals + [0.0])
    span = (hi - lo) or 1.0
    z = (0 - lo) / span * 100
    out = []
    for p in rows:
        v = _f(p.get("value"))
        if v is None:
            out.append({"label": p.get("label"), "value": p.get("value"), "x0": round(z, 3), "w": 0.0, "none": True, "neg": False})
            continue
        pos = (v - lo) / span * 100
        out.append({"label": p.get("label"), "value": p.get("value"), "x0": round(min(z, pos), 3), "w": round(abs(pos - z), 3),
                    "none": False, "neg": v < 0})
    return {"rows": out, "zero": round(z, 3)}


def parts(series: list[dict], *, gap: float = 0.6) -> dict:
    """구성비(도넛 · 100% 누적 막대) — 0 이상 값만 몫을 갖는다. 조각마다 {label, value, share(%), start, len, slot, none}.
    None · 음수 · 0 은 몫 0(그리지 않는다 — title 과 표에는 남는다). 합계 total(Decimal 합 · 숫자가 하나도 없으면 None)."""
    vals = [_f(p.get("value")) for p in series]
    pos = [v for v in vals if v is not None and v > 0]
    tot = sum(pos)
    nums = [p.get("value") for p in series if _f(p.get("value")) is not None]
    total = sum((Decimal(str(v)) for v in nums), Decimal(0)) if nums else None
    out, acc, k = [], 0.0, 0
    for p, v in zip(series, vals):
        share = (v / tot * 100) if (tot and v is not None and v > 0) else 0.0
        drawn = share > 0
        out.append({"label": p.get("label"), "value": p.get("value"), "share": round(share, 1), "start": round(acc, 3),
                    "len": round(max(share - (gap if drawn and len(pos) > 1 else 0), 0.0), 3), "none": v is None,
                    "slot": (k % 6) + 1 if drawn else 0})
        if drawn:
            k += 1
        acc += share
    return {"parts": out, "total": total, "drawn": len(pos)}


def meter(value: Any, maximum: Any = 100) -> dict:
    """진행 막대 · 게이지 — {pct(0~100 로 자른 채움), over(최대 초과), none}."""
    v, m = _f(value), _f(maximum) or 100.0
    if v is None:
        return {"pct": 0.0, "over": False, "none": True}
    return {"pct": round(max(0.0, min(v / m * 100, 100.0)), 2), "over": v > m, "none": False}


def spark(series: list[Any]) -> str:
    """스파크라인 점 목록(viewBox 0 0 100 30) — None 은 건너뛴다. 값이 둘 미만이면 빈 글자(그리지 않는다)."""
    vals = [_f(p.get("value") if isinstance(p, dict) else p) for p in series]
    pts = [(i, v) for i, v in enumerate(vals) if v is not None]
    if len(pts) < 2:
        return ""
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    span = (hi - lo) or 1.0
    n = max(len(vals) - 1, 1)
    return " ".join(f"{round(i / n * 100, 2)},{round(27 - (v - lo) / span * 24, 2)}" for i, v in pts)


def multi(rows: list[dict], keys: list[str], *, max_labels: int = 6) -> dict:
    """여러 줄 선(같은 단위 · 축 하나) — rows: [{label, parts: [{label: key, value}]}](stacked 와 같은 모양) · keys: 계열 순서(색 순서 · 최대 6).
    눈금은 모든 계열의 값을 함께 본다. {n, w, x: [{label, short, x, show_x, values: {key: value}}], ticks, y0, series: [{key, slot, segments, dots}]}."""
    n = len(rows)
    vals: dict[str, list[Any]] = {k: [] for k in keys}
    for r in rows:
        m = {p.get("label"): p.get("value") for p in (r.get("parts") or [])}
        for k in keys:
            vals[k].append(m.get(k))
    sc = scale([v for k in keys for v in vals[k]])
    w = 100.0 / n if n else 100.0
    every = _label_every(n, max_labels)
    xs = [{"label": r.get("label"), "short": short_label(r.get("label")), "x": round(w * i + w / 2, 3),
           "show_x": (i % every == 0) or (i == n - 1 and n <= max_labels), "values": {k: vals[k][i] for k in keys}}
          for i, r in enumerate(rows)]
    series = []
    for j, k in enumerate(keys):
        segs, cur, dots = [], [], []
        for i, v in enumerate(vals[k]):
            fv = _f(v)
            if fv is None:
                if cur:
                    segs.append(" ".join(cur))
                cur = []
                continue
            y = sc["y"](fv)
            cur.append(f"{xs[i]['x']},{y}")
            dots.append({"x": xs[i]["x"], "y": y})
        if cur:
            segs.append(" ".join(cur))
        series.append({"key": k, "slot": (j % 6) + 1, "segments": segs, "dots": dots})
    return {"n": n, "w": round(w, 3), "x": xs, "ticks": sc["ticks"], "y0": sc["y0"], "series": series}


GLOBALS = {"viz_columns": columns, "viz_bars_h": bars_h, "viz_parts": parts, "viz_meter": meter, "viz_spark": spark,
           "viz_short": short_label, "viz_multi": multi}
