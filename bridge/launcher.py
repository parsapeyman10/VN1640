#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
launcher.py -- start the bridge and open the tester (one command, all modes)
===========================================================================
The .bat files used to do this work themselves, and every step of it was a
separate thing that could silently break: a wrong script name, `start` with the
title in the wrong position, a hard-coded port, `timeout` sleeping instead of
waiting, `endlocal` in the wrong place.  Two of those bugs meant neither
launcher had ever worked.

So the .bat files are now three lines each and everything real happens here,
where it can be tested on any platform:

    python bridge/launcher.py sim         # tester only, no CANoe
    python bridge/launcher.py canoe       # tester + CANoe over COM

What it does:

  1. checks that the files it needs are actually there, and says which is missing
  2. starts the bridge as a child process and keeps its console alive
     (a child, not `start`: we can then wait for it, report its exit code and
     stop it with Ctrl+C)
  3. polls /api/health until the bridge answers, instead of sleeping a fixed
     number of seconds -- and reads back the port the bridge really chose,
     because the bridge walks forward when the configured port is taken
  4. opens the tester in the app-mode window, falling back to the browser
  5. on Ctrl+C or when the window closes, stops the bridge

    --dry-run     do everything except launch, and print the plan
    --no-window   start the bridge and print the URL (for a terminal user)
    --keep        do not stop the bridge when the window closes
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BRIDGE = HERE / "nbcm_bridge.py"
WINDOW = HERE / "nbcm_window.py"
FIND = HERE / "find_bridge.py"
LOCAL_CFG = HERE / "config.local.json"
CONFIG = HERE / "config.json"

WINDOWS = platform.system() == "Windows"


# --------------------------------------------------------------------------- #
def say(msg: str = ""):
    print(msg, flush=True)


def port_from_config() -> int:
    env = os.environ.get("NBCM_PORT", "").strip()
    if env.isdigit():
        return int(env)
    for path in (LOCAL_CFG, CONFIG):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data.get("port"), int):
            return data["port"]
    return 8770


def check_files() -> list[str]:
    missing = []
    for f in (BRIDGE, WINDOW, FIND):
        if not f.exists():
            missing.append(f.name)
    return missing


def port_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def health(url: str, timeout: float = 0.8) -> dict | None:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/health",
                                    timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except Exception:                                            # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) and "ok" in payload else None


def wait_for_bridge(proc: subprocess.Popen | None, timeout: float = 30.0) -> str | None:
    """Poll the port window until a bridge answers. Returns its base URL."""
    base = port_from_config()
    deadline = time.time() + timeout
    last_note = 0.0
    while time.time() < deadline:
        for port in range(base + 1, base + 12):
            if health(f"http://127.0.0.1:{port}"):
                return f"http://127.0.0.1:{port}/"

        if proc is not None and proc.poll() is not None:
            say(f"\n[ERROR] the bridge exited immediately (code {proc.returncode}).")
            say("        Its output is above. Most likely causes:")
            say("          - the port is taken        set another in bridge/config.local.json")
            say("          - CANoe mode without CANoe  use: python bridge/launcher.py sim")
            say("          - pywin32 missing          pip install pywin32")
            return None

        if time.time() - last_note > 5:
            say("        still waiting for the bridge ...")
            last_note = time.time()
        time.sleep(0.4)
    return None


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="start the NBCM bridge and open the tester")
    ap.add_argument("mode", nargs="?", default="sim", choices=["sim", "canoe"],
                    help="sim = no CANoe, canoe = connect over COM")
    ap.add_argument("--dry-run", action="store_true", help="print the plan only")
    ap.add_argument("--no-window", action="store_true",
                    help="do not open the tester window")
    ap.add_argument("--keep", action="store_true",
                    help="leave the bridge running after the window closes")
    ap.add_argument("--canoe-config", default=None,
                    help="path to the .cfg CANoe should open")
    args = ap.parse_args(argv)

    say("")
    say("  NBCM CAN tester")
    say(f"  mode   : {'simulator (no CANoe)' if args.mode == 'sim' else 'CANoe 12 over COM'}")
    say(f"  folder : {ROOT}")

    missing = check_files()
    if missing:
        say("")
        say(f"[ERROR] missing next to this script: {', '.join(missing)}")
        say(f"        expected in {HERE}")
        say("        The launchers must stay inside the bridge\\ folder.")
        return 2

    port = port_from_config()
    say(f"  port   : {port} (websocket) / {port + 1} (http)")
    if LOCAL_CFG.exists():
        say("  config : bridge/config.local.json overrides the defaults")
    if not port_free(port):
        say("")
        say(f"[warn] port {port} is already in use.")
        say("       If a bridge is already running, this will just use it.")
        say("       Otherwise set a different port in bridge/config.local.json:")
        say('           {"port": 8780}')
    say("")

    # a bridge may already be up: reuse it instead of starting a second one
    existing = wait_for_bridge(None, timeout=1.5)
    proc: subprocess.Popen | None = None

    if existing:
        say(f"[ok] a bridge is already running at {existing}")
        url = existing
    else:
        cmd = [sys.executable, str(BRIDGE), f"--{args.mode}",
               "--port", str(port)]
        if args.canoe_config:
            cmd += ["--canoe-config", args.canoe_config]
        say(f"[1/3] starting the bridge: {' '.join(cmd[1:])}")
        if args.dry_run:
            say("      (dry run - not started)")
            return 0
        try:
            proc = subprocess.Popen(cmd, cwd=str(ROOT))
        except OSError as e:
            say(f"[ERROR] could not start python: {e}")
            return 1
        url = wait_for_bridge(proc)
        if not url:
            # wait_for_bridge already explained *why* when the process died;
            # only add the timeout message when it is actually still running
            if proc.poll() is None:
                say("[ERROR] the bridge did not answer within 30 seconds.")
                say("        It is still running; read its output above.")
            if proc.poll() is None and not args.keep:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            return 1
        say(f"[ok] bridge at {url}")

    if not url:
        return 1

    payload = health(url) or {}
    say(f"      mode={payload.get('mode')} canoe={payload.get('canoe')} "
        f"sysvars={payload.get('sysvars')} driveMode={payload.get('driveMode')}")
    if payload.get("error"):
        say(f"[warn] bridge reports: {payload['error']}")
        if args.mode == "canoe":
            say("       CANoe is not reachable over COM.  Is it running, and is "
                "pywin32 installed?  (pip install pywin32)")

    if args.no_window:
        say(f"\nopen the tester at {url}   (Ctrl+C to stop)")
        try:
            while True:
                if proc is not None and proc.poll() is not None:
                    say(f"\n[ERROR] the bridge exited (code {proc.returncode}).")
                    return 1
                # also stop when the HTTP endpoint disappears (bridge killed
                # from another window, or reused from a previous run)
                if not health(url, timeout=0.5):
                    say("\n[ERROR] the bridge stopped answering; exiting.")
                    return 1
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        if proc and proc.poll() is None:
            say("\nstopping the bridge ...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        return 0

    say("[3/3] opening the tester ...")
    if args.dry_run:
        say("      (dry run - not opened)")
        return 0
    rc = subprocess.call([sys.executable, str(WINDOW), "--url", url,
                          "--size", "1280x900", "--always-on-top"], cwd=str(ROOT))
    if rc != 0:
        say("[warn] app window failed; opening the default browser instead.")
        import webbrowser
        webbrowser.open(url)

    if proc and not args.keep:
        say("stopping the bridge ...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    say("done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\ninterrupted")
        raise SystemExit(130)
