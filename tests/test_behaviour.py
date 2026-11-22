#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_behaviour.py -- do the simulated ECUs actually react?

These are the rules, not the plumbing: switch a node off and the rest of the
network must *know*, with the right signals and for the right reason.  Every
case is a pure call, so nothing sleeps and nothing needs CANoe.

Run:  python3 tests/test_behaviour.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import behaviour                                                    # noqa: E402

FAILS: list[str] = []


def ok(cond, msg):
    if not cond:
        FAILS.append(msg)


def main() -> int:
    data = json.loads((ROOT / "can_tester/assets/signal_map.json").read_text(encoding="utf-8"))
    m = behaviour.build_from_model(data)

    # ---- 1. a quiet network must not be declared dead --------------------
    alive = m.compute({"values": {}, "offline": {}, "last_seen": {}}, now_ms=0)
    ok(not any(alive["absent"].values()),
       "at measurement start nothing may be reported absent: "
       + str([k for k, v in alive["absent"].items() if v]))
    ok(alive["values"] == {} or all(v == 0 for v in alive["values"].values()),
       "nothing was missing, so no value may be forced")

    # ---- 2. the switch is instant, and only affects that node -----------
    r = m.compute({"values": {}, "offline": {"EMS": True}, "last_seen": {}}, now_ms=0)
    ok(r["absent"].get("EMS") is True, "OFFLINE_EMS must make EMS absent at once")
    others = [k for k, v in r["absent"].items() if v and k != "EMS"]
    ok(not others, "switching EMS off must not mark other nodes absent: " + str(others))

    # ---- 3. the absent node keeps reporting, and says so ----------------
    ok(r["values"].get("Hs_Ems_Com_Loss") == 1.0,
       "an absent EMS must publish Com_Loss = 1")
    ok(r["values"].get("Hs_Ems_Com_Loss_Counter", 0) >= 1,
       "the loss counter must start counting")
    ok("Hs_Ems_Com_Loss" not in m.substitutes,
       "Com_Loss is the report, not a substitute: it must not be overwritten")

    # ---- 4. the counter saturates instead of wrapping -------------------
    vals = {"Hs_Ems_Com_Loss_Counter": 255.0}
    r2 = m.compute({"values": vals, "offline": {"EMS": True}, "last_seen": {}}, now_ms=0)
    ok(r2["values"]["Hs_Ems_Com_Loss_Counter"] == 255.0,
       "a saturated counter must stay at its maximum, not wrap to 0")

    # ---- 5. and the counter clears when the node comes back -------------
    r3 = m.compute({"values": {"Hs_Ems_Com_Loss_Counter": 12.0},
                    "offline": {}, "last_seen": {}}, now_ms=0)
    ok(r3["values"]["Hs_Ems_Com_Loss_Counter"] == 0.0,
       "the counter must clear when the node is back")

    # ---- 6. a timeout needs the bus to go quiet, the switch does not ----
    seen = {f"{n['net']}:{msg}": 1000.0 for n in data["nodes"]
            for msg, _ in m.live_frames.get(n["node"], [])}
    fresh = m.compute({"values": {}, "offline": {}, "last_seen": seen}, now_ms=1200)
    ok(not any(fresh["absent"].values()), "frames seen 200 ms ago are not absent")
    stale = m.compute({"values": {}, "offline": {}, "last_seen": seen}, now_ms=2000)
    ok(all(stale["absent"][n["node"]] for n in data["nodes"] if m.live_frames.get(n["node"])),
       "frames older than 500 ms must be absent: "
       + str([k for k, v in stale["absent"].items() if not v and m.live_frames.get(k)]))

    # ---- 7. a slow frame is not a liveness source ----------------------
    slow = [s for s in m.signals if int(s.get("cycle") or 0) > behaviour.LIVE_CYCLE_MAX_MS]
    ok(bool(slow), "the model is expected to contain slow frames (e.g. 5000 ms ambient)")
    for s in slow:
        frames = [f for f, _ in m.live_frames.get(s["node"], [])]
        ok(s["msg"] not in frames or any(
            int(x.get("cycle") or 0) <= behaviour.LIVE_CYCLE_MAX_MS
            for x in m.signals if x["msg"] == s["msg"]),
           f"a {s['cycle']} ms frame must not be used as a 500 ms liveness source")

    # ---- 8. absent data is replaced, never frozen ----------------------
    r4 = m.compute({"values": {"Hs_Abs_Wheel_Speed_Fl": 80.0},
                    "offline": {"ABS": True}, "last_seen": {}}, now_ms=0)
    ok(r4["values"].get("Hs_Abs_Wheel_Speed_Fl") == 0.0,
       "a frozen 80 km/h wheel speed is the trap: it must fall to 0")

    # ---- 9. the cascade reaches the dependants -------------------------
    r5 = m.compute({"values": {}, "offline": {"ABS": True}, "last_seen": {}}, now_ms=0)
    ok(r5["values"].get("Hs_Abs_VehicleSpeed_Invalid") == 1.0,
       "with ABS gone the vehicle speed must be flagged invalid")
    ok(r5["values"].get("Hs_Icu_Com_Loss") == 1.0,
       "ICU needs ABS, so ICU must report the loss too")
    rules = {x["rule"] for x in r5["reasons"]}
    ok({"substitute", "cascade"} <= rules,
       "the reasons must say which rule fired, got " + str(rules))

    # ---- 10. every reason names a real signal --------------------------
    known = {s["sig"] for s in m.signals}
    for case in (r, r4, r5):
        for x in case["reasons"]:
            ok(not x["signal"] or x["signal"] in known,
               f"reason references an unknown signal: {x['signal']}")
            ok(x["text"].strip() != "", "every reason needs a human sentence")

    # ---- 10b. recovery clears what the fault set ----------------------
    # the live sim showed VehicleSpeed_Invalid stuck at 1 after ABS came back
    back = m.compute({"values": {"Hs_Abs_VehicleSpeed_Invalid": 1.0,
                                 "Hs_Abs_Com_Loss": 1.0,
                                 "Hs_Abs_Com_Loss_Counter": 7.0},
                      "offline": {}, "last_seen": {}}, now_ms=0)
    ok(back["values"].get("Hs_Abs_VehicleSpeed_Invalid") == 0.0,
       "a cascade flag must clear when the node returns")
    ok(back["values"].get("Hs_Abs_Com_Loss") == 0.0,
       "Com_Loss must clear when the node returns")
    ok(back["values"].get("Hs_Abs_Com_Loss_Counter") == 0.0,
       "the loss counter must reset when the node returns")

    # ---- 11. silence from a node with no supervision frame is harmless --
    no_sup = [n["node"] for n in data["nodes"] if n["node"] not in m.sup_of]
    ok(no_sup, "expected at least one node without a supervision frame")
    r6 = m.compute({"values": {}, "offline": {n: True for n in no_sup},
                    "last_seen": {}}, now_ms=0)
    invented = [x["signal"] for x in r6["reasons"]
                if x["signal"] and x["signal"] not in
                {s2["sig"] for s2 in m.signals}]
    ok(not invented, "a node without a supervision frame must not invent one: "
       + str(invented))
    for n in no_sup:
        sup_names = set(m.sup_of.get(n, {}).values())
        ok(not sup_names, f"{n} has no supervision frame, so it has no SUP fields")

    # ---- 12. the three runtimes must agree -----------------------------
    # behaviour.py (reference) / js/react.js (browser) / the generated CAPL all
    # encode the same five rules.  If they drift, the bench and the browser
    # teach different things -- so the rule *tables* are compared here, and the
    # browser result is compared in tests/react_ui_test.js.
    js = (ROOT / "can_tester/js/react.js").read_text(encoding="utf-8")
    py_deps = {(d[0], d[1], d[2]) for d in m.dependencies}
    js_deps = set()
    import re as _re
    for dm in _re.finditer(r"\['(\w+)', '(\w+)', '([\w]+)'", js):
        js_deps.add(tuple(dm.groups()))
    ok(py_deps == js_deps,
       f"the browser and the Python rules disagree: py-only={py_deps-js_deps} js-only={js_deps-py_deps}")

    js_absent = _re.search(r"ABSENT_AFTER_MS\s*=\s*(\d+)", js)
    ok(js_absent and int(js_absent.group(1)) == behaviour.ABSENT_AFTER_MS,
       f"the absence timeout differs: python={behaviour.ABSENT_AFTER_MS} js={js_absent and js_absent.group(1)}")

    capl = (ROOT / "canoe/NBCM_Behaviour.can").read_text(encoding="utf-8")
    cap1 = _re.search(r"BEHAVIOUR_ABSENT_MS = (\d+)", capl)
    ok(cap1 and int(cap1.group(1)) == behaviour.ABSENT_AFTER_MS,
       f"the CAPL absence timeout differs: {cap1 and cap1.group(1)}")
    ok(all((sup.get("comloss") or "") in capl
           for sup in (m.sup_of.get(n["node"]) or {} for n in data["nodes"]) if sup),
       "every supervision frame in the model must be handled by the CAPL")

    for f in FAILS:
        print("FAIL " + f)
    if FAILS:
        print(f"\nFAIL -- {len(FAILS)} problem(s)")
        return 1
    print("PASS -- the simulated ECUs react, time out and substitute correctly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
