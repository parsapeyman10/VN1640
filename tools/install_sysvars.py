#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install_sysvars.py -- create NBCM_Test::* system variables through CANoe COM
============================================================================
Manual path (preferred, works in every CANoe 12 build):
    Environment -> System Variables -> Import -> canoe/NBCM_Test.vsysvar

This script is the fallback for when that dialog fights you: it creates the
same 499 variables one by one through the COM API, inside the currently open
configuration, and saves it.  Run it on the Windows PC with CANoe open.

    python tools/install_sysvars.py --dry-run
    python tools/install_sysvars.py
    python tools/install_sysvars.py --save       # also save the configuration

Notes
-----
* Only run this when the configuration does NOT already contain NBCM_Test;
  existing variables are detected and skipped, so re-running is safe.
* Float variables get min/max from the workbook, which is what makes the
  numeric controls in the panels show a sensible range.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VSYSVAR = ROOT / "canoe" / "NBCM_Test.vsysvar"
DEFAULT_NS = "NBCM_Test"


def parse_vsysvar(path: Path) -> tuple[str, list[dict]]:
    root = ET.parse(path).getroot()
    # structure: systemvariables/namespace[name=""]/namespace[name="NBCM_Test"]
    inner = None
    for ns in root.findall("namespace"):
        for sub in ns.findall("namespace"):
            if sub.get("name") == DEFAULT_NS:
                inner = sub
                break
        if inner is None and ns.get("name") == DEFAULT_NS:
            inner = ns
        if inner is not None:
            break
    if inner is None:
        raise SystemExit(f"error: namespace {DEFAULT_NS} not found in {path}")

    out = []
    seen: set[str] = set()
    for v in inner.findall("variable"):
        name = v.get("name")
        if name in seen:            # CANoe rejects duplicate names; skip rather
            continue                # than fail halfway through an import
        seen.add(name)
        out.append({
            "name": name,
            "type": v.get("type") or "int",
            "start": v.get("startValue") or "0",
            "min": v.get("minValue"),
            "max": v.get("maxValue"),
            "unit": v.get("unit") or "",
            "comment": v.get("comment") or "",
        })
    return DEFAULT_NS, out


def connect_canoe():
    if platform.system() != "Windows":
        raise SystemExit("error: this script talks to CANoe over COM and only runs on Windows")
    try:
        import win32com.client as win32
    except ImportError:
        raise SystemExit("error: pywin32 is missing.  pip install pywin32")
    try:
        return win32.GetActiveObject("CANoe.Application"), win32
    except Exception:                                            # noqa: BLE001
        raise SystemExit("error: no running CANoe instance. Start CANoe and open your "
                         "configuration first (this script must not create a new one).")


def get_or_create_namespace(app, name: str):
    namespaces = app.System.Namespaces
    try:
        return namespaces(name), False
    except Exception:                                            # noqa: BLE001
        return namespaces.Add(name), True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="install NBCM_Test system variables via COM")
    ap.add_argument("--vsysvar", type=Path, default=VSYSVAR)
    ap.add_argument("--dry-run", action="store_true", help="only report what would happen")
    ap.add_argument("--save", action="store_true", help="save the CANoe configuration afterwards")
    args = ap.parse_args(argv)

    if not args.vsysvar.exists():
        print(f"error: {args.vsysvar} not found. Run tools/build_capl.py first.", file=sys.stderr)
        return 2

    ns_name, variables = parse_vsysvar(args.vsysvar)
    print(f"namespace : {ns_name}")
    print(f"variables : {len(variables)}")

    if args.dry_run:
        for v in variables[:8]:
            print(f"  {v['type']:<6} {v['name']:<38} start={v['start']}")
        print("  ...")
        print("dry run: nothing was sent to CANoe")
        return 0

    app, _ = connect_canoe()
    try:
        running = app.Measurement.Running
    except Exception:                                            # noqa: BLE001
        running = False
    if running:
        print("warning: a measurement is running; variables created now are only "
              "available after the measurement is restarted", file=sys.stderr)

    ns, created_ns = get_or_create_namespace(app, ns_name)
    print(f"namespace {'created' if created_ns else 'already present'}")

    existing = set()
    try:
        for v in ns.Variables:
            existing.add(v.Name)
    except Exception:                                            # noqa: BLE001
        pass
    print(f"existing variables in namespace: {len(existing)}")

    created = skipped = failed = 0
    for v in variables:
        if v["name"] in existing:
            skipped += 1
            continue
        try:
            typ = "Float" if v["type"] == "float" else "Integer"
            var = ns.Variables.Add(v["name"], typ)
            # set the limits before the value, so the start value cannot fall
            # outside the range CANoe already knows about
            for attr, key in (("Min", "min"), ("Max", "max")):
                raw = v.get(key)
                if raw is None:
                    continue
                try:
                    setattr(var, attr, float(raw))
                except Exception:                                # noqa: BLE001
                    pass
            try:
                var.Value = float(v["start"])
            except Exception:                                    # noqa: BLE001
                pass
            created += 1
            if created % 50 == 0:
                print(f"  ... {created} created")
        except Exception as e:                                   # noqa: BLE001
            failed += 1
            if failed <= 5:
                print(f"  FAILED {v['name']}: {e}", file=sys.stderr)

    print(f"\ncreated={created} skipped(existing)={skipped} failed={failed}")

    if args.save:
        try:
            app.Configuration.Save()
            print("configuration saved")
        except Exception as e:                                   # noqa: BLE001
            print(f"warning: could not save the configuration: {e}", file=sys.stderr)
    else:
        print("not saved - press Ctrl+S in CANoe, or re-run with --save")

    if failed:
        print("\nsome variables failed. If the names look fine, add the file manually:\n"
              "  Environment -> System Variables -> Import -> canoe/NBCM_Test.vsysvar",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
