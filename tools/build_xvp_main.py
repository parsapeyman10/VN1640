#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_xvp_main.py -- the single "everything" CANoe panel
=======================================================
One .xvp that is usable on its own: a dashboard, a driving scenario, all 13
node kill switches, a signal browser per node, a timeout monitor and the test
suite control.  Instead of fifteen files to add, you add one.

Structure is copied from panels CANoe itself produced:

    Panel
      TabControl                     (VectorTabControl + VectorTabPage children)
        Page: Dashboard               gauges, LEDs, drive-scenario controls
        Page: Nodes                   13 switches + LED per node
        Page: Signals                 one page per node, value + slider + LED
        Page: Monitor                 watchdog rows (value + LED)
        Page: Tests                   the 6 test results + scenario control

The simulation behind it is CAPL, not the panel: a .xvp can only read and write
symbols.  See canoe/NBCM_TesterBridge.can -- SCENARIO_RUNNING makes it ramp a
drive cycle, and DRIVE_MODE decides who owns the signals.

    python tools/build_xvp_main.py
    python tools/build_xvp_main.py --version 10.0.96.0
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
DEFAULT_MAP = ROOT / "can_tester" / "assets" / "signal_map.json"
DEFAULT_OUT = ROOT / "canoe" / "panels" / "NBCM_Main.xvp"
FONT = "Microsoft Sans Serif, 8.25pt"
FONT_SMALL = "Microsoft Sans Serif, 7.5pt"

V = "10.0.96.0"
SER = ("Vector.CANalyzer.Panels.PanelSerializer, Vector.CANalyzer.Panels.Serializer, "
       f"Version={V}, Culture=neutral, PublicKeyToken=null")
PANEL_T = ("Vector.CANalyzer.Panels.Runtime.Panel, Vector.CANalyzer.Panels.Common, "
           f"Version={V}, Culture=neutral, PublicKeyToken=null")
TAB_T = ("Vector.CANalyzer.Panels.Design.TabControl, Vector.CANalyzer.Panels.CommonControls, "
         f"Version={V}, Culture=neutral, PublicKeyToken=null")
PAGE_T = ("Vector.CANalyzer.Panels.Design.TabPage, Vector.CANalyzer.Panels.CommonControls, "
          f"Version={V}, Culture=neutral, PublicKeyToken=null")
SWITCH_T = ("Vector.CANalyzer.Panels.Design.SwitchControl, Vector.CANalyzer.Panels.CommonControls, "
            f"Version={V}, Culture=neutral, PublicKeyToken=null")
LED_T = ("Vector.CANalyzer.Panels.Design.LEDControl, Vector.CANalyzer.Panels.CommonControls, "
         f"Version={V}, Culture=neutral, PublicKeyToken=null")
NUM_T = ("Vector.CANalyzer.Panels.Design.NumericUpDownControl, "
         f"Vector.CANalyzer.Panels.CommonControls, Version={V}, Culture=neutral, PublicKeyToken=null")
TRACK_T = ("Vector.CANalyzer.Panels.Design.TrackBarControl, "
           f"Vector.CANalyzer.Panels.CommonControls, Version={V}, Culture=neutral, PublicKeyToken=null")
TEXT_T = ("Vector.CANalyzer.Panels.Design.StaticTextControl, "
          f"Vector.CANalyzer.Panels.CommonControls, Version={V}, Culture=neutral, PublicKeyToken=null")
GROUP_T = ("Vector.CANalyzer.Panels.Design.GroupBoxControl, "
           f"Vector.CANalyzer.Panels.CommonControls, Version={V}, Culture=neutral, PublicKeyToken=null")
GAUGE_T = ("Vector.CANalyzer.Panels.Design.AnalogGaugeControl, "
           f"Vector.CANalyzer.Panels.AnalogGauge, Version={V}, Culture=neutral, PublicKeyToken=null")
LCD_T = ("Vector.CANalyzer.Panels.Design.LCDControl, "
         f"Vector.CANalyzer.Panels.CommonControls, Version={V}, Culture=neutral, PublicKeyToken=null")

NAMESPACE = "NBCM_Test"


def sym(var: str) -> str:
    """System-variable binding string."""
    return f"4;16;{NAMESPACE};;;{var};1;;;-1"


def fmt(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "0"
    return str(int(f)) if f == int(f) else f"{f:.6g}"


def ident(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", s)
    return s if not s[:1].isdigit() else "_" + s


# --------------------------------------------------------------------------- #
# tooltips: the same explanation the HTML tester shows behind the (i) button
# --------------------------------------------------------------------------- #
def _glossary():
    import signal_glossary
    return signal_glossary


def signal_tip(sig: dict) -> str:
    """Hover text for one signal control, straight from signal_glossary."""
    try:
        rec = _glossary().build()["signals"].get(sig.get("id") or sig["sig"])
        if rec is None:
            rec = _glossary().build()["signals"].get(
                f"{sig['node']}:{sig['msg']}:{sig['sig']}")
        if rec:
            return _glossary().tooltip_text(rec)
    except Exception:                                             # noqa: BLE001
        pass
    # never leave a control without a tooltip: fall back to the facts we know
    return (f"{sig['sig']} — {sig['node']} / {sig['msg']}\n"
            f"{'دوحالته' if sig['kind'] == 'bool' else 'عددی'} · "
            f"{sig['min']}..{sig['max']} {sig['unit'] or ''} · هر {sig.get('cycle', 0)} ms")


def node_tip(node: dict) -> str:
    """Hover text for a whole node."""
    try:
        info = _glossary().build()["nodes"].get(node["node"])
        if info:
            return (f"{node['node']} — {info['title']}\n{info['about']}\n"
                    f"{node.get('nMsg', 0)} پیام · {node.get('nSig', 0)} سیگنال · "
                    f"{node['net']}-CAN")
    except Exception:                                             # noqa: BLE001
        pass
    return f"{node['node']} — {node['net']}-CAN"


# --------------------------------------------------------------------------- #
class Ctl:
    def __init__(self, kind, name, caption, loc, size, props=None):
        self.kind, self.name, self.caption = kind, name, caption
        self.loc, self.size = loc, size
        self.props = props or {}

    def render(self, depth: int, children=()) -> str:
        pad = "  " * depth
        types = {"tab": TAB_T, "page": PAGE_T, "switch": SWITCH_T, "led": LED_T,
                 "num": NUM_T, "track": TRACK_T, "text": TEXT_T, "group": GROUP_T,
                 "gauge": GAUGE_T, "lcd": LCD_T}
        kids = "".join(children)
        out = [f'{pad}<Object Type="{types[self.kind]}" Name="{self.name}" '
               f'Children="Controls" ControlName="{escape(self.caption)}">',
               f'{pad}  <Property Name="Name">{self.name}</Property>',
               f'{pad}  <Property Name="Size">{self.size[0]}, {self.size[1]}</Property>',
               f'{pad}  <Property Name="Location">{self.loc[0]}, {self.loc[1]}</Property>']
        for k, v in self.props.items():
            out.append(f'{pad}  <Property Name="{k}">{escape(str(v))}</Property>')
        if kids:
            out.append(kids.rstrip("\n"))
        out.append(f"{pad}</Object>")
        return "\n".join(out) + "\n"


def text(name, caption, loc, body, size=(120, 16), small=False, bold=False):
    props = {"Text": body}
    if small:
        props["Font"] = FONT_SMALL
    if bold:
        props["Font"] = "Microsoft Sans Serif, 8.25pt, style=B"
    return Ctl("text", name, "Static Text", loc, size, props)


def infobtn(name, loc, tip, size=(13, 13)):
    """A small circled "!" next to a control; CANoe shows `tip` on hover.

    Static Text is used rather than a button because it takes no focus and cannot
    be clicked by mistake while the panel is live.
    """
    return Ctl("text", name, "Static Text", loc, size, {
        "Text": "(i)",
        "Font": FONT_SMALL,
        "ForeColor": "0, 90, 170",
        "CustomToolTipText": tip,
    })


def switch(name, loc, var, size=(21, 26)):
    return Ctl("switch", name, "Switch/Indicator", loc, size, {
        "StateCnt": 2, "Activation": "Left", "SwitchValues": "1;2;0;1",
        "SymbolConfiguration": sym(var)})


def led(name, loc, var, size=(16, 16), on=(0, 200, 0), off=(190, 190, 190)):
    return Ctl("led", name, "LED", loc, size, {
        "SymbolConfiguration": sym(var),
        "OnColor": f"{on[0]}, {on[1]}, {on[2]}",
        "OffColor": f"{off[0]}, {off[1]}, {off[2]}"})


def lcd(name, loc, var, size=(80, 26), decimals=0):
    return Ctl("lcd", name, "LCD Control", loc, size, {
        "DecimalPlaces": decimals, "SymbolConfiguration": sym(var)})


def num(name, loc, var, lo, hi, step=1, size=(70, 20)):
    return Ctl("num", name, "Numeric Up/Down", loc, size, {
        "Minimum": fmt(lo), "Maximum": fmt(hi), "Increment": fmt(step),
        "SymbolConfiguration": sym(var)})


def gauge(name, loc, var, legend, size=(120, 120)):
    return Ctl("gauge", name, "Analog Gauge", loc, size, {
        "BackgroundColor": "White", "ScaleMargin": "2", "IsMargin": "False",
        "GaugeFont": "Microsoft Sans Serif, 8pt",
        "MainTicksNumber": "10", "LegendText": legend,
        "SymbolConfiguration": sym(var)})


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def page_dashboard(nodes) -> str:
    c = []
    c.append(text("TxtTitle", "Static Text", (10, 6),
                  "NBCM DENA - CANoe 12 tester   |   one panel for the whole bench",
                  (600, 20), bold=True))
    hint = text("TxtHint", "Static Text", (10, 26),
                "Set DRIVE_MODE=1 (TESTER) to let this panel and the HTML tester write "
                "the bus.  DRIVE_MODE=0 gives the bus back to the restbus.",
                (596, 16), small=True)
    hint.props["CustomToolTipText"] = (
        "این پنل و تستر HTML هر دو روی یک شبیه‌سازی کار می‌کنند.\n"
        "DRIVE_MODE=0 : اتوبوس دست restbus است و سناریو خودش رانندگی می‌کند.\n"
        "DRIVE_MODE=1 : کنترل به تستر می‌رسد و هر چه در پنل یا HTML تغییر دهید روی باس می‌رود.\n"
        "علامت (i) کنار هر سیگنال: نگه داشتن موس توضیح کوتاه، کلیک برای توضیح کامل در تستر HTML.")
    c.append(hint)
    c.append(infobtn("I_Hint", (614, 26), hint.props["CustomToolTipText"]))

    # --- instrument cluster ------------------------------------------------
    c.append(Ctl("group", "GrpCluster", "Group Box", (10, 46), (388, 150),
                 {"Text": "Cluster"}))
    c.append(gauge("GaugeSpeed", (18, 62), "Hs_Abs_VehicleSpeed", "km/h", (128, 128)))
    c.append(gauge("GaugeRpm", (152, 62), "Hs_Ems_Rpm", "rpm", (120, 120)))
    c.append(lcd("LcdSpeed", (286, 66), "Hs_Abs_VehicleSpeed", (100, 30), 1))
    c.append(text("TxtSpeed", "Static Text", (286, 96), "VehicleSpeed", (100, 14), small=True))
    c.append(lcd("LcdRpm", (286, 114), "Hs_Ems_Rpm", (100, 30), 0))
    c.append(text("TxtRpm", "Static Text", (286, 144), "EngineRpm", (100, 14), small=True))

    # --- drive scenario ----------------------------------------------------
    c.append(Ctl("group", "GrpScenario", "Group Box", (10, 202), (388, 96),
                 {"Text": "Drive scenario (simulated in CAPL)"}))
    c.append(switch("SwScenario", (20, 218), "SCENARIO_RUNNING"))
    c.append(text("TxtScenario", "Static Text", (44, 220), "SCENARIO_RUNNING", (150, 16)))
    c.append(led("LedScenario", (198, 218), "SCENARIO_RUNNING", (16, 16)))
    c.append(text("TxtScenarioHint", "Static Text", (220, 220),
                  "OK = CAPL is ramping the drive cycle", (168, 16), small=True))

    c.append(switch("SwManual", (20, 244), "MANUAL_SPEED_MODE"))
    c.append(text("TxtManual", "Static Text", (44, 246), "MANUAL_SPEED_MODE", (150, 16)))
    c.append(num("NumSpeed", (20, 268), "MANUAL_SPEED_KMH", 0, 250, 1, (82, 20)))
    c.append(text("TxtTarget", "Static Text", (108, 270), "target km/h", (80, 16), small=True))
    c.append(led("LedManual", (198, 246), "MANUAL_SPEED_MODE", (16, 16)))
    c.append(text("TxtManualHint", "Static Text", (220, 248),
                  "manual speed overrides the ramp", (168, 16), small=True))

    # --- ownership ---------------------------------------------------------
    c.append(switch("SwDrive", (20, 272), "DRIVE_MODE"))
    c.append(text("TxtDrive", "Static Text", (44, 274), "DRIVE_MODE  (0=restbus, 1=tester)",
                  (160, 16)))
    c.append(led("LedDrive", (214, 272), "DRIVE_MODE", (16, 16),
                 on=(0, 140, 255), off=(190, 190, 190)))
    c.append(text("TxtDriveHint", "Static Text", (236, 274),
                  "blue = the tester owns the bus", (152, 16), small=True))

    # --- right column: network health --------------------------------------
    x = 410
    c.append(Ctl("group", "GrpHealth", "Group Box", (x, 46), (250, 252),
                 {"Text": "Network health"}))
    c.append(text("TxtHealthHdr", "Static Text", (x + 8, 60),
                  "carrier LED + message age", (230, 16), small=True))
    y = 80
    for n in nodes:
        c.append(led(f"LedNode_{ident(n['node'])}", (x + 8, y), f"HB_{n['node']}", (14, 14)))
        c.append(text(f"TxtNode_{ident(n['node'])}", "Static Text", (x + 26, y - 1),
                      f"{n['node']}", (40, 15), small=True))
        c.append(lcd(f"LcdAge_{ident(n['node'])}", (x + 70, y - 5),
                     f"AGE_{n['node']}", (64, 20), 0))
        c.append(text(f"TxtAge_{ident(n['node'])}", "Static Text", (x + 138, y - 1),
                      "ms", (24, 15), small=True))
        y += 18
        if y > 260:
            break  # the editor caps a group; the Nodes page carries the rest
    return render_page("Dashboard", c, 670, 312)


def page_nodes(nodes) -> str:
    c = [text("TxtTitle", "Static Text", (10, 6),
              "Node kill switches - 1 makes the restbus node stop transmitting",
              (600, 20), bold=True)]
    c.append(text("TxtHint", "Static Text", (10, 26),
                  "CAPL reads OFFLINE_<NODE>: while it is 1 the node's messages are "
                  "suppressed, so the tester sees a real timeout.",
                  (620, 16), small=True))

    cols = 3
    y0 = 48
    for i, n in enumerate(nodes):
        col, row = i % cols, i // cols
        x = 10 + col * 216
        y = y0 + row * 52
        c.append(Ctl("group", f"Grp_{ident(n['node'])}", "Group Box", (x, y), (206, 46),
                     {"Text": f"{n['node']}  ({n['net']}-CAN)"}))
        c.append(switch(f"Sw_{ident(n['node'])}", (x + 10, y + 16), f"OFFLINE_{n['node']}"))
        c.append(led(f"Led_{ident(n['node'])}", (x + 36, y + 20),
                     f"OFFLINE_{n['node']}", (14, 14), on=(220, 60, 60), off=(0, 190, 90)))
        tip = node_tip(n)
        nm = text(f"Txt_{ident(n['node'])}", "Static Text", (x + 56, y + 18),
                  f"{n['node']} - OFFLINE switch", (100, 15), small=True)
        cnt = text(f"TxtCount_{ident(n['node'])}", "Static Text", (x + 56, y + 30),
                   f"{n['nMsg']} msgs / {n['nSig']} sigs", (110, 15), small=True)
        for extra in (nm, cnt):
            extra.props["CustomToolTipText"] = tip
            c.append(extra)
        c.append(infobtn(f"I_{ident(n['node'])}", (x + 178, y + 17), tip))
    return render_page("Nodes", c, 670, 312)


def page_signals(node, sigs, part=0, total_sigs=None) -> str:
    """One page per node: value display, slider and a boolean LED where useful."""
    name = node["node"] + (f" ({part + 1})" if part else "")
    n_all = total_sigs if total_sigs is not None else len(sigs)
    c = [text("TxtTitle", "Static Text", (8, 4),
              f"{name} - {n_all} signals  ({node['net']}-CAN)",
              (600, 18), bold=True)]
    c.append(text("TxtColA", "Static Text", (8, 24), "signal", (150, 14), small=True))
    c.append(text("TxtColB", "Static Text", (168, 24), "value", (70, 14), small=True))
    c.append(text("TxtColC", "Static Text", (246, 24), "set", (140, 14), small=True))

    y = 40
    lh = 16
    col_w = 165
    per_col = 16
    for i, s in enumerate(sigs):
        col, row = divmod(i, per_col)
        x = 8 + col * col_w
        yy = y + row * lh
        name = s["sig"]
        tip = signal_tip(s)
        # the label and every control on the row carry the same explanation, so a
        # hover anywhere on the row answers "what is this signal".
        lbl = text(f"L_{ident(name)}", "Static Text", (x, yy), name, (128, 14), small=True)
        lbl.props["CustomToolTipText"] = tip
        c.append(lbl)
        c.append(infobtn(f"I_{ident(name)}", (x + 130, yy - 1), tip))
        if s["kind"] == "bool":
            ledc = led(f"V_{ident(name)}", (x + 150, yy + 1), name, (12, 12))
            swc = switch(f"S_{ident(name)}", (x + 180, yy - 3), name, (18, 20))
            ledc.props["CustomToolTipText"] = tip
            swc.props["CustomToolTipText"] = tip
            c.append(ledc)
            c.append(swc)
        else:
            lcdc = lcd(f"V_{ident(name)}", (x + 150, yy - 3), name, (52, 19), 0)
            step = 1 if s["kind"] == "enum" else max(1, round((s["max"] - s["min"]) / 50))
            numc = num(f"S_{ident(name)}", (x + 206, yy - 2), name,
                       s["min"], s["max"], step, (58, 18))
            lcdc.props["CustomToolTipText"] = tip
            numc.props["CustomToolTipText"] = tip
            c.append(lcdc)
            c.append(numc)
    return render_page(node["node"], c, 670, 312)


def page_monitor(nodes) -> str:
    c = [text("TxtTitle", "Static Text", (10, 6),
              "Timeout / carrier monitor", (600, 20), bold=True)]
    c.append(text("TxtHint", "Static Text", (10, 26),
                  "green = message seen within the last 500 ms; red = missing "
                  "(node killed or not transmitting)",
                  (620, 16), small=True))
    c.append(text("TxtH1", "Static Text", (14, 44), "node", (60, 14), small=True))
    c.append(text("TxtH2", "Static Text", (90, 44), "carrier", (50, 14), small=True))
    c.append(text("TxtH3", "Static Text", (150, 44), "age (ms)", (70, 14), small=True))
    c.append(text("TxtH4", "Static Text", (240, 44), "node", (60, 14), small=True))
    c.append(text("TxtH5", "Static Text", (316, 44), "carrier", (50, 14), small=True))
    c.append(text("TxtH6", "Static Text", (376, 44), "age (ms)", (70, 14), small=True))

    for i, n in enumerate(nodes):
        col, row = divmod(i, 7)
        x = 14 + col * 226
        y = 60 + row * 24
        c.append(text(f"M_{ident(n['node'])}", "Static Text", (x, y + 2),
                      n["node"], (66, 15), small=True))
        c.append(led(f"MC_{ident(n['node'])}", (x + 74, y + 3), f"HB_{n['node']}", (13, 13)))
        c.append(lcd(f"MA_{ident(n['node'])}", (x + 96, y), f"AGE_{n['node']}", (68, 21), 0))
        c.append(switch(f"MO_{ident(n['node'])}", (x + 178, y - 1),
                        f"OFFLINE_{n['node']}", (18, 22)))
    return render_page("Monitor", c, 670, 312)


def page_tests() -> str:
    c = [text("TxtTitle", "Static Text", (10, 6), "Test suite - verdicts", (600, 20), bold=True)]
    c.append(text("TxtHint", "Static Text", (10, 26),
                  "The suite itself runs in the HTML tester or from run_suite.py; "
                  "these variables carry the verdict back so it is visible in CANoe.",
                  (620, 16), small=True))
    c.append(text("TxtH1", "Static Text", (14, 48), "test", (80, 14), small=True))
    c.append(text("TxtH2", "Static Text", (110, 48), "verdict", (50, 14), small=True))
    c.append(text("TxtH3", "Static Text", (176, 48), "detail", (300, 14), small=True))

    rows = [("TC_RESULT_PASS", "PASS count"),
            ("TC_RESULT_FAIL", "FAIL count"),
            ("TC_LAST_PASS", "last PASS  (1 = pass)"),
            ("TC_LAST_FAIL", "last FAIL  (1 = fail)")]
    y = 66
    for var, label in rows:
        c.append(text(f"TL_{ident(var)}", "Static Text", (14, y + 3), label, (140, 15), small=True))
        c.append(led(f"LD_{ident(var)}", (160, y + 3), var, (14, 14),
                     on=(0, 190, 90), off=(200, 60, 60)))
        c.append(lcd(f"LV_{ident(var)}", (186, y), var, (70, 21), 0))
        y += 26

    c.append(Ctl("group", "GrpRun", "Group Box", (300, 60), (350, 150),
                 {"Text": "Run control"}))
    c.append(switch("SwRunScenario", (312, 76), "SCENARIO_RUNNING"))
    c.append(text("TxtRun1", "Static Text", (338, 78), "SCENARIO_RUNNING", (150, 16)))
    c.append(text("TxtRun2", "Static Text", (312, 104),
                  "SCENARIO_RUNNING=1 -> the CAPL ramp drives the car:\n"
                  "  standstill, 60, 120, back to 0   (20 s cycle)",
                  (330, 40), small=True))
    c.append(switch("SwRunDrive", (312, 148), "DRIVE_MODE"))
    c.append(text("TxtRun3", "Static Text", (338, 150),
                  "DRIVE_MODE (tester owns the bus)", (280, 16)))
    c.append(text("TxtRun4", "Static Text", (312, 176),
                  "Full report, step editing and the suite file live in the HTML tester.",
                  (330, 30), small=True))
    return render_page("Tests", c, 670, 312)


PAGE_W, PAGE_H = 660, 292


def render_page(name: str, controls: list[Ctl], tab_w: int, tab_h: int) -> str:
    body = "".join(c.render(3) for c in controls)
    return (f'    <Object Type="{PAGE_T}" Name="Page_{ident(name)}" '
            f'Children="Controls" ControlName="{escape(name)}">\n'
            f'      <Property Name="Name">Page_{ident(name)}</Property>\n'
            f'      <Property Name="Size">{PAGE_W}, {PAGE_H}</Property>\n'
            f'      <Property Name="Location">3, 22</Property>\n'
            f'      <Property Name="Text">{escape(name)}</Property>\n'
            f'{body}'
            f'    </Object>\n')


def build(data: dict) -> str:
    nodes = data["nodes"]
    by_sig = {}
    for s in data["signals"]:
        by_sig.setdefault(s["sig"], s)

    pages = [page_dashboard(nodes), page_nodes(nodes), page_monitor(nodes),
             page_tests()]
    for n in nodes:
        sigs, seen = [], set()
        for m in n.get("msgs", []):
            for full in m.get("sigs", []):
                nm = full.split(":")[-1]
                if nm in by_sig and nm not in seen:
                    seen.add(nm)
                    sigs.append(by_sig[nm])
        # A page holds 4 columns x 16 rows = 64 rows.  Cutting the list at 64
        # silently dropped 21 EMS and 42 ICN signals from the panel; the rest of
        # each node now continues on its own tab.
        per_page = 4 * 16
        for part, start in enumerate(range(0, max(len(sigs), 1), per_page)):
            pages.append(page_signals(n, sigs[start:start + per_page],
                                      part=part, total_sigs=len(sigs)))

    tab_props = "\n".join([
        f'      <Property Name="Name">TabMain</Property>',
        f'      <Property Name="Size">{PAGE_W + 6}, {PAGE_H + 28}</Property>',
        f'      <Property Name="Location">6, 6</Property>',
        f'      <Property Name="Font">{FONT}</Property>',
        f'      <Property Name="TabIndex">0</Property>',
        f'      <Property Name="FlatStyle">True</Property>',
        f'      <Property Name="ActiveBackColor">128, 255, 128</Property>',
        f'      <Property Name="InactiveBackColor">White</Property>',
        f'      <Property Name="ActiveTextColor">Black</Property>',
        f'      <Property Name="InactiveTextColor">Black</Property>',
    ])
    children = "".join(pages)
    body = (f'    <Object Type="{TAB_T}" Name="TabMain" Children="Controls" '
            f'ControlName="Tab Control">\n{tab_props}\n{children}    </Object>\n')

    return f"""<?xml version="1.0" encoding="utf-8"?>
<Panel Type="{SER}">
  <Object Type="{PANEL_T}" Name="Panel" Children="Controls" ControlName="NBCM Main">
{body}    <Property Name="Name">Panel</Property>
    <Property Name="Size">{PAGE_W + 20}, {PAGE_H + 44}</Property>
    <Property Name="BackColor">White</Property>
    <Property Name="Font">{FONT}</Property>
  </Object>
</Panel>
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="build the all-in-one CANoe panel")
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    if not args.map.exists():
        print(f"error: {args.map} not found; run tools/build_data.py first")
        return 2
    data = json.loads(args.map.read_text(encoding="utf-8"))
    xml = build(data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(xml, encoding="utf-8")

    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    controls = root.findall(".//Object")
    bindings = root.findall('.//Property[@Name="SymbolConfiguration"]')
    pages = [o for o in controls
             if "TabPage" in (o.get("Type") or "")]
    print(f"wrote {args.out.relative_to(ROOT)}")
    print(f"  pages     : {len(pages)}")
    print(f"  controls  : {len(controls)}")
    print(f"  bindings  : {len(bindings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
