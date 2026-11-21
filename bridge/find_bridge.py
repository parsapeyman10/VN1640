#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_bridge.py -- work out where the running bridge is listening
=================================================================
The launcher must not hard-code `http://127.0.0.1:8771`.  The bridge:

  * serves HTTP on `port + 1` while the WebSocket uses `port`,
  * falls forward to the next free port when the requested one is taken,
  * can be moved by `bridge/config.local.json`, `--port` or `NBCM_PORT`,

so any fixed URL in a .bat file is wrong sooner or later.

This prints the base URL of the first bridge that answers `GET /api/health`,
and exits non-zero with a readable reason if none does.  Kept in Python rather
than in cmd because that is the only way it can be tested off Windows.

    python bridge/find_bridge.py                  # print the URL
    python bridge/find_bridge.py --wait 25        # keep trying for 25 s
    python bridge/find_bridge.py --json           # full health payload
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "bridge" / "config.json"
LOCAL = ROOT / "bridge" / "config.local.json"

# how far the bridge may walk forward from the requested port
PORT_WINDOW = 10


def configured_port() -> int:
    """Port the bridge was told to use: env > config.local.json > config.json."""
    env = os.environ.get("NBCM_PORT")
    if env and env.strip().isdigit():
        return int(env)

    for path in (LOCAL, CONFIG):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        port = data.get("port")
        if isinstance(port, int) and port > 0:
            return port
    return 8770


def probe(port: int, timeout: float = 0.6) -> dict | None:
    """Return the health payload if a bridge answers on this port, else None."""
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    # a health payload without "ok" is some other web server on that port
    if not isinstance(payload, dict) or "ok" not in payload:
        return None
    return payload


def find(wait: float = 0.0, base_port: int | None = None) -> tuple[str, dict] | None:
    """Scan the port window until a bridge answers. Returns (url, health)."""
    base = base_port or configured_port()
    deadline = time.time() + max(0.0, wait)
    while True:
        for port in range(base + 1, base + 1 + PORT_WINDOW):
            health = probe(port)
            if health:
                return f"http://127.0.0.1:{port}/", health
        if time.time() >= deadline:
            return None
        time.sleep(1.0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="locate the running NBCM bridge")
    ap.add_argument("--wait", type=float, default=0.0,
                    help="seconds to keep retrying (default: try once)")
    ap.add_argument("--port", type=int, default=None,
                    help="base WebSocket port to start scanning from")
    ap.add_argument("--json", action="store_true", help="print the health payload")
    args = ap.parse_args(argv)

    result = find(args.wait, args.port)
    if not result:
        base = args.port or configured_port()
        print(f"no bridge answered on ports {base + 1}-{base + PORT_WINDOW}\n"
              f"  - is the bridge running?  python bridge/nbcm_bridge.py --sim\n"
              f"  - a firewall rule may block localhost\n"
              f"  - check bridge/config.local.json for a different port",
              file=sys.stderr)
        return 1

    url, health = result
    if args.json:
        print(json.dumps({"url": url, **health}, indent=2, ensure_ascii=False))
    else:
        print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
