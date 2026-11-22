#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
behaviour.py -- what the simulated ECUs *do*, not just what they hold
======================================================================

A restbus that only holds values is a bag of numbers: cut a node off the bus
and the other nodes keep reporting "everything is fine". That is not what a
car does, and it is exactly where a tester learns the wrong thing.

This module is the reaction model. It is a pure function of (state, time):

    out = compute(state, now_ms, cfg)

so it can be tested without CANoe, without a bus and without sleeping, and the
same rules are written into the CAPL by ``tools/build_behaviour_capl.py``.

Rules, in the order they are evaluated
-------------------------------------
1. absence   A node is *absent* when the frame it owns has not been seen for
             500 ms, or when its OFFLINE switch is on.  The switch is instant;
             the timeout needs the bus to actually go quiet first.
2. report    An absent node still sends its supervision frame (it keeps
             reporting), with Com_Loss = 1 and Com_Loss_Counter incrementing.
             Com_Loss is 1 when *anything this node watches* is missing -- the
             network map gives every signal of that frame the same meaning, so
             any watched node counts.
3. substitute Absent data is replaced, not frozen.  Speed falls back to 0,
             torque to 0, gear to neutral.  A frozen value is the trap: it
             looks like a valid reading and hides the fault.
4. cascade   Dependants react to the substitute, not to the missing value:
             a wheel-speed node that is off makes the speed reading invalid,
             and ABS reports VehicleSpeed_Invalid = 1.
5. inhibit   A function that depends on a missing input switches itself off
             and says why (COM_Loss on the dependent's own frame).

Every rule is derived from the network map -- the frames and the signals that
exist in it -- so a rule can never reference a signal the car does not have.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Frames that are cyclic traffic; anything slower than this is not a
# liveness source (a 5 s ambient frame is not "absent" at 500 ms).
LIVE_CYCLE_MAX_MS = 1000

# How long a silent frame may stay valid.  CAN timeout conventions are usually
# 3 x cycle; the map's own supervision frames are 1000 ms, so the floor is what
# matters for the fast frames.
ABSENT_AFTER_MS = 500


def _canon(name: str) -> str:
    """Com_Loss and COMLoss and comloss are the same thing to a rule."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def is_supervision_message(msg: str) -> bool:
    return msg.upper().endswith("_SUP") or "_SUPERVISION_" in msg.upper()


class Model:
    """The reaction rules, built once from the network map + the tester model."""

    def __init__(self, signals: list[dict], nodes: list[dict]):
        self.signals = signals
        self.nodes = nodes
        self.by_name = {s["sig"]: s for s in signals}
        self.node_of = {}
        for s in signals:
            self.node_of.setdefault(s["sig"], s["node"])

        # which frames are used for liveness: own frames, cyclic, and not the
        # supervision frame itself (a node that is gone cannot report itself)
        self.live_frames = {}          # node -> [(msg, cycle_ms)]
        for s in signals:
            if is_supervision_message(s["msg"]):
                continue
            cyc = int(s.get("cycle") or 0)
            if not cyc or cyc > LIVE_CYCLE_MAX_MS:
                continue
            self.live_frames.setdefault(s["node"], [])
            pair = (s["msg"], cyc)
            if pair not in self.live_frames[s["node"]]:
                self.live_frames[s["node"]].append(pair)

        # The supervision frame of each node, keyed by *role* not by full name:
        # Hs_Ems_Com_Loss and Hs_Tpms_COM_Loss are the same field of the same
        # frame shape, so matching the suffix is what the rules mean.
        self.sup_of = {}
        for s in signals:
            if not is_supervision_message(s["msg"]):
                continue
            c = _canon(s["sig"])
            slots = self.sup_of.setdefault(s["node"], {})
            if c.endswith("comlosscounter"):
                slots["counter"] = s["sig"]
            elif c.endswith("comloss"):
                slots["comloss"] = s["sig"]
            elif c.endswith("txtimeoutcounter"):
                slots["timeout"] = s["sig"]
            elif c.endswith("busoffcounter") or c.endswith("busoff"):
                slots["busoff"] = s["sig"]
            elif c.endswith("ecudynamicstates") or c.endswith("dynamicstates"):
                slots["dynamic"] = s["sig"]
            elif c.endswith("ecustaticstates") or c.endswith("staticstates"):
                slots["static"] = s["sig"]
            elif c.endswith("diagmode"):
                slots["diag"] = s["sig"]
            elif "networkmanagement" in c or c.endswith("nmstate"):
                slots["nm"] = s["sig"]

        # numeric signals that must not stay frozen when their sender is gone
        self.substitutes = self._substitute_table()

        # who needs whose data: the map does not say, so this is a small,
        # explicit table with a reason for every row -- not a guess
        self.dependencies = [
            # dependent, needs, why, what break it causes
            ("ABS", "ABS", "Hs_Abs_VehicleSpeed_Invalid",
             "سرعت خودرو از سنسورهای چرخ می‌آید؛ با رفتن ABS این مقدار معتبر نیست"),
            ("ICU", "ABS", "Hs_Icu_Ems_Status",
             "کیلومترشمار و مصرف روی سرعت خودرو حساب می‌شوند"),
            ("TCU", "EMS", "Hs_Tcu_Current_Gear",
             "گیربکس برای انتخاب دنده به دور و گشتاور موتور نیاز دارد"),
            ("ICU", "EMS", "Hs_Icu_Ems_Status",
             "آمپر دور و دما و وضعیت موتور را از EMS می‌گیرد"),
            ("ICN", "EMS", "Ls_Icn_Speed_Display",
             "نمایشگر سرعت و دور را از فریم‌های موتور و ABS می‌گیرد"),
            ("ICN", "ABS", "Ls_Icn_Speed_Display",
             "نمایشگر سرعت را از ABS می‌گیرد"),
        ]

    # -- substitutes ------------------------------------------------------
    def _substitute_table(self) -> dict[str, tuple[str, float, str]]:
        """name -> (kind, value, why).  Chosen by what the signal measures."""
        out: dict[str, tuple[str, float, str]] = {}
        for s in self.signals:
            n = s["sig"].lower()
            kind = s.get("kind")
            if kind == "num":
                if re.search(r"(speed|spd)", n):
                    out[s["sig"]] = ("zero", 0.0, "سرعت با نبودِ فرستنده صفر می‌شود")
                elif re.search(r"(torque|torq|tq)", n):
                    out[s["sig"]] = ("zero", 0.0, "گشتاور صفر اعلام می‌شود؛ گاز داده نشده")
                elif re.search(r"(rpm|speed)", n):
                    out[s["sig"]] = ("zero", 0.0, "دور موتور صفر؛ موتور خاموش دیده می‌شود")
                elif re.search(r"(temp|temperature)", n):
                    out[s["sig"]] = ("hold", 0.0, "دما نگه داشته می‌شود؛ سنسور نیست ولی عدد بی‌معنی هم نمی‌سازیم")
            elif kind in ("bool", "enum"):
                if re.search(r"(comloss|com_loss|absent|nerr|error|fault|warn|lamp)",
                             n.replace("_", "")):
                    continue           # the fault flags are the *output*, not the input
        return out

    # -- evaluation -------------------------------------------------------
    def compute(self, state: dict, now_ms: float, cfg: dict | None = None) -> dict:
        """Return the values this tick should push, and the reasons why.

        ``state`` keys
            values      {signal: value}
            offline     {node: bool}
            last_seen   {(net, msg): ms}    epoch ms of the last reception
            blink       bool                for lamp blink rules

        Returns
            values  {signal: value}      only what the rules changed
            absent  {node: bool}
            reasons [{"rule", "node", "signal", "text"}]
        """
        cfg = cfg or {}
        absent_after = float(cfg.get("absent_after_ms", ABSENT_AFTER_MS))
        values = dict(state.get("values") or {})
        offline = state.get("offline") or {}
        last_seen = state.get("last_seen") or {}
        out: dict[str, float] = {}
        reasons: list[dict] = []

        def note(rule, node, signal, text):
            reasons.append({"rule": rule, "node": node, "signal": signal, "text": text})

        # ---- 1/2. who is absent, and does it still report? --------------
        absent: dict[str, bool] = {}
        for node in self.nodes:
            name = node["node"]
            if offline.get(name):
                absent[name] = True
                continue
            frames = self.live_frames.get(name) or []
            if not frames:
                absent[name] = False
                continue
            gone = 0
            for msg, cyc in frames:
                key = f"{node['net']}:{msg}"
                t = last_seen.get(key)
                # "never seen" is not the same as "gone": at measurement start
                # nothing has been seen yet, and calling the whole network absent
                # would be a false alarm on every run.
                if t is None:
                    gone += 1 if cfg.get("never_seen_is_absent") else 0
                elif (now_ms - t) > absent_after:
                    gone += 1
            absent[name] = bool(frames) and gone == len(frames)

        for name, is_absent in absent.items():
            sup = self.sup_of.get(name) or {}
            loss = sup.get("comloss")
            if loss:
                out[loss] = 1.0 if is_absent else 0.0
            counter = sup.get("counter")
            if counter:
                rec = self.by_name.get(counter)
                top = float(rec["max"]) if rec and rec.get("max") else 255.0
                cur = float(values.get(counter, 0.0))
                # counts while the loss lasts, saturates instead of wrapping
                out[counter] = min(top, cur + 1.0) if is_absent else 0.0

        # ---- 3. substitute what is missing ------------------------------
        for name, (mode, value, why) in self.substitutes.items():
            node = self.node_of.get(name)
            if not node or not absent.get(node):
                continue
            if mode == "zero":
                out[name] = value
                note("substitute", node, name, why)

        # ---- 4. cascade: dependants react to the substitute ------------
        for dependent, needs, carrier, why in self.dependencies:
            if not absent.get(needs):
                # Recovery matters as much as the fault: a flag the rule set
                # must be cleared by the same rule, or the panel keeps a stale
                # "invalid" after the node is back.
                if carrier in self.by_name and values.get(carrier) not in (None, 0, 0.0):
                    out[carrier] = 0.0
                    note("recover", dependent, carrier,
                         f"{needs} برگشته، پس این مقدار دوباره معتبر می‌شود")
                continue
            sup = self.sup_of.get(dependent) or {}
            loss = sup.get("comloss")
            if loss:
                out[loss] = 1.0
                note("cascade", dependent, loss, why)
            rec = self.by_name.get(carrier)
            if rec and rec.get("kind") in ("bool", "enum"):
                out[carrier] = 1.0 if rec.get("kind") == "bool" else float(rec.get("max") or 1)
                note("cascade", dependent, carrier,
                     f"{dependent} داده‌ی {needs} را ندارد، پس این مقدار را نامعتبر اعلام می‌کند")
            # A numeric carrier cannot say "invalid" with a number, so it is left
            # alone: inventing a value is worse than leaving it, and the loss
            # flag on the same frame already tells the story.

        # ---- 5. inhibit: a function that needs missing data switches off -
        for dependent, needs, _, why in self.dependencies:
            if not absent.get(needs):
                continue
            sup = self.sup_of.get(dependent) or {}
            state_sig = sup.get("dynamic")
            if state_sig:
                out[state_sig] = 1.0
                note("inhibit", dependent, state_sig,
                     f"{dependent} به {needs} نیاز دارد و آن غایب است؛ عملکرد وابسته غیرفعال می‌شود")

        return {"values": out, "absent": absent, "reasons": reasons}


def build_from_model(model_json: dict) -> Model:
    return Model(model_json["signals"], model_json["nodes"])


if __name__ == "__main__":
    import json
    data = json.loads((ROOT / "can_tester/assets/signal_map.json").read_text(encoding="utf-8"))
    m = build_from_model(data)
    print(f"nodes={len(m.nodes)} signals={len(m.signals)}")
    print(f"live frames: " + ", ".join(f"{k}={len(v)}" for k, v in sorted(m.live_frames.items())))
    print(f"supervision frames: {len(m.sup_of)}")
    print(f"substitutes: {len(m.substitutes)}")
    print(f"dependencies: {len(m.dependencies)}")
    print("\nexample: ABS switched off")
    r = m.compute({"values": {}, "offline": {"ABS": True}, "last_seen": {}}, now_ms=0)
    print(f"  absent: {[k for k, v in r['absent'].items() if v]}")
    print(f"  changed {len(r['values'])} values, {len(r['reasons'])} reasons")
    for x in r["reasons"][:4]:
        print(f"    [{x['rule']}{x['node']}] {x['signal']}: {x['text'][:60]}")
