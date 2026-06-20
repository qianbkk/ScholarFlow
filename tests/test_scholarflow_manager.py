"""scripts/scholarflow.py cross-platform launcher smoke tests (R10.5.40+).

Replaces the R10.5.23-era tests that targeted the old root-level scholarflow.py
(which used start_local / stop_local / BACKEND_PORT constants). R10.5.41
deleted the old launcher; the replacement is scripts/scholarflow.py with a
completely different subcommand-driven API (start/stop/restart/status/logs/
install/clean/open).

R10.5.52 cleanup: --v4 flag and newversion/ path were removed (v4 experimental
deleted). Test 4 now asserts v4 absence to prevent regression.

These tests are static: read the file, assert presence + shape of public API.
They do NOT import or exec the script (which would risk subprocess side-effects
during pytest collection).
"""
from __future__ import annotations

import re
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

SCHOLARFLOW_PY = (ROOT / "scripts" / "scholarflow.py").read_text(encoding="utf-8")
VITE_CFG = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")


# ===== Test 1: launcher lives in scripts/ not root =====
def test_launcher_path_is_scripts_scholarflow():
    """R10.5.41 cleanup: the launcher moved to scripts/scholarflow.py so the
    project root doesn't carry a Windows-only .bat. The old root-level
    scholarflow.py was git-rm'd in the same commit.
    """
    assert (ROOT / "scripts" / "scholarflow.py").is_file(), (
        "scripts/scholarflow.py missing — R10.5.41 cleanup expected the "
        "launcher to live in scripts/."
    )
    assert not (ROOT / "scholarflow.py").exists(), (
        "Root-level scholarflow.py should have been removed in R10.5.41 "
        "cleanup; if you re-introduced it, this test is now out of date."
    )
    assert not (ROOT / "scholarflow.bat").exists(), (
        "scholarflow.bat (Windows .bat) was removed in R10.5.41 in favor of "
        "the cross-platform Python launcher."
    )


# ===== Test 2: shebang line + cross-platform marker =====
def test_launcher_has_shebang_and_platform_note():
    assert SCHOLARFLOW_PY.startswith("#!/usr/bin/env python3"), (
        "scripts/scholarflow.py must start with a shebang so it runs on Linux/macOS."
    )
    # Cross-platform coverage: the docstring or kill code must mention
    # the divergent platforms. Accept any of: Windows + Linux, Windows + POSIX,
    # Windows + macOS, etc. (don't over-specify).
    has_windows = "Windows" in SCHOLARFLOW_PY
    has_posix = "Linux" in SCHOLARFLOW_PY or "macOS" in SCHOLARFLOW_PY or "POSIX" in SCHOLARFLOW_PY
    assert has_windows and has_posix, (
        "Launcher should explicitly handle both Windows (taskkill) and "
        "POSIX (SIGTERM) PID kill paths."
    )


# ===== Test 3: 8 documented subcommands are wired =====
def test_launcher_exposes_all_eight_subcommands():
    """R10.5.40 spec: 8 subcommands. Each must have a `def cmd_*` function
    registered in build_parser().
    """
    expected = ["start", "stop", "restart", "status", "logs", "install", "clean", "open"]
    for sub in expected:
        func = f"def cmd_{sub}("
        assert func in SCHOLARFLOW_PY, f"missing {func} definition"
    # build_parser must register all 8
    parser_block = SCHOLARFLOW_PY.split("def build_parser(")[1] if "def build_parser(" in SCHOLARFLOW_PY else ""
    for sub in expected:
        # Each subcommand should appear in the add_subparsers block too.
        assert f'"{sub}"' in parser_block, (
            f'subcommand "{sub}" missing from build_parser() subparsers block'
        )


# ===== Test 4: --v4 flag was removed in R10.5.52 (v4 experimental) =====
def test_v4_flag_removed():
    """R10.5.52 cleanup: v4 experimental removed; --v4 flag must NOT be present.

    Regression guard: if someone re-introduces the --v4 flag pointing at
    newversion/ (now deleted), this test fails fast.
    """
    assert '"--v4"' not in SCHOLARFLOW_PY and "'--v4'" not in SCHOLARFLOW_PY, (
        "--v4 flag was removed in R10.5.52 (v4 experimental deleted); "
        "do not re-introduce — see BACKLOG.md H-002 (已决策: 删 v4)."
    )
    # v4 ports (9000/6173) and v4 paths (newversion/) must NOT appear in
    # the live launcher source. (May appear in test docstrings as historical
    # notes — this test scans only the launcher.)
    assert "6173" not in SCHOLARFLOW_PY, "v4 frontend port 6173 must not be in launcher"
    assert "9000" not in SCHOLARFLOW_PY, "v4 backend port 9000 must not be in launcher"
    assert "newversion" not in SCHOLARFLOW_PY, (
        "newversion/ path must not be in launcher (v4 deleted in R10.5.52)"
    )
    # v1 ports must still be present
    assert "5173" in SCHOLARFLOW_PY, "missing v1 frontend port 5173"
    assert "8000" in SCHOLARFLOW_PY, "missing v1 backend port 8000"


# ===== Test 5: port detection (avoid hardcoded "in use" assumptions) =====
def test_launcher_uses_socket_for_port_check():
    """port_free() must use real socket.connect_ex() to detect in-use ports,
    not naive string parsing of netstat output. Verify the signature + body.
    """
    assert "def port_free(" in SCHOLARFLOW_PY
    # socket import is the tell
    assert "import socket" in SCHOLARFLOW_PY
    # The check itself
    assert "connect_ex" in SCHOLARFLOW_PY or "connect((" in SCHOLARFLOW_PY, (
        "port_free should use socket.connect_ex or socket.connect to test "
        "port availability; do not regress to parsing netstat/ss text."
    )


# ===== Test 6: socket-bind semantics (independent of the launcher) =====
def test_socket_bind_and_release_semantics():
    """Same socket semantics test as R10.5.23 — kept for regression. Bind a
    port, verify connect succeeds; close it, verify connect fails.
    """
    free_port = 49152
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", free_port))
    s.listen(1)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect(("127.0.0.1", free_port))
            in_use = True
        except (ConnectionRefusedError, socket.timeout, OSError):
            in_use = False
    s.close()
    assert in_use is True, "socket.connect should succeed against bind+listen"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect(("127.0.0.1", free_port))
            in_use = True
        except (ConnectionRefusedError, socket.timeout, OSError):
            in_use = False
    assert in_use is False, "socket.close should release the port"


# ===== Test 7: PID file persistence =====
def test_launcher_persists_pids_to_disk():
    """read_pids / write_pids must hit the LOGS dir, not /tmp, so a restart
    on the same machine finds the prior process state.
    """
    assert "PIDFILE" in SCHOLARFLOW_PY, "missing PIDFILE constant"
    assert "read_pids" in SCHOLARFLOW_PY
    assert "write_pids" in SCHOLARFLOW_PY
    # LOGS must be under the project, not /tmp
    assert "LOGS = ROOT" in SCHOLARFLOW_PY or "LOGS = Path" in SCHOLARFLOW_PY, (
        "LOGS dir should be project-relative, not /tmp"
    )


# ===== Test 8: vite.config.ts frontend port matches v1 =====
def test_vite_config_frontend_port_5173():
    """vite.config.ts server.port = 5173 must match scripts/scholarflow.py
    v1 frontend port constant. Regression guard against R10.5.20-style
    port drift.
    """
    m = re.search(r"port:\s*(\d+)", VITE_CFG)
    assert m, "vite.config.ts missing server.port"
    assert int(m.group(1)) == 5173, (
        f"vite.config.ts port {m.group(1)} != 5173 (R10.5.20 regression shape)"
    )


# ===== Test 9: --help produces a real usage string =====
def test_launcher_help_mentions_scholarflow():
    """--help output should be self-describing (project name visible)."""
    # Check the launcher mentions the project name in its module docstring
    # and in print() calls so --help / status output makes the project clear.
    assert "ScholarFlow" in SCHOLARFLOW_PY, "launcher source must mention ScholarFlow"
    # argparse description or epilog
    assert "description=" in SCHOLARFLOW_PY or "epilog=" in SCHOLARFLOW_PY, (
        "Launcher should set argparse description= and/or epilog= so --help "
        "output is self-describing."
    )


# ===== Test 10: launcher does NOT depend on any non-stdlib package =====
def test_launcher_is_stdlib_only():
    """scripts/scholarflow.py must use only Python stdlib (no psutil, no
    requests, no click). This keeps the launcher runnable on any box
    that has Python, no venv setup needed.
    """
    imports = re.findall(r"^(?:from\s+(\S+)\s+import|import\s+(\S+))", SCHOLARFLOW_PY, re.M)
    flat = [a or b for a, b in imports]
    for mod in flat:
        # Allow relative imports of own modules and stdlib
        if mod.startswith("."):
            continue
        top = mod.split(".")[0]
        # Disallow: psutil, requests, click, typer, rich
        assert top not in {"psutil", "requests", "click", "typer", "rich"}, (
            f"launcher must not depend on {top!r}; use stdlib only."
        )
