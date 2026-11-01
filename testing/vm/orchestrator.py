#!/usr/bin/env python3
"""
Homelab Blueprint - VM End-to-End Test Suite Orchestrator
Executes on the Windows host machine to manage the full lifecycle of an ephemeral
Ubuntu 24.04 LTS test virtual machine using Canonical Multipass (Hyper-V) or WSL2.

Flow:
  1. Detects available hypervisor engine (Multipass or WSL2 Ubuntu 24.04 micro-VM)
  2. Ensures clean isolated test guest environment
  3. Archives and stages the blueprint cleanly into /opt/homelab-blueprint
  4. Executes the in-guest lifecycle and invariant assertion runner
  5. Transfers JUnit XML / JSON test artifacts back to host
  6. Automatically tears down / cleans up test artifacts
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional

# Ensure UTF-8 output on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_VM_NAME = "homelab-e2e"
DEFAULT_UBUNTU_RELEASE = "24.04"


def find_multipass_binary() -> Optional[str]:
    """Locates the multipass executable on PATH or default Windows installation folders"""
    bin_path = shutil.which("multipass")
    if bin_path:
        return bin_path

    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Multipass" / "bin" / "multipass.exe",
        Path(r"C:\Program Files\Multipass\bin\multipass.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


class VMOrchestrator:
    def __init__(
        self,
        engine: str = "auto",
        vm_name: str = DEFAULT_VM_NAME,
        cpus: int = 2,
        memory: str = "4G",
        disk: str = "20G",
        keep_vm: bool = False
    ):
        self.requested_engine = engine
        self.vm_name = vm_name
        self.cpus = cpus
        self.memory = memory
        self.disk = disk
        self.keep_vm = keep_vm
        self.start_time = time.time()
        self.multipass_bin = find_multipass_binary()
        self.active_engine = self._detect_engine()

    def log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [VM-HOST] {msg}", flush=True)

    def _detect_engine(self) -> str:
        """Determines whether to use Multipass Hyper-V or WSL2 hardware VM"""
        if self.requested_engine in ("multipass", "wsl"):
            return self.requested_engine

        # Auto detection: Check if Multipass can access Hyper-V
        if self.multipass_bin:
            try:
                res = subprocess.run([self.multipass_bin, "networks"], capture_output=True, text=True, timeout=5)
                if "Hyper-V service does not exist" not in res.stderr and res.returncode == 0:
                    return "multipass"
            except Exception:
                pass

        # Check if WSL2 is ready
        wsl_bin = shutil.which("wsl")
        if wsl_bin:
            try:
                res = subprocess.run([wsl_bin, "-l", "-v"], capture_output=True, text=True, timeout=5)
                if "Ubuntu-24.04" in res.stdout or "Ubuntu" in res.stdout:
                    return "wsl"
            except Exception:
                pass

        return "wsl"

    # =========================================================================
    # WSL2 Engine Implementation
    # =========================================================================
    def _run_wsl(self, cmd: List[str], check: bool = False) -> subprocess.CompletedProcess:
        full_cmd = ["wsl", "-d", "Ubuntu-24.04", "-u", "root", "--"] + cmd
        return subprocess.run(full_cmd, capture_output=True, text=True, check=check)

    def _stage_wsl(self) -> bool:
        self.log("📦 Packaging clean blueprint repository (excluding APK caches & transients)...")
        temp_tar = Path(r"C:\temp\blueprint_clean.tar.gz")
        temp_tar.parent.mkdir(parents=True, exist_ok=True)

        cmd = ["git", "-C", str(REPO_ROOT), "archive", "--format=tar.gz", "-o", str(temp_tar), "HEAD"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            self.log(f"❌ Failed to create git archive: {res.stderr}")
            return False

        self.log(f"  Archive created ({temp_tar.stat().st_size} bytes). Staging into VM /opt/homelab-blueprint...")
        self._run_wsl(["mkdir", "-p", "/opt/homelab-blueprint"])
        self._run_wsl(["tar", "-xzf", "/mnt/c/temp/blueprint_clean.tar.gz", "-C", "/opt/homelab-blueprint"])
        self._run_wsl(["chown", "-R", "root:root", "/opt/homelab-blueprint"])
        return True

    def _execute_wsl(self) -> int:
        self.log("🎯 Launching In-Guest Test Suite inside Ubuntu 24.04 VM...")
        guest_script = "/opt/homelab-blueprint/testing/vm/test_vm_lifecycle.py"
        proc = subprocess.run(["wsl", "-d", "Ubuntu-24.04", "-u", "root", "--", "python3", guest_script])
        return proc.returncode

    def _retrieve_wsl(self, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"📥 Retrieving test artifacts to '{output_dir}'...")
        for r_name in ["vm_test_results.json", "vm_test_results.xml"]:
            res = self._run_wsl(["cat", f"/tmp/{r_name}"])
            if res.returncode == 0 and res.stdout.strip():
                (output_dir / r_name).write_text(res.stdout, encoding="utf-8")
                self.log(f"  -> Successfully retrieved {r_name}")

    def _teardown_wsl(self):
        if self.keep_vm:
            self.log("📌 Flag --keep-vm active. Retaining VM state.")
            self.log("   -> Access shell via: wsl -d Ubuntu-24.04")
            return
        self.log("🧹 Cleaning up temporary test artifacts in VM...")
        self._run_wsl(["rm", "-f", "/drive_media.img"])
        self.log("✅ Guest test artifacts cleaned.")

    # =========================================================================
    # Multipass Engine Implementation
    # =========================================================================
    def _run_multipass(self, args: List[str], capture: bool = True, timeout: int = 600) -> subprocess.CompletedProcess:
        cmd = [self.multipass_bin] + args
        self.log(f"$ multipass {' '.join(args)}")
        return subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)

    def _stage_multipass(self) -> bool:
        temp_tar = Path(r"C:\temp\blueprint_clean.tar.gz")
        temp_tar.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(REPO_ROOT), "archive", "--format=tar.gz", "-o", str(temp_tar), "HEAD"], check=True)

        res = self._run_multipass(["transfer", str(temp_tar), f"{self.vm_name}:/tmp/blueprint.tar.gz"])
        if res.returncode != 0:
            return False

        self._run_multipass(["exec", self.vm_name, "--", "sudo", "mkdir", "-p", "/opt/homelab-blueprint"])
        self._run_multipass(["exec", self.vm_name, "--", "sudo", "tar", "-xzf", "/tmp/blueprint.tar.gz", "-C", "/opt/homelab-blueprint"])
        return True

    def _execute_multipass(self) -> int:
        guest_script = "/opt/homelab-blueprint/testing/vm/test_vm_lifecycle.py"
        proc = subprocess.run([self.multipass_bin, "exec", self.vm_name, "--", "sudo", "python3", guest_script])
        return proc.returncode

    def _retrieve_multipass(self, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        for r_name in ["vm_test_results.json", "vm_test_results.xml"]:
            src = f"{self.vm_name}:/tmp/{r_name}"
            dst = output_dir / r_name
            self._run_multipass(["transfer", src, str(dst)])

    def _teardown_multipass(self):
        if self.keep_vm:
            return
        self._run_multipass(["delete", self.vm_name])
        self._run_multipass(["purge"])

    # =========================================================================
    # Main Workflow
    # =========================================================================
    def run_all(self, report_dir: Optional[Path] = None) -> bool:
        if report_dir is None:
            report_dir = REPO_ROOT / "testing" / "vm" / "reports"

        self.log("============================================================")
        self.log(f"      AUTOMATED VM END-TO-END HARNESS (Engine: {self.active_engine.upper()})")
        self.log("============================================================")

        success = False
        try:
            if self.active_engine == "wsl":
                if not self._stage_wsl():
                    return False
                exit_code = self._execute_wsl()
                success = (exit_code == 0)
                self._retrieve_wsl(report_dir)
            else:
                self.log(f"🚀 Provisioning fresh Multipass VM '{self.vm_name}'...")
                self._run_multipass(["launch", DEFAULT_UBUNTU_RELEASE, "--name", self.vm_name, "--cpus", str(self.cpus), "--memory", self.memory, "--disk", self.disk], capture=False)
                if not self._stage_multipass():
                    return False
                exit_code = self._execute_multipass()
                success = (exit_code == 0)
                self._retrieve_multipass(report_dir)

            return success
        finally:
            if self.active_engine == "wsl":
                self._teardown_wsl()
            else:
                self._teardown_multipass()
            total_duration = time.time() - self.start_time
            self.log(f"🏁 VM Orchestrator run finished in {total_duration:.2f}s. Verdict: {'PASS' if success else 'FAIL'}")


def main():
    parser = argparse.ArgumentParser(description="Homelab Blueprint VM E2E Orchestrator (Windows Host)")
    parser.add_argument("--run-all", action="store_true", help="Execute complete VM provisioning, testing, and teardown")
    parser.add_argument("--engine", choices=["auto", "wsl", "multipass"], default="auto", help="Hypervisor virtualization engine (default: auto)")
    parser.add_argument("--keep-vm", action="store_true", help="Do not purge VM state after testing")
    parser.add_argument("--vm-name", default=DEFAULT_VM_NAME, help=f"Name of the VM (default: {DEFAULT_VM_NAME})")
    parser.add_argument("--cpus", type=int, default=2, help="vCPU count (default: 2)")
    parser.add_argument("--memory", default="4G", help="RAM size (default: 4G)")
    parser.add_argument("--disk", default="20G", help="Root disk size (default: 20G)")
    parser.add_argument("--reports-dir", type=str, default="", help="Directory to save retrieved test reports")

    args = parser.parse_args()

    orchestrator = VMOrchestrator(
        engine=args.engine,
        vm_name=args.vm_name,
        cpus=args.cpus,
        memory=args.memory,
        disk=args.disk,
        keep_vm=args.keep_vm
    )

    if args.run_all:
        rep_dir = Path(args.reports_dir).resolve() if args.reports_dir else None
        success = orchestrator.run_all(report_dir=rep_dir)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
