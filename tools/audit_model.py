#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_model.py -- is the simulation actually complete?
======================================================

"Complete" is easy to claim and hard to check, so this prints a per-signal
matrix for all 1078 signals in the official network map:

    dbc   in a .dbc (so CANoe can name it)
    rest  the restbus actually sends that message
    pane  some panel binds the signal
    expl  the HTML tester explains it

The five columns are not equally required.  A message whose sender is NBCM is
*deliberately* not simulated: the point of a restbus is to fake every other
node while the real NBCM sits on the bus.  Pretending to be NBCM as well would
collide with the hardware you are testing.  Those rows are reported separately
so a real gap is never hidden among expected ones.

Run:
    python tools/audit_model.py            # summary
    python tools/audit_model.py --list     # every gap, by name
    python tools/audit_model.py --json     # machine readable
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_XLSX = ROOT / "NBCM_CAN_Simulation_Package/1_Final/NBCM_Dena_CAN_Network_Map.xlsx"
RESTBUS = ROOT / "NBCM_Full_Restbus_Simulation.can"
PANELS = ROOT / "canoe" / "panels"
DBC_DIR = ROOT / "dist/NBCM_CAN_Simulation_Package/Database"


def _load_map() -> dict:
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import build_package
    return build_package.load_netmap(MAP_XLSX)


def _restbus_coverage() -> tuple[set[str], set[str]]:
    text = RESTBUS.read_text(encoding="utf-8-sig", errors="replace")
    sent = set(re.findall(r"output\(msg_(\w+)\)", text))
    written = set(re.findall(r"msg_\w+\.(\w+)\s*=", text))
    return sent, written


def _panel_symbols() -> set[str]:
    out: set[str] = set()
    for f in PANELS.glob("*.xvp"):
        t = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'SymbolConfiguration">[^<]*?;;;([\w.]+)', t):
            out.add(m.group(1))
    return out


def _dbc_frames() -> set[str]:
    out: set[str] = set()
    for f in DBC_DIR.glob("*.dbc"):
        t = f.read_text(encoding="utf-8", errors="replace")
        out |= set(re.findall(r"^BO_ \d+ (\w+)", t, re.M))
    return out


def _explained() -> set[str]:
    p = ROOT / "can_tester" / "assets" / "signal_map.json"
    if not p.exists():
        return set()
    data = json.loads(p.read_text(encoding="utf-8"))
    return {s["sig"] for s in data["signals"]}


def audit() -> dict:
    nm = _load_map()
    sent, written = _restbus_coverage()
    panel = _panel_symbols()
    dbc = _dbc_frames()
    expl = _explained()

    rows = []
    for s in nm["signals"]:
        msg = next((m for m in nm["messages"] if m["MessageName"] == s["MessageName"]), None)
        sender = (msg or {}).get("Sender", "").strip()
        rows.append({
            "signal": s["SignalName"],
            "message": s["MessageName"],
            "network": s["Network"],
            "sender": sender,
            "own": sender == "NBCM",          # NBCM's own output: not to be faked
            "dbc": s["MessageName"] in dbc,
            "rest": s["MessageName"] in sent,
            "written": s["SignalName"] in written,
            "pane": s["SignalName"] in panel,
            "expl": s["SignalName"] in expl,
        })
    return {"rows": rows, "messages": nm["messages"]}


def summary(a: dict) -> int:
    rows = a["rows"]
    rest = [r for r in rows if not r["own"]]
    own = [r for r in rows if r["own"]]
    print(f"network map : {len(a['messages'])} messages, {len(rows)} signals")
    print(f"  not NBCM  : {len(rest)} signals  <- the restbus has to carry these")
    print(f"  NBCM own  : {len(own)} signals  <- deliberately NOT simulated\n")

    def line(label, key, pool):
        got = sum(1 for r in pool if r[key])
        print(f"  {label:34} {got:5}/{len(pool):5}  {100*got/len(pool):5.1f}%")
        return pool, [r for r in pool if not r[key]]

    print("restbus scope (must be 100%):")
    p, m_dbc = line("frame in a .dbc", "dbc", rest)
    p, m_rest = line("frame actually sent", "rest", rest)
    p, m_writ = line("signal actually written", "written", rest)
    p, m_pane = line("signal bound in a panel", "pane", rest)
    p, m_expl = line("signal explained in HTML", "expl", rest)

    print("\nNBCM's own output (reported, not simulated by design):")
    p, o_rest = line("frame sent by the simulator", "rest", own)
    p, o_pane = line("signal bound in a panel", "pane", own)
    p, o_expl = line("signal explained in HTML", "expl", own)

    real_gap = m_dbc + m_rest + m_writ
    seen = set()
    uniq = []
    for r in real_gap:
        if r["signal"] in seen:
            continue
        seen.add(r["signal"])
        uniq.append(r)
    print(f"\nGENUINE GAPS (restbus scope): {len(uniq)} signals")
    by = defaultdict(list)
    for r in uniq:
        by[(r["network"], r["message"], r["sender"])].append(r["signal"])
    for (net, msg, sender), sigs in sorted(by.items()):
        print(f"  {net} {msg:34} sender={sender or '(none)':8} {len(sigs)} signals")
    return len(uniq)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="name every gap")
    ap.add_argument("--json", action="store_true", help="machine readable")
    args = ap.parse_args(argv)

    a = audit()
    if args.json:
        print(json.dumps(a["rows"], ensure_ascii=False, indent=1))
        return 0
    gap = summary(a)
    if args.list:
        print("\nby name:")
        for r in a["rows"]:
            if r["own"]:
                continue
            miss = [k for k in ("dbc", "rest", "written", "pane", "expl") if not r[k]]
            if miss:
                print(f"  {r['network']} {r['message']:32} {r['signal']:36} missing={','.join(miss)}")
    return 0 if gap == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
