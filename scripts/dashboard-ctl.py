#!/usr/bin/env python3
"""Start, stop, or check the read-only dashboard server (Windows and macOS).

    python scripts/dashboard-ctl.py start [--open]
    python scripts/dashboard-ctl.py stop
    python scripts/dashboard-ctl.py status

This launcher is separate from the server on purpose: dashboard-server.py stays
a pure read-only GET server that never spawns anything, while this tool is what
the Hermes chat (or you) uses to switch it on and off. Prints one JSON line.
"""
import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "scripts" / "dashboard-server.py"
PID_FILE = ROOT / "data" / "dashboard-server.pid"
LOG_FILE = ROOT / "data" / "dashboard-server.log"


def server_port():
    m = re.search(r"^PORT\s*=\s*(\d+)", SERVER.read_text(encoding="utf-8"), re.M)
    return int(m.group(1)) if m else 5301


PORT = server_port()
URL = f"http://127.0.0.1:{PORT}/"


def out(status, message, **extra):
    print(json.dumps({"status": status, "url": URL, "message": message, **extra}))


def port_open():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
            return True
    except OSError:
        return False


def is_dashboard():
    """True only if the program answering on the port is this dashboard."""
    try:
        with urllib.request.urlopen(URL, timeout=2) as r:
            return r.status == 200 and b"Job Hunter" in r.read(4096)
    except (urllib.error.URLError, OSError):
        return False


def read_pid():
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def wait_for(predicate, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.25)
    return predicate()


def cmd_start(args):
    if is_dashboard():
        out("running", "Dashboard is already running.", pid=read_pid())
        if args.open:
            webbrowser.open(URL)
        return 0
    if port_open():
        out("error", f"Port {PORT} is already used by another program, so the dashboard can't start.")
        return 1
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "ab")
    if os.name == "nt":
        extra = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        extra = {"start_new_session": True}
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)], cwd=str(ROOT), stdin=subprocess.DEVNULL,
        stdout=log, stderr=log, close_fds=True, **extra,
    )
    PID_FILE.write_text(str(proc.pid))
    if not wait_for(is_dashboard, 8):
        tail = ""
        try:
            tail = LOG_FILE.read_text(errors="replace")[-400:]
        except OSError:
            pass
        out("error", "Dashboard did not start in time.", log_tail=tail)
        return 1
    out("running", "Dashboard started.", pid=proc.pid)
    if args.open:
        webbrowser.open(URL)
    return 0


def kill(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=15)
    else:
        os.kill(pid, signal.SIGTERM)


def cmd_stop(_args):
    if not is_dashboard():
        PID_FILE.unlink(missing_ok=True)
        out("stopped", "Dashboard was not running.")
        return 0
    pid = read_pid()
    if pid is None:
        out("error", "Dashboard is running but was not started by this tool, so it can't be stopped from here. Close its window instead.")
        return 1
    try:
        kill(pid)
    except OSError as e:
        out("error", f"Could not stop the dashboard: {e}")
        return 1
    if not wait_for(lambda: not is_dashboard(), 8):
        out("error", "Asked the dashboard to stop, but it is still answering.")
        return 1
    PID_FILE.unlink(missing_ok=True)
    out("stopped", "Dashboard stopped.")
    return 0


def cmd_status(_args):
    if is_dashboard():
        out("running", "Dashboard is running.", pid=read_pid())
    elif port_open():
        out("error", f"Something else is using port {PORT}.")
    else:
        out("stopped", "Dashboard is not running.")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("start", help="Start the dashboard in the background")
    a.add_argument("--open", action="store_true", help="Also open it in your browser")
    a.set_defaults(func=cmd_start)
    sub.add_parser("stop", help="Stop the dashboard").set_defaults(func=cmd_stop)
    sub.add_parser("status", help="Say whether the dashboard is running").set_defaults(func=cmd_status)
    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
