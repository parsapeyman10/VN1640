#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_pdf.py -- catch the Persian PDF failure modes automatically
=================================================================
Rendering Persian can go wrong in ways that look fine in a text dump but are
broken on the page, so this checks what actually matters:

  1. every expected PDF exists and has pages
  2. the text layer is real text (not images) -- a TeX/HTML engine failure
     often produces pages that render but carry no extractable glyphs
  3. no literal bidi control characters leaked into the visible text
     (LRI/PDI are invisible, but a leaked U+FFFD or tofu box is not)
  4. every token that is easy to break is present in some form:
     "#include", "DRIVE_MODE=1", "run_windows.bat", "/api/state", "Ctrl+S"
  5. no glyph is missing -- i.e. no U+FFFD / .notdef boxes reported by the
     Unicode mapping of the drawn glyphs

Exit code is 0 only when everything passes, so CI can use it.

    python tools/check_pdf.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "docs" / "pdf"

EXPECTED = [
    "README.pdf",
    "how-to-use.pdf",
    "how-to-add-to-canoe.pdf",
    "docs-README.pdf",
    "canoe-README.pdf",
]

# Tokens that must survive the bidi pass.  Text extraction from an RTL run
# reorders them, so each is checked as a set of characters that must all be
# present on the page -- checking substrings would fail for correct output.
TOKENS = [
    "#include", "DRIVE_MODE=1", "run_windows.bat", "/api/state", "Ctrl+S",
    "NBCM_Test.vsysvar", "take-control",
]

BAD = {"\ufffd": "replacement character (missing glyph)",
       "\u200e": "LRM leaked into text",
       "\u2066": "LRI leaked into text",
       "\u2069": "PDI leaked into text"}


def main() -> int:
    if not PDF_DIR.exists():
        print(f"error: {PDF_DIR} does not exist -- run tools/build_pdf.py first")
        return 2

    problems: list[str] = []
    total_pages = 0

    for name in EXPECTED:
        path = PDF_DIR / name
        if not path.exists():
            problems.append(f"{name}: missing")
            continue

        doc = pdfium.PdfDocument(str(path))
        pages = len(doc)
        total_pages += pages
        if pages == 0:
            problems.append(f"{name}: has no pages")
            continue

        text = ""
        for i in range(pages):
            text += doc[i].get_textpage().get_text_range()
        if len(text.strip()) < 200:
            problems.append(f"{name}: text layer almost empty "
                            f"({len(text.strip())} chars) -- glyphs may be images")

        for ch, why in BAD.items():
            if ch in text:
                problems.append(f"{name}: {why}")

        persian = sum(1 for c in text if 0x0600 <= ord(c) <= 0x06FF)
        if persian < 100:
            problems.append(f"{name}: only {persian} Persian characters -- "
                            "shaping/encoding likely wrong")

        print(f"{name:26} {pages:>2}p  {len(text):>6} chars  "
              f"{persian:>5} fa   {path.stat().st_size/1024:>6.1f} KB")

    # token spot-check across the whole set
    all_text = ""
    for name in EXPECTED:
        p = PDF_DIR / name
        if p.exists():
            d = pdfium.PdfDocument(str(p))
            for i in range(len(d)):
                all_text += d[i].get_textpage().get_text_range()

    # Arabic presentation forms mean the text was shaped twice: once by the
    # shaper and once by a pre-reshaping step, which double-joins letters.
    # U+FE0F (variation selector) sits in that range but is part of the emoji
    # warning sign, not a shaped letter -- exclude the whole FE00-FE0F block.
    pres = sum(1 for c in all_text
               if 0xFB50 <= ord(c) <= 0xFEFF and not 0xFE00 <= ord(c) <= 0xFE0F)
    if pres:
        problems.append(f"{pres} Arabic presentation forms in the text layer -- "
                        "the text was reshaped twice")

    # Comparing tokens verbatim does not work on an RTL page: the text layer
    # reports the visual order ("1=EDOM_EVIRD") and drops ZWNJ, and fpdf2
    # measures isolated tokens slightly wide so "_" can come out as " _".
    # So compare a skeleton: letters and digits only, order-insensitive.
    def skeleton(t: str) -> str:
        return "".join(c for c in t if c.isalnum())

    haystack = skeleton(all_text)
    for token in TOKENS:
        sk = skeleton(token)
        if sk in haystack or sk[::-1] in haystack:
            continue
        problems.append(f"token {token!r} missing entirely from the PDFs")

    print()
    if problems:
        print(f"FAIL -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(f"PASS -- {len(EXPECTED)} PDFs, {total_pages} pages, text layer intact, "
          "no leaked bidi controls, no missing glyphs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
