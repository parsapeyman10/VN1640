#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_xvp.py -- generate real CANoe Panel Designer files (*.xvp)
==============================================================
CANoe 12 accepts panels as .xvp (XML).  This script turns the generated signal
model into panels you can add with  Home -> Panel -> Add Panel...

Output (in canoe/panels/):
    NBCM_Test_Overview.xvp     dashboard + node offline switches + scenario mode
    NBCM_<NODE>.xvp            one panel per node (13 files)
    panels_index.csv           which panel contains what

Every control is bound to a System Variable from the NBCM_Test namespace
(canoe/NBCM_Test.vsysvar), because CAPL variables cannot be bound from a panel
and system variables are what NBCM_TesterBridge.can copies into the restbus.

SymbolConfiguration layout (verified against panels shipped by Vector samples):
    4;16;<Namespace>;;;<VariableName>;1;;;-1
    ^  ^   ^                    ^
    |  |   |                    +-- 6th field: variable name
    |  |   +----------------------- 3rd field: namespace
    |  +--------------------------- 2nd field: 16 = system variable source
    +------------------------------ 1st field: 4  = system variable

Usage:
    python tools/build_xvp.py
    python tools/build_xvp.py --version 8.5.80.0     # assembly version stamp
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAP = ROOT / "can_tester" / "assets" / "signal_map.json"
DEFAULT_OUT = ROOT / "canoe" / "panels"

NAMESPACE = "NBCM_Test"

# The same explanations the HTML tester shows behind its (i) button: the text
# lives in tools/signal_glossary.py so the two can never drift apart.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import signal_glossary as _glossary
except Exception:                                                 # noqa: BLE001
    _glossary = None
# A real, older assembly version. CANoe upgrades panels on open, so stamping an
# older version is safer than inventing a version number that does not exist.
DEFAULT_VERSION = "8.5.80.0"

SER = ("Vector.CANalyzer.Panels.PanelSerializer, Vector.CANalyzer.Panels.Serializer, "
       "Version={v}, Culture=neutral, PublicKeyToken=null")
PANEL_T = ("Vector.CANalyzer.Panels.Runtime.Panel, Vector.CANalyzer.Panels.Common, "
           "Version={v}, Culture=neutral, PublicKeyToken=null")
SWITCH_T = ("Vector.CANalyzer.Panels.Design.SwitchControl, Vector.CANalyzer.Panels.CommonControls, "
            "Version={v}, Culture=neutral, PublicKeyToken=null")
NUM_T = ("Vector.CANalyzer.Panels.Design.NumericUpDownControl, "
         "Vector.CANalyzer.Panels.CommonControls, Version={v}, Culture=neutral, PublicKeyToken=null")
TEXT_T = ("Vector.CANalyzer.Panels.Design.StaticTextControl, "
          "Vector.CANalyzer.Panels.CommonControls, Version={v}, Culture=neutral, PublicKeyToken=null")
GROUP_T = ("Vector.CANalyzer.Panels.Design.GroupBoxControl, Vector.CANalyzer.Panels.CommonControls, "
           "Version={v}, Culture=neutral, PublicKeyToken=null")
GAUGE_T = ("Vector.CANalyzer.Panels.Design.AnalogGaugeControl, Vector.CANalyzer.Panels.AnalogGauge, "
           "Version={v}, Culture=neutral, PublicKeyToken=null")
LCD_T = ("Vector.CANalyzer.Panels.Design.LCDControl, Vector.CANalyzer.Panels.CommonControls, "
         "Version={v}, Culture=neutral, PublicKeyToken=null")

# --------------------------------------------------------------------------- #
# .cnp writer (legacy Panel Editor format)
# --------------------------------------------------------------------------- #
# .cnp is the text format of the retired Panel Editor ("VPanel").  CANoe 12 still
# converts it on open, but Vector announced: conversion is no longer automatic
# from CANoe 19 and will be dropped afterwards.  Which is why .xvp stays the
# primary output -- but a .cnp is produced too, because:
#   * it is a second, independent way into the same configuration, and
#   * its signal binding (Sig:<SignalName>) is positional (bus signal, no DBC
#     name needed), so a converted panel can bind *without* system variables.
# Element layouts below follow panels in the wild, e.g.
#   ElemSwitchAndDisplay 29 30 440 105 Sig:WN_Position <PE> EnvVar:X 0 0 0 17
#   ElemBN 0 240 270 35 EnvVar:Errframe -16
#   ElemMeter 70 71 175 150 EnvVar:evengspeedrec 0 -130 110 1000 8000 3 1 255 0 0 0 0

def cnp_q(text: str) -> str:
    return '"' + str(text).replace('"', "'") + '"'


def cnp_panel(name: str, elements: list[str], width: int, height: int) -> str:
    """Build a VPanel document.  Every element is one line; '@' terminates."""
    head = [
        f"VPanel {len(elements)} {int(width)} {int(height)} 0 0 255{cnp_q(name)}",
        "192 192 192",
        str(len(elements)),
    ]
    return "\n".join(head + elements) + "\n@\n"


def cnp_switch(x, y, var, w=21, h=30) -> str:
    return f"ElemSwitchAndDisplay {x} {y} {w} {h} SysSig:{var} <PE> 0 0 0 17 1 1 0 1"


def cnp_button(x, y, var, w=70, h=20) -> str:
    return f"ElemBN {x} {y} {w} {h} SysSig:{var} -16"


def cnp_meter(x, y, var, lo, hi, w=120, h=110) -> str:
    return (f"ElemMeter {x} {y} {w} {h} SysSig:{var} 0 0 0 "
            f"{int(lo) if float(lo).is_integer() else lo} "
            f"{int(hi) if float(hi).is_integer() else hi} 1 1 255 0 0 0 0")


# --------------------------------------------------------------------------- #
# small XML helpers
# --------------------------------------------------------------------------- #
def sym_conf(var: str, namespace: str = NAMESPACE) -> str:
    """System-variable binding string used by Panel Designer."""
    return f"4;16;{namespace};;;{var};1;;;-1"


class Control:
    """One panel control plus the properties Panel Designer writes for it."""

    def __init__(self, kind: str, name: str, caption: str, loc, size, props: dict):
        self.kind = kind
        self.name = name
        self.caption = caption
        self.loc = loc
        self.size = size
        self.props = props

    def render(self, version: str) -> str:
        types = {"switch": SWITCH_T, "num": NUM_T, "text": TEXT_T,
                 "group": GROUP_T, "gauge": GAUGE_T, "lcd": LCD_T}
        t = types[self.kind].format(v=version)
        out = [f'    <Object Type="{t}" Name="{self.name}" Children="Controls" '
               f'ControlName="{escape(self.caption)}">',
               f'      <Property Name="Name">{self.name}</Property>',
               f'      <Property Name="Size">{self.size[0]}, {self.size[1]}</Property>',
               f'      <Property Name="Location">{self.loc[0]}, {self.loc[1]}</Property>']
        for k, v in self.props.items():
            out.append(f'      <Property Name="{k}">{escape(str(v))}</Property>')
        out.append("    </Object>")
        return "\n".join(out)


def switch(name, caption, loc, var, size=(21, 30)):
    return Control("switch", name, caption, loc, size, {
        "StateCnt": 2,
        "Activation": "Left",
        "SwitchValues": "1;2;0;1",
        "SymbolConfiguration": sym_conf(var),
    })


def numeric(name, caption, loc, var, lo, hi, step=1, size=(86, 20)):
    return Control("num", name, caption, loc, size, {
        "Minimum": _fmt_num(lo),
        "Maximum": _fmt_num(hi),
        "Increment": _fmt_num(step),
        "SymbolConfiguration": sym_conf(var),
    })


def tip_for(sig: dict) -> str:
    """Hover text for a signal control."""
    if _glossary is not None:
        try:
            recs = _glossary.build()["signals"]
            rec = recs.get(sig.get("id")) or recs.get(f"{sig['node']}:{sig['msg']}:{sig['sig']}")
            if rec:
                return _glossary.tooltip_text(rec)
        except Exception:                                         # noqa: BLE001
            pass
    return (f"{sig['sig']} — {sig['node']} / {sig['msg']}\n"
            f"{'دوحالته' if sig['kind'] == 'bool' else 'عددی'} · "
            f"{sig['min']}..{sig['max']} {sig['unit'] or ''} · هر {sig.get('cycle', 0)} ms")


def tip_for_node(node: dict) -> str:
    """Hover text for a node."""
    if _glossary is not None:
        try:
            info = _glossary.build()["nodes"].get(node["node"])
            if info:
                return (f"{node['node']} — {info['title']}\n{info['about']}\n"
                        f"{node.get('nMsg', 0)} پیام · {node.get('nSig', 0)} سیگنال · "
                        f"{node['net']}-CAN")
        except Exception:                                         # noqa: BLE001
            pass
    return f"{node['node']} — {node['net']}-CAN"


def infobtn(name: str, loc, tip: str, size=(13, 16)) -> "Control":
    """A small circled "!" next to a control; CANoe shows `tip` on hover."""
    return Control("text", name, "Static Text", loc, size, {
        "Text": "(i)",
        "Font": "Microsoft Sans Serif, 7.5pt",
        "ForeColor": "0, 90, 170",
        "CustomToolTipText": tip,
    })


def label(name, caption, loc, text, size=(120, 18)):
    return Control("text", name, caption, loc, size, {"Text": text})


def lcd(name, caption, loc, var, size=(90, 26), decimals=0):
    return Control("lcd", name, caption, loc, size, {
        "DecimalPlaces": decimals,
        "SymbolConfiguration": sym_conf(var),
    })


def _fmt_num(v) -> str:
    """Panel Designer wants invariant numbers."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "0"
    return str(int(f)) if f == int(f) else f"{f:.6g}"


def clean_id(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", s)
    return s if not s[:1].isdigit() else "_" + s


# --------------------------------------------------------------------------- #
# panels
# --------------------------------------------------------------------------- #
def render_panel(panel_name: str, controls: list[Control], width: int, height: int,
                 version: str) -> str:
    body = "\n".join(c.render(version) for c in controls)
    return f"""<?xml version="1.0"?>
<Panel Type="{SER.format(v=version)}">
  <Object Type="{PANEL_T.format(v=version)}" Name="Panel" Children="Controls" ControlName="{escape(panel_name)}">
{body}
    <Property Name="Name">{escape(panel_name)}</Property>
    <Property Name="Size">{width}, {height}</Property>
    <Property Name="BackColor">White</Property>
  </Object>
</Panel>
"""


def build_overview(nodes: list[dict], signals: list[dict], version: str) -> tuple[str, int, int]:
    """Dashboard + the controls an operator needs during a measurement."""
    c: list[Control] = []
    y = 8
    c.append(label("TxtTitle", "Static Text", (8, y),
                   "NBCM Test Panel - restbus / CANoe 12", (420, 22)))
    y += 28

    # --- live values
    c.append(Control("group", "GrpLive", "Group Box", (8, y), (340, 132),
                     {"Text": "Live values"}))
    # speeds are read from the signal values published by the CAPL bridge
    c.append(lcd("LcdSpeed", "LCD Control", (18, y + 22), "Hs_Abs_VehicleSpeed", (110, 30), 1))
    c.append(label("TxtSpeed", "Static Text", (134, y + 28), "VehicleSpeed km/h", (140, 18)))
    c.append(lcd("LcdRpm", "LCD Control", (18, y + 58), "Hs_Ems_Rpm", (110, 30), 0))
    c.append(label("TxtRpm", "Static Text", (134, y + 64), "Engine Rpm", (140, 18)))
    c.append(lcd("LcdOdo", "LCD Control", (18, y + 94), "LS_ICN_ODO", (110, 30), 0))
    c.append(label("TxtOdo", "Static Text", (134, y + 100), "Odometer (m)", (140, 18)))

    # --- tester / CANoe ownership
    x2 = 360
    c.append(Control("group", "GrpMode", "Group Box", (x2, y), (300, 132),
                     {"Text": "Control source"}))
    c.append(switch("SwDriveMode", "Switch/Indicator", (x2 + 12, y + 30), "DRIVE_MODE"))
    c.append(label("TxtDriveMode", "Static Text", (x2 + 42, y + 32),
                   "DRIVE_MODE  0=CANoe  1=tester", (240, 18)))
    c.append(switch("SwScenario", "Switch/Indicator", (x2 + 12, y + 66), "SCENARIO_RUNNING"))
    c.append(label("TxtScenario", "Static Text", (x2 + 42, y + 68),
                   "SCENARIO_RUNNING", (240, 18)))
    c.append(switch("SwManualMode", "Switch/Indicator", (x2 + 12, y + 96), "MANUAL_SPEED_MODE"))
    c.append(label("TxtManualMode", "Static Text", (x2 + 42, y + 98),
                   "MANUAL_SPEED_MODE", (130, 18)))
    c.append(numeric("NumManualSpeed", "Numeric Up/Down", (x2 + 176, y + 96),
                     "MANUAL_SPEED_KMH", 0, 250, 1, (66, 20)))
    y += 142

    # --- node offline switches (2 columns)
    rows_per_col = 7
    cols = 2
    box_h = 24 + rows_per_col * 34
    c.append(Control("group", "GrpNodes", "Group Box", (8, y), (300, box_h),
                     {"Text": "Node offline switch (1 = node silent)"}))
    for i, n in enumerate(nodes):
        col = i // rows_per_col
        row = i % rows_per_col
        cx = 18 + col * 150
        cy = y + 22 + row * 34
        c.append(switch(f"SwOff_{clean_id(n['node'])}", "Switch/Indicator", (cx, cy),
                        f"OFFLINE_{n['node']}", (21, 26)))
        c.append(label(f"TxtOff_{clean_id(n['node'])}", "Static Text", (cx + 27, cy + 4),
                       f"{n['node']} ({n['net']})", (105, 18)))

    width = 680
    height = max(y + box_h + 20, 420)
    return render_panel("NBCM Test Overview", c, width, height, version), width, height


def build_node_panel(node: dict, signals_by_sig: dict, version: str) -> tuple[str, int, int]:
    """One panel per node: a labelled control for every signal of that node."""
    sigs = [signals_by_sig[s] for s in _node_signal_names(node, signals_by_sig)]
    rows_per_col = 34
    col_w = 250
    cols = max(1, -(-len(sigs) // rows_per_col))          # ceil
    width = 12 + cols * col_w
    height = 42 + rows_per_col * 26

    c: list[Control] = []
    ttl = label("TxtTitle", "Static Text", (10, 8),
                f"{node['node']}  -  {node['net']}-CAN  -  "
                f"{node['nMsg']} messages / {node['nSig']} signals", (cols * col_w - 40, 20))
    ttl.props["CustomToolTipText"] = tip_for_node(node)
    c.append(ttl)
    c.append(infobtn("I_Node", (cols * col_w - 26, 7), tip_for_node(node)))

    for i, s in enumerate(sigs):
        col = i // rows_per_col
        row = i % rows_per_col
        x = 10 + col * col_w
        y = 38 + row * 26
        tip = tip_for(s)
        lbl = label(f"Txt_{clean_id(s['sig'])}", "Static Text", (x, y + 2),
                    s["sig"], (138, 18))
        lbl.props["CustomToolTipText"] = tip
        c.append(lbl)
        c.append(infobtn(f"I_{clean_id(s['sig'])}", (x + 140, y + 1), tip))
        if s["kind"] == "bool":
            sw = switch(f"Sw_{clean_id(s['sig'])}", "Switch/Indicator", (x + 162, y),
                        s["sig"], (20, 24))
            sw.props["CustomToolTipText"] = tip
            c.append(sw)
        else:
            step = 1 if s["kind"] == "enum" else max(0.1, round((s["max"] - s["min"]) / 100, 3))
            nb = numeric(f"Num_{clean_id(s['sig'])}", "Numeric Up/Down", (x + 164, y + 3),
                         s["sig"], s["min"], s["max"], step, (72, 20))
            nb.props["CustomToolTipText"] = tip
            c.append(nb)
    return render_panel(f"NBCM {node['node']}", c, width, height, version), width, height


def _node_signal_names(node: dict, signals_by_sig: dict) -> list[str]:
    """Preserve the order the workbook uses (message order, then signal order)."""
    out, seen = [], set()
    for m in node.get("msgs", []):
        for full_id in m.get("sigs", []):
            sig = full_id.split(":")[-1]
            if sig in signals_by_sig and sig not in seen:
                seen.add(sig)
                out.append(sig)
    return out


# --------------------------------------------------------------------------- #
def build_smoke_panel(version: str) -> tuple[str, int, int]:
    """A three-control panel to prove the whole chain in under a minute."""
    c = [
        label("TxtTitle", "Static Text", (10, 8),
              "NBCM smoke test: flip the switch, value must follow", (420, 20)),
        switch("SwDriveMode", "Switch/Indicator", (10, 34), "DRIVE_MODE", (21, 30)),
        label("TxtDriveMode", "Static Text", (40, 38), "DRIVE_MODE", (110, 18)),
        lcd("LcdDriveMode", "LCD Control", (160, 36), "DRIVE_MODE", (70, 26)),
        switch("SwAbsOff", "Switch/Indicator", (10, 76), "OFFLINE_ABS", (21, 30)),
        label("TxtAbsOff", "Static Text", (40, 80), "OFFLINE_ABS", (110, 18)),
        lcd("LcdAbsOff", "LCD Control", (160, 78), "OFFLINE_ABS", (70, 26)),
        lcd("LcdSpeed", "LCD Control", (250, 36), "Hs_Abs_VehicleSpeed", (110, 26), 1),
        label("TxtSpeed", "Static Text", (250, 64), "Hs_Abs_VehicleSpeed", (150, 18)),
    ]
    return render_panel("NBCM Smoke", c, 380, 120, version), 380, 120


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="generate CANoe Panel Designer .xvp files")
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--version", default=DEFAULT_VERSION,
                    help=f"assembly version stamp (default {DEFAULT_VERSION})")
    ap.add_argument("--no-node-panels", action="store_true",
                    help="only generate the overview panel")
    args = ap.parse_args(argv)

    if not args.map.exists():
        print(f"error: {args.map} not found. Run tools/build_data.py first.")
        return 2
    data = json.loads(args.map.read_text(encoding="utf-8"))
    nodes = data["nodes"]
    signals = data["signals"]
    by_sig = {}
    for s in signals:
        by_sig.setdefault(s["sig"], s)

    outdir = args.out
    outdir.mkdir(parents=True, exist_ok=True)

    produced = []
    xml, w, h = build_smoke_panel(args.version)
    p = outdir / "NBCM_Smoke.xvp"
    p.write_text(xml, encoding="utf-8")
    produced.append((p.name, "smoke", w, h, "one switch per concept, for the first wiring check"))

    # legacy twin of the smoke panel, context-menu variant for the panel itself
    els = [
        cnp_switch(10, 34, "NBCM_Test::DRIVE_MODE"),
        cnp_switch(10, 76, "NBCM_Test::OFFLINE_ABS"),
        cnp_meter(250, 30, "NBCM_Test::Hs_Abs_VehicleSpeed", 0, 200, 120, 110),
    ]
    p = outdir / "NBCM_Smoke.cnp"
    p.write_text(cnp_panel("NBCM Smoke (cnp)", els, 380, 150), encoding="utf-8")
    produced.append((p.name, "smoke (legacy)", 380, 150, "legacy Panel Editor variant"))

    xml, w, h = build_overview(nodes, signals, args.version)
    p = outdir / "NBCM_Test_Overview.xvp"
    p.write_text(xml, encoding="utf-8")
    produced.append((p.name, "overview", w, h, "dashboard + offline switches + control source"))

    if not args.no_node_panels:
        for n in nodes:
            xml, w, h = build_node_panel(n, by_sig, args.version)
            p = outdir / f"NBCM_{clean_id(n['node'])}.xvp"
            p.write_text(xml, encoding="utf-8")
            produced.append((p.name, n["node"], w, h, f"{n['nSig']} signals"))

    idx = outdir / "panels_index.csv"
    idx.write_text("file,target,width,height,content\n" + "\n".join(
        f"{a},{b},{c},{d},{e}" for a, b, c, d, e in produced) + "\n", encoding="utf-8")

    print(f"generated {len(produced)} panels in {outdir}")
    for a, b, c, d, e in produced:
        print(f"  {a:<28} {c}x{d}  {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
