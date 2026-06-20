"""Smoke test for scripts/scholarflow.py cross-platform launcher (R10.5.40).

Verifies the CLI is invocable, prints a usage string that contains the word
"ScholarFlow", and that all subcommands are listed. Does not start servers.
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "scholarflow.py"


def test_help_contains_scholarflow():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, f"scholarflow --help failed: {result.stderr}"
    out = (result.stdout + result.stderr).lower()
    assert "scholarflow" in out, f"usage string missing 'ScholarFlow': {result.stdout}"


def test_help_lists_all_subcommands():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, timeout=15,
    )
    out = result.stdout + result.stderr
    for sub in ("start", "stop", "restart", "status", "logs", "install", "clean", "open"):
        assert sub in out, f"subcommand {sub!r} missing from --help output"


def test_no_v4_flag_in_help():
    """R10.5.52: v4 experimental removed. Ensure --v4 is no longer accepted.

    argparse should reject unknown flags with non-zero exit + error message.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "start", "--v4"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode != 0, "start --v4 should be rejected (v4 removed in R10.5.52)"
    assert "unrecognized arguments" in (result.stderr or "") or \
           "unrecognized" in (result.stderr or ""), \
        f"expected argparse rejection, got: {result.stderr[:200]}"