#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nbcm_window.py -- show the HTML tester in a compact window next to CANoe
=======================================================================
CANoe 12 cannot host an HTML page: Panel Designer has no browser/WebView
control and version 12 has no add-in API for custom windows (the .NET add-in
model arrived in later versions).  The practical way to keep the tester on the
same screen as CANoe is an application-mode browser window:

    * Edge / Chrome `--app=URL` gives a window with no address bar, no tabs
      and no menus, so it looks and behaves like a tool window
    * Windows can pin it always-on-top and place it next to the CANoe window

    python bridge/nbcm_window.py                 # 1280x900 next to CANoe
    python bridge/nbcm_window.py --always-on-top # keep above CANoe
    python bridge/nbcm_window.py --port 8770 --size 900x1200

Tested target: Windows 10/11 with Edge (present on every supported install).
Standard library only.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request


EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser(explicit: str | None = None) -> tuple[str, str]:
    if explicit:
        return os.path.basename(explicit), explicit
    for p in EDGE_PATHS:
        if os.path.exists(p):
            return "edge", p
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return "chrome", p
    for name in ("msedge", "chrome", "chromium"):
        p = shutil.which(name)
        if p:
            return name, p
    raise FileNotFoundError(
        "Edge/Chrome not found. Install Microsoft Edge or pass --browser "
        r'"C:\path\to\msedge.exe"')


def wait_for_ui(url: str, timeout: float = 20.0) -> bool:
    """Wait until the bridge serves the tester, so we never open a blank tab."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1.5) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def pin_always_on_top(title_part: str = "NBCM") -> bool:
    """Best-effort always-on-top via ctypes (Windows only)."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        HWND_TOPMOST, SWP_NOMOVE, SWP_NOSIZE = -1, 0x0002, 0x0001
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if title_part.lower() in buf.value.lower():
                    found.append(hwnd)
            return True

        user32.EnumWindows(enum_proc, 0)
        for hwnd in found:
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        return bool(found)
    except Exception:                                             # noqa: BLE001
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="open the NBCM tester in an app-mode window")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8770,
                    help="bridge port (UI is served on port+1)")
    ap.add_argument("--url", default=None, help="open this url instead of the bridge UI")
    ap.add_argument("--size", default="1200x900", help="WxH, default 1200x900")
    ap.add_argument("--always-on-top", action="store_true")
    ap.add_argument("--browser", default=None, help="path to msedge.exe / chrome.exe")
    ap.add_argument("--wait", type=float, default=20.0, help="seconds to wait for the bridge")
    args = ap.parse_args(argv)

    url = args.url or f"http://{args.host}:{args.port + 1}/"
    if not args.url and not wait_for_ui(f"http://{args.host}:{args.port + 1}"):
        print(f"warning: the bridge is not answering on {args.host}:{args.port + 1}.",
              file=sys.stderr)
        print("         start it first:  python bridge/nbcm_bridge.py --canoe",
              file=sys.stderr)

    try:
        name, exe = find_browser(args.browser)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    w, _, h = args.size.partition("x")
    profile = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                           "NBCM-Tester", "browser-profile")
    os.makedirs(profile, exist_ok=True)

    cmd = [
        exe,
        f"--app={url}",
        f"--window-size={int(w)},{int(h)}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
    ]
    print(f"opening {name}: {url}")
    proc = subprocess.Popen(cmd)
    if args.always_on_top:
        time.sleep(2.5)
        ok = pin_always_on_top("NBCM")
        print("always-on-top:", "ok" if ok else "not applied (window title not found)")
    print("close the window to exit.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
