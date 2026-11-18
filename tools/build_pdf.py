#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pdf.py -- render the project's Persian Markdown documents to PDF
=====================================================================
No pandoc / LaTeX / Chromium here, so the Markdown is parsed into a small block
tree and laid out on an A4 canvas.

The hard part of Persian PDF is the text engine, and fpdf2 already has one:
it runs HarfBuzz for contextual shaping and the bidi algorithm for ordering.
So this script does **not** touch glyphs itself -- it hands logical-order
Persian strings to fpdf2 with `set_text_shaping(True, direction="rtl")` and
lets it do the shaping. (An earlier version placed glyphs by hand; every
character landed on the same spot, which is why this file looks the way it
does now.)

Usage
-----
    python tools/build_pdf.py                 # every doc -> docs/pdf/
    python tools/build_pdf.py --only how-to-use
    python tools/build_pdf.py --list
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "assets" / "fonts"
OUT_DIR = ROOT / "docs" / "pdf"

DOCS = [
    ("README.md", "README.pdf", "معرفی و مرور"),
    ("docs/how-to-use.md", "how-to-use.pdf", "راهنمای استفاده قدم‌به‌قدم"),
    ("docs/how-to-add-to-canoe.md", "how-to-add-to-canoe.pdf", "افزودن به CANoe 12"),
    ("docs/README.md", "docs-README.pdf", "راهنمای کامل فنی"),
    ("canoe/README.md", "canoe-README.pdf", "فایل‌های سمت CANoe"),
]

PAGE_W, PAGE_H = 210, 297
ML, MR, MT, MB = 16, 16, 18, 20
CW = PAGE_W - ML - MR

INK = (25, 25, 30)
MUTED = (95, 100, 110)
ACCENT = (28, 62, 110)
RULE = (205, 212, 222)
CODE_BG = (244, 246, 248)
CODE_INK = (40, 44, 54)
HEAD_BG = (232, 237, 245)

RTL_CHARS = re.compile(r"[\u0590-\u08FF\uFB1D-\uFEFF]")

# Directional isolates.  Persian paragraphs carry Latin tokens whose internal
# order must survive: without isolation "#include" is rendered "include#" and
# "DRIVE_MODE=1" comes out as "1=DRIVE_MODE", because the leading neutral
# character takes the paragraph direction.  LRI/PDI pin each token to LTR
# without adding a visible character.
LRI, PDI = "\u2066", "\u2069"

# Only tokens that *start with a neutral character* need isolating.  A token
# starting with a letter or digit is already handled correctly by the bidi
# algorithm (it stays LTR); isolating part of one -- say the path in
# "python tools/doctor.py" while leaving "python" outside -- makes the two
# halves drift apart, which is worse than the original problem.
TOKEN_RE = re.compile(
    r"(?<![\w./\\<>:-])"                  # must start a token, not sit
    r"(?:"                                  # inside a path like tools/doctor.py
    r"[#@/][\w.\\/<>-]+"                  # #include   /api/state   --x
    r"|--?[a-z][\w-]*"                   # --take-control  --sim
    r"|[A-Za-z_][\w.]*=[\w.\\/-]+"       # DRIVE_MODE=1
    r")")


def isolate_tokens(text: str) -> str:
    """Wrap Latin technical tokens in LRI…PDI so bidi leaves them alone."""
    if not has_rtl(text):
        return text
    return TOKEN_RE.sub(lambda m: LRI + m.group(0) + PDI, text)


def has_rtl(t: str) -> bool:
    return bool(RTL_CHARS.search(t))


# --------------------------------------------------------------------------- #
# Markdown -> blocks
# --------------------------------------------------------------------------- #
def clean(text: str) -> str:
    """Strip Markdown inline syntax, keep readable text."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = text.replace("`", "")
    return text.strip()


def parse(md: str) -> list[dict]:
    lines = md.replace("\t", "    ").splitlines()
    out: list[dict] = []
    i, n = 0, len(lines)

    while i < n:
        raw = lines[i]
        s = raw.strip()

        if s.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i].rstrip())
                i += 1
            i += 1
            out.append({"k": "code", "text": "\n".join(buf)})
            continue

        if not s:
            i += 1
            continue

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            out.append({"k": "hr"})
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            lvl = len(m.group(1))
            out.append({"k": f"h{min(lvl, 3)}", "text": clean(m.group(2))})
            i += 1
            continue

        if s.startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = split_row(s)
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i].strip()))
                i += 1
            out.append({"k": "table", "rows": [head] + rows})
            continue

        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append({"k": "quote", "text": clean(" ".join(b for b in buf if b))})
            continue

        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", raw)
        if m:
            depth = min(len(m.group(1)) // 2, 2)
            ordered = m.group(2)[0].isdigit()
            buf = [clean(m.group(3))]
            i += 1
            while i < n:
                nxt = lines[i]
                if not nxt.strip():
                    break
                if re.match(r"^(\s*)([-*+]|\d+[.)])\s+", nxt):
                    break
                if nxt.startswith("    "):
                    buf.append(clean(nxt))
                    i += 1
                else:
                    break
            out.append({"k": "num" if ordered else "li",
                        "text": " ".join(buf), "depth": depth})
            continue

        buf = [s]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(("#", ">", "```", "|"))
                    or re.fullmatch(r"(-{3,}|\*{3,})", nxt)
                    or re.match(r"^(\s*)([-*+]|\d+[.)])\s+", lines[i])):
                break
            buf.append(nxt)
            i += 1
        out.append({"k": "p", "text": clean(" ".join(buf))})
    return out


def split_row(row: str) -> list[str]:
    row = row.strip().strip("|")
    return [clean(c) for c in row.split("|")]


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
class Doc(FPDF):
    def __init__(self, title: str, source: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.doc_title = title
        self.source = source
        self.set_margins(ML, MT, MR)
        self.set_auto_page_break(True, MB)
        self.add_font("Vazir", "", str(FONT_DIR / "Vazirmatn-Regular.ttf"))
        self.add_font("Vazir", "B", str(FONT_DIR / "Vazirmatn-Bold.ttf"))
        self.add_font("Mono", "", str(FONT_DIR / "DejaVuSansMono.ttf"))
        # Vazirmatn carries no arrows (U+2192), box drawing (U+2500) or media
        # symbols (U+25B6 / U+2713), which the docs use. DejaVu covers them, so
        # fpdf2 swaps glyphs per character instead of dropping them.
        self.add_font("DejaVu", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.set_fallback_fonts(["DejaVu"], exact_match=False)
        self.set_font("Vazir", "", 10.5)
        self.set_text_color(*INK)

    # -- primitives --------------------------------------------------------- #
    def rtl(self):
        self.set_text_shaping(True, direction="rtl")

    def ltr(self):
        self.set_text_shaping(True, direction="ltr")

    def para(self, text: str, size=10.5, style="", color=INK,
             align="R", width=None, gap_after=2.0, indent=0.0, line_h=None):
        """One flowing paragraph, wrapped by fpdf2 with shaping on."""
        w = width if width is not None else CW - indent
        self.set_font("Vazir", style, size)
        self.set_text_color(*color)
        if has_rtl(text):
            self.rtl()
        else:
            self.ltr()
        if line_h is None:
            line_h = size * 0.62
        self.set_x(ML + indent)
        self.multi_cell(w, line_h, isolate_tokens(text), align=align,
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_y(self.get_y() + gap_after)

    def heading(self, text, size, color, rule=False, gap_before=3.0, gap_after=2.0):
        self.set_y(self.get_y() + gap_before)
        self.para(text, size=size, style="B", color=color, gap_after=gap_after)
        if rule:
            self.set_draw_color(*ACCENT)
            self.set_line_width(0.6)
            y = self.get_y() - gap_after * 0.4
            self.line(ML + CW * 0.42, y, PAGE_W - MR, y)
            self.set_line_width(0.2)
            self.set_y(y + 2.5)

    # -- blocks ------------------------------------------------------------- #
    def blocks(self, bs: list[dict]):
        for b in bs:
            getattr(self, "_" + b["k"], self._p)(b)

    def _hr(self, b):
        self.set_y(self.get_y() + 2)
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        self.line(ML, self.get_y(), PAGE_W - MR, self.get_y())
        self.set_y(self.get_y() + 4)

    def _h1(self, b):
        self.heading(b["text"], 18, INK, rule=True, gap_before=2, gap_after=4)

    def _h2(self, b):
        self.heading(b["text"], 13.5, ACCENT, gap_before=4.5, gap_after=1.5)

    def _h3(self, b):
        self.heading(b["text"], 11.2, (60, 65, 75), gap_before=3.5, gap_after=1.2)

    def _p(self, b):
        self.para(b["text"])

    def _li(self, b):
        self._bullet(b, "•")

    def _num(self, b):
        self._bullet(b, "–")

    def _bullet(self, b, mark):
        depth = b.get("depth", 0)
        indent = 5 + depth * 5
        # marker on the right, text to its left: RTL needs the text cell first
        self.set_font("Vazir", "", 10.5)
        self.set_text_color(*MUTED)
        self.set_xy(PAGE_W - MR - indent, self.get_y())
        self.rtl()
        self.cell(3.5, 6, mark, align="C")
        self.set_y(self.get_y())
        self.para(b["text"], indent=indent + 4.5, gap_after=1.2)

    def _quote(self, b):
        y0 = self.get_y()
        self.set_fill_color(246, 247, 250)
        self.para(b["text"], color=(55, 60, 70), indent=4, gap_after=0.0)
        y1 = self.get_y()
        self.set_draw_color(150, 165, 190)
        self.set_line_width(1.1)
        self.line(PAGE_W - MR + 1.5, y0, PAGE_W - MR + 1.5, y1 - 1)
        self.set_y(y1 + 2)

    RUN_RE = re.compile(r"[\u0590-\u08FF\uFB1D-\uFEFF][\u0590-\u08FF\uFB1D-\uFEFF\s]*")

    def _code(self, b):
        """Code block.  A line like `rem یک‌بار` mixes scripts, so each run is
        drawn with its own direction; forcing the whole line one way would
        either reverse the code or break the Persian letter joining."""
        size = 8.4
        lh = 4.4
        pad = 2.0
        lines = b["text"].split("\n") or [""]
        for ln in lines:
            if self.get_y() + lh + pad * 2 > PAGE_H - MB:
                self.add_page()
            self.set_fill_color(*CODE_BG)
            self.rect(ML, self.get_y(), CW, lh + pad, style="F")
            # note: monospace matters here -- the ASCII diagrams in docs/README.md
            # only line up if every glyph has the same advance.
            y = self.get_y() + pad * 0.6
            self._line_runs(ln, size, lh, ML + 2.5, y)
            self.set_y(self.get_y() + lh + pad * 0.6)
        self.set_y(self.get_y() + 2.5)

    def _line_runs(self, line: str, size: float, lh: float, x0: float, y: float):
        """Draw a single line left-to-right, switching direction per script run."""
        self.set_font("Mono", "", size)
        self.set_text_color(*CODE_INK)
        x = x0
        limit = ML + CW - 2.5
        for run in self._split_runs(line):
            if not run:
                continue
            rtl = bool(has_rtl(run))
            self.set_text_shaping(True, direction="rtl" if rtl else "ltr")
            w = self.get_string_width(run)
            if x + w > limit:                     # long code line: wrap
                x = x0
                y += lh
            self.set_xy(x, y)
            self.cell(w + 0.5, lh, run, align="R" if rtl else "L")
            x += w + (0.6 if not run.endswith(" ") else 0)

    @classmethod
    def _split_runs(cls, line: str) -> list[str]:
        """Split a line into maximal RTL / non-RTL runs, keeping whitespace."""
        if not line:
            return [""]
        runs, cur, cur_rtl = [], "", None
        for ch in line:
            r = bool(RTL_CHARS.match(ch))
            if cur_rtl is None or r == cur_rtl or ch.isspace():
                cur += ch
            else:
                runs.append(cur)
                cur = ch
            if not ch.isspace():
                cur_rtl = r
        if cur:
            runs.append(cur)
        return runs

    def _table(self, b):
        rows = b["rows"]
        if not rows:
            return
        size = 8.8
        lh = 4.3
        pad = 1.6
        ncol = max(len(r) for r in rows)
        rows = [r + [""] * (ncol - len(r)) for r in rows]

        # natural widths, clamped, then distributed over the content width
        widths = []
        for c in range(ncol):
            self.set_font("Vazir", "", size)
            self.rtl()
            need = max(self.get_string_width(isolate_tokens(r[c])) for r in rows) + 5
            widths.append(min(max(need, 14), CW * 0.55))
        tot = sum(widths)
        if tot > CW:
            widths = [w * CW / tot for w in widths]
        else:
            widths = [w + (CW - tot) / ncol for w in widths]

        def draw_row(row, header: bool):
            cells, height = [], 0.0
            for c in range(ncol):
                self.set_font("Vazir", "B" if header else "", size)
                self.rtl()
                lines = self.multi_cell(widths[c], lh, isolate_tokens(row[c]),
                                        align="R", dry_run=True, output="LINES",
                                        padding=2.0) or [""]
                cells.append(lines)
                height = max(height, len(lines) * lh)
            height += pad * 2
            if self.get_y() + height > PAGE_H - MB:
                self.add_page()
                if not header:
                    draw_row(rows[0], True)
            y = self.get_y()
            if header:
                self.set_fill_color(*HEAD_BG)
                self.rect(ML, y, CW, height, style="F")
            self.set_draw_color(*RULE)
            self.set_line_width(0.15)
            self.line(ML, y, PAGE_W - MR, y)
            x_right = PAGE_W - MR
            for c in range(ncol):
                w = widths[c]
                cx = x_right - sum(widths[:c]) - w
                self.set_font("Vazir", "B" if header else "", size)
                self.set_text_color(*(INK if header else (35, 38, 45)))
                self.rtl()
                self.set_xy(cx, y + pad)
                self.multi_cell(w, lh, isolate_tokens(row[c]), align="R",
                                padding=2.0, new_x=XPos.LEFT, new_y=YPos.NEXT)
            # separators after the text, so anti-aliasing of the glyphs cannot
            # clip them; they span the full row height, top border to bottom
            self.set_draw_color(*RULE)
            self.set_line_width(0.15)
            xr = PAGE_W - MR
            for c in range(1, ncol):
                xsep = xr - sum(widths[:c])
                self.line(xsep, y, xsep, y + height)
            self.set_y(y + height)

        for ri, row in enumerate(rows):
            draw_row(row, ri == 0)
        self.set_draw_color(*RULE)
        self.set_line_width(0.15)
        self.line(ML, self.get_y(), PAGE_W - MR, self.get_y())
        self.set_y(self.get_y() + 3)

    # -- footer ------------------------------------------------------------- #
    def footer(self):
        self.set_y(-13)
        self.set_font("Vazir", "", 7.6)
        self.set_text_color(*MUTED)
        self.rtl()
        label = f"{self.doc_title}  ·  صفحه {self.page_no()} از {{nb}}"
        self.cell(CW, 6, label, align="R")
        self.ltr()
        self.set_xy(ML, self.get_y())
        self.cell(CW, 6, self.source, align="L")


# --------------------------------------------------------------------------- #
def render(md_path: Path, pdf_path: Path, title: str) -> dict:
    doc = Doc(title, str(md_path.relative_to(ROOT)))
    doc.set_title(title)
    doc.set_author("NBCM CAN Tester")
    doc.alias_nb_pages()
    doc.add_page()
    doc.blocks(parse(md_path.read_text(encoding="utf-8")))
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc.output(str(pdf_path))
    return {"pages": doc.page_no(), "title": title}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="render Persian Markdown docs to PDF")
    ap.add_argument("--only", help="build docs whose path contains this")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)

    for f in ("Vazirmatn-Regular.ttf", "Vazirmatn-Bold.ttf"):
        if not (FONT_DIR / f).exists():
            print(f"error: missing font assets/fonts/{f} (Vazirmatn, SIL OFL)")
            return 2

    todo = [d for d in DOCS if not args.only or args.only in d[0]]
    if args.list:
        for src, out, title in todo:
            print(f"{src:32} -> {out:24} {title}")
        return 0
    if not todo:
        print("no docs matched")
        return 1

    for src, out, title in todo:
        md = ROOT / src
        if not md.exists():
            print(f"skip (missing): {src}")
            continue
        info = render(md, args.out / out, title)
        kb = (args.out / out).stat().st_size / 1024
        print(f"{src:32} -> {(args.out/out).relative_to(ROOT)!s:26} "
              f"{info['pages']:>2}p {kb:>7.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
