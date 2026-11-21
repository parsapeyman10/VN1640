#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_vsysvar.py -- validate NBCM_Test.vsysvar the way CANoe does
=================================================================
CANoe refuses a system variable file with the unhelpful message

    "The data model contains at least one error. Please fix all errors and
     repeat the operation."

and points at no line.  Every rule below was taken from files CANoe itself
wrote (Engine/Lights, UDS, A429 samples), so a file that passes this has the
shape CANoe expects:

  1. root is <systemvariables version="4"> and there is exactly one namespace
     level above the named namespace
  2. `bitcount` is present on every variable -- 32 for int, **64 for float**.
     A float without bitcount is what broke the first two attempts.
  3. `type` is one CANoe knows: int, float, string, struct, genericarray...
  4. integer types carry `isSigned` and 32/64 bitcount
  5. `startValue` (and min/max) parse as numbers, and start lies inside
     minValue..maxValue
  6. maxValue > minValue (a degenerate range is an error)
  7. names are unique inside the namespace, non-empty, and contain no
     whitespace or characters CANoe will not accept
  8. attributes required by the format are all present
  9. numbers are written plainly (no nan/inf/exponent surprises)

`--canonical` also re-emits the file with attributes in the order CANoe writes
them, which makes a diff against a real Vector file readable.

    python tools/check_vsysvar.py
    python tools/check_vsysvar.py --canonical
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "canoe" / "NBCM_Test.vsysvar"

KNOWN_TYPES = {"int", "float", "string", "struct", "genericarray",
               "bytearray", "bool", "enum"}

REQUIRED = ["anlyzLocal", "readOnly", "valueSequence", "unit", "name",
            "comment", "encoding", "type", "bitcount"]

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(::[A-Za-z_][A-Za-z0-9_]*)*$")

problems: list[str] = []
notes: list[str] = []


def bad(msg: str):
    problems.append(msg)


def num(value: str | None):
    """Parse a number CANoe would accept, or None."""
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except ValueError:
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def check(path: Path) -> None:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        bad(f"not valid XML: {e}")
        return

    if root.tag != "systemvariables":
        bad(f"root element is <{root.tag}>, expected <systemvariables>")
    ver = root.get("version")
    if ver != "4":
        bad(f'root version is {ver!r}, CANoe writes "4"')

    # exactly one unnamed wrapper namespace, then the named one
    top = root.findall("namespace")
    if len(top) != 1:
        bad(f"expected one top-level namespace, found {len(top)}")
        return
    if top[0].get("name") != "":
        bad(f'top-level namespace should have name="", has {top[0].get("name")!r}')

    inner = [n for n in top[0].findall("namespace")]
    named = [n for n in inner if n.get("name")]
    if len(named) != 1:
        bad(f"expected one named namespace under the wrapper, found {len(named)}")
        return
    ns = named[0]
    ns_name = ns.get("name")

    variables = ns.findall("variable")
    if not variables:
        bad(f"namespace {ns_name!r} has no variables")
        return

    seen: dict[str, int] = {}
    for i, v in enumerate(variables, 1):
        name = v.get("name") or f"<#{i}>"
        where = f"{name} (#{i})"

        # 7. name
        if not v.get("name"):
            bad(f"#{i}: variable has no name")
        elif not NAME_RE.match(v.get("name")):
            bad(f"{where}: name is not a valid CANoe identifier")
        else:
            if v.get("name") in seen:
                bad(f"{where}: duplicate name (also #{seen[v.get('name')]})")
            seen[v.get("name")] = i

        # 6. required attributes
        missing = [a for a in REQUIRED if v.get(a) is None]
        if missing:
            bad(f"{where}: missing attribute(s) {missing}")

        typ = v.get("type")
        if typ not in KNOWN_TYPES:
            bad(f"{where}: unknown type {typ!r}")

        # 2. bitcount is mandatory and type-dependent
        bc = v.get("bitcount")
        if bc is not None:
            if not bc.isdigit():
                bad(f"{where}: bitcount {bc!r} is not a number")
            elif typ == "float" and bc != "64":
                bad(f"{where}: float must have bitcount=64, has {bc}")
            elif typ == "int" and bc not in ("32", "64"):
                bad(f"{where}: int should have bitcount 32 or 64, has {bc}")

        # 4. integer signedness
        if typ in ("int", "float") and v.get("isSigned") is None:
            bad(f"{where}: {typ} needs isSigned")

        # 5. startValue inside min..max
        start = num(v.get("startValue"))
        lo = num(v.get("minValue"))
        hi = num(v.get("maxValue"))
        for label, val, raw in (("startValue", start, v.get("startValue")),
                                ("minValue", lo, v.get("minValue")),
                                ("maxValue", hi, v.get("maxValue"))):
            if raw is not None and val is None:
                bad(f"{where}: {label}={raw!r} is not a number")
            if raw is not None and re.search(r"[eE]", raw or ""):
                notes.append(f"{where}: {label}={raw} uses exponent notation")

        if lo is not None and hi is not None:
            # 6. degenerate range
            if hi <= lo:
                bad(f"{where}: maxValue {hi} is not greater than minValue {lo}")
            # 5. start inside the range
            if start is not None and not (lo <= start <= hi):
                bad(f"{where}: startValue {start} outside [{lo}, {hi}]")

        # 9. numbers must be plain
        if typ == "float" and bc == "64" and v.get("minValue") is None:
            notes.append(f"{where}: float without range (allowed, but CANoe "
                         "shows no limits in the dialog)")

    print(f"namespace : {ns_name}")
    print(f"variables : {len(variables)}")
    print(f"unique    : {len(seen)}")


def canonical(path: Path) -> None:
    """Re-emit with CANoe's attribute order, for diffing against a real file."""
    order = ["anlyzLocal", "readOnly", "valueSequence", "unit", "name",
             "comment", "bitcount", "isSigned", "encoding", "type",
             "startValue", "minValue", "minValuePhys",
             "maxValue", "maxValuePhys"]
    tree = ET.parse(path)
    for v in tree.iter("variable"):
        attrs = dict(v.attrib)
        for k in list(attrs):
            del v.attrib[k]
        for k in order:
            if k in attrs:
                v.set(k, attrs.pop(k))
        for k, val in attrs.items():          # anything unexpected last
            v.set(k, val)
    out = path.with_suffix(".canonical.vsysvar")
    tree.write(out, encoding="utf-8", xml_declaration=True)
    print(f"canonical form written to {out}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="validate a CANoe .vsysvar file")
    ap.add_argument("path", nargs="?", type=Path, default=DEFAULT)
    ap.add_argument("--canonical", action="store_true",
                    help="also write a re-ordered copy for diffing")
    args = ap.parse_args(argv)

    if not args.path.exists():
        print(f"error: {args.path} not found", file=sys.stderr)
        return 2

    check(args.path)
    if args.canonical:
        canonical(args.path)

    print()
    if problems:
        print(f"FAIL -- {len(problems)} error(s) CANoe would reject:")
        for p in problems[:40]:
            print(f"  - {p}")
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more")
        return 1

    if notes:
        print(f"{len(notes)} note(s):")
        for n in notes[:10]:
            print(f"  . {n}")
        print()

    print(f"PASS -- {args.path.name} has the shape CANoe writes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
