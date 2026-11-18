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


def test_vsysvar_matches_canoe_shape():
    """4. CANoe's "data model contains at least one error" has specific causes.

    The reported failure was a float without bitcount (must be 64) and a start
    value outside [minValue, maxValue] (LS_ICN_ODO = 12345000 in a bool range).
    """
    root = ET.parse(ROOT / "canoe" / "NBCM_Test.vsysvar").getroot()
    ns = [e for e in root.iter("namespace") if e.get("name") == "NBCM_Test"][0]
    vars_ = ns.findall("variable")

    no_bitcount = [v.get("name") for v in vars_ if v.get("bitcount") is None]
    check("every variable has bitcount", not no_bitcount,
          ", ".join(no_bitcount[:3]))

    wrong_float = [v.get("name") for v in vars_
                   if v.get("type") == "float" and v.get("bitcount") != "64"]
    check("every float has bitcount 64", not wrong_float,
          ", ".join(wrong_float[:3]))

    out_of_range, degenerate = [], []
    for v in vars_:
        try:
            st = float(v.get("startValue") or 0)
            lo = v.get("minValue")
            hi = v.get("maxValue")
            if lo is None or hi is None:
                continue
            lo, hi = float(lo), float(hi)
        except (TypeError, ValueError):
            continue
        if hi <= lo:
            degenerate.append(f"{v.get('name')} [{lo},{hi}]")
        elif not (lo <= st <= hi):
            out_of_range.append(f"{v.get('name')} start={st} [{lo},{hi}]")
    check("no degenerate min/max range", not degenerate,
          "; ".join(degenerate[:3]))
    check("every startValue inside its range", not out_of_range,
          "; ".join(out_of_range[:3]))


def test_vsysvar_checker_rejects_broken_files():
    """The checker must fail on the exact bugs that reached the user."""
    import tempfile
    broken = {
        "float-no-bitcount": '<variable anlyzLocal="2" readOnly="false" '
            'valueSequence="false" unit="" name="A" comment="" '
            'encoding="65001" type="float" startValue="0" />',
        "start-outside": '<variable anlyzLocal="2" readOnly="false" '
            'valueSequence="false" unit="" name="B" comment="" bitcount="32" '
            'isSigned="true" encoding="65001" type="int" startValue="9" '
            'minValue="0" maxValue="1" />',
    }
    for label, var in broken.items():
        xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
               '<systemvariables version="4"><namespace name="" comment="" '
               'interface=""><namespace name="T" comment="" interface="">'
               f'{var}</namespace></namespace></systemvariables>')
        with tempfile.NamedTemporaryFile("w", suffix=".vsysvar",
                                         delete=False, encoding="utf-8") as f:
            f.write(xml)
            path = f.name
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "check_vsysvar.py"),
                            path], capture_output=True, text=True)
        check(f"check_vsysvar.py rejects {label}", r.returncode == 1,
              f"rc={r.returncode}")
        Path(path).unlink(missing_ok=True)


def test_main_panel_is_self_consistent():
    """5. The all-in-one panel must not bind anything that does not exist."""
    import collections
    panel = ROOT / "canoe" / "panels" / "NBCM_Main.xvp"
    check("NBCM_Main.xvp exists", panel.exists())
    if not panel.exists():
        return
    root = ET.parse(panel).getroot()
    declared = {v.get("name") for v in
                ET.parse(ROOT / "canoe" / "NBCM_Test.vsysvar").iter("variable")}
    used, malformed = collections.Counter(), []
    for prop in root.iter("Property"):
        if prop.get("Name") != "SymbolConfiguration" or not prop.text:
            continue
        if not prop.text.startswith("4;16;NBCM_Test;;;"):
            malformed.append(prop.text[:30])
            continue
        used[prop.text.split(";")[5]] += 1
    missing = sorted(set(used) - declared)
    check("every panel binding resolves to a variable", not missing,
          ", ".join(missing[:5]))
    check("no malformed symbol bindings", not malformed, ", ".join(malformed[:3]))

    tabs = root.find("./Object/Object")
    pages = tabs.findall("Object") if tabs is not None else []
    check("panel has the tab control with all pages", len(pages) >= 17,
          f"{len(pages)} pages")
    labels = [p.find('Property[@Name="Text"]').text for p in pages]
    for must in ("Dashboard", "Nodes", "Monitor", "Tests"):
        check(f"page {must!r} present", must in labels)

    # non-ASCII in panel text renders as a box with the default label font
    odd = set()
    for prop in root.iter("Property"):
        if prop.get("Name") in ("Text", "LegendText") and prop.text:
            odd |= {c for c in prop.text if ord(c) > 127}
    check("panel labels are ASCII (no missing-glyph boxes)", not odd, "".join(sorted(odd)))


def test_verdict_reaches_the_bridge():
    """6. A suite verdict must be visible to the CANoe panel."""
    port = 9840
    env = {"NBCM_PORT": str(port), "PATH": "/usr/bin:/bin"}
    proc = subprocess.Popen(
        [sys.executable, str(BAT / "nbcm_bridge.py"), "--sim", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port + 1}"
        for _ in range(40):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=1)
                break
            except Exception:                                    # noqa: BLE001
                time.sleep(0.3)
        body = json.dumps({"passed": 6, "failed": 1,
                           "lastPass": False, "lastFail": True}).encode()
        req = urllib.request.Request(base + "/api/verdict", data=body,
                                     headers={"content-type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        state = json.loads(urllib.request.urlopen(base + "/api/state", timeout=3).read())
        v = state.get("verdict") or {}
        check("verdict is stored on the bridge",
              v.get("passed") == 6 and v.get("failed") == 1, str(v))
        check("verdict marks the last FAIL", v.get("lastFail") is True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


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
def test_package_is_consistent():
    """Build the CANoe package into a temp dir and check it hangs together.

    The package is only useful if the DBC, the restbus and the panel agree: a
    signal the CAPL writes must exist in the frame it writes it to, every
    message object must have an id, and the panel must only bind variables the
    vsysvar declares.  All of those were broken at least once.
    """
    import json
    import re
    import subprocess
    import sys
    import tempfile

    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([sys.executable, str(root / "tools" / "build_package.py"),
                            "--out", td], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-800:]
        out = Path(td)

        def frames(path):
            f, cur = {}, None
            for line in path.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^BO_ \d+ (\w+):", line)
                if m:
                    cur = m.group(1)
                    f[cur] = set()
                m = re.match(r"^ SG_ (\w+) ", line)
                if m and cur:
                    f[cur].add(m.group(1))
            return f

        dbc = {}
        for name in ("NBCM_HS.dbc", "NBCM_LS.dbc"):
            dbc.update(frames(out / "Database" / name))
        can = (out / "Nodes" / "Restbus.can").read_text(encoding="utf-8")

        decl = re.findall(r"^\s*message\s+(\w+)\s+msg_(\w+);", can, re.M)
        assert decl, "restbus declares no messages"
        assert all(a == b for a, b in decl), "message name != variable name"
        missing = [a for a, _ in decl if a not in dbc]
        assert not missing, f"CAPL declares messages with no DBC frame: {missing[:5]}"

        writes = set(re.findall(r"\bmsg_(\w+)\.(\w+)\s*=", can))
        assert len(writes) == 481, f"expected 481 signal writes, got {len(writes)}"
        bad = [(m, sg) for m, sg in writes if sg not in dbc.get(m, ())]
        assert not bad, f"writes to a signal not in that frame: {bad[:5]}"

        # the panel may only bind variables the vsysvar declares
        vs = (out / "SystemVariables" / "NBCM_Test.vsysvar").read_text(encoding="utf-8")
        declared = set(re.findall(r'<variable\s[^>]*?name="([^"]+)"', vs))
        xvp = (out / "Panels" / "NBCM_Main.xvp").read_text(encoding="utf-8")
        bound = {v for _, v in re.findall(r"4;16;(\w+);;;(\w+);1;;;-1", xvp)}
        assert bound, "panel has no bindings"
        assert not bound - declared, f"panel binds undeclared vars: {sorted(bound - declared)[:5]}"

        # no fabricated .cfg, and the manifest must describe what is really there
        assert not list(out.rglob("*.cfg")), "a .cfg was generated"
        man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        real = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
        assert {f["path"] for f in man["files"]} == real, "manifest does not match the files"
        assert all(f["note"] for f in man["files"]), "manifest entry with no note"
        assert man["counts"]["signals"] == 481
    print(f"  PASS  package build is self-consistent (481 writes, {len(bound)} bindings)")


# --------------------------------------------------------------------------- #
def main() -> int:
    print("launcher and sysvar regression tests\n")
    for fn in (test_bat_targets_exist, test_bat_line_endings,
               test_no_hardcoded_url, test_vsysvar_unique,
               test_vsysvar_matches_canoe_shape,
               test_vsysvar_checker_rejects_broken_files,
               test_main_panel_is_self_consistent,
               test_verdict_reaches_the_bridge,
               test_package_is_consistent,
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
