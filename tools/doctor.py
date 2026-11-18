#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doctor.py -- one-shot health check for the test bench
====================================================
Run this first whenever something looks wrong.  Every check prints PASS/WARN/FAIL
plus what to do about it, so you do not have to read the whole manual.

    python tools/doctor.py
    python tools/doctor.py --bridge http://127.0.0.1:8771
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ok_all = True


def line(status: str, title: str, detail: str = "", fix: str = ""):
    global ok_all
    if status == "FAIL":
        ok_all = False
    print(f"[{status:^4}] {title}")
    if detail:
        print(f"       {detail}")
    if fix:
        print(f"       -> {fix}")


def check_python():
    v = sys.version_info
    if v >= (3, 9):
        line("PASS", f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        line("FAIL", f"Python {v.major}.{v.minor} too old", fix="install Python 3.9 or newer")


def check_data():
    data_js = ROOT / "can_tester" / "assets" / "data.js"
    sigmap = ROOT / "can_tester" / "assets" / "signal_map.json"
    if not sigmap.exists():
        line("FAIL", "signal_map.json missing", fix="python tools/build_data.py")
        return None
    try:
        data = json.loads(sigmap.read_text(encoding="utf-8"))
    except Exception as e:                                       # noqa: BLE001
        line("FAIL", "signal_map.json unreadable", str(e), "python tools/build_data.py")
        return None
    meta = data.get("meta", {})
    line("PASS", "data model", f'{meta.get("nodes")} nodes / {meta.get("messages")} msgs / '
                              f'{meta.get("signals")} signals')
    if data_js.exists():
        line("PASS", "data.js present (browser can load it directly)")
    else:
        line("WARN", "data.js missing", fix="python tools/build_data.py")
    for w in meta.get("warnings", []) or []:
        line("WARN", "workbook inconsistency", w,
             "fix the source sheet or accept the detail sheet as truth")
    return data


def check_canoe_files(data):
    vs = ROOT / "canoe" / "NBCM_Test.vsysvar"
    capl = ROOT / "canoe" / "NBCM_TesterBridge.can"
    if not vs.exists() or not capl.exists():
        line("WARN", "CANoe side files not generated",
             fix="python tools/build_capl.py")
        return
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(vs).getroot()
        n = len(root.findall(".//variable"))
        line("PASS", "NBCM_Test.vsysvar valid", f"{n} system variables")
    except Exception as e:                                       # noqa: BLE001
        line("FAIL", "NBCM_Test.vsysvar is not valid xml", str(e), "python tools/build_capl.py")
    txt = capl.read_text(encoding="utf-8")
    if data:
        names = {s["sig"] for s in data.get("signals", [])}
        missing = [n for n in names if f"NBCM_Test::{n}" not in txt]
        if missing:
            line("FAIL", "CAPL bridge misses signals", ", ".join(missing[:5]), "python tools/build_capl.py")
        else:
            line("PASS", "CAPL bridge references every signal")


def check_vsysvar_shape(data):
    """CANoe says only "the data model contains at least one error"; check the
    rules it actually enforces (see tools/check_vsysvar.py)."""
    path = ROOT / "canoe" / "NBCM_Test.vsysvar"
    if not path.exists():
        line("WARN", "vsysvar not generated", fix="python tools/build_capl.py")
        return
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except Exception as e:                                       # noqa: BLE001
        line("FAIL", "vsysvar is not valid XML", str(e), "python tools/build_capl.py")
        return
    nss = [n for n in root.iter("namespace") if n.get("name") == "NBCM_Test"]
    if len(nss) != 1:
        line("FAIL", "vsysvar has no single NBCM_Test namespace",
             f"{len(nss)} found", "python tools/build_capl.py")
        return
    vars_ = nss[0].findall("variable")
    no_bc = [v.get("name") for v in vars_ if v.get("bitcount") is None]
    bad_f = [v.get("name") for v in vars_
             if v.get("type") == "float" and v.get("bitcount") != "64"]
    out_rng = []
    for v in vars_:
        try:
            lo, hi = v.get("minValue"), v.get("maxValue")
            if lo is None or hi is None:
                continue
            lo, hi = float(lo), float(hi)
            st = float(v.get("startValue") or 0)
        except (TypeError, ValueError):
            continue
        if hi <= lo or not (lo <= st <= hi):
            out_rng.append(v.get("name"))
    if no_bc or bad_f or out_rng:
        detail = []
        if no_bc:
            detail.append(f"{len(no_bc)} without bitcount")
        if bad_f:
            detail.append(f"{len(bad_f)} float without 64 bits")
        if out_rng:
            detail.append(f"{len(out_rng)} start value out of range")
        line("FAIL", "CANoe would reject the system variables",
             ", ".join(detail), "python tools/build_capl.py")
    else:
        line("PASS", "system variables match CANoe's shape",
             f"{len(vars_)} vars, all with bitcount and a valid range")


def check_panels(data):
    pdir = ROOT / "canoe" / "panels"
    if not pdir.exists():
        line("WARN", "panel files not generated", fix="python tools/build_xvp.py")
        return
    files = sorted(pdir.glob("*.xvp"))
    if not files:
        line("WARN", "no .xvp panels found", fix="python tools/build_xvp.py")
        return
    declared = set()
    if data:
        declared = {s["sig"] for s in data.get("signals", [])}
        declared |= {f"OFFLINE_{n['node']}" for n in data.get("nodes", [])}
        declared |= {"DRIVE_MODE", "SCENARIO_RUNNING", "MANUAL_SPEED_MODE", "MANUAL_SPEED_KMH"}
    bad_xml, unknown, bindings = [], set(), 0
    import xml.etree.ElementTree as ET
    for f in files:
        try:
            root = ET.parse(f).getroot()
        except Exception as e:                                   # noqa: BLE001
            bad_xml.append(f"{f.name}: {e}")
            continue
        for prop in root.findall('.//Property[@Name="SymbolConfiguration"]'):
            txt = (prop.text or "").strip()
            if not txt:
                continue
            bindings += 1
            parts = txt.split(";")
            if len(parts) < 6 or parts[0] != "4" or parts[1] != "16":
                unknown.add(f"{f.name}: odd binding {txt[:40]}")
                continue
            name = parts[5]
            if declared and name not in declared:
                unknown.add(f"{f.name}: {name}")
    cnps = sorted(pdir.glob("*.cnp"))
    if cnps:
        bad_cnp = []
        for f in cnps:
            try:
                first = f.read_text(encoding="utf-8", errors="replace").splitlines()[0]
                if not first.startswith("VPanel"):
                    bad_cnp.append(f.name + ": missing VPanel header")
            except Exception as e:                               # noqa: BLE001
                bad_cnp.append(f"{f.name}: {e}")
        if bad_cnp:
            line("FAIL", "invalid .cnp files", "; ".join(bad_cnp[:3]), "python tools/build_xvp.py")
        else:
            line("PASS", "legacy .cnp present", f"{len(cnps)} file(s), VPanel header ok "
                                                "(converted by CANoe 12)")

    if bad_xml:
        line("FAIL", "invalid .xvp xml", "; ".join(bad_xml[:3]), "python tools/build_xvp.py")
    else:
        line("PASS", "panels valid", f"{len(files)} files, {bindings} control bindings")
    if unknown:
        line("FAIL", "panel bindings point at unknown variables",
             ", ".join(sorted(unknown)[:5]), "python tools/build_xvp.py")
    else:
        line("PASS", "every panel binding matches a generated variable")


def check_pywin32():
    if platform.system() != "Windows":
        line("WARN", "not Windows", "COM/CANoe checks are skipped on this machine",
             "run the bridge on the PC where CANoe is installed")
        return False
    try:
        import win32com.client  # noqa: F401
        line("PASS", "pywin32 available")
        return True
    except Exception:                                            # noqa: BLE001
        line("FAIL", "pywin32 not installed", fix="pip install pywin32")
        return False


def check_canoe_com():
    if platform.system() != "Windows":
        return
    try:
        import win32com.client as win32
    except Exception:                                            # noqa: BLE001
        return
    try:
        app = win32.GetActiveObject("CANoe.Application")
        line("PASS", "running CANoe instance found")
    except Exception:
        try:
            app = win32.DispatchEx("CANoe.Application")
            line("WARN", "CANoe was not running - a new instance was started")
        except Exception as e:                                   # noqa: BLE001
            line("FAIL", "cannot talk to CANoe over COM", str(e),
                 "start CANoe (or run it once with -regserver) and retry")
            return
    try:
        v = app.Version
        line("PASS", "CANoe version", f"{v.major}.{v.minor}.{v.Build}")
    except Exception:                                            # noqa: BLE001
        pass
    try:
        namespaces = app.System.Namespaces
        ns = namespaces("NBCM_Test")
        ns.Variables("DRIVE_MODE")
        line("PASS", "system variables NBCM_Test::* are available")
    except Exception as e:                                       # noqa: BLE001
        line("FAIL", "NBCM_Test system variables missing in this configuration", str(e),
             "add canoe/NBCM_Test.vsysvar to the CANoe configuration")
    try:
        running = app.Measurement.Running
        line("PASS" if running else "WARN", "measurement",
             "running" if running else "stopped - press Start in CANoe")
    except Exception:                                            # noqa: BLE001
        pass


def check_bridge(url: str):
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=4) as r:
            h = json.loads(r.read().decode())
    except (urllib.error.URLError, OSError) as e:
        line("WARN", "bridge not reachable", str(e),
             "python bridge/nbcm_bridge.py --canoe")
        return
    line("PASS", "bridge reachable", f"mode={h.get('mode')} canoe={h.get('canoe')} "
                                     f"sysvars={h.get('sysvars')} measurement={h.get('measRunning')}")
    if h.get("canoe") and not h.get("sysvars"):
        line("FAIL", "bridge cannot write signals",
             "system variables missing",
             "add canoe/NBCM_Test.vsysvar and canoe/NBCM_TesterBridge.can")
    if h.get("error"):
        line("WARN", "bridge reported an error", h["error"])


def check_suite():
    p = ROOT / "tests" / "test_suite.json"
    if not p.exists():
        line("WARN", "tests/test_suite.json missing", fix="export it from the tester's editor tab")
        return
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
        n = len(s.get("tests", []))
        line("PASS", "test suite", f"{n} tests")
    except Exception as e:                                       # noqa: BLE001
        line("FAIL", "test_suite.json invalid", str(e))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="diagnose the NBCM tester setup")
    ap.add_argument("--bridge", default="http://127.0.0.1:8771")
    ap.add_argument("--skip-com", action="store_true", help="do not touch a running CANoe")
    args = ap.parse_args(argv)

    print("=" * 74)
    print(" NBCM CAN tester - environment check")
    print("=" * 74)

    print("\n-- host ------------------------------------------------------------")
    line("PASS", f"{platform.system()} {platform.release()}", platform.machine())
    check_python()

    print("\n-- data ------------------------------------------------------------")
    data = check_data()

    print("\n-- CANoe project files ---------------------------------------------")
    check_canoe_files(data)
    check_vsysvar_shape(data)
    check_panels(data)

    print("\n-- CANoe connection ------------------------------------------------")
    has_pywin32 = check_pywin32()
    if has_pywin32 and not args.skip_com:
        check_canoe_com()

    print("\n-- bridge ----------------------------------------------------------")
    check_bridge(args.bridge)
    check_suite()

    print("\n" + "=" * 74)
    print(" RESULT:", "everything essential is ready" if ok_all else "see the FAIL lines above")
    print("=" * 74)
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
