#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_launchers.py -- regression tests for the bugs that shipped and broke
=========================================================================
Three real failures, each caught by the user before I noticed:

  1. every .bat referenced `bcm_bridge.py` / `bcm_window.py`; the files are
     `nbcm_bridge.py` / `nbcm_window.py`, so neither launcher ever started
  2. run_sim.bat slept 3 s and opened a hard-coded http://127.0.0.1:8771/ --
     if the port moved, the browser got nothing
  3. NBCM_Test.vsysvar contained 21 duplicate variable names, so CANoe refused
     the import with "Duplicate System Variable"

Run:  python tests/test_launchers.py
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAT = ROOT / "bridge"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = ""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


# --------------------------------------------------------------------------- #
def test_bat_targets_exist():
    """1. every .py a launcher names must exist."""
    for bat in sorted(BAT.glob("*.bat")):
        text = bat.read_text(encoding="utf-8", errors="replace")
        named = re.findall(r'([\w_]+\.py)', text)
        for n in named:
            exists = (BAT / n).exists() or (ROOT / n).exists()
            check(f"{bat.name} -> {n} exists", exists)


def test_no_hardcoded_url():
    """2. the launcher must not assume the tester port."""
    for bat in sorted(BAT.glob("*.bat")):
        text = bat.read_text(encoding="utf-8", errors="replace")
        urls = re.findall(r"127\.0\.0\.1:8\d{3}", text)
        check(f"{bat.name} has no hard-coded 127.0.0.1:87xx", not urls,
              ", ".join(urls))
    launcher = (BAT / "launcher.py").read_text(encoding="utf-8")
    check("launcher.py discovers the port", "find_bridge" in launcher
          or "port_from_config" in launcher)
    check("launcher.py polls health instead of sleeping",
          "wait_for_bridge" in launcher)


def test_vsysvar_unique():
    """3. CANoe rejects duplicate system variable names."""
    path = ROOT / "canoe" / "NBCM_Test.vsysvar"
    root = ET.parse(path).getroot()
    ns = [e for e in root.iter("namespace") if e.get("name") == "NBCM_Test"]
    check("exactly one NBCM_Test namespace", len(ns) == 1, str(len(ns)))
    names = [v.get("name") for v in ns[0].findall("variable")]
    dupes = {n for n in names if names.count(n) > 1}
    check("no duplicate variable names", not dupes, ", ".join(sorted(dupes)[:5]))
    check("variable count is sane", 400 < len(names) < 600, f"{len(names)} vars")
    # the merged ones must still say where else the signal lives
    merged = [v for v in ns[0].findall("variable")
              if "also in" in (v.get("comment") or "")]
    check("merged duplicates keep their other carrier in the comment",
          len(merged) == 21, f"{len(merged)} merged")


def test_bat_line_endings():
    for bat in sorted(BAT.glob("*.bat")):
        raw = bat.read_bytes()
        check(f"{bat.name} uses CRLF", b"\r\n" in raw)


def test_find_bridge_against_a_live_bridge():
    """The port discovery must work against a real bridge, not a mock."""
    port = 9730
    env = {"NBCM_PORT": str(port), "PATH": "/usr/bin:/bin"}
    proc = subprocess.Popen(
        [sys.executable, str(BAT / "nbcm_bridge.py"), "--sim", "--port", str(port)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = None
        deadline = time.time() + 20
        while time.time() < deadline:
            r = subprocess.run([sys.executable, str(BAT / "find_bridge.py"),
                                "--port", str(port)], capture_output=True, text=True)
            if r.returncode == 0:
                url = r.stdout.strip()
                break
            time.sleep(0.5)
        check("find_bridge.py locates the bridge", bool(url), url or "not found")
        if url:
            with urllib.request.urlopen(url + "api/health", timeout=3) as resp:
                payload = json.loads(resp.read())
            check("health payload is a bridge", payload.get("ok") is True)
            check("health reports simulator mode", payload.get("mode") == "sim")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_find_bridge_fails_cleanly():
    """No bridge -> non-zero exit and a readable message, never a hang."""
    t0 = time.time()
    r = subprocess.run([sys.executable, str(BAT / "find_bridge.py"),
                        "--port", "9870"], capture_output=True, text=True)
    took = time.time() - t0
    check("find_bridge.py exits non-zero with no bridge", r.returncode == 1,
          f"rc={r.returncode}")
    check("find_bridge.py does not hang", took < 15, f"{took:.1f}s")
    check("find_bridge.py explains the failure",
          "no bridge answered" in (r.stderr or ""))


def test_launcher_dry_run():
    r = subprocess.run([sys.executable, str(BAT / "launcher.py"), "sim", "--dry-run"],
                       capture_output=True, text=True, cwd=str(ROOT))
    check("launcher.py --dry-run succeeds", r.returncode == 0, f"rc={r.returncode}")
    check("dry run prints the mode", "simulator" in r.stdout or "CANoe" in r.stdout)
    check("dry run prints the folder", str(ROOT) in r.stdout)


def test_launcher_reports_missing_files():
    """Point the launcher at an empty folder: it must say which file is missing."""
    code = (
        "import sys;sys.path.insert(0,r'%s');"
        "import launcher;"
        "launcher.BRIDGE=__import__('pathlib').Path('/nope/nbcm_bridge.py');"
        "sys.exit(launcher.main(['sim','--dry-run']))" % str(BAT))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, cwd=str(ROOT))
    check("launcher.py reports a missing bridge", r.returncode == 2,
          f"rc={r.returncode}")
    check("launcher.py names the missing file", "nbcm_bridge.py" in r.stdout)


# --------------------------------------------------------------------------- #
def main() -> int:
    print("launcher and sysvar regression tests\n")
    for fn in (test_bat_targets_exist, test_bat_line_endings,
               test_no_hardcoded_url, test_vsysvar_unique,
               test_find_bridge_fails_cleanly, test_launcher_dry_run,
               test_launcher_reports_missing_files,
               test_find_bridge_against_a_live_bridge):
        print(f"-- {fn.__name__}")
        try:
            fn()
        except Exception as e:                                   # noqa: BLE001
            print(f"  FAIL  raised {type(e).__name__}: {e}")
            failures.append(fn.__name__)
        print()

    if failures:
        print(f"FAIL -- {len(failures)} problem(s): {', '.join(failures)}")
        return 1
    print("PASS -- all launcher and sysvar checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
