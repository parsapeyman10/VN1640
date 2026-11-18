#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_suite.py -- headless run of the same test suite, for CI and for Regressions
===============================================================================
The browser tester and this runner execute the *same* tests/test_suite.json with
the same step semantics.  Use this one when nobody is watching a screen.

    python bridge/run_suite.py --suite tests/test_suite.json --report-dir reports
    python bridge/run_suite.py --suite tests/test_suite.json --junit reports/junit.xml

Exit code: 0 when every executed test PASSed, 1 when something FAILed,
           2 on usage/configuration errors, 3 when the run was aborted.

Transport: it talks to a running nbcm_bridge.py over HTTP, so CANoe stays a
single point of truth and the runner never needs pywin32 itself.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUITE = ROOT / "tests" / "test_suite.json"
DEFAULT_MAP = ROOT / "can_tester" / "assets" / "signal_map.json"


def http_json(url: str, payload=None, timeout=10):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Bridge:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def health(self): return http_json(self.base + "/api/health")
    def state(self): return http_json(self.base + "/api/state")
    def signal(self, name, value): return http_json(self.base + "/api/signal", {"signal": name, "value": value})
    def offline(self, node, flag): return http_json(self.base + "/api/offline", {"node": node, "offline": bool(flag)})
    def drive(self, tester): return http_json(self.base + "/api/drive", {"tester": bool(tester)})
    def measurement(self, action): return http_json(self.base + "/api/measurement", {"action": action})


OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "~=": lambda a, b: abs(a - b) <= abs(b) * 0.02 + 1e-9,
    "exists": lambda a, b=None: a is not None,
    "notexists": lambda a, b=None: a is None,
}


def resolve(name: str, sigmap: dict) -> str:
    """Accept a signal name and return it in canonical form."""
    if name in sigmap:
        return name
    for k in sigmap:
        if k.lower() == name.lower():
            return k
    return name


class Runner:
    def __init__(self, bridge: Bridge, suite: dict, sigmap: dict, verbose=True):
        self.b = bridge
        self.suite = suite
        self.sigmap = sigmap
        self.d = suite.get("defaults", {})
        self.verbose = verbose
        self.offline_state = {}
        self.results = []

    def log(self, lvl, text):
        if self.verbose:
            print(f"[{lvl:<6}] {text}", flush=True)

    # -- value access -------------------------------------------------------
    def value_of(self, name):
        st = self.b.state()
        for n, v in st.get("frames", []):
            if n == name:
                return v
        return None

    def value_of_cached(self, name, cache):
        if name in cache:
            return cache[name]
        v = self.value_of(name)
        cache[name] = v
        return v

    # -- steps --------------------------------------------------------------
    def run_test(self, t):
        started = time.time()
        res = {"id": t["id"], "title": t.get("title", t["id"]), "suite": t.get("suite", "—"),
               "verdict": "RUNNING", "reason": "", "steps": []}
        self.log("INFO", f"-> {t['id']}  {t.get('title','')}")
        cache = {}
        for i, st in enumerate(t.get("steps", []), 1):
            if "log" in st:
                self.log("INFO", "   " + str(st["log"]))
                continue
            if "wait" in st or "settle" in st:
                time.sleep(float(st.get("wait", st.get("settle"))) / 1000.0)
                continue
            if "set" in st:
                for k, v in st["set"].items():
                    if k == "$offline":
                        for node, flag in v.items():
                            self.b.offline(node, flag)
                            self.offline_state[node] = bool(flag)
                    else:
                        self.b.signal(resolve(k, self.sigmap), v)
                time.sleep(float(self.d.get("settle", 350)) / 1000.0)
                cache.clear()
                continue
            if "expect" in st:
                ok, text = self.eval_expect(st["expect"], cache)
                res["steps"].append({"step": i, "ok": ok, "text": text})
                if not ok:
                    res["verdict"] = "FAIL"
                    res["reason"] = text
                    break
                self.log("PASS", "   + " + text)
                continue
            if "require" in st:
                rq = st["require"]
                op = OPS.get(rq.get("op", "exists"), OPS["exists"])
                expected = rq.get("value", rq.get("expected"))
                deadline = time.time() + float(rq.get("timeout", self.d.get("timeout", 4000))) / 1000.0
                last = None
                while time.time() < deadline:
                    last = self.value_of(resolve(rq["signal"], self.sigmap))
                    if op(last, expected):
                        break
                    time.sleep(float(self.d.get("poll", 100)) / 1000.0)
                ok = op(last, expected)
                text = f"wait {rq['signal']} {rq.get('op','exists')} {expected if expected is not None else ''} (got {last})"
                res["steps"].append({"step": i, "ok": ok, "text": text})
                if not ok:
                    res["verdict"] = "FAIL"
                    res["reason"] = "Timeout: " + text
                    break
                self.log("PASS", "   + " + text)
                continue
            res["verdict"] = "INCONC"
            res["reason"] = f"unsupported step {list(st)}"
            break

        if res["verdict"] == "RUNNING":
            res["verdict"] = "PASS"
        res["duration_ms"] = int((time.time() - started) * 1000)
        self.log(res["verdict"], f"<- {res['id']}  {res['verdict']}" + (f"  ({res['reason']})" if res["reason"] else ""))
        self.results.append(res)
        return res

    def eval_expect(self, ex, cache):
        if "offline" in ex:
            node = ex["offline"]
            fresh = self.b.state().get("offline", {}).get(node, False)
            return bool(fresh), f"node {node} offline (got {fresh})"
        if "online" in ex:
            node = ex["online"]
            fresh = self.b.state().get("offline", {}).get(node, False)
            return (not fresh), f"node {node} online (got {not fresh})"
        if "fresh" in ex or "absent" in ex:
            st = self.b.state()
            msg = ex.get("fresh") or ex.get("absent")
            ages = st.get("msgAge") or {}
            age = None
            for k, v in ages.items():
                if k.endswith(":" + msg):
                    age = v
                    break
            limit = ex.get("within", 2500)
            if "fresh" in ex:
                ok = age is not None and age <= limit
                return ok, f"message {msg} fresh (<{limit}ms) — age: {age}"
            ok = age is None or age > limit
            return ok, f"message {msg} absent for {limit}ms — age: {age}"
        if "signal" in ex:
            name = resolve(ex["signal"], self.sigmap)
            actual = self.value_of_cached(name, cache)
            op = OPS.get(ex.get("op", "=="))
            expected = ex.get("value", ex.get("expected"))
            if op is None:
                return False, f"unknown operator {ex.get('op')}"
            ok = op(actual, expected)
            return ok, f"{name} {ex.get('op','==')} {expected} (got {actual})"
        return False, "unsupported expect"

    def run(self):
        for t in self.suite.get("tests", []):
            self.run_test(t)


# --------------------------------------------------------------------------- #
def to_junit(rep: dict) -> str:
    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&apos;"))
    by_suite: dict[str, list] = {}
    for t in rep["tests"]:
        by_suite.setdefault(t["suite"], []).append(t)
    s = ['<?xml version="1.0" encoding="UTF-8"?>']
    s.append(f'<testsuites name="{esc(rep["run"]["dut"])}" tests="{rep["summary"]["total"]}" '
             f'failures="{rep["summary"]["fail"]}" skipped="{rep["summary"]["not_run"]}">')
    for name, tests in by_suite.items():
        fails = sum(1 for t in tests if t["verdict"] == "FAIL")
        s.append(f'  <testsuite name="{esc(name)}" tests="{len(tests)}" failures="{fails}">')
        for t in tests:
            s.append(f'    <testcase classname="{esc(name)}" name="{esc(t["id"] + " " + t["title"])}" '
                     f'time="{(t.get("duration_ms") or 0)/1000:.3f}">')
            if t["verdict"] == "FAIL":
                s.append(f'      <failure message="{esc(t["reason"])}"/>')
            elif t["verdict"] in ("NONE", "INCONC"):
                s.append(f'      <skipped message="{esc(t["verdict"] + " " + t.get("reason",""))}"/>')
            s.append("    </testcase>")
        s.append("  </testsuite>")
    s.append("</testsuites>")
    return "\n".join(s) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="headless NBCM suite runner")
    ap.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP)
    ap.add_argument("--bridge", default="http://127.0.0.1:8771", help="bridge HTTP base url")
    ap.add_argument("--report-dir", type=Path, default=ROOT / "reports")
    ap.add_argument("--junit", type=Path, default=None)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--operator", default="CI")
    ap.add_argument("--dut", default="NBCM")
    ap.add_argument("--take-control", action="store_true",
                    help="set DRIVE_MODE=1 so the tests own the signals")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if not args.suite.exists():
        print(f"error: suite not found: {args.suite}", file=sys.stderr)
        return 2
    suite = json.loads(args.suite.read_text(encoding="utf-8"))
    sigmap = {}
    if args.map.exists():
        data = json.loads(args.map.read_text(encoding="utf-8"))
        sigmap = {s["sig"]: s for s in data.get("signals", [])}

    bridge = Bridge(args.bridge)
    try:
        health = bridge.health()
    except Exception as e:                                        # noqa: BLE001
        print(f"error: bridge not reachable at {args.bridge}: {e}", file=sys.stderr)
        print("       start it with:  python bridge/nbcm_bridge.py --canoe", file=sys.stderr)
        return 2
    if not args.quiet:
        print(f"bridge: mode={health.get('mode')} canoe={health.get('canoe')} "
              f"sysvars={health.get('sysvars')} measurement={health.get('measRunning')}")

    if args.take_control:
        bridge.drive(True)

    runner = Runner(bridge, suite, sigmap, verbose=not args.quiet)
    runner.run()

    total = len(runner.results)
    passed = sum(1 for r in runner.results if r["verdict"] == "PASS")
    failed = sum(1 for r in runner.results if r["verdict"] == "FAIL")
    inconc = sum(1 for r in runner.results if r["verdict"] == "INCONC")
    verdict = "FAIL" if failed else ("INCONC" if inconc else "PASS")

    run_id = args.run_id or ("RUN-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    report = {
        "schema": "nbcm-test-report/1.0",
        "run": {"id": run_id, "operator": args.operator, "dut": args.dut,
                "tool": "nbcm_bridge run_suite.py", "canoe": "CANoe 12"},
        "summary": {"total": total, "pass": passed, "fail": failed,
                    "inconclusive": inconc, "not_run": 0},
        "tests": runner.results,
        "environment": {"generated": datetime.now(timezone.utc).isoformat(),
                        "bridge": health, "suite": str(args.suite)},
        "verdict": verdict,
    }

    args.report_dir.mkdir(parents=True, exist_ok=True)
    out = args.report_dir / f"report_{run_id}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.junit:
        args.junit.parent.mkdir(parents=True, exist_ok=True)
        args.junit.write_text(to_junit(report), encoding="utf-8")

    print(f"\nverdict: {verdict}   pass={passed} fail={failed} inconclusive={inconc} total={total}")
    print(f"report : {out}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
