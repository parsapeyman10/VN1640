#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cmd_sim.py -- a small cmd.exe interpreter, enough to test the .bat launchers
===========================================================================
There is no cmd.exe (and no wine) on this machine, so the launchers cannot be
run for real.  Instead this executes the actual .bat files with real if/else
evaluation, real `call`, real `goto` and real blocks, and *runs* the python
commands they contain.  That catches the class of bug that made the previous
launchers useless -- a wrong script name, a path that does not resolve, an
unquoted variable -- which a static linter cannot see.

Supported: set/setlocal, if [not] defined|exist|errorlevel with ( ) blocks,
for /f (reported, not executed), call, goto, start (reported), exit /b, echo.

    python tools/cmd_sim.py bridge/run_sim.bat sim
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path


class Cmd:
    def __init__(self, cwd: Path, execute: bool = True, verbose: bool = True):
        self.cwd = cwd
        self.vars: dict[str, str] = {}
        self.rc = 0
        self.execute = execute
        self.verbose = verbose
        self.output: list[str] = []

    # -- output -------------------------------------------------------------- #
    def log(self, msg: str):
        self.output.append(msg)
        if self.verbose:
            print(msg)

    # -- variable expansion -------------------------------------------------- #
    def exp(self, text: str) -> str:
        text = text.replace("%~dp0", str(self.cwd) + "\\")
        text = text.replace("%~n0", self.vars.get("_name", ""))
        text = re.sub(r"%~(\d)", lambda m: self.vars.get(m.group(1), ""), text)

        def rep(m):
            key = m.group(1).lower()
            for k, v in self.vars.items():
                if k.lower() == key:
                    return v
            return m.group(0)

        return re.sub(r"%([\w~]+)%", rep, text)

    # -- conditions ---------------------------------------------------------- #
    def test(self, cond: str) -> bool:
        c = cond.strip()
        neg = False
        low = c.lower()
        if low.startswith("not "):
            neg, c = True, c[4:].strip()
            low = c.lower()

        if low.startswith("defined "):
            name = c[8:].strip()
            res = name.lower() in {k.lower() for k in self.vars}
        elif low.startswith("exist "):
            target = c[6:].strip()
            target = self.exp(target).strip('"').replace("\\", "/")
            p = Path(target)
            if not p.is_absolute():
                p = self.cwd / p
            res = p.exists()
        elif low.startswith("errorlevel "):
            try:
                res = self.rc >= int(c[11:].strip())
            except ValueError:
                res = False
        elif low.startswith("/i "):
            rest = c[3:]
            m = re.match(r'"([^"]*)"\s*==\s*"([^"]*)"', rest)
            if m:
                res = self.exp(m.group(1)).lower() == self.exp(m.group(2)).lower()
            else:
                res = False
        elif "==" in c:
            left, right = c.split("==", 1)
            res = self.exp(left.strip().strip('"')) == self.exp(right.strip().strip('"'))
        else:
            self.log(f"  [sim] cannot evaluate condition: {cond!r}")
            res = False
        return not res if neg else res

    # -- one command --------------------------------------------------------- #
    def exec_line(self, line: str, labels: dict) -> int | None:
        line = line.strip()
        if not line or line.lower().startswith(("rem ", "rem", "::", "@echo")):
            return None
        low = line.lower()

        if low.startswith(("setlocal", "endlocal", "timeout", "pause", "cls")):
            return None

        if low.startswith('set "'):
            m = re.match(r'set\s+"([\w~]+)=(.*)"\s*$', line, re.I)
            if m:
                self.vars[m.group(1)] = self.exp(m.group(2))
            return None

        if low.startswith("cd /d") or low.startswith("cd "):
            target = self.exp(line[5:]).strip().strip('"')
            p = Path(target)
            if not p.is_absolute():
                p = self.cwd / p
            p = p.resolve()
            if not p.is_dir():
                self.log(f"  [ERROR] cd: {p} is not a directory")
                self.rc = 1
            else:
                self.cwd = p
            return None

        if low.startswith("echo"):
            text = line[4:].strip()
            if text:
                self.log("   " + self.exp(text))
            return None

        if low.startswith("exit /b"):
            self.rc = int((line.split() + ["0"])[-1] or 0)
            return self.rc

        if low.startswith("goto"):
            lab = line.split()[1].lstrip(":").lower()
            if lab in labels:
                return labels[lab]
            self.log(f"  [sim] unknown label :{lab}")
            return None

        if low.startswith("start "):
            self.log(f"  [start] {self.exp(line)[:100]}")
            return None

        if low.startswith("call "):
            target = self.exp(line[5:]).strip()
            m = re.match(r'"([^"]+)"\s*(.*)$', target)
            if m:
                script, rest = m.group(1), m.group(2)
            else:
                parts = target.split()
                script, rest = parts[0], " ".join(parts[1:])
            path = Path(script.replace("\\", "/"))
            if not path.is_absolute():
                path = self.cwd / path
            if not path.exists():
                self.log(f"  [ERROR] call: {path} does not exist")
                self.rc = 1
                return None
            self.log(f"  [call] {path.name} {rest}")
            sub = Cmd(self.cwd, self.execute, self.verbose)
            sub.vars.update({"1": rest.split()[0] if rest else ""})
            saved = self.cwd
            sub.rc = sub.run(path, rest)
            self.cwd = sub.cwd
            self.rc = sub.rc
            return None

        if ".py" in low or low.startswith(("py ", "python ")):
            cmd = self.exp(line)
            if not self.execute:
                self.log(f"  [exec] {cmd[:100]}")
                return None
            self.log(f"  [exec] {cmd[:100]}")
            import subprocess
            try:
                args = shlex.split(cmd.replace("\\", "/"))
                res = subprocess.run(args, cwd=str(self.cwd), capture_output=True,
                                     text=True, timeout=120)
                self.rc = res.returncode
                for ln in (res.stdout or "").strip().splitlines()[-6:]:
                    self.log(f"        | {ln}")
                for ln in (res.stderr or "").strip().splitlines()[-4:]:
                    self.log(f"        ! {ln}")
            except Exception as e:                                # noqa: BLE001
                self.log(f"        ! could not run: {e}")
                self.rc = 1
            return None

        self.log(f"  [sim] unhandled: {line[:90]}")
        return None

    # -- file ---------------------------------------------------------------- #
    def run(self, path: Path, args: str = "") -> int:
        path = Path(str(path).replace("\\", "/")).resolve()
        lines = path.read_text(encoding="utf-8", errors="replace") \
                    .replace("\r\n", "\n").split("\n")
        self.vars["_name"] = path.stem
        saved_dir = self.cwd
        self.cwd = path.parent

        labels = {}
        for n, l in enumerate(lines):
            m = re.match(r"\s*:(\w+)\s*$", l)
            if m:
                labels[m.group(1).lower()] = n

        i = 0
        while i < len(lines):
            raw = lines[i]
            line = raw.strip()
            i += 1

            if not line or line.lower().startswith(("rem", "::", "@echo")):
                continue

            # if ... ( ... ) block
            m = re.match(r"^if\s+(/i\s+)?(.*?)\s*\($", line, re.I)
            if m:
                cond = ((m.group(1) or "") + m.group(2)).strip()
                body, depth = [], 1
                while i < len(lines) and depth:
                    nxt = lines[i]
                    depth += nxt.count("(") - nxt.count(")")
                    if depth:
                        body.append(nxt)
                    i += 1
                if self.test(cond):
                    for bl in body:
                        self.exec_line(bl, labels)
                else:
                    self.log(f"  [if] false -> {cond[:80]}")
                continue

            # if on one line
            m = re.match(r"^if\s+(/i\s+)?(.+?)\s+(\S.*)$", line, re.I)
            if m and not m.group(3).lower().startswith("("):
                cond = ((m.group(1) or "") + m.group(2)).strip()
                if self.test(cond):
                    self.exec_line(m.group(3), labels)
                continue

            # for /f ... : report, do not fake it
            if line.lower().startswith("for "):
                self.log(f"  [for]  {self.exp(line)[:100]}")
                continue

            jump = self.exec_line(line, labels)
            if isinstance(jump, int) and jump >= 0 and jump < len(lines) \
                    and "goto" in line.lower():
                i = jump
            elif isinstance(jump, int) and line.lower().startswith("exit"):
                self.cwd = saved_dir
                return jump

        self.cwd = saved_dir
        return self.rc


def main(argv=None) -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    script = Path(args[0])
    rest = " ".join(args[1:])
    from pathlib import Path as P
    c = Cmd(Path(".").resolve())
    rc = c.run(script, rest)
    print(f"\nexit code: {rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
