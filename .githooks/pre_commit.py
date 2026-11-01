#!/usr/bin/env python3
"""
Homelab Blueprint - Tier 1 Pre-Commit Hook Engine
Performs rapid (< 3s) local verification on staged files before allowing a git commit:
  1. Python syntax & compilation check (py_compile)
  2. Secret & private key sanitization
  3. Documentation relative link integrity
  4. CLI interface sanity parsing (--help)
  5. Shell script static analysis (if shellcheck is available)
"""

import os
import re
import sys
import py_compile
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def get_staged_files():
    """Returns list of staged files (added, copied, modified)."""
    try:
        res = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True
        )
        return [f.strip() for f in res.stdout.splitlines() if f.strip()]
    except Exception:
        return []


def check_python_syntax(staged_files):
    py_files = [f for f in staged_files if f.endswith(".py")]
    if not py_files:
        return True, "No Python files staged"

    errors = []
    for rel_path in py_files:
        full_path = REPO_ROOT / rel_path
        if not full_path.exists():
            continue
        try:
            py_compile.compile(str(full_path), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(f"{rel_path}: {e}")

    if errors:
        return False, "\n".join(errors)
    return True, f"Verified {len(py_files)} Python file(s)"


def check_secrets(staged_files):
    """Scans staged files for high-risk private keys and token patterns."""
    secret_patterns = [
        (re.compile(r"-----BEGIN (?:RSA |OPENSSH |DSA |EC |PGP )?PRIVATE KEY-----"), "Private Key Block"),
        (re.compile(r"\bghp_[a-zA-Z0-9]{36}\b"), "GitHub Personal Access Token"),
        (re.compile(r"\bgithub_pat_[a-zA-Z0-9_]{82}\b"), "Fine-grained GitHub Token"),
        (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS Access Key ID"),
    ]

    findings = []
    for rel_path in staged_files:
        # Ignore sample, template, documentation files, and test fixtures
        if any(rel_path.endswith(ext) for ext in [".example", ".sample", ".png", ".jpg", ".jpeg", ".svg", ".ico"]):
            continue

        full_path = REPO_ROOT / rel_path
        if not full_path.exists() or full_path.is_dir():
            continue

        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            for pattern, label in secret_patterns:
                if pattern.search(content):
                    findings.append(f"{rel_path}: Contains {label}")
        except Exception:
            pass

    if findings:
        return False, "\n".join(findings)
    return True, "No leaked keys or unencrypted tokens found"


def check_doc_integrity(staged_files):
    md_staged = [f for f in staged_files if f.endswith(".md")]
    if not md_staged:
        return True, "No documentation modified"

    test_script = REPO_ROOT / "testing" / "test_docs_integrity.py"
    if not test_script.exists():
        return True, "test_docs_integrity.py not found, skipping"

    res = subprocess.run([sys.executable, str(test_script)], cwd=str(REPO_ROOT), capture_output=True, text=True)
    if res.returncode != 0:
        return False, res.stderr.strip() or res.stdout.strip()
    return True, f"Validated links across documentation ({len(md_staged)} staged)"


def check_cli_argument_parsing(staged_files):
    cli_tools = [
        "apps/immich-face-xmp-exporter/sync_space_faces.py",
        "apps/immich-face-xmp-exporter/export_faces_to_xmp.py",
        "setup/config_core/schema_migrator.py"
    ]
    staged_set = set(staged_files)
    to_verify = [t for t in cli_tools if t in staged_set]
    if not to_verify:
        return True, "No core CLI tools modified"

    errors = []
    for tool_rel in to_verify:
        full_tool = REPO_ROOT / tool_rel
        if not full_tool.exists():
            continue
        res = subprocess.run([sys.executable, str(full_tool), "--help"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        if res.returncode != 0:
            errors.append(f"{tool_rel} --help failed with exit code {res.returncode}")

    if errors:
        return False, "\n".join(errors)
    return True, f"Verified CLI argument parsing on {len(to_verify)} tool(s)"


def check_shell_scripts(staged_files):
    sh_files = [f for f in staged_files if f.endswith(".sh")]
    if not sh_files:
        return True, "No shell scripts modified"

    shellcheck_cmd = "shellcheck"
    try:
        probe = subprocess.run([shellcheck_cmd, "--version"], capture_output=True, text=True)
        if probe.returncode != 0:
            return True, "ShellCheck not installed locally (deferred to CI)"
    except Exception:
        return True, "ShellCheck not installed locally (deferred to CI)"

    errors = []
    for sh in sh_files:
        full_path = REPO_ROOT / sh
        if not full_path.exists():
            continue
        res = subprocess.run([shellcheck_cmd, "--severity=warning", str(full_path)], capture_output=True, text=True)
        if res.returncode != 0:
            errors.append(f"{sh}:\n{res.stdout}")

    if errors:
        return False, "\n".join(errors)
    return True, f"ShellCheck passed for {len(sh_files)} script(s)"


def main():
    staged = get_staged_files()
    if not staged:
        sys.exit(0)

    print("\n" + "=" * 62)
    print(" 🛡️  HOMELAB BLUEPRINT - TIER 1 PRE-COMMIT VERIFICATION")
    print("=" * 62)

    checks = [
        ("Python Syntax & Compilation", check_python_syntax),
        ("Secret Sanitization Scan", check_secrets),
        ("CLI Argument Parsing (--help)", check_cli_argument_parsing),
        ("Documentation & Link Integrity", check_doc_integrity),
        ("ShellScript Static Analysis", check_shell_scripts),
    ]

    all_passed = True
    for name, fn in checks:
        passed, msg = fn(staged)
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"[{status}] {name}")
        if not passed:
            all_passed = False
            for line in msg.splitlines():
                print(f"       -> {line}")
        elif "No " not in msg and "not " not in msg:
            print(f"       -> {msg}")

    print("-" * 62)
    if not all_passed:
        print("🚨 COMMIT REJECTED: One or more pre-commit quality checks failed.")
        print("   Fix the issues listed above before committing.")
        print("   (Emergency override: 'git commit --no-verify')")
        print("=" * 62 + "\n")
        sys.exit(1)

    print("🎉 ALL PRE-COMMIT CHECKS PASSED: Proceeding with commit.\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
