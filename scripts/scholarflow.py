#!/usr/bin/env python3
"""ScholarFlow cross-platform launcher (R10.5.40).

Stdlib only — works on Windows, macOS, Linux. Windows users: chmod is a no-op
on NTFS so `chmod +x` does not apply; invoke via `python scripts/scholarflow.py`.

Usage:
    python scripts/scholarflow.py start        # start backend (8000) + frontend (5173)
    python scripts/scholarflow.py stop         # stop both
    python scripts/scholarflow.py restart
    python scripts/scholarflow.py status
    python scripts/scholarflow.py logs         # tail both logs
    python scripts/scholarflow.py install      # pip install + npm install
    python scripts/scholarflow.py clean        # remove logs, __pycache__, dist
    python scripts/scholarflow.py open         # open browser to running instance
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)
PIDFILE = LOGS / "scholarflow.pids"

# Version defaults (R10.5.52: v4 experimental removed, v1 is the only version)
V1 = {"backend_port": 8000, "frontend_port": 5173,
      "backend_dir": ROOT / "backend",
      "frontend_dir": ROOT / "frontend",
      "backend_module": "backend.main:app",
      "frontend_cmd": ["npm", "run", "dev"]}


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) != 0


def read_pids() -> dict:
    if not PIDFILE.exists():
        return {}
    out = {}
    for line in PIDFILE.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            try:
                out[k] = int(v)
            except ValueError:
                pass
    return out


def write_pids(pids: dict) -> None:
    PIDFILE.write_text("\n".join(f"{k}={v}" for k, v in pids.items()) + "\n")


def alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True


def spawn(cmd, cwd, log_name, env=None):
    log_path = LOGS / log_name
    log_f = open(log_path, "ab", buffering=0)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore
    return subprocess.Popen(
        cmd, cwd=str(cwd), stdout=log_f, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env or os.environ.copy(),
        creationflags=creationflags,
    )


def wait_port(port: int, label: str, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not port_free(port):
            print(f"  [ok] {label} listening on :{port}")
            return True
        time.sleep(0.5)
    print(f"  [timeout] {label} not listening on :{port} after {timeout}s")
    return False


def _resolve(p):
    """Return the spawned proc or the stale PID."""
    return p if p else None


def cmd_start(args):
    cfg = V1
    label = "v1"
    print(f"Starting ScholarFlow {label} ...")
    pids = read_pids()
    if pids.get(f"{label}_backend") and alive(pids[f"{label}_backend"]):
        print(f"  [skip] {label} backend already running (pid {pids[f'{label}_backend']})")
        return 0
    if not cfg["backend_dir"].exists():
        print(f"  [error] backend dir missing: {cfg['backend_dir']}")
        return 1
    if not cfg["frontend_dir"].exists():
        print(f"  [error] frontend dir missing: {cfg['frontend_dir']}")
        return 1
    env = os.environ.copy()
    backend = spawn(
        [sys.executable, "-m", "uvicorn", cfg["backend_module"],
         "--host", "127.0.0.1", "--port", str(cfg["backend_port"])],
        cwd=cfg["backend_dir"], log_name=f"backend-{label}.log", env=env,
    )
    pids[f"{label}_backend"] = backend.pid
    frontend = spawn(cfg["frontend_cmd"], cwd=cfg["frontend_dir"],
                     log_name=f"frontend-{label}.log", env=env)
    pids[f"{label}_frontend"] = frontend.pid
    write_pids(pids)
    wait_port(cfg["backend_port"], f"{label} backend", timeout=30)
    wait_port(cfg["frontend_port"], f"{label} frontend", timeout=30)
    print(f"  [done] {label} running. Backend :{cfg['backend_port']}, "
          f"frontend :{cfg['frontend_port']}")
    print(f"  logs: {LOGS}")
    return 0


def _kill_pid(pid: int) -> None:
    if pid <= 0 or not alive(pid):
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           check=False, capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                if not alive(pid):
                    break
                time.sleep(0.1)
            if alive(pid):
                os.kill(pid, signal.SIGKILL)
    except Exception as e:
        print(f"  [warn] kill {pid} failed: {e}")


def cmd_stop(args):
    cfg = V1
    label = "v1"
    pids = read_pids()
    for key in (f"{label}_backend", f"{label}_frontend"):
        pid = pids.pop(key, 0)
        _kill_pid(pid)
    write_pids(pids)
    print(f"Stopped {label}.")
    return 0


def cmd_restart(args):
    cmd_stop(args)
    time.sleep(1)
    return cmd_start(args)


def cmd_status(args):
    pids = read_pids()
    if not pids:
        print("No running ScholarFlow processes tracked.")
        return 0
    for key, pid in pids.items():
        print(f"  {key}: pid {pid} {'alive' if alive(pid) else 'dead'}")
    cfg, label = V1, "v1"
    bp = "free" if port_free(cfg["backend_port"]) else "in-use"
    fp = "free" if port_free(cfg["frontend_port"]) else "in-use"
    print(f"  {label}: backend :{cfg['backend_port']}={bp}, "
          f"frontend :{cfg['frontend_port']}={fp}")
    return 0


def cmd_logs(args):
    files = sorted(LOGS.glob("*.log"))
    if not files:
        print("No log files yet.")
        return 0
    tail = ["powershell", "-NoProfile", "-Command",
            f"Get-Content -Wait -Tail 50 {' '.join(str(f) for f in files)}"]
    cmd = tail if sys.platform == "win32" else ["tail", "-f", "-n", "50", *map(str, files)]
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_install(args):
    cfg = V1
    label = "v1"
    print(f"Installing {label} deps ...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-r",
                    str(cfg["backend_dir"] / "requirements.txt")], check=False)
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    subprocess.run([npm, "install"], cwd=str(cfg["frontend_dir"]), check=False)
    print(f"  [done] {label} deps installed.")
    return 0


def cmd_clean(args):
    targets = [LOGS, ROOT / ".pytest_cache"]
    for d in [ROOT / "backend" / "__pycache__", ROOT / "frontend" / "dist"]:
        if d.exists():
            targets.append(d)
    for t in targets:
        if t.is_dir():
            import shutil
            shutil.rmtree(t, ignore_errors=True)
            print(f"  [clean] {t}")
    print("  [done] cleaned.")
    return 0


def cmd_open(args):
    cfg = V1
    url = f"http://127.0.0.1:{cfg['frontend_port']}/"
    print(f"Opening {url}")
    webbrowser.open(url)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="scholarflow",
                                description="ScholarFlow cross-platform launcher")
    subs = p.add_subparsers(dest="cmd")
    for name in ("start", "stop", "restart", "status", "logs", "install", "clean", "open"):
        subs.add_parser(name)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    handlers = {"start": cmd_start, "stop": cmd_stop, "restart": cmd_restart,
                "status": cmd_status, "logs": cmd_logs, "install": cmd_install,
                "clean": cmd_clean, "open": cmd_open}
    handler = handlers.get(args.cmd)
    if handler is None:
        build_parser().print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())