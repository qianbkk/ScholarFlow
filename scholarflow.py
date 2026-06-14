"""ScholarFlow management CLI (Python core for scholarflow.bat).

R10.5.1 rewrite: replaces the complex .bat logic with subprocess.Popen
plus requests-based health checks. Avoids cmd quoting, MSYS bash
interception, and silent start failures.

Usage:
  Interactive:  python scholarflow.py
  CLI:          python scholarflow.py [start|stop|status|logs backend|...]
"""
import sys
import os
import io
import time
import signal
import socket
import subprocess
import webbrowser
import shutil
from pathlib import Path

# Windows: force stdout/stderr to UTF-8 (avoid cmd GBK encoding errors)
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# ===== Paths =====
ROOT = Path(__file__).parent.resolve()
RUN_DIR = ROOT / ".run"
LOG_DIR = ROOT / "logs"
CACHE_DIR = ROOT / "backend" / ".cache"
FRONTEND_DIR = ROOT / "frontend"
# R10.5.23: 端口从 env 读, 默认 8000/5173. 跟 vite.config.ts proxy target 默认值
# 对齐 (8000), 用户想用其他端口 (避开冲突) 在 shell 里 set BACKEND_PORT=8766 即可,
# 但需要同步改 frontend/vite.config.ts 的 proxy target (R10.5.20 留下的坑).
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "5173"))

BACKEND_PID_FILE = RUN_DIR / "backend.pid"
FRONTEND_PID_FILE = RUN_DIR / "frontend.pid"
BACKEND_LOG = LOG_DIR / "backend.log"
FRONTEND_LOG = LOG_DIR / "frontend.log"

RUN_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


# ===== ANSI colors =====
class C:
    H = "\033[1;36;40m"
    G = "\033[92m"
    Y = "\033[93m"
    R = "\033[91m"
    B = "\033[94m"
    X = "\033[0m"


def banner():
    print(f"""{C.H}===============================================================
  ScholarFlow Manager  v1.0.1  (Python core)
===============================================================  {C.X}
  Backend  http://127.0.0.1:{BACKEND_PORT}   (uvicorn :{BACKEND_PORT})
  Frontend http://127.0.0.1:{FRONTEND_PORT}   (vite :{FRONTEND_PORT})
  API      http://127.0.0.1:{BACKEND_PORT}/docs
{C.H}==============================================================={C.X}""")


def menu():
    print(f"""
  {C.G}[1]{C.X} Start - local mode (uvicorn + vite)
  {C.G}[2]{C.X} Start - Docker mode (docker compose up -d)
  {C.G}[3]{C.X} Stop
  {C.G}[4]{C.X} Restart
  {C.G}[5]{C.X} Status
  {C.G}[6]{C.X} View logs
  {C.G}[7]{C.X} Install dependencies
  {C.G}[8]{C.X} Clean cache
  {C.G}[9]{C.X} Open browser
  {C.G}[0]{C.X} Exit""")


# ===== Process management =====
def is_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            PROCESS_QUERY_LIMITED = 0x1000
            kernel32 = ctypes.windll.kernel32
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
            if h == 0:
                return False
            STILL_ACTIVE = 259
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            kernel32.CloseHandle(h)
            return code.value == STILL_ACTIVE
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            return False


def wait_for_port(port: int, timeout_s: int = 30, label: str = "") -> int:
    print(f"  [wait] {label} ready (max {timeout_s}s)...", end="", flush=True)
    for i in range(1, (timeout_s // 2) + 1):
        time.sleep(2)
        if port_in_use(port):
            print(f" {C.G}[OK] {i} checks{C.X}")
            return i
    print(f" {C.Y}[timeout]{C.X}")
    return -1


def kill_pid(pid: int, label: str = "") -> bool:
    if not pid or not is_alive(pid):
        return False
    print(f"  [stop] {label} PID {pid}", end="", flush=True)
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=5, creationflags=CREATE_NO_WINDOW,
            )
        else:
            os.kill(pid, signal.SIGTERM)
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
        for _ in range(10):
            if not is_alive(pid):
                print(f" {C.G}[OK]{C.X}")
                return True
            time.sleep(0.3)
        print(f" {C.R}[failed]{C.X}")
        return False
    except Exception as e:
        print(f" {C.R}[error: {e}]{C.X}")
        return False


def read_pid_file(path: Path) -> int:
    try:
        if path.exists():
            return int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        pass
    return 0


def write_pid_file(path: Path, pid: int):
    path.write_text(str(pid), encoding="utf-8")


# ===== Actions =====
def start_local():
    if port_in_use(BACKEND_PORT):
        # R10.5.23: 端口冲突给明确指引, 不静默 fail. 之前只 warn + return,
        # 但 frontend 还会继续启动, 然后用户看到"前端连不上后端"困惑.
        print(f"  {C.R}[error] port {BACKEND_PORT} is already in use!{C.X}")
        print()
        print(f"  Likely cause: 之前手动启动的 uvicorn / gunicorn / 其他 dev server 还在跑.")
        print(f"  Frontend 端 vite.config.ts proxy target 默认指向 :{BACKEND_PORT},")
        print(f"  如果你在其他端口跑后端, 必须同步改 frontend/vite.config.ts 的 proxy target.")
        print()
        print(f"  Solutions:")
        print(f"    [A] 释放 :{BACKEND_PORT} 端口:")
        print(f"          netstat -ano | findstr :{BACKEND_PORT}")
        print(f"          taskkill /F /PID <上面最后一列的 PID>")
        print(f"    [B] 用其他端口跑后端 + 改 vite proxy:")
        print(f"          set BACKEND_PORT=8766 && python scholarflow.py start")
        print(f"          # 然后改 frontend/vite.config.ts proxy target → 8766")
        print(f"    [C] 跑 `python scholarflow.py stop` 杀本脚本启动过的进程 (如果有)")
        return
    if port_in_use(FRONTEND_PORT):
        print(f"  {C.R}[error] port {FRONTEND_PORT} is already in use!{C.X}")
        print(f"  Solutions:")
        print(f"    [A] 释放 :{FRONTEND_PORT} 端口: netstat -ano | findstr :{FRONTEND_PORT}")
        print(f"    [B] 用其他端口: set FRONTEND_PORT=5180 && python scholarflow.py start")
        return

    print(f"  [1/2] Starting backend (uvicorn :{BACKEND_PORT})...")
    backend_log = open(BACKEND_LOG, "w", encoding="utf-8", errors="replace")
    print(f"         log: {BACKEND_LOG}")
    # R10.5.12: 透传 ENVIRONMENT 让后端走对应限流档 (dev/test/prod).
    # 默认 dev, 想切 prod: shell 里 set ENVIRONMENT=prod 再 start.
    child_env = os.environ.copy()
    env_label = child_env.get("ENVIRONMENT", "dev (default)")
    print(f"         ENVIRONMENT={env_label}")
    bp = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
        cwd=str(ROOT),
        env=child_env,  # 显式传 env (Windows 默认会继承, 但显式更稳)
        stdout=backend_log,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )
    write_pid_file(BACKEND_PID_FILE, bp.pid)
    print(f"         PID {bp.pid}")

    print(f"  [2/2] Starting frontend (vite :{FRONTEND_PORT})...")
    print(f"         vite proxy → http://127.0.0.1:{BACKEND_PORT} (frontend/vite.config.ts)")
    frontend_log = open(FRONTEND_LOG, "w", encoding="utf-8", errors="replace")
    print(f"         log: {FRONTEND_LOG}")
    npx_cmd = shutil.which("npx") or "npx.cmd"
    fp = subprocess.Popen(
        [npx_cmd, "vite", "--host", "127.0.0.1", "--port", str(FRONTEND_PORT)],
        cwd=str(FRONTEND_DIR),
        stdout=frontend_log,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )
    write_pid_file(FRONTEND_PID_FILE, fp.pid)
    print(f"         PID {fp.pid}")

    backend_ready = wait_for_port(BACKEND_PORT, timeout_s=30, label=f"backend :{BACKEND_PORT}")
    frontend_ready = wait_for_port(FRONTEND_PORT, timeout_s=30, label=f"frontend :{FRONTEND_PORT}")

    print(f"\n  {C.G}[done] services started{C.X}")
    print(f"  backend  PID {bp.pid}  log: {BACKEND_LOG}")
    print(f"  frontend PID {fp.pid}  log: {FRONTEND_LOG}")
    if backend_ready == -1 or frontend_ready == -1:
        print(f"\n  {C.Y}[warn] one or both services didn't bind port in 30s. Check logs above.{C.X}")
    print(f"\n  {C.G}Open in browser: http://127.0.0.1:{FRONTEND_PORT}/{C.X}")


def start_docker():
    if not (ROOT / "docker-compose.yml").exists():
        print(f"  {C.R}[error] docker-compose.yml not found{C.X}")
        return
    # R10.5.12: 透传 ENVIRONMENT + SCHOLARFLOW_DB_DIR 给 docker compose 容器.
    env_label = os.environ.get("ENVIRONMENT", "dev (default)")
    print(f"  [1/1] docker compose up -d --build (ENVIRONMENT={env_label}) ...")
    r = subprocess.run(
        ["docker", "compose", "up", "-d", "--build"],
        cwd=str(ROOT), env=os.environ.copy(),
    )
    if r.returncode == 0:
        print(f"  {C.G}[done] docker containers started{C.X}")
    else:
        print(f"  {C.R}[error] docker compose exit code {r.returncode}{C.X}")


def stop_local():
    bp = read_pid_file(BACKEND_PID_FILE)
    fp = read_pid_file(FRONTEND_PID_FILE)
    if bp:
        kill_pid(bp, "backend")
        BACKEND_PID_FILE.unlink(missing_ok=True)
    else:
        print("  [skip] backend not running (no PID file)")
    if fp:
        kill_pid(fp, "frontend")
        FRONTEND_PID_FILE.unlink(missing_ok=True)
    else:
        print("  [skip] frontend not running (no PID file)")

    for port, label in [(BACKEND_PORT, "backend"), (FRONTEND_PORT, "frontend")]:
        if port_in_use(port):
            print(f"  {C.Y}[warn] port {port} still in use, trying to kill by port{C.X}")
            try:
                if sys.platform == "win32":
                    out = subprocess.run(
                        ["netstat", "-ano"], capture_output=True, text=True, timeout=5,
                        creationflags=CREATE_NO_WINDOW,
                    ).stdout
                    for line in out.splitlines():
                        if f":{port} " in line and "LISTENING" in line:
                            pid = line.strip().split()[-1]
                            kill_pid(int(pid), f"port {port}")
            except Exception as e:
                print(f"  {C.R}[error] port kill failed: {e}{C.X}")


def show_status():
    print(f"\n{C.H}  === Runtime Status ==={C.X}\n")
    # R10.5.12: 模式 + 限流档 + DB 目录 — 方便用户确认当前在哪个 ENVIRONMENT.
    env_label = os.environ.get("ENVIRONMENT", "dev (default)")
    db_dir = os.environ.get("SCHOLARFLOW_DB_DIR") or str(ROOT / "backend" / ".cache")
    print(f"  Mode:       {C.Y}{env_label}{C.X}")
    print(f"  DB dir:     {db_dir}")
    try:
        # 读后端日志里最后出现的 RATE_LIMITS 行作为参考 (后端启动时打印)
        if BACKEND_LOG.exists():
            tail = BACKEND_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
            rate_line = next((l for l in tail if "RATE_LIMITS" in l or "search=" in l), None)
            if rate_line:
                print(f"  Rate limit: {rate_line.strip()[:80]}")
    except Exception:
        pass
    print()
    for label, port, pid_file in [
        ("Backend", BACKEND_PORT, BACKEND_PID_FILE),
        ("Frontend", FRONTEND_PORT, FRONTEND_PID_FILE),
    ]:
        pid = read_pid_file(pid_file)
        alive = is_alive(pid) if pid else False
        in_use = port_in_use(port)
        status = f"{C.G}running (local){C.X}" if alive else (
            f"{C.Y}PID file stale{C.X}" if pid else f"{C.R}not running{C.X}"
        )
        port_status = f"{C.G}listening{C.X}" if in_use else f"{C.R}not listening{C.X}"
        print(f"  {label} (:{port})")
        print(f"    PID:    {pid or '-'}")
        print(f"    Process:{status}")
        print(f"    Port:   {port_status}")
        print()

    from shutil import which
    if which("docker"):
        print(f"  {C.H}  === Docker containers ==={C.X}")
        subprocess.run(
            ["docker", "ps", "--filter", "name=scholarflow",
             "--format", "    {{.Names}}  {{.Status}}  {{.Ports}}"],
        )
    print()


def show_logs():
    print(f"\n{C.H}  === Logs (last 30 lines) ==={C.X}\n")
    print("  [1] backend")
    print("  [2] frontend")
    print("  [3] backend live (Ctrl+C to exit)")
    print("  [4] frontend live (Ctrl+C to exit)")
    print("  [0] back\n")
    try:
        choice = input("  choose: ").strip()
    except EOFError:
        return
    log_map = {"1": BACKEND_LOG, "2": FRONTEND_LOG}
    if choice in log_map:
        path = log_map[choice]
        if not path.exists():
            print(f"  [none] {path.name} not found")
        else:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines[-30:]:
                    print(f"    {line}")
            except Exception as e:
                print(f"  [error] {e}")
    elif choice in ("3", "4"):
        path = log_map[choice[1]]
        if not path.exists():
            print(f"  [none] {path.name} not found")
            return
        print(f"  tail -f {path} (Ctrl+C to exit)")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.5)
                        continue
                    print(f"    {line.rstrip()}")
        except KeyboardInterrupt:
            pass


def install_deps():
    py = sys.executable
    print(f"  [1/3] upgrade pip ...")
    subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip"], cwd=str(ROOT))
    print(f"  [2/3] backend deps (backend/requirements.txt) ...")
    subprocess.run(
        [py, "-m", "pip", "install", "-r", str(ROOT / "backend" / "requirements.txt")],
        cwd=str(ROOT),
    )
    print(f"  [3/3] dev deps (requirements-dev.txt) ...")
    subprocess.run(
        [py, "-m", "pip", "install", "-r", str(ROOT / "requirements-dev.txt")],
        cwd=str(ROOT),
    )

    from shutil import which
    if which("npm"):
        print(f"  [frontend] npm install ...")
        subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=str(FRONTEND_DIR))
    else:
        print(f"  {C.R}[error] npm not in PATH, skip frontend{C.X}")

    if which("docker"):
        ans = input("  [optional] build Docker image? [y/N]: ").strip().lower()
        if ans == "y":
            print("  [docker] docker compose build ...")
            subprocess.run(["docker", "compose", "build"], cwd=str(ROOT))

    print(f"  {C.G}[done] dependencies installed{C.X}")


def clean_cache():
    print(f"\n  {C.Y}[warn] will delete:{C.X}")
    print(f"    - {CACHE_DIR} (SQLite cache)")
    print(f"    - {LOG_DIR}/*.log (logs)")
    print(f"    - {FRONTEND_DIR / 'dist'} (frontend build)")
    ans = input("  confirm? [y/N]: ").strip().lower()
    if ans != "y":
        print("  [cancelled]")
        return
    import shutil
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
        print(f"  {C.G}[OK] {CACHE_DIR}{C.X}")
    for f in LOG_DIR.glob("*.log"):
        f.unlink(missing_ok=True)
        print(f"  {C.G}[OK] {f}{C.X}")
    dist = FRONTEND_DIR / "dist"
    if dist.exists():
        shutil.rmtree(dist, ignore_errors=True)
        print(f"  {C.G}[OK] {dist}{C.X}")
    print(f"  {C.G}[done]{C.X}")


def open_browser():
    print("  opening browser ...")
    webbrowser.open(f"http://127.0.0.1:{FRONTEND_PORT}/")
    webbrowser.open(f"http://127.0.0.1:{BACKEND_PORT}/docs")


# ===== Main =====
def run_interactive():
    actions = {
        "1": ("Start - local mode", start_local),
        "2": ("Start - Docker mode", start_docker),
        "3": ("Stop", stop_local),
        "4": ("Restart", lambda: (stop_local(), time.sleep(2), start_local())),
        "5": ("Status", show_status),
        "6": ("Logs", show_logs),
        "7": ("Install deps", install_deps),
        "8": ("Clean cache", clean_cache),
        "9": ("Open browser", open_browser),
    }
    while True:
        try:
            banner()
            menu()
            choice = input("\n  choose [0-9]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {C.G}bye!{C.X}\n")
            return
        if choice == "0":
            print(f"\n  {C.G}bye!{C.X}\n")
            return
        if choice in actions:
            label, fn = actions[choice]
            print(f"\n  === {label} ===\n")
            try:
                fn()
            except Exception as e:
                import traceback
                print(f"  {C.R}[error] {e}{C.X}")
                traceback.print_exc()
            print()
            try:
                input("  press any key to continue...")
            except (EOFError, KeyboardInterrupt):
                pass
        else:
            print(f"  {C.R}[error] invalid choice{C.X}")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "start":
            start_local()
        elif cmd == "start-docker":
            start_docker()
        elif cmd == "stop":
            stop_local()
        elif cmd == "status":
            show_status()
        elif cmd == "logs":
            target = sys.argv[2] if len(sys.argv) > 2 else "backend"
            log = BACKEND_LOG if target == "backend" else FRONTEND_LOG
            if log.exists():
                print(log.read_text(encoding="utf-8", errors="replace"))
            else:
                print(f"[none] {log}")
        else:
            print(f"unknown command: {cmd}")
            print("usage: python scholarflow.py [start|stop|status|logs backend|logs frontend]")
            sys.exit(1)
    else:
        run_interactive()


if __name__ == "__main__":
    main()
