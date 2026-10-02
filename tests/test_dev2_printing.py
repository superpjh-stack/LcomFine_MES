"""`app/printing.py` — Code 128 바코드(인라인 SVG)와 라벨 조각 (G-14 · D-04).

바코드 → 디코드 → 원래 번호. 디코더는 이 파일에 따로 있다(SVG 의 막대에서 모듈을 다시 읽고 체크섬까지 검증한다).
`zbarimg` 가 깔려 있으면 실제 바코드 디코더로도 읽어 본다(표 자체가 틀렸는지는 그것만이 잡는다).
DB 를 쓰지 않는다.
"""
import re
import shutil
import struct
import subprocess
import zlib

import pytest

from lcomfine.app import printing

#: 가설 채번 형식(progress-dev1.md §1)의 번호와, 세트 B·C 전환이 섞이는 경우들
SAMPLES = [
    "R261003-0001", "M261003-001", "J261003-001", "L261003-012", "S261003-001", "C261003-999",
    "A", "AB", "12", "1234", "12345", "123456", "A1234", "A12345", "1234AB", "AB123456CD", "12AB34",
    "0000", "99", "X-1", "LOT 2026/10 #7", "abc~xyz", "R261003-10000",
]


# ── 이 파일의 디코더 (printing 의 인코더와 따로 짠다) ───────────────────
def _modules_from_svg(svg: str) -> str:
    """SVG 의 막대 사각형 → 모듈 문자열. 좌우 여백(quiet zone)이 10 모듈 이상인지도 본다."""
    m = int(re.search(r'data-module="(\d+)"', svg).group(1))
    total = int(re.search(r'viewBox="0 0 (\d+) ', svg).group(1))
    assert total % m == 0
    bars = re.search(r'<g class="bars"[^>]*>(.*?)</g>', svg, re.S).group(1)
    cells = ["0"] * (total // m)
    for x, w in re.findall(r'<rect x="(\d+)" y="0" width="(\d+)"', bars):
        assert int(x) % m == 0 and int(w) % m == 0
        for k in range(int(x) // m, (int(x) + int(w)) // m):
            cells[k] = "1"
    line = "".join(cells)
    left, right = len(line) - len(line.lstrip("0")), len(line) - len(line.rstrip("0"))
    assert left >= 10 and right >= 10, f"여백 부족: {left} / {right}"
    return line.strip("0")


def _pattern(widths: str) -> str:
    return "".join(("1" if k % 2 == 0 else "0") * int(w) for k, w in enumerate(widths))


def _decode(modules: str) -> str:
    """모듈 문자열 → 원래 글자. 시작·정지·체크섬이 틀리면 AssertionError."""
    by_pattern = {_pattern(w): v for v, w in enumerate(printing.CODE128_WIDTHS)}
    stop = _pattern(printing.CODE128_STOP_WIDTHS)
    assert modules.endswith(stop), "정지 심벌이 없다"
    body = modules[: -len(stop)]
    assert len(body) % 11 == 0, "심벌 경계가 11 모듈이 아니다"
    values = [by_pattern[body[i:i + 11]] for i in range(0, len(body), 11)]
    start, data, check = values[0], values[1:-1], values[-1]
    assert start in (104, 105), f"시작 심벌이 B·C 가 아니다: {start}"
    assert check == (start + sum(pos * v for pos, v in enumerate(data, start=1))) % 103, "체크섬 불일치"
    code_set = "B" if start == 104 else "C"
    out = []
    for v in data:
        if code_set == "C":
            if v == 100:
                code_set = "B"
            else:
                assert v < 100
                out.append(f"{v:02d}")
        elif v == 99:
            code_set = "C"
        else:
            assert v < 96
            out.append(chr(v + 32))
    return "".join(out)


def _png(modules: str, scale: int = 3, height: int = 80, quiet: int = 12) -> bytes:
    """모듈 문자열 → 흑백 PNG (zbarimg 에 먹이는 용도)."""
    row_bits = "0" * quiet + modules + "0" * quiet
    row = bytes(0 if b == "1" else 255 for b in row_bits for _ in range(scale))
    raw = b"".join(b"\x00" + row for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", len(row), height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ── 표 ──────────────────────────────────────────────────────────────────
def test_code128_table_shape():
    """심벌 106개(0~105) · 각 6칸 · 합 11 모듈 · 폭 1~4 · 서로 다름 · 막대 모듈 합은 짝수(Code 128 의 성질)."""
    t = printing.CODE128_WIDTHS
    assert len(t) == 106 and len(set(t)) == 106
    for v, w in enumerate(t):
        assert len(w) == 6 and all(c in "1234" for c in w), (v, w)
        assert sum(int(c) for c in w) == 11, (v, w)
        assert sum(int(c) for c in w[0::2]) % 2 == 0, (v, w)
    assert sum(int(c) for c in printing.CODE128_STOP_WIDTHS) == 13


def test_code128_known_patterns():
    """규격서에 적힌 모듈 패턴 몇 개와 글자 그대로 같은가."""
    assert _pattern(printing.CODE128_WIDTHS[0]) == "11011001100"       # 값 0 (세트 B 의 공백)
    assert _pattern(printing.CODE128_WIDTHS[1]) == "11001101100"
    assert _pattern(printing.CODE128_WIDTHS[103]) == "11010000100"     # Start A
    assert _pattern(printing.CODE128_WIDTHS[104]) == "11010010000"     # Start B
    assert _pattern(printing.CODE128_WIDTHS[105]) == "11010011100"     # Start C
    assert _pattern(printing.CODE128_STOP_WIDTHS) == "1100011101011"   # Stop


def test_code128_checksum_known_value():
    """손으로 계산한 체크섬: `AB` = Start B(104) + 1×33 + 2×34 = 205 → 205 mod 103 = 102."""
    assert printing.code128_symbols("AB") == [104, 33, 34, 102]
    # 숫자 4자리는 세트 C: Start C(105) + 1×12 + 2×34 = 185 → 82
    assert printing.code128_symbols("1234") == [105, 12, 34, 82]


# ── 바코드 → 디코드 → 원래 번호 ─────────────────────────────────────────
@pytest.mark.parametrize("value", SAMPLES)
def test_barcode_svg_round_trip(value):
    svg = str(printing.barcode_svg(value))
    assert svg.startswith("<svg") and "http://" not in svg.replace("http://www.w3.org/2000/svg", "")   # 외부 참조 0
    assert "<image" not in svg and "href" not in svg
    assert _decode(_modules_from_svg(svg)) == value


@pytest.mark.parametrize("value", SAMPLES)
def test_modules_match_svg(value):
    assert _modules_from_svg(str(printing.barcode_svg(value, show_text=False))) == printing.code128_modules(value)


def test_set_c_makes_numbers_shorter():
    """숫자가 긴 번호는 세트 C 로 폭이 줄어든다(같은 번호를 전부 세트 B 로 찍은 길이보다 짧다)."""
    value = "R261003-0001"
    all_b = (1 + len(value) + 1) * 11 + 13
    assert len(printing.code128_modules(value)) < all_b
    assert _decode(printing.code128_modules(value)) == value


def test_text_and_height_options():
    with_text = str(printing.barcode_svg("R261003-0001", height=60))
    assert ">R261003-0001</text>" in with_text and 'height="60"' in with_text
    assert "<text" not in str(printing.barcode_svg("R261003-0001", show_text=False))


@pytest.mark.parametrize("bad", ["", "롤-001", "A\tB", "é"])
def test_bad_value_is_value_error(bad):
    """빈 값·찍을 수 없는 글자는 조용히 바꾸지 않고 ValueError."""
    with pytest.raises(ValueError):
        printing.barcode_svg(bad)


def test_value_is_escaped():
    svg = str(printing.barcode_svg('A<"&>B'))
    assert "A&lt;&#34;&amp;&gt;B" in svg and '<"&>' not in svg
    assert _decode(_modules_from_svg(svg)) == 'A<"&>B'


@pytest.mark.skipif(shutil.which("zbarimg") is None, reason="zbarimg(실제 바코드 디코더)가 이 장비에 없다")
@pytest.mark.parametrize("value", ["R261003-0001", "M261003-001", "J261003-001", "AB123456CD", "12345", "abc~xyz"])
def test_real_decoder_reads_it(value, tmp_path):
    """실제 디코더(zbar)가 같은 막대에서 같은 번호를 읽는다 — 표·체크섬·정지 심벌이 규격과 맞는지의 독립 확인."""
    png = tmp_path / "barcode.png"
    png.write_bytes(_png(_modules_from_svg(str(printing.barcode_svg(value)))))
    out = subprocess.run(["zbarimg", "-q", str(png)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == f"CODE-128:{value}"


# ── 라벨 조각 ───────────────────────────────────────────────────────────
def test_render_label_fragment():
    label = printing.Label(printing.ROLL_LABEL, "R261003-0007", [("Job", "J261003-001"), ("품목", "제품 <A> (예시)")])
    html = str(printing.render_label(label))
    assert 'data-label-kind="롤 라벨"' in html and 'data-label-number="R261003-0007"' in html
    assert "제품 &lt;A&gt; (예시)" in html                                   # 값은 이스케이프된다
    assert _decode(_modules_from_svg(html[html.index("<svg"): html.index("</svg>") + 6])) == "R261003-0007"
    assert "http" not in html.replace("http://www.w3.org/2000/svg", "") and "<img" not in html and "<link" not in html
