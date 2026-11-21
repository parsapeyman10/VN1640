#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_data.py  --  NBCM CAN Tester data generator
=================================================
The binding reference workbook (NBCM_Panel_Binding_Reference.xlsx) is the single
source of truth.  This script converts it into:

  can_tester/assets/data.js          (loaded directly by index.html, no build step)
  can_tester/assets/signal_map.json  (machine readable map used by the bridge/CI)

Run:
    python tools/build_data.py
    python tools/build_data.py --xlsx other.xlsx --out can_tester/assets

No third-party packages required (reads the xlsx with zipfile + ElementTree).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX = ROOT / "NBCM_Panel_Binding_Reference.xlsx"
DEFAULT_OUT = ROOT / "can_tester" / "assets"
DEFAULT_NETMAP = (ROOT / "NBCM_CAN_Simulation_Package" / "1_Final"
                  / "NBCM_Dena_CAN_Network_Map.xlsx")

# Column order of "Signals" sheet (sheet2), see NBCM_Panel_Binding_Reference.xlsx
COLS = [
    "node", "network", "message", "cycle_ms", "signal",
    "default", "unit", "min", "max", "control", "offline_switch",
]


# --------------------------------------------------------------------------- #
# xlsx reading
# --------------------------------------------------------------------------- #
def _col_idx(ref: str) -> int:
    letters = re.match(r"([A-Z]+)", ref).group(1)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_sheet(zf: zipfile.ZipFile, path: str) -> list[list[str]]:
    """Read one worksheet as a list of rows (list of cell strings)."""
    shared: list[str] = []
    try:
        sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in sroot.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(
                "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
    except KeyError:
        pass

    root = ET.fromstring(zf.read(path))
    rows: list[list[str]] = []
    for r in root.findall(".//m:row", NS):
        cells: dict[int, str] = {}
        for c in r.findall("m:c", NS):
            t = c.get("t")
            if t == "s":
                v = c.find("m:v", NS)
                val = shared[int(v.text)] if v is not None and v.text else ""
            elif t == "inlineStr":
                n = c.find("m:is/m:t", NS)
                val = n.text if n is not None and n.text else ""
            else:
                v = c.find("m:v", NS)
                val = v.text if v is not None and v.text else ""
            cells[_col_idx(c.get("r", "A1"))] = val.strip()
        width = (max(cells) + 1) if cells else 0
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


def to_num(txt: str, default=0.0) -> float:
    try:
        return float(str(txt).replace(",", "."))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# model building
# --------------------------------------------------------------------------- #
def control_kind(control: str, mn: float, mx: float) -> str:
    """Map the spreadsheet's suggestion to a UI control type."""
    c = (control or "").lower()
    if "dropdown" in c or "enum" in c:
        return "enum"
    if mn == 0 and mx == 1:
        return "bool"
    if "switch" in c or "led" in c:
        return "bool" if mx <= 1 else "num"
    if "slider" in c or "numeric" in c:
        return "num"
    if mx > 255 and mn == 0:
        return "num"
    return "num"


def parse_cycle(txt: str, event_default: int = 1000) -> int:
    m = re.search(r"-?\d+", txt or "")
    if txt and re.search(r"event", txt, re.I):
        return event_default          # event based -> tester polls at 1 s
    return int(m.group()) if m else event_default


def _merge_map_only(netmap_path, rows_seen, messages, nodes):
    """Add signals that the network map has and the binding workbook does not.

    Only messages in the restbus scope are added: NBCM's own output is
    deliberately not simulated.  Everything a panel needs comes from the map
    itself -- message, cycle, bit layout, the owning node, a control kind.
    """
    if not netmap_path or not Path(netmap_path).exists():
        return []
    try:
        import build_package
        nm = build_package.load_netmap(Path(netmap_path))
    except Exception:                                             # noqa: BLE001
        return []

    senders = {(m["Network"], m["MessageName"]): m["Sender"] for m in nm["messages"]}
    cycles = {(m["Network"], m["MessageName"]): m["CycleTime_ms"] for m in nm["messages"]}
    have = {x["sig"] for x in rows_seen}
    added = []

    for x in nm["signals"]:
        name = x["SignalName"]
        if name in have:
            continue
        msg_sender = (senders.get((x["Network"], x["MessageName"])) or "").strip()
        if msg_sender.upper() == "NBCM":
            continue
        node = (msg_sender.split(",")[0].strip().upper() if msg_sender else "")
        if not node:
            # No sender in the map.  The *message* name is the reliable clue
            # (LS_ID_TARA_PEPS_1 -> PEPS); the signal name is not (Ls_Door_Lock_PKE
            # belongs to PEPS, not to a "DOOR" node that does not exist).
            mm = re.search(r"(?:^|_)(PEPS|ICN|ICU|EMS|ABS|TCU|EPS|HVAC|MMS|RBG|TPMS|ITPMS|DIAG|ESC)(?:_|$)",
                           x["MessageName"].upper())
            if not mm:
                m = re.match(r"(?:Ls|Hs)_([A-Za-z]{2,5})_", name)
                mm = m
            node = mm.group(1).upper() if mm else "NBCM"
        bits = int(x["Length_bit"] or 1)
        signed = x["Signed"].strip() in ("1", "true", "True")
        hi = (2 ** (bits - 1) - 1) if signed else (2 ** bits - 1)
        # a 1-bit signal is a switch; anything wider is a number or a code
        control = ("Switch / LED" if bits == 1
                   else "Dropdown (Enum)" if bits <= 4 else "Numeric Edit / Slider")
        try:
            cycle_i = int(float(cycles.get((x["Network"], x["MessageName"])) or 0))
        except (TypeError, ValueError):
            cycle_i = 0
        sig = {
            "id": f"{node}:{x['MessageName']}:{name}",
            "node": node, "net": x["Network"], "msg": x["MessageName"], "sig": name,
            "cycle": cycle_i, "def": 0.0, "unit": x["Unit"] or "",
            "min": float(-(2 ** (bits - 1)) if signed else 0), "max": float(hi),
            "kind": control_kind(control, 0.0, float(hi)),
            "hint": control, "offline": "OFFLINE_" + node,
            "added_from_map": True,
        }
        rows_seen.append(sig)
        added.append(sig)
        if node not in nodes:
            nodes[node] = {"node": node, "net": x["Network"],
                           "offline": sig["offline"], "msgs": OrderedDict(),
                           "n_sig": 0, "from_map": True}
        n = nodes[node]
        n["n_sig"] += 1
        n["msgs"].setdefault(x["MessageName"],
                             {"msg": x["MessageName"], "cycle": cycle_i, "sigs": []})
        n["msgs"][x["MessageName"]]["sigs"].append(sig["id"])
        messages.setdefault((x["Network"], x["MessageName"]),
                            {"msg": x["MessageName"], "net": x["Network"],
                             "cycle": cycle_i, "node": node, "n_sig": 0})
        messages[(x["Network"], x["MessageName"])]["n_sig"] += 1

    return added
def build(xlsx: Path, netmap_path: Path | None = None) -> dict:
    with zipfile.ZipFile(xlsx) as zf:
        names = zf.namelist()
        sheet_paths = sorted(p for p in names if re.match(r"xl/worksheets/sheet\d+\.xml$", p))
        summary_rows = read_sheet(zf, sheet_paths[0])
        signal_rows = read_sheet(zf, sheet_paths[1])

    # --- locate the header row (first row containing 'SignalName_CAPLVariable'-ish)
    header_i = 0
    for i, row in enumerate(signal_rows[:10]):
        joined = " ".join(row).lower()
        if "signal" in joined and "node" in joined:
            header_i = i
            break
    body = signal_rows[header_i + 1:]

    nodes: "OrderedDict[str, dict]" = OrderedDict()
    messages: "OrderedDict[tuple, dict]" = OrderedDict()
    signals: list[dict] = []

    for row in body:
        row = (row + [""] * len(COLS))[: len(COLS)]
        rec = dict(zip(COLS, row))
        node, net, msg, sig = (rec["node"].upper(), rec["network"].upper(),
                               rec["message"], rec["signal"])
        if not node or not sig:
            continue
        mn, mx = to_num(rec["min"]), to_num(rec["max"], 1.0)
        cycle = parse_cycle(rec["cycle_ms"])
        kind = control_kind(rec["control"], mn, mx)

        sig_id = f"{node}:{msg}:{sig}"
        signal = {
            "id": sig_id,
            "node": node,
            "net": net,
            "msg": msg,
            "sig": sig,
            "cycle": cycle,
            "def": to_num(rec["default"]),
            "unit": rec["unit"],
            "min": mn,
            "max": mx,
            "kind": kind,
            "hint": rec["control"],
            "offline": rec["offline_switch"] or f"OFFLINE_{node}",
        }
        signals.append(signal)

        if node not in nodes:
            nodes[node] = {"node": node, "net": net, "offline": signal["offline"],
                           "msgs": OrderedDict(), "n_sig": 0}
        n = nodes[node]
        n["n_sig"] += 1
        n["msgs"].setdefault(msg, {"msg": msg, "cycle": cycle, "sigs": []})
        n["msgs"][msg]["sigs"].append(sig_id)
        messages.setdefault((net, msg), {"msg": msg, "net": net, "cycle": cycle,
                                         "node": node, "n_sig": 0})
        messages[(net, msg)]["n_sig"] += 1

    # --- signals the binding workbook does not list -------------------------
    # The binding workbook is written for the panels, and it leaves out one
    # message the network map defines: LS_ID_TARA_PEPS_1 (0x138, 12 signals,
    # no sender in the map).  Leaving it out means the frame is on the bus but
    # no panel, no HTML row and no explanation knows about it.  It is added here
    # from the network map itself, so the model covers the restbus scope
    # without editing a workbook that is not ours to edit.
    added = _merge_map_only(netmap_path, rows_seen=signals, messages=messages, nodes=nodes)
    if added:
        print(f"  added {len(added)} signals from the network map "
              f"({', '.join(sorted({s['msg'] for s in added}))})")

    # --- cross-check against the summary sheet when present.
    # The sheet starts with a merged title row, so locate the header by name
    # instead of assuming a fixed offset.
    header_i = None
    for i, row in enumerate(summary_rows[:8]):
        if row and row[0].strip().lower() in ("node", "گره"):
            header_i = i
            break
    summary: list[dict] = []
    valid_nodes = set()
    for row in summary_rows[(header_i + 1) if header_i is not None else 0:]:
        row = (row + [""] * 5)[:5]
        node = row[0].strip()
        # node names are short alphanumerics; skip free text from a title row
        if not node or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,15}", node):
            continue
        if not row[1].strip():          # a node row always names its network
            continue
        valid_nodes.add(node.upper())
        summary.append({
            "node": node.upper(), "net": row[1].upper(),
            "msgs": int(to_num(row[2])), "sigs": int(to_num(row[3])),
            "offline": row[4] or f"OFFLINE_{node.upper()}",
        })

    warnings = []
    missing_from_summary = sorted(set(nodes) - valid_nodes)
    if missing_from_summary and valid_nodes:
        warnings.append("summary sheet omits: " + ", ".join(missing_from_summary))
    for s in summary:
        actual = nodes.get(s["node"])
        if not actual:
            warnings.append(f"node {s['node']} listed in summary but has no signals")
            continue
        if actual["n_sig"] != s["sigs"]:
            warnings.append(f"{s['node']}: summary says {s['sigs']} signals, "
                            f"detail has {actual['n_sig']}")
        if len(actual["msgs"]) != s["msgs"]:
            warnings.append(f"{s['node']}: summary says {s['msgs']} messages, "
                            f"detail has {len(actual['msgs'])}")

    out_nodes = []
    for n in nodes.values():
        out_nodes.append({
            "node": n["node"], "net": n["net"], "offline": n["offline"],
            "nSig": n["n_sig"], "nMsg": len(n["msgs"]),
            "msgs": [{"msg": m["msg"], "cycle": m["cycle"], "sigs": m["sigs"]}
                     for m in n["msgs"].values()],
        })

    return {
        "meta": {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": xlsx.name,
            "nodes": len(out_nodes),
            "messages": len(messages),
            "signals": len(signals),
            "warnings": warnings,
        },
        "nodes": out_nodes,
        "signals": signals,
        "messages": list(messages.values()),
        "summary": summary,
    }


# --------------------------------------------------------------------------- #
# writers
# --------------------------------------------------------------------------- #
def write_outputs(model: dict, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(model, ensure_ascii=False, separators=(",", ":"))
    (outdir / "data.js").write_text(
        "/* AUTO-GENERATED by tools/build_data.py - do not edit by hand.\n"
        f"   source: {model['meta']['source']}   generated: {model['meta']['generated']} */\n"
        f"window.NBCM_DATA = {payload};\n",
        encoding="utf-8",
    )
    (outdir / "signal_map.json").write_text(
        json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")

    # The explanations behind the (i) button and the CANoe tooltips are derived
    # from the signal map, so they are rebuilt here: one command keeps the model
    # and the text that describes it in step.
    try:
        import signal_glossary
        signal_glossary.write_outputs()
    except Exception as e:                                        # noqa: BLE001
        print(f"  warning: could not write descriptions: {e}", file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--netmap", type=Path, default=DEFAULT_NETMAP,
                    help="official network map; signals it has and the workbook "
                         "does not are added to the model")
    args = ap.parse_args(argv)

    if not args.xlsx.exists():
        print(f"error: workbook not found: {args.xlsx}", file=sys.stderr)
        return 2

    model = build(args.xlsx, netmap_path=args.netmap)
    write_outputs(model, args.out)
    meta = model["meta"]
    print(f"nodes={meta['nodes']}  messages={meta['messages']}  signals={meta['signals']}")
    for w in meta["warnings"]:
        print(f"  warning: {w}")
    print(f"wrote {args.out / 'data.js'} and {args.out / 'signal_map.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
