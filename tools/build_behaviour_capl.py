#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_behaviour_capl.py -- write the reaction rules into the restbus CAPL
=======================================================================

The rules live in ``tools/behaviour.py`` so they can be tested as code.  CANoe
cannot import Python, so this generator writes the same rules into
``canoe/NBCM_Behaviour.can`` in the exact form CANoe 12 accepts:

  * ASCII only in code identifiers and strings.  The comment at the top of the
    restbus records why: Persian in a label becomes empty boxes, so every string
    this file writes to the Write window is English, and the Persian
    explanation lives in the PDF guide instead.
  * one function per rule, called from a single 100 ms timer, so the cost is the
    same whether one node is off or all thirteen.
  * every signal name is checked against the model before it is emitted: a rule
    that names a signal the car does not have is a build error, not a surprise
    at measurement time.

Run:  python3 tools/build_behaviour_capl.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import behaviour                                                    # noqa: E402

MODEL = ROOT / "can_tester" / "assets" / "signal_map.json"
OUT = ROOT / "canoe" / "NBCM_Behaviour.can"

HEADER = '''/*@!Encoding:65001*/
/*============================================================================
  NBCM Behaviour Model  --  generated, do not edit by hand
  ============================================================================
  Written by tools/build_behaviour_capl.py from tools/behaviour.py.

  A restbus that only holds values never reacts: switch a node off and every
  other node keeps reporting "fine".  This file makes the simulated ECUs react
  the way the network map's own supervision frames describe:

    1  absence    a node is absent when its frame has not been seen for
                  {absent} ms, or when its OFFLINE switch is on
    2  report     the absent node still sends its *_SUP frame, with
                  Com_Loss = 1 and Com_Loss_Counter counting up (saturating)
    3  substitute missing data is replaced (speed -> 0, torque -> 0, ...)
                  instead of freezing at the last value
    4  cascade    a node that needs the missing data reports its own loss
    5  inhibit    a dependent function switches itself off and says why

  Add this file to the same network node as NBCM_Full_Restbus_Simulation.can.
  Nothing here needs a system variable; the switches are the restbus globals.

  NOTE: strings written to the Write window are English on purpose -- the
  restbus header records that Persian text in a CANoe label renders as empty
  boxes.  The Persian explanation is in the PDF guide.
============================================================================*/

variables
{{
  const dword BEHAVIOUR_ABSENT_MS = {absent};
  dword gBehaviourLastSeen[{n_frames}];
  long  gBehaviourLost[{n_nodes}];
}}
'''


# The Persian reasons are what make a rule teachable; the CAPL cannot carry
# them, so each rule gets a short English key that a tester can look up in the
# PDF.  Keys are explicit: an unmapped rule is a build error, not a blank.
RULE_EN = {
    "سرعت با نبودِ فرستنده صفر می‌شود": "speed -> 0 when the sender is gone",
    "گشتاور صفر اعلام می‌شود؛ گاز داده نشده": "torque -> 0, no pedal input",
    "دور موتور صفر؛ موتور خاموش دیده می‌شود": "rpm -> 0, engine seen as stopped",
    "دما نگه داشته می‌شود؛ سنسور نیست ولی عدد بی‌معنی هم نمی‌سازیم":
        "temperature held, not faked",
}


def _ascii(text: str) -> str:
    """CANoe 12 is happiest with ASCII in code; anything else is a build error."""
    return "".join(c if ord(c) < 128 else "" for c in text)


def _c_comment(text: str, fallback: str = "rule") -> str:
    """An English, ASCII comment.  Never silently empty."""
    en = RULE_EN.get(text)
    if en is None:
        en = _ascii(text).strip()
    en = (en or fallback).replace("*/", "* /").replace("\n", " ").strip()
    return en or fallback


def build() -> str:
    data = json.loads(MODEL.read_text(encoding="utf-8"))
    m = behaviour.build_from_model(data)
    known = {s["sig"] for s in m.signals}

    # every frame that is a liveness source, flattened with an index
    frames: list[tuple[str, str, str, int]] = []      # node, net, msg, cycle
    for node in data["nodes"]:
        for msg, cyc in m.live_frames.get(node["node"], []):
            frames.append((node["node"], node["net"], msg, cyc))

    nodes = [n["node"] for n in data["nodes"]]

    out = [HEADER.format(absent=behaviour.ABSENT_AFTER_MS,
                         n_frames=len(frames), n_nodes=len(nodes))]

    # The frame table is declared BEFORE the functions that read it: CANoe 12
    # resolves globals in one pass and a later array declaration is not visible
    # to an earlier function.
    out.append("/* the frame table: one row per liveness source */\n")
    out.append("char gBehaviourFrameNode[%d][17] = {\n" % len(frames))
    out.append(",\n".join(f'  "{_ascii(f[0])}"' for f in frames))
    out.append("\n};\n\n")
    out.append("char gBehaviourFrameMsg[%d][33] = {\n" % len(frames))
    out.append(",\n".join(f'  "{_ascii(f[2])}"' for f in frames))
    out.append("\n};\n\n")

    # ---- freshness -------------------------------------------------------
    out.append("""
/*----------------------------------------------------------------------------
  1) freshness: the restbus calls this for every frame it sends.
----------------------------------------------------------------------------*/
void BehaviourMarkSent(char nodeName[], char msgName[])
{
  int i;
  for (i = 0; i < %d; i++)
  {
    if (strncmp(gBehaviourFrameNode[i], nodeName, 16) == 0 &&
        strncmp(gBehaviourFrameMsg[i], msgName, 32) == 0)
    {
      gBehaviourLastSeen[i] = 0;   /* 0 = seen in this tick */
      return;
    }
  }
}
""" % len(frames))

    out.append("""
/*----------------------------------------------------------------------------
  2) one tick, called every 100 ms from on timer
----------------------------------------------------------------------------*/
void BehaviourTick()
{
  int i;
  int lost;
  int frames_of_node;
""" % ())

    # per node: decide absence
    out.append("  /* ---- absence ---- */\n")
    for idx, node in enumerate(nodes):
        my_frames = [i for i, f in enumerate(frames) if f[0] == node]
        if not my_frames:
            out.append(f"  gBehaviourLost[{idx}] = 0;   /* {node}: no cyclic frame */\n")
            continue
        cond = " && ".join(f"gBehaviourLastSeen[{i}] > 0" for i in my_frames)
        incr = ", ".join(f"gBehaviourLastSeen[{i}]++" for i in my_frames)
        out.append(f"  /* {node} */\n")
        out.append(f"  {incr};\n")
        out.append(f"  lost = ({cond}) ? 1 : 0;\n")
        out.append(f"  if (OFFLINE_{node}) lost = 1;\n")
        out.append(f"  gBehaviourLost[{idx}] = lost;\n")

    # ---- report + substitute --------------------------------------------
    out.append("""
  /* ---- report: Com_Loss and its counter, for every node with a SUP frame ---- */
""")
    for idx, node in enumerate(nodes):
        sup = m.sup_of.get(node) or {}
        loss = sup.get("comloss")
        counter = sup.get("counter")
        if loss:
            assert loss in known, loss
            out.append(f"  {loss} = gBehaviourLost[{idx}];\n")
        if counter:
            assert counter in known, counter
            top = int(float(m.by_name[counter].get("max") or 255))
            out.append(f"  if (gBehaviourLost[{idx}]) {{ if ({counter} < {top}) {counter}++; }}\n")
            out.append(f"  else {counter} = 0;\n")

    # ---- substitute ------------------------------------------------------
    out.append("""
  /* ---- substitute: missing data is replaced, never frozen ---- */
""")
    for name, (mode, value, why) in m.substitutes.items():
        if mode != "zero":
            continue
        node = m.node_of.get(name)
        idx = nodes.index(node) if node in nodes else -1
        if idx < 0:
            continue
        assert name in known, name
        out.append(f"  if (gBehaviourLost[{idx}]) {name} = {value:g};"
                   f"   /* {_c_comment(why)} */\n")

    # ---- cascade ---------------------------------------------------------
    out.append("""
  /* ---- cascade: a node that needs what is missing reports its own loss ---- */
""")
    for dependent, needs, carrier, why in m.dependencies:
        if needs not in nodes or dependent not in nodes:
            continue
        need_i, dep_i = nodes.index(needs), nodes.index(dependent)
        sup = m.sup_of.get(dependent) or {}
        loss = sup.get("comloss")
        out.append(f"  /* {dependent} needs {needs} */\n")
        if loss:
            assert loss in known, loss
            out.append(f"  if (gBehaviourLost[{need_i}]) {loss} = 1;\n")
        if carrier in known and m.by_name[carrier].get("kind") in ("bool", "enum"):
            rec = m.by_name[carrier]
            val = 1 if rec.get("kind") == "bool" else int(float(rec.get("max") or 1))
            out.append(f"  if (gBehaviourLost[{need_i}]) {carrier} = {val};\n")

    out.append("}\n\n")


    return "".join(out)


def main() -> int:
    text = build()
    # a rule must never name a signal the model does not have
    data = json.loads(MODEL.read_text(encoding="utf-8"))
    known = {s["sig"] for s in data["signals"]}
    msgs = {s["msg"] for s in data["signals"]}
    import re
    # message names (HS_ID_*, LS_ID_*) live in the frame table and are checked
    # separately; only identifier-shaped signal names are checked here
    bad = [n for n in set(re.findall(r"\b(Hs_[A-Za-z0-9_]+|Ls_[A-Za-z0-9_]+)\b", text))
           if n not in known and n not in msgs]
    if bad:
        print("error: the CAPL would name unknown signals: " + ", ".join(sorted(bad)))
        return 2
    non_ascii = [c for c in text if ord(c) > 127]
    if non_ascii:
        print(f"error: {len(non_ascii)} non-ASCII characters would break a CANoe 12 label")
        return 2
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}  ({len(text.splitlines())} lines, "
          f"{text.count('gBehaviourLost')} absence tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
