#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_capl.py -- generate the CANoe 12 side of the tester
=========================================================
Input : can_tester/assets/signal_map.json   (produced by tools/build_data.py)
Output: canoe/NBCM_Test.vsysvar             system-variable definition file
        canoe/NBCM_TesterBridge.can         CAPL node that binds sysvars <-> restbus

Why system variables?
----------------------
CANoe's COM/.NET API can read bus signals, but it cannot write the *CAPL
variables* your restbus model uses (long OFFLINE_ABS, double Hs_Abs_VehicleSpeed,
...).  System variables are the documented exchange medium for external programs,
are readable/writable from COM, from CAPL (`@sysvar::...`) and bindable from
Panel Designer.  So the tester talks system variables, and a small CAPL node
copies them to/from the restbus variables each 100 ms.

Direction is controlled by NBCM_Test::DRIVE_MODE
    0 = internal scenario owns the signals (tester only observes)
    1 = tester owns the signals (scenario values are overwritten)

Run:  python tools/build_capl.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAP = ROOT / "can_tester" / "assets" / "signal_map.json"
DEFAULT_OUT = ROOT / "canoe"

NAMESPACE = "NBCM_Test"

CONTROL_VARS = [
    # name, type, start, comment
    ("DRIVE_MODE", "int", 0, "0=restbus scenario owns signals, 1=tester (HTML/CAPL/COM) owns them"),
    ("SCENARIO_RUNNING", "int", 1, "driving scenario running"),
    ("MANUAL_SPEED_MODE", "int", 0, "1 = manual speed"),
    ("MANUAL_SPEED_KMH", "float", 0, "manual speed value in km/h"),
    ("HB_BRIDGE", "int", 0, "heartbeat written by the external bridge (optional)"),
]


# --------------------------------------------------------------------------- #
def xml_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def capl_safe(name: str) -> str:
    """CAPL identifiers must be valid C identifiers."""
    n = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return n if not n[:1].isdigit() else "_" + n


def build_vsysvar(signals: list[dict]) -> str:
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<systemvariables version="4">',
             '  <namespace name="" comment="" interface="">',
             f'    <namespace name="{NAMESPACE}" comment="NBCM CAN tester bridge" interface="">']

    for name, typ, start, comment in CONTROL_VARS:
        if typ == "int":
            lines.append(
                f'      <variable anlyzLocal="2" readOnly="false" valueSequence="false" unit="" '
                f'name="{name}" comment="{xml_escape(comment)}" bitcount="32" isSigned="true" '
                f'encoding="65001" type="int" minValue="-2147483648" maxValue="2147483647" '
                f'startValue="{start}" />')
        else:
            lines.append(
                f'      <variable anlyzLocal="2" readOnly="false" valueSequence="false" unit="" '
                f'name="{name}" comment="{xml_escape(comment)}" encoding="65001" type="float" '
                f'startValue="{start}" />')

    # A system variable name must be unique inside the namespace: CANoe aborts
    # the whole import with "Duplicate System Variable" otherwise.  The workbook
    # reuses some signal names across two messages (21 of them, e.g. LS_ICN_ODO
    # appears in LS_ID_DENA_ODO_IC and LS_ID_ICNI2_IC), so keep the first
    # definition and list the other carriers in the comment.
    carriers: dict[str, list[str]] = {}
    for s in signals:
        carriers.setdefault(s["sig"], []).append(s["msg"])

    emitted: set[str] = set()
    for s in signals:
        sig = s["sig"]
        if sig in emitted:
            continue
        emitted.add(sig)

        msgs = carriers.get(sig, [])
        comment = f'{s["node"]} / {s["msg"]}'
        if len(msgs) > 1:
            comment += " (also in: " + ", ".join(m for m in msgs if m != s["msg"]) + ")"

        if s["kind"] == "bool" or (s["min"] == 0 and s["max"] == 1):
            lines.append(
                f'      <variable anlyzLocal="2" readOnly="false" valueSequence="false" unit="" '
                f'name="{xml_escape(sig)}" comment="{xml_escape(comment)}" bitcount="32" '
                f'isSigned="true" encoding="65001" type="int" minValue="0" maxValue="1" '
                f'startValue="{int(s["def"])}" />')
        else:
            lines.append(
                f'      <variable anlyzLocal="2" readOnly="false" valueSequence="false" '
                f'unit="{xml_escape(s["unit"] or "")}" name="{xml_escape(sig)}" '
                f'comment="{xml_escape(comment)}" encoding="65001" type="float" '
                f'startValue="{s["def"]}" />')

    # node offline switches
    nodes = sorted({s["node"] for s in signals})
    for n in nodes:
        lines.append(
            f'      <variable anlyzLocal="2" readOnly="false" valueSequence="false" unit="" '
            f'name="OFFLINE_{n}" comment="1 = {n} stops transmitting (tester controlled)" '
            f'bitcount="32" isSigned="true" encoding="65001" type="int" minValue="0" maxValue="1" '
            f'startValue="0" />')

    dupes = {k: v for k, v in carriers.items() if len(v) > 1}
    if dupes:
        print(f"  merged {len(dupes)} duplicate signal name(s) "
              f"(one system variable per name, all carriers listed in the comment)")

    lines += ['    </namespace>', '  </namespace>', '</systemvariables>', '']
    return "\n".join(lines)


def build_capl(signals: list[dict]) -> str:
    nodes = sorted({s["node"] for s in signals})
    ns = NAMESPACE
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    out: list[str] = []
    a = out.append
    a("/*@!Encoding:65001*/")
    a("/*============================================================================")
    a("  NBCM_TesterBridge.can -- CANoe 12 bridge between the HTML tester and the")
    a("  restbus simulation in NBCM_Full_Restbus_Simulation.can")
    a("")
    a(f"  GENERATED by tools/build_capl.py on {now}")
    a("  Do not edit by hand -- change the workbook and regenerate.")
    a("")
    a("  HOW TO USE")
    a("  1) Add canoe/NBCM_Test.vsysvar to the CANoe configuration")
    a("     (System Variables window -> Import / add as file).")
    a("  2) Add this file to the SAME network node as the restbus simulation")
    a("     (or as an include in it) so it can see the CAPL variables.")
    a("  3) Measurement start: values flow restbus -> system variables.")
    a("  4) The HTML tester (or COM, or CAPL) sets NBCM_Test::DRIVE_MODE=1 to take")
    a("     control; then system variables -> restbus each 100 ms.")
    a("")
    a("  SIGNAL CONTRACT")
    a("    NBCM_Test::<SignalName>      = value of that signal")
    a("    NBCM_Test::OFFLINE_<NODE>    = 1 -> node stops transmitting")
    a("    NBCM_Test::DRIVE_MODE        = 0 observe / 1 control")
    a("============================================================================*/")

    a("")
    a("variables")
    a("{")
    a("  msTimer tmrTesterBridge;")
    a("  long  gLastDriveMode = 0;")
    a("  long  gTick = 0;")
    a("}")
    a("")
    a("on start")
    a("{")
    a("  setTimerCyclic(tmrTesterBridge, 100);")
    a(f'  write("[TesterBridge] active, namespace {ns}");')
    a("}")
    a("")
    a("/*----------------------------------------------------------------------------")
    a("  One tick: either publish restbus values to the system variables")
    a("  (DRIVE_MODE=0) or push tester values into the restbus (DRIVE_MODE=1).")
    a("----------------------------------------------------------------------------*/")
    a("on timer tmrTesterBridge")
    a("{")
    a("  long i;")
    a(f'  long driveMode = @sysvar::{ns}::DRIVE_MODE;')
    a("")
    a("  // node offline switches always come from the tester")
    for n in nodes:
        a(f'  OFFLINE_{capl_safe(n)} = @sysvar::{ns}::OFFLINE_{n};')
    a("")
    a("  if (driveMode != gLastDriveMode)")
    a("  {")
    a('    write("[TesterBridge] DRIVE_MODE = %d", driveMode);')
    a("    gLastDriveMode = driveMode;")
    a("  }")
    a("")
    a("  // scenario controls are always visible to both sides")
    a(f'  SCENARIO_RUNNING = @sysvar::{ns}::SCENARIO_RUNNING;')
    a(f'  MANUAL_SPEED_MODE = @sysvar::{ns}::MANUAL_SPEED_MODE;')
    a(f'  MANUAL_SPEED_KMH = @sysvar::{ns}::MANUAL_SPEED_KMH;')
    a("")
    a("  if (driveMode == 1)")
    a("  {")
    a("    // tester owns the signals")
    for s in signals:
        var = capl_safe(s["sig"])
        a(f'    {var} = @sysvar::{ns}::{s["sig"]};')
    a("  }")
    a("  else")
    a("  {")
    a("    // restbus owns the signals -- publish them so the HTML panel can display")
    for s in signals:
        var = capl_safe(s["sig"])
        a(f'    @sysvar::{ns}::{s["sig"]} = {var};')
    a("  }")
    a("")
    a("  // keep the panel mirror of the node switches in sync")
    for n in nodes:
        a(f'  @sysvar::{ns}::OFFLINE_{n} = OFFLINE_{capl_safe(n)};')
    a("")
    a("  gTick++;")
    a(f'  @sysvar::{ns}::HB_BRIDGE = 0;   // reserved')
    a("}")
    a("")
    a("/*----------------------------------------------------------------------------")
    a("  Convenience handlerse -- allow simple keyboard checks from CANoe itself.")
    a("----------------------------------------------------------------------------*/")
    a("on key 't'")
    a("{")
    a(f'  @sysvar::{ns}::DRIVE_MODE = (@sysvar::{ns}::DRIVE_MODE == 1) ? 0 : 1;')
    a('  write("[TesterBridge] DRIVE_MODE toggled");')
    a("}")
    a("")
    return "\n".join(out)


def build_binding_list(signals: list[dict]) -> str:
    """Panel Designer needs system variables; give a csv for bulk binding."""
    rows = ["# Panel Designer binding list (System Variable)", "Node,Message,Signal,SystemVariable,Unit,Min,Max"]
    for s in signals:
        rows.append(",".join([s["node"], s["msg"], s["sig"], f"{NAMESPACE}::{s['sig']}",
                              s["unit"] or "", str(s["min"]), str(s["max"])]))
    return "\n".join(rows) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="generate CANoe system variables + CAPL bridge")
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    if not args.map.exists():
        print(f"error: {args.map} not found. Run tools/build_data.py first.", file=sys.stderr)
        return 2
    data = json.loads(args.map.read_text(encoding="utf-8"))
    signals = data["signals"]
    args.out.mkdir(parents=True, exist_ok=True)

    vs = args.out / "NBCM_Test.vsysvar"
    vs.write_text(build_vsysvar(signals), encoding="utf-8")

    capl = args.out / "NBCM_TesterBridge.can"
    capl.write_text(build_capl(signals), encoding="utf-8")

    bind = args.out / "panel_binding_systemvars.csv"
    bind.write_text(build_binding_list(signals), encoding="utf-8")

    print(f"signals={len(signals)} nodes={len({s['node'] for s in signals})}")
    print(f"wrote {vs}")
    print(f"wrote {capl}")
    print(f"wrote {bind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
