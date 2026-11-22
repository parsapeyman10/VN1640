#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nbcm_bridge.py -- connect the HTML tester to Vector CANoe 12
===========================================================
Runs on the Windows PC where CANoe is installed.  Standard library only:
the WebSocket server is implemented here, so no `pip install` is required.
`pywin32` is needed only for the real CANoe connection (`--sim` works without).

Quick start (Windows, Python 3.9+):

    pip install pywin32                      # only for real CANoe access
    python bridge/nbcm_bridge.py --canoe      # open CANoe config + serve tester
    python bridge/nbcm_bridge.py --sim        # bridge without CANoe (dry test)

Then open http://127.0.0.1:8770/ in a browser (or point CANoe's docked browser
window / Edge app-mode window at it) and choose the WebSocket source.

REST endpoints (used by CI and by the tester's HTTP mode)
    GET  /api/health                 -> {"ok":true,...}
    GET  /api/state                  -> signals + offline + measurement state
    POST /api/signal   {"signal":"Hs_Abs_VehicleSpeed","value":60}
    POST /api/offline  {"node":"ABS","offline":true}
    POST /api/measurement {"action":"start"|"stop"}

WebSocket protocol (JSON text frames)
    server -> client : {"type":"state", "frames":[[name,val],...], "offline":{...}, "measRunning":bool}
                       {"pong":<echo of client ts>}
    client -> server : {"cmd":"set","signal":..,"value":..} | {"cmd":"offline","node":..,"flag":..}
                       {"cmd":"ping","t":..} | {"cmd":"watch","signals":[..]} | {"cmd":"hello",...}
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import socket
import struct
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "can_tester" / "assets" / "signal_map.json"
WEB_ROOT = ROOT / "can_tester"
CONFIG_FILE = ROOT / "bridge" / "config.json"

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8770,
    "canoe": {
        "enabled": True,
        "config_path": "",
        "autostart": False,          # start CANoe/measurement automatically
        "autostart_measurement": False,
        "bus": "CAN",
        "channel_hs": 1,
        "channel_ls": 2,
        "poll_hz": 4,
        "offline_namespace": "NBCM_Test",
        "offline_prefix": "OFFLINE_",
        "poll_signals": [
            "Hs_Abs_VehicleSpeed", "Hs_Abs_VehicleSpeed_Invalid", "Hs_Ems_Rpm",
            "Hs_Ems_Fuel_Tank_Level_Out", "LS_ICN_ODO", "Hs_Abs_Active"
        ],
    },
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def load_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception as e:                                    # noqa: BLE001
        log(f"warn: cannot read {p}: {e}")
        return default


def deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# CANoe link
# --------------------------------------------------------------------------- #
class CanoeLink:
    """Thin, defensive wrapper around the CANoe COM automation interface."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.app = None
        self.available = False
        self.error = ""
        self.meas_running = False
        self._signal_cache: dict[tuple, object] = {}
        self._var_cache: dict[str, object] = {}
        self.namespace = None
        self.sysvars_ok = False

    # -- connection ---------------------------------------------------------
    def connect(self) -> bool:
        try:
            import win32com.client as win32                      # type: ignore
        except Exception as e:                                   # noqa: BLE001
            self.error = ("pywin32 not installed (pip install pywin32). "
                          f"Detail: {e}")
            return False
        try:
            try:
                self.app = win32.GetActiveObject("CANoe.Application")
                log("attached to the running CANoe instance")
            except Exception:                                    # noqa: BLE001
                self.app = win32.DispatchEx("CANoe.Application")
                log("started a new CANoe instance")
            try:
                v = self.app.Version
                log(f"CANoe version {v.major}.{v.minor}.{v.Build}")
            except Exception:                                    # noqa: BLE001
                pass

            cfg_path = (self.cfg.get("config_path") or "").strip()
            if cfg_path:
                p = Path(cfg_path)
                if not p.exists():
                    self.error = f"CANoe config not found: {p}"
                    log("warn:", self.error)
                else:
                    self.app.Open(str(p))
                    log("opened config", p)
                    time.sleep(2.0)

            if self.cfg.get("autostart_measurement"):
                self.start_measurement()

            self._probe_sysvars()
            self.available = True
            self._refresh_measurement_state()
            return True
        except Exception as e:                                    # noqa: BLE001
            self.error = f"COM error: {e}"
            log("error:", self.error)
            return False

    # -- system variables (primary route) -----------------------------------
    def _probe_sysvars(self):
        """Detect the NBCM_Test namespace produced by tools/build_capl.py."""
        ns_name = self.cfg.get("offline_namespace", "NBCM_Test")
        try:
            self.namespace = self.app.System.Namespaces(ns_name)
            # touch one variable to be sure it is usable
            self.namespace.Variables("DRIVE_MODE")
            self.sysvars_ok = True
            log(f"system variables found: {ns_name}")
        except Exception as e:                                    # noqa: BLE001
            self.namespace = None
            self.sysvars_ok = False
            log(f"system variables NOT available ({ns_name}): {e}")
            log("  -> add canoe/NBCM_Test.vsysvar to the configuration and "
                "canoe/NBCM_TesterBridge.can to the restbus node")

    def _var(self, name):
        obj = self._var_cache.get(name)
        if obj is None:
            if self.namespace is None:
                raise RuntimeError("namespace not available")
            obj = self.namespace.Variables(name)
            self._var_cache[name] = obj
        return obj

    def read_var(self, name):
        try:
            return float(self._var(name).Value)
        except Exception as e:                                    # noqa: BLE001
            self.error = f"read_var({name}): {e}"
            return None

    def write_var(self, name, value):
        try:
            self._var(name).Value = float(value)
            return True
        except Exception as e:                                    # noqa: BLE001
            self.error = f"write_var({name}): {e}"
            return False

    def set_drive_mode(self, tester_owns: bool):
        return self.write_var("DRIVE_MODE", 1 if tester_owns else 0)

    # -- measurement --------------------------------------------------------
    def _refresh_measurement_state(self):
        try:
            self.meas_running = bool(self.app.Measurement.Running)
        except Exception:                                        # noqa: BLE001
            self.meas_running = False
        return self.meas_running

    def start_measurement(self) -> bool:
        try:
            if not self.app.Measurement.Running:
                self.app.Measurement.Start()
                for _ in range(100):
                    if self.app.Measurement.Running:
                        break
                    time.sleep(0.1)
            self.meas_running = bool(self.app.Measurement.Running)
            log("measurement started" if self.meas_running else "measurement did not start")
            return self.meas_running
        except Exception as e:                                    # noqa: BLE001
            self.error = f"start_measurement: {e}"
            log("error:", self.error)
            return False

    def stop_measurement(self) -> bool:
        try:
            if self.app.Measurement.Running:
                self.app.Measurement.Stop()
                time.sleep(0.3)
            self.meas_running = bool(self.app.Measurement.Running)
            log("measurement stopped")
            return True
        except Exception as e:                                    # noqa: BLE001
            self.error = f"stop_measurement: {e}"
            return False

    # -- signal access ------------------------------------------------------
    def _bus(self):
        return self.app.GetBus(self.cfg.get("bus", "CAN"))

    def _sig_obj(self, channel: int, message: str, signal: str):
        key = (channel, message, signal)
        obj = self._signal_cache.get(key)
        if obj is None:
            obj = self._bus().GetSignal(channel, message, signal)
            self._signal_cache[key] = obj
        return obj

    def read_signal(self, channel: int, message: str, signal: str):
        if self.sysvars_ok:
            v = self.read_var(signal)
            if v is not None:
                return v
        try:
            return float(self._sig_obj(channel, message, signal).Value)
        except Exception as e:                                    # noqa: BLE001
            self.error = f"read_signal({message}.{signal}): {e}"
            return None

    def write_signal(self, channel: int, message: str, signal: str, value: float) -> bool:
        """Writes through the system-variable bridge.

        System variables are the only route that reliably reaches CAPL variables
        (NBCM_TesterBridge.can copies them into the restbus).  Writing the COM
        signal object is kept as a fallback; it does not touch CAPL variables,
        so a failure there is reported instead of silently swallowed.
        """
        if self.sysvars_ok and self.write_var(signal, value):
            return True
        try:
            obj = self._sig_obj(channel, message, signal)
            obj.Value = float(value)
            return True
        except Exception as e:                                    # noqa: BLE001
            self.error = f"write_signal({message}.{signal}): {e}"
            return False

    # -- node offline switches (system variables) ---------------------------
    def set_offline(self, node: str, flag: bool) -> bool:
        var_name = self.cfg.get("offline_prefix", "OFFLINE_") + node
        return self.write_var(var_name, 1 if flag else 0)

    def publish_verdict(self, passed: int, failed: int,
                        last_pass: bool, last_fail: bool) -> bool:
        """Write the suite verdict into NBCM_Test::TC_*.

        The CANoe panel binds to these four variables, so a run started in the
        HTML tester (or from run_suite.py) leaves a visible result inside CANoe,
        including when nobody is looking at the browser.
        """
        values = (
            ("TC_RESULT_PASS", passed),
            ("TC_RESULT_FAIL", failed),
            ("TC_LAST_PASS", 1 if last_pass else 0),
            ("TC_LAST_FAIL", 1 if last_fail else 0),
        )
        ok = True
        for name, value in values:
            ok = self.write_var(name, value) and ok
        return ok

    def define_sysvars(self, names, type_name: str = "Integer") -> int:
        """Best effort: create the system variables used by the CAPL bridge."""
        created = 0
        ns_name = self.cfg.get("offline_namespace", "NBCM_Test")
        try:
            namespaces = self.app.System.Namespaces
            try:
                ns = namespaces(ns_name)
            except Exception:                                    # noqa: BLE001
                ns = namespaces.Add(ns_name)
            for n in names:
                try:
                    ns.Variables(n)
                except Exception:                                # noqa: BLE001
                    ns.Variables.Add(n, type_name)
                    created += 1
        except Exception as e:                                    # noqa: BLE001
            self.error = f"define_sysvars: {e}"
        return created


class SimLink:
    """Stand-in for CanoeLink so the bridge can be tested without CANoe.

    In simulator mode this link is also the *behaviour* engine: it owns the
    reaction rules from tools/behaviour.py, so cutting a node off in the browser
    produces the same consequences the CAPL produces in CANoe (Com_Loss flags,
    counters, substitutes, cascades).  One rule table, two runtimes.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.available = True
        self.error = ""
        self.meas_running = True
        self.model = None          # behaviour.Model, set by the bridge
        self.values: dict[str, float] = {}
        self.last_seen: dict[str, float] = {}
        self.last_tick = 0.0
        self.reasons: list[dict] = []

    def connect(self): return True
    def start_measurement(self): self.meas_running = True; return True
    def stop_measurement(self): self.meas_running = False; return True
    def read_signal(self, *_): return 0.0
    def write_signal(self, *a): return True
    def set_offline(self, *a): return True
    def read_var(self, *_): return None
    def write_var(self, *a): return True
    def set_drive_mode(self, *_): return True
    def define_sysvars(self, *a, **k): return 0

    def publish_verdict(self, passed, failed, last_pass, last_fail):
        # nothing to write to without CANoe; the hub keeps it for the UI
        return True

    # -- behaviour -------------------------------------------------------
    def step(self, now: float, offline: dict, incoming: dict) -> dict:
        """Run one reaction tick and return the values the sim now holds.

        ``offline``  {node: bool}   from the UI switches
        ``incoming`` {(net, msg): epoch_ms}  frames the tester just pushed
        """
        if self.model is None:
            return {}
        self.last_seen.update(incoming)
        out = self.model.compute(
            {"values": self.values, "offline": offline,
             "last_seen": self.last_seen},
            now_ms=now * 1000.0,
            cfg={"never_seen_is_absent": False})
        self.values.update(out["values"])
        self.reasons = out["reasons"]
        return out["values"]


# --------------------------------------------------------------------------- #
# shared state
# --------------------------------------------------------------------------- #
class Hub:
    def __init__(self, data: dict, cfg: dict):
        self.data = data
        self.cfg = cfg
        self.verdict = {"passed": 0, "failed": 0, "lastPass": False, "lastFail": False}
        self.lock = threading.RLock()   # re-entrant: state() calls msg_ages() inside the lock
        self.signals = {}                     # name -> value
        self.meta = {}                        # name -> signal record
        self.offline = {n["node"]: False for n in data.get("nodes", [])}
        self.meas_running = False
        self.drive_mode = 0          # 0 = CANoe scenario owns, 1 = tester owns
        self.frames = []                      # latest [[name,value],...]
        self.watch = set(cfg["canoe"].get("poll_signals") or [])
        self.msg_last = {}            # message key "NET:MSG" -> last seen (epoch)
        self.clients = set()
        self.link = None              # set by main(); state() reads its reasons
        for s in data.get("signals", []):
            self.meta.setdefault(s["sig"], s)
            self.signals.setdefault(s["sig"], s["def"])

    def value(self, name, default=0.0):
        return self.signals.get(name, default)

    def clamp(self, name, value):
        """Physical range check: a tester must not push garbage onto the bus."""
        rec = self.meta.get(name)
        if not rec:
            return value
        try:
            v = float(value)
        except (TypeError, ValueError):
            return value
        if rec.get("kind") == "bool":
            return 1.0 if v else 0.0
        lo, hi = rec.get("min"), rec.get("max")
        if lo is not None and v < lo:
            return float(lo)
        if hi is not None and v > hi:
            return float(hi)
        return v

    def set_local(self, name, value, raw=False):
        if not raw:
            value = self.clamp(name, value)
        with self.lock:
            self.signals[name] = value
            # a value the tester just wrote must be reported back, otherwise the
            # panel would show stale data for signals outside the watch list
            self.watch.add(name)

    def mark_msg(self, key):
        self.msg_last[key] = time.time()

    def msg_ages(self):
        now = time.time()
        with self.lock:
            keys = list(self.msg_last.keys())
        out = {}
        for k in keys:
            out[k] = int((now - self.msg_last[k]) * 1000)
        return out

    def set_offline(self, node, flag):
        with self.lock:
            if node in self.offline:
                self.offline[node] = bool(flag)
                return True
        return False

    def state(self):
        with self.lock:
            frames = list(self.frames)
            ages = self.msg_ages()
            return {
                "type": "state",
                "frames": frames,
                "offline": dict(self.offline),
                "measRunning": self.meas_running,
                "driveMode": self.drive_mode,
                "verdict": dict(self.verdict),
                "msgAge": ages,
                "reasons": list(getattr(self.link, "reasons", []) or []),
                "t": time.time(),
            }

    def broadcast(self, obj):
        dead = []
        for c in list(self.clients):
            try:
                c.send_json(obj)
            except Exception:                                     # noqa: BLE001
                dead.append(c)
        for d in dead:
            self.clients.discard(d)


# --------------------------------------------------------------------------- #
# polling thread: CANoe -> hub
# --------------------------------------------------------------------------- #
def poll_loop(hub: Hub, link, stop: threading.Event):
    """Keeps the hub in sync.

    CANoe mode : reads every watched signal through COM/sysvars and marks the
                 owning message as seen, so the tester can do Timeout checks.
    Sim mode   : acts as a tiny restbus -- keeps the values the client wrote and
                 marks all messages of online nodes as seen once per tick.
    """
    is_sim = isinstance(link, SimLink)
    hz = float(hub.cfg["canoe"].get("poll_hz") or 4)
    period = 1.0 / max(hz, 0.5)
    chan_hs = int(hub.cfg["canoe"].get("channel_hs") or 1)
    chan_ls = int(hub.cfg["canoe"].get("channel_ls") or 2)

    # in sim mode every message is "alive"; in CANoe mode we mark per read
    all_msgs = []
    for n in hub.data.get("nodes", []):
        for m in n.get("msgs", []):
            # node records carry `net` at node level, message records do not
            all_msgs.append((n["node"], n["net"] + ":" + m["msg"]))

    while not stop.is_set():
        t0 = time.time()
        try:
            if is_sim:
                # A node that is online is "seen" every tick; a node that is off
                # is not, so the reaction rules can time it out.
                incoming = {}
                for node, key in all_msgs:
                    if not hub.offline.get(node, False):
                        incoming[key] = time.time() * 1000.0
                        hub.mark_msg(key)
                with hub.lock:
                    offline = dict(hub.offline)
                # one reaction tick: loss flags, counters, substitutes, cascades
                changes = link.step(time.time(), offline, incoming)
                for name, val in changes.items():
                    hub.signals[name] = val
                    hub.watch.add(name)
                with hub.lock:
                    watch = list(hub.watch)
                    frames = [[name, hub.signals.get(name, 0.0)] for name in watch]
                hub.frames = frames
                hub.meas_running = bool(getattr(link, "meas_running", False))
            else:
                hub.meas_running = bool(link._refresh_measurement_state())
                with hub.lock:
                    watch = list(hub.watch)
                frames = []
                for name in watch:
                    rec = hub.meta.get(name)
                    if not rec:
                        continue
                    ch = chan_hs if rec["net"] == "HS" else chan_ls
                    v = link.read_signal(ch, rec["msg"], name)
                    if v is None:
                        continue
                    hub.set_local(name, v)
                    frames.append([name, v])
                    if not hub.offline.get(rec["node"], False):
                        hub.mark_msg(rec["net"] + ":" + rec["msg"])
                with hub.lock:
                    hub.frames = frames
            hub.broadcast(hub.state())
        except Exception:                                         # noqa: BLE001
            log("poll error:", traceback.format_exc(limit=2))
        stop.wait(max(0.02, period - (time.time() - t0)))


# --------------------------------------------------------------------------- #
# minimal WebSocket implementation (RFC 6455, text frames only)
# --------------------------------------------------------------------------- #
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WSClient:
    def __init__(self, sock: socket.socket, addr):
        self.sock = sock
        self.addr = addr
        self.alive = True
        self.lock = threading.RLock()   # re-entrant: state() calls msg_ages() inside the lock

    def handshake(self, request_headers: dict) -> bool:
        key = request_headers.get("sec-websocket-key")
        if not key:
            return False
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        resp = ("HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n")
        self.sock.sendall(resp.encode())
        return True

    def send_json(self, obj):
        self.send_text(json.dumps(obj, separators=(",", ":")))

    def send_text(self, text: str):
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(n)
        elif n < 65536:
            header.append(126)
            header += struct.pack("!H", n)
        else:
            header.append(127)
            header += struct.pack("!Q", n)
        with self.lock:
            self.sock.sendall(bytes(header) + payload)

    def recv_message(self):
        """Returns (opcode, payload) or (None, None) on close."""
        b1, b2 = self._read_exact(2)
        opcode = b1 & 0x0F
        masked = b2 & 0x80
        ln = b2 & 0x7F
        if ln == 126:
            ln = struct.unpack("!H", self._read_exact(2))[0]
        elif ln == 127:
            ln = struct.unpack("!Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else b"\x00\x00\x00\x00"
        data = bytearray(self._read_exact(ln)) if ln else bytearray()
        if masked:
            for i in range(ln):
                data[i] ^= mask[i % 4]
        return opcode, bytes(data)

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("socket closed")
            buf += chunk
        return buf

    def close(self):
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:                                         # noqa: BLE001
            pass
        try:
            self.sock.close()
        except Exception:                                         # noqa: BLE001
            pass


def ws_serve(hub: Hub, link, host: str, port: int, stop: threading.Event,
             http_fallback: bool = False):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(16)
    log(f"websocket listening on ws://{host}:{port}/")
    while not stop.is_set():
        try:
            srv.settimeout(0.5)
            conn, addr = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=ws_client_thread,
                         args=(hub, link, conn, addr, http_fallback),
                         daemon=True).start()
    srv.close()


def _serve_http_on_ws_port(conn: socket.socket, raw: bytes, head: str):
    """Run one plain HTTP request through the regular REST/static handler.

    The request bytes are already partly consumed by the WebSocket sniffing, so
    they are pushed back into a fake rfile before the handler runs.  Everything
    after the header block (a POST body) is already in ``raw`` as well.
    """
    import io

    class _Conn:
        """Just enough of a socket for BaseHTTPRequestHandler."""

        def __init__(self, sock):
            self._sock = sock

        def makefile(self, mode="rb", *a, **k):
            return io.BytesIO(raw) if "r" in mode else _Writer(self._sock)

        def sendall(self, data):
            self._sock.sendall(data)

        def close(self):
            self._sock.close()

        def settimeout(self, t):
            try:
                self._sock.settimeout(t)
            except OSError:
                pass

        def getsockname(self):
            return self._sock.getsockname()

    class _Writer:
        def __init__(self, sock):
            self._sock = sock

        def write(self, b):
            self._sock.sendall(b)
            return len(b)

        def flush(self):
            pass

    try:
        Handler(_Conn(conn), ("0.0.0.0", 0), None)
    except Exception as e:                                        # noqa: BLE001
        log("http-fallback failed:", e)
        try:
            conn.close()
        except OSError:
            pass


def ws_client_thread(hub: Hub, link, conn: socket.socket, addr,
                     http_fallback: bool = False):
    raw = b""
    conn.settimeout(5)
    try:
        while b"\r\n\r\n" not in raw:
            chunk = conn.recv(4096)
            if not chunk:
                return
            raw += chunk
    except socket.timeout:
        conn.close()
        return

    head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1")
    lines = head.split("\r\n")
    headers = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            headers[k.strip().lower()] = v.strip()

    if headers.get("upgrade", "").lower() != "websocket":
        # Not a WebSocket.  On the UI port this ends the connection (that is how
        # it behaved historically).  On the WebSocket port we answer it as a
        # normal HTTP request instead, so the same port can be opened in a
        # browser and used by the preview proxy -- the two things a user is
        # most likely to point at the port the docs call "the bridge".
        if http_fallback:
            _serve_http_on_ws_port(conn, raw, head)
        else:
            conn.close()
        return

    client = WSClient(conn, addr)
    if not client.handshake(headers):
        conn.close()
        return
    hub.clients.add(client)
    log(f"ws client connected {addr[0]} (total {len(hub.clients)})")
    client.sock.settimeout(None)
    try:
        client.send_json(hub.state())
        while client.alive and not stop_flag.is_set():
            opcode, data = client.recv_message()
            if opcode is None or opcode == 0x8:
                break
            if opcode == 0x9:                                  # ping -> pong
                with client.lock:
                    client.sock.sendall(bytes([0x8A, len(data)]) + data)
                continue
            if opcode != 0x1:
                continue
            try:
                msg = json.loads(data.decode("utf-8", "replace"))
            except Exception:                                  # noqa: BLE001
                continue
            handle_cmd(hub, link, client, msg)
    except Exception:                                          # noqa: BLE001
        pass
    finally:
        hub.clients.discard(client)
        client.close()
        log(f"ws client disconnected (total {len(hub.clients)})")


def handle_cmd(hub: Hub, link, client: WSClient, msg: dict):
    cmd = msg.get("cmd")
    if cmd == "ping":
        client.send_json({"pong": msg.get("t")})
        return
    if cmd == "hello":
        log("client hello:", msg.get("client"), msg.get("ver"))
        client.send_json(hub.state())
        return
    if cmd == "set":
        name, value = msg.get("signal"), msg.get("value")
        rec = hub.meta.get(name)
        if not rec:
            client.send_json({"type": "error", "msg": f"unknown signal {name}"})
            return
        hub.set_local(name, value, raw=bool(msg.get("raw")))
        value = hub.signals.get(name, value)
        if hub.meas_running:
            ch = int(hub.cfg["canoe"].get("channel_hs" if rec["net"] == "HS" else "channel_ls") or 1)
            ok = link.write_signal(ch, rec["msg"], name, value)
            if not ok:
                client.send_json({"type": "error", "msg": link.error})
        return
    if cmd == "offline":
        node, flag = msg.get("node"), bool(msg.get("flag"))
        hub.set_offline(node, flag)
        ok = link.set_offline(node, flag)
        hub.broadcast({"type": "offline", "offline": dict(hub.offline)})
        if not ok:
            client.send_json({"type": "error", "msg": link.error})
        return
    if cmd == "watch":
        names = [n for n in (msg.get("signals") or []) if n]
        with hub.lock:
            hub.watch = set(names)
        return
    if cmd == "drive":
        mode = 1 if bool(msg.get("tester")) else 0
        hub.drive_mode = mode
        ok = link.set_drive_mode(mode == 1)
        hub.broadcast({"type": "drive", "driveMode": mode})
        if not ok:
            client.send_json({"type": "error", "msg": getattr(link, "error", "drive mode failed")})
        return
    if cmd == "measurement":
        action = msg.get("action")
        if action == "start":
            link.start_measurement()
        elif action == "stop":
            link.stop_measurement()
        hub.meas_running = bool(getattr(link, "meas_running", False))
        hub.broadcast({"type": "meas", "running": hub.meas_running})
        return


# --------------------------------------------------------------------------- #
# HTTP: REST + static files
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    hub: Hub = None                # type: ignore
    link = None
    server_version = "NBCMBridge/1.0"

    def log_message(self, fmt, *args):                          # noqa: A003
        pass

    # -- helpers ------------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:                                       # noqa: BLE001
            return {}

    # -- routes -------------------------------------------------------------
    def do_HEAD(self):                                           # noqa: N802
        # Tools that probe a URL (preview proxies, health checks, curl -I) use
        # HEAD first.  BaseHTTPRequestHandler answers 501 for it unless it is
        # implemented, which makes a perfectly good server look dead.
        # Answer with the same status/headers as GET and no body, which is what
        # the headers already promise via Content-Length.
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def do_OPTIONS(self):                                        # noqa: N802
        self._send(204, b"")

    def do_GET(self):                                            # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            real = isinstance(self.link, CanoeLink)
            return self._json(200, {
                "ok": True, "mode": "canoe" if real else "sim",
                "canoe": real, "sysvars": bool(getattr(self.link, "sysvars_ok", False)),
                "error": getattr(self.link, "error", ""),
                "clients": len(self.hub.clients), "measRunning": self.hub.meas_running,
                "driveMode": self.hub.drive_mode,
            })
        if path == "/api/state":
            return self._json(200, self.hub.state())
        if path == "/api/signals":
            return self._json(200, {"meta": self.hub.data.get("meta", {}),
                                    "signals": self.hub.data.get("signals", [])})
        return self._static(path)

    def do_POST(self):                                           # noqa: N802
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/signal":
            name, value = body.get("signal"), body.get("value")
            rec = self.hub.meta.get(name)
            if not rec:
                return self._json(404, {"ok": False, "error": f"unknown signal {name}"})
            self.hub.set_local(name, value, raw=bool(body.get("raw")))
            value = self.hub.signals.get(name, value)
            ok = True
            if self.hub.meas_running:
                ch = int(self.hub.cfg["canoe"].get("channel_hs" if rec["net"] == "HS" else "channel_ls") or 1)
                ok = self.link.write_signal(ch, rec["msg"], name, value)
            return self._json(200, {"ok": boo(ok), "applied": value,
                                    "error": getattr(self.link, "error", "")})
        if path == "/api/offline":
            node, flag = body.get("node"), bool(body.get("offline"))
            changed = self.hub.set_offline(node, flag)
            ok = self.link.set_offline(node, flag) if changed else False
            self.hub.broadcast({"type": "offline", "offline": dict(self.hub.offline)})
            return self._json(200, {"ok": boo(ok), "error": getattr(self.link, "error", "")})
        if path == "/api/drive":
            mode = 1 if bool(body.get("tester")) else 0
            self.hub.drive_mode = mode
            ok = self.link.set_drive_mode(mode == 1)
            self.hub.broadcast({"type": "drive", "driveMode": mode})
            return self._json(200, {"ok": boo(ok), "driveMode": mode,
                                    "error": getattr(self.link, "error", "")})
        if path == "/api/verdict":
            # mirror a suite result into the system variables the CANoe panel
            # binds to, so the verdict is visible inside CANoe without the app
            passed = int(body.get("passed") or 0)
            failed = int(body.get("failed") or 0)
            self.hub.verdict = {"passed": passed, "failed": failed,
                                "lastPass": bool(body.get("lastPass")),
                                "lastFail": bool(body.get("lastFail"))}
            ok = self.link.publish_verdict(passed, failed,
                                           bool(body.get("lastPass")),
                                           bool(body.get("lastFail"))) \
                 if hasattr(self.link, "publish_verdict") else False
            self.hub.broadcast({"type": "verdict", **self.hub.verdict})
            return self._json(200, {"ok": boo(ok), "error": getattr(self.link, "error", "")})
        if path == "/api/measurement":
            action = body.get("action")
            if action == "start":
                self.link.start_measurement()
            elif action == "stop":
                self.link.stop_measurement()
            self.hub.meas_running = bool(getattr(self.link, "meas_running", False))
            self.hub.broadcast({"type": "meas", "running": self.hub.meas_running})
            return self._json(200, {"ok": True, "running": self.hub.meas_running})
        return self._json(404, {"ok": False, "error": "not found"})

    # -- static -------------------------------------------------------------
    def _static(self, path: str):
        rel = unquote(path.lstrip("/")) or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        target = (WEB_ROOT / rel).resolve()
        try:
            target.relative_to(WEB_ROOT.resolve())
        except ValueError:
            return self._send(403, b"forbidden", "text/plain")
        if not target.exists() or not target.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = {
            ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
        }.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)


def boo(v):
    return bool(v)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
stop_flag = threading.Event()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NBCM tester <-> CANoe 12 bridge")
    ap.add_argument("--config", type=Path, default=CONFIG_FILE)
    ap.add_argument("--sim", action="store_true", help="do not touch CANoe, serve only")
    ap.add_argument("--canoe", action="store_true", help="connect to CANoe (default when enabled)")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--canoe-config", default=None, help="path to the .cfg to open")
    ap.add_argument("--start-measurement", action="store_true")
    ap.add_argument("--define-sysvars", action="store_true",
                    help="create NBCM_Test::OFFLINE_<NODE> system variables in CANoe")
    args = ap.parse_args(argv)

    cfg = deep_merge(DEFAULT_CONFIG, load_json(args.config, {}) or {})
    if args.host:
        cfg["host"] = args.host
    if args.port:
        cfg["port"] = args.port
    if args.canoe_config:
        cfg["canoe"]["config_path"] = args.canoe_config
    if args.start_measurement:
        cfg["canoe"]["autostart_measurement"] = True
    if args.sim:
        cfg["canoe"]["enabled"] = False
    if args.canoe:
        cfg["canoe"]["enabled"] = True

    data = load_json(DATA_FILE, None)
    if not data:
        print(f"error: {DATA_FILE} not found. Run: python tools/build_data.py", file=sys.stderr)
        return 2

    hub = Hub(data, cfg)
    hub.link = None            # set below; state() reports its reasons

    link = SimLink(cfg) if not cfg["canoe"]["enabled"] else CanoeLink(cfg["canoe"])
    if isinstance(link, CanoeLink):
        if not link.connect():
            log("continuing WITHOUT CANoe:", link.error)
        elif args.define_sysvars:
            names = [cfg["canoe"]["offline_prefix"] + n for n in hub.offline]
            n = link.define_sysvars(names)
            log(f"defined {n} system variables in {cfg['canoe']['offline_namespace']}")

    hub.link = link                                            # type: ignore
    if isinstance(link, SimLink):
        # simulator mode is also a behaviour bench: same rules as the CAPL
        try:
            sys.path.insert(0, str(ROOT / "tools"))
            import behaviour
            link.model = behaviour.build_from_model(data)
            link.values = dict(hub.signals)
            log(f"sim behaviour model: {len(link.model.sup_of)} supervision frames, "
                f"{len(link.model.substitutes)} substitutes")
        except Exception:                                         # noqa: BLE001
            log("sim behaviour model unavailable:", traceback.format_exc(limit=1))
    if isinstance(link, CanoeLink) and link.available and cfg["canoe"].get("take_control"):
        hub.drive_mode = 1
        link.set_drive_mode(True)
        log("DRIVE_MODE=1 (tester owns the signals)")

    poll_thread = threading.Thread(target=poll_loop, args=(hub, link, stop_flag), daemon=True)
    poll_thread.start()

    Handler.hub = hub
    Handler.link = link
    http_port = int(cfg["port"]) + 1

    # The WebSocket port answers plain HTTP too, so opening the port named on the
    # command line in a browser shows the tester instead of an empty page.  The
    # dedicated UI port (port + 1) keeps working exactly as before.
    ws_thread = threading.Thread(
        target=ws_serve, args=(hub, link, cfg["host"], cfg["port"], stop_flag, True),
        daemon=True)
    ws_thread.start()

    httpd = ThreadingHTTPServer((cfg["host"], http_port), Handler)
    log(f"tester UI  : http://{cfg['host']}:{http_port}/")
    log(f"websocket  : ws://{cfg['host']}:{cfg['port']}/   (also serves the UI over http)")
    log(f"CANoe      : {'connected' if link.available and isinstance(link, CanoeLink) else 'simulation'}")
    log("Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("stopping")
    finally:
        stop_flag.set()
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
