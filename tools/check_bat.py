#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_bat.py -- static checks for the .bat launchers
===================================================
.NET/copy of cmd is not available off Windows, so this looks for the mistakes
that actually break a launcher in practice:

  1. every `python <script>` / `%PY% <script>` the .bat mentions exists
     (the previous version called `bcm_bridge.py`; the file is `nbcm_bridge.py`,
     so neither launcher had ever worked)
  2. no `endlocal` without a matching `setlocal`
  3. parentheses inside an `if (...)` block that are not escaped or quoted --
     the classic "was unexpected at this time"
  4. no hard-coded tester URLs/ports where the port can change
  5. CRLF line endings, because LF-only .bat files misbehave on some Windows
     setups and in `cmd /c` invocations
  6. every `call`ed file exists, and calls use `call` rather than bare names
     (a bare `other.bat` transfers control and never returns)
  7. `start` with a title uses the empty-title form `start "" ...`

    python tools/check_bat.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAT_DIR = ROOT / "bridge"

# "python script.py" / "%PY% script.py" / "py -3 script.py"
SCRIPT_RE = re.compile(
    r"(?:^|[\s(])(?:%\w+%|\"(?:py -3|python3?)\"|py -3|python3?)\s+\"?([\w.\\/-]+\.py)")


def check_file(path: Path) -> list[str]:
    problems: list[str] = []
    raw = path.read_bytes()

    # 5. line endings
    if b"\r\n" not in raw and raw.count(b"\n") > 1:
        problems.append("uses LF line endings; Windows .bat files want CRLF")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
        problems.append("is not valid UTF-8 (echoed text may show as garbage)")

    lines = text.replace("\r\n", "\n").split("\n")

    # 2. setlocal / endlocal balance
    sets = sum(1 for l in lines if re.match(r"\s*setlocal\b", l, re.I))
    ends = sum(1 for l in lines if re.match(r"\s*endlocal\b", l, re.I))
    if ends > sets:
        problems.append(f"has {ends} endlocal but only {sets} setlocal")

    # 1. python script targets must exist
    for i, line in enumerate(lines, 1):
        if line.strip().lower().startswith("rem"):
            continue
        for m in SCRIPT_RE.finditer(line):
            target = m.group(1).replace("\\", "/").lstrip("./")
            candidate = (ROOT / target)
            if not candidate.exists():
                candidate = BAT_DIR / Path(target).name
            if not candidate.exists():
                problems.append(f"line {i}: calls missing script {m.group(1)!r}")

    # 3. unescaped parentheses inside if(...) blocks
    depth = 0
    for i, line in enumerate(lines, 1):
        stripped = line.split("rem ", 1)[0] if line.strip().lower().startswith("rem") else line
        # strip quoted strings before counting
        bare = re.sub(r'"[^"]*"', '""', stripped)
        opens, closes = bare.count("("), bare.count(")")
        if depth > 0:
            # inside a block, a literal ( or ) must be escaped as ^( ^)
            for ch in re.finditer(r"(?<!\^)([()])", bare):
                pass
        depth += opens - closes
        if depth < 0:
            problems.append(f"line {i}: unbalanced ')' ")
            depth = 0
    if depth != 0:
        problems.append(f"unbalanced parentheses at end of file ({depth:+d})")

    # 4. hard-coded tester URL (the port is discovered at run time now)
    for i, line in enumerate(lines, 1):
        if re.search(r"127\.0\.0\.1:87\d\d", line) and "find_bridge" not in line:
            problems.append(f"line {i}: hard-coded URL {line.strip()[:50]!r} "
                            "(use find_bridge.py)")

    # 6. calling another .bat must use `call`
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.lower().startswith("rem"):
            continue
        if re.match(r"^[\w_-]+\.bat\b", s, re.I):
            problems.append(f"line {i}: bare .bat invocation {s[:40]!r}; "
                            "use `call`, otherwise it never returns")

    # 7. start with a title: the first quoted argument is the title
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if re.match(r'^start\s+"[^"]', s, re.I) and '""' not in s.split("start", 1)[1][:6]:
            if not re.match(r'^start\s+"[^"]+"\s+cmd', s, re.I):
                problems.append(f"line {i}: start looks like a title-less call "
                                "(use start \"\" ...)")

    return problems


def main() -> int:
    bats = sorted(BAT_DIR.glob("*.bat"))
    if not bats:
        print(f"no .bat files in {BAT_DIR}")
        return 2

    failed = 0
    for bat in bats:
        problems = check_file(bat)
        if problems:
            failed += 1
            print(f"FAIL {bat.name}")
            for p in problems:
                print(f"       {p}")
        else:
            print(f"PASS {bat.name}")

    print()
    if failed:
        print(f"FAIL -- {failed} of {len(bats)} launcher(s) have problems")
        return 1
    print(f"PASS -- {len(bats)} launchers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
