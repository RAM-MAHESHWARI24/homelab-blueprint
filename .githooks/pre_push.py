#!/usr/bin/env python3
"""
Homelab Blueprint - Tier 2 Pre-Push Hook Engine
Performs medium-weight validation before sending outbound commits to GitHub:
  1. Configuration schema integrity (schema_migrator.py --check)
  2. Setup wizard verification suite (test_setup.py)
  3. Control Hub unit smoke suite (test_standalone.py)
  4. Complete documentation link integrity
"""

import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_check(name, cmd, cwd=REPO_ROOT):
    print(f"\n▶ Running: {name}...")
    res = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if res.returncode == 0:
        print(f"✅ [PASS] {name}")
        return True, ""
    else:
        print(f"❌ [FAIL] {name}")
        err = res.stderr.strip() or res.stdout.strip()
        return False, err


def main():
    print("\n" + "=" * 62)
    print(" 🚀 HOMELAB BLUEPRINT - TIER 2 PRE-PUSH VERIFICATION")
    print("=" * 62)

    checks = [
        (
            "Configuration Schema Migration Check",
            [sys.executable, "setup/config_core/schema_migrator.py", "--check"],
            REPO_ROOT
        ),
        (
            "Setup Wizard Verification Test Suite",
            [sys.executable, "setup/test_setup.py"],
            REPO_ROOT
        ),
        (
            "Control Hub Standalone Unit Suite",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            REPO_ROOT / "apps" / "control-hub"
        ),
        (
            "Documentation Integrity & Anchor Verification",
            [sys.executable, "testing/test_docs_integrity.py"],
            REPO_ROOT
        )
    ]

    all_passed = True
    failed_reports = []

    for name, cmd, cwd in checks:
        passed, err = run_check(name, cmd, cwd=cwd)
        if not passed:
            all_passed = False
            failed_reports.append((name, err))

    print("\n" + "=" * 62)
    if not all_passed:
        print("🚨 PUSH REJECTED: One or more pre-push test suites failed.")
        print("   Fix regressions before pushing to remote origin.")
        for name, err in failed_reports:
            print(f"\n--- Failure Details: {name} ---")
            lines = err.splitlines()
            print("\n".join(lines[-15:]))
        print("\n" + "=" * 62)
        print("   (Emergency override: 'git push --no-verify')\n")
        sys.exit(1)

    print("🎉 ALL PRE-PUSH SUITES PASSED (100%): Proceeding with git push.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
