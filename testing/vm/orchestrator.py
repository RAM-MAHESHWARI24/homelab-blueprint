#!/usr/bin/env python3
"""
Homelab Blueprint - VM End-to-End Test Suite Orchestrator
Executes on the Windows host machine to manage the full lifecycle of an ephemeral
Ubuntu 24.04 LTS test virtual machine using Canonical Multipass (Hyper-V).

Flow:
  1. Detects host Multipass hypervisor CLI
  2. Launches isolated Ubuntu 24.04 VM (2 vCPU, 4GB RAM, 20GB root disk)
  3. Archives and provisions the blueprint into the VM at /opt/homelab-blueprint
  4. Executes the in-guest lifecycle and invariant assertion runner
  5. Transfers JUnit XML / JSON test artifacts back to host
  6. Automatically purges the VM (unless --keep-vm is specified)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
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


def find_multipass_binary() -> str:
    """Locates the multipass executable on PATH or default Windows installation folders"""
    bin_path = shutil.which("multipass")
    if bin_path:
        return bin_path

    # Standard Windows install locations
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Multipass" / "bin" / "multipass.exe",
        Path(r"C:\Program Files\Multipass\bin\multipass.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    raise FileNotFoundError("Canonical Multipass executable not found. Ensure Multipass is installed on Windows.")


class VMOrchestrator:
    def __init__(self, vm_name: str = DEFAULT_VM_NAME, cpus: int = 2, memory: str = "4G", disk: str = "20G", keep_vm: bool = False):
        self.multipass = find_multipass_binary()
        self.vm_name = vm_name
        self.cpus = cpus
        self.memory = memory
        self.disk = disk
        self.keep_vm = keep_vm
        self.start_time = time.time()

    def log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [VM-HOST] {msg}", flush=True)

    def run_multipass(self, args: List[str], capture: bool = True, timeout: int = 600) -> subprocess.CompletedProcess:
        cmd = [self.multipass] + args
        self.log(f"$ multipass {' '.join(args)}")
        return subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)

    def instance_exists(self) -> bool:
        """Checks if the VM instance currently exists in Multipass"""
        res = self.run_multipass(["list", "--format", "json"])
        if res.returncode == 0:
            try:
                data = json.loads(res.stdout)
                for inst in data.get("list", []):
                    if inst.get("name") == self.vm_name:
                        return True
            except Exception:
                pass
        return False

    def teardown(self):
        """Purges the test VM instance from the hypervisor"""
        if self.keep_vm:
            self.log(f"📌 Flag --keep-vm active. Retaining VM '{self.vm_name}'.")
            res = self.run_multipass(["info", self.vm_name, "--format", "json"])
            try:
                info = json.loads(res.stdout).get("info", {}).get(self.vm_name, {})
                ipv4 = info.get("ipv4", ["unknown"])[0]
                self.log(f"   -> VM IPv4: {ipv4}")
                self.log(f"   -> Access shell via: multipass shell {self.vm_name}")
            except Exception:
                pass
            return

        self.log(f"🧹 Tearing down ephemeral VM '{self.vm_name}'...")
        self.run_multipass(["delete", self.vm_name])
        self.run_multipass(["purge"])
        self.log("✅ VM deleted and storage purged.")

    def launch_vm(self) -> bool:
        """Launches a pristine Ubuntu 24.04 instance"""
        if self.instance_exists():
            self.log(f"Instance '{self.vm_name}' already exists. Deleting previous instance...")
            self.run_multipass(["delete", self.vm_name])
            self.run_multipass(["purge"])

        self.log(f"🚀 Provisioning fresh Ubuntu {DEFAULT_UBUNTU_RELEASE} instance '{self.vm_name}' ({self.cpus} vCPUs, {self.memory} RAM, {self.disk} Disk)...")
        launch_args = [
            "launch", DEFAULT_UBUNTU_RELEASE,
            "--name", self.vm_name,
            "--cpus", str(self.cpus),
            "--memory", self.memory,
            "--disk", self.disk
        ]
        res = self.run_multipass(launch_args, capture=False, timeout=600)
        if res.returncode != 0:
            self.log(f"❌ Failed to launch Multipass VM.")
            return False

        self.log("⏳ Waiting for VM cloud-init to finish...")
        self.run_multipass(["exec", self.vm_name, "--", "cloud-init", "status", "--wait"])
        return True

    def transfer_blueprint_to_vm(self) -> bool:
        """Packs the local blueprint into a clean tarball and transfers it into the VM"""
        self.log("📦 Packaging local repository into deployment bundle...")
        temp_dir = Path(tempfile.mkdtemp(prefix="homelab_e2e_archive_"))
        archive_path = temp_dir / "blueprint.tar.gz"

        def _tar_filter(tarinfo):
            # Exclude transient git / cache data
            name = tarinfo.name
            if any(part in name for part in [".git", "__pycache__", ".pytest_cache", "venv"]):
                return None
            return tarinfo

        try:
            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(str(REPO_ROOT), arcname="homelab-blueprint", filter=_tar_filter)

            self.log(f"  Archive created ({archive_path.stat().st_size} bytes). Transferring to VM...")
            res = self.run_multipass(["transfer", str(archive_path), f"{self.vm_name}:/tmp/blueprint.tar.gz"])
            if res.returncode != 0:
                self.log(f"❌ Failed to transfer blueprint archive: {res.stderr}")
                return False

            self.log("  Extracting blueprint into /opt/homelab-blueprint inside VM...")
            self.run_multipass(["exec", self.vm_name, "--", "sudo", "mkdir", "-p", "/opt"])
            self.run_multipass(["exec", self.vm_name, "--", "sudo", "rm", "-rf", "/opt/homelab-blueprint"])
            self.run_multipass(["exec", self.vm_name, "--", "sudo", "tar", "-xzf", "/tmp/blueprint.tar.gz", "-C", "/opt"])
            self.run_multipass(["exec", self.vm_name, "--", "sudo", "chown", "-R", "ubuntu:ubuntu", "/opt/homelab-blueprint"])
            self.log("✅ Blueprint successfully staged in VM at /opt/homelab-blueprint.")
            return True
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def execute_in_guest_suite(self) -> int:
        """Executes the in-guest lifecycle test script inside the VM, streaming stdout/stderr"""
        self.log("🎯 Launching In-Guest Test Suite inside VM...")
        guest_script = "/opt/homelab-blueprint/testing/vm/test_vm_lifecycle.py"

        # Stream output directly to console
        proc = subprocess.run(
            [self.multipass, "exec", self.vm_name, "--", "sudo", "python3", guest_script]
        )
        return proc.returncode

    def retrieve_test_reports(self, output_dir: Path):
        """Transfers JUnit XML and JSON test reports from the VM to the host"""
        output_dir.mkdir(parents=True, exist_ok=True)
        self.log(f"📥 Retrieving test artifacts from VM to '{output_dir}'...")

        for report_file in ["vm_test_results.json", "vm_test_results.xml"]:
            src = f"{self.vm_name}:/tmp/{report_file}"
            dst = output_dir / report_file
            res = self.run_multipass(["transfer", src, str(dst)])
            if res.returncode == 0 and dst.exists():
                self.log(f"  -> Successfully retrieved {dst.name}")
            else:
                self.log(f"  -> Notice: {report_file} was not generated or could not be transferred.")

    def run_all(self, report_dir: Optional[Path] = None) -> bool:
        """Executes the complete end-to-end VM test orchestration"""
        if report_dir is None:
            report_dir = REPO_ROOT / "testing" / "vm" / "reports"

        self.log("============================================================")
        self.log("      AUTOMATED VM END-TO-END (E2E) TEST HARNESS")
        self.log("============================================================")

        success = False
        try:
            if not self.launch_vm():
                return False

            if not self.transfer_blueprint_to_vm():
                return False

            exit_code = self.execute_in_guest_suite()
            success = (exit_code == 0)

            self.retrieve_test_reports(report_dir)

            return success
        finally:
            self.teardown()
            total_duration = time.time() - self.start_time
            self.log(f"🏁 VM Orchestrator run finished in {total_duration:.2f}s. Verdict: {'PASS' if success else 'FAIL'}")


def main():
    parser = argparse.ArgumentParser(description="Homelab Blueprint VM E2E Orchestrator (Windows Host)")
    parser.add_argument("--run-all", action="store_true", help="Execute complete VM provisioning, testing, and teardown")
    parser.add_argument("--keep-vm", action="store_true", help="Do not purge the VM after testing (allows interactive inspection)")
    parser.add_argument("--vm-name", default=DEFAULT_VM_NAME, help=f"Name of the VM (default: {DEFAULT_VM_NAME})")
    parser.add_argument("--cpus", type=int, default=2, help="vCPU count (default: 2)")
    parser.add_argument("--memory", default="4G", help="RAM size (default: 4G)")
    parser.add_argument("--disk", default="20G", help="Root disk size (default: 20G)")
    parser.add_argument("--teardown-only", action="store_true", help="Purge any existing test VM and exit")
    parser.add_argument("--reports-dir", type=str, default="", help="Directory to save retrieved test reports")

    args = parser.parse_args()

    orchestrator = VMOrchestrator(
        vm_name=args.vm_name,
        cpus=args.cpus,
        memory=args.memory,
        disk=args.disk,
        keep_vm=args.keep_vm
    )

    if args.teardown_only:
        orchestrator.teardown()
        sys.exit(0)

    if args.run_all:
        rep_dir = Path(args.reports_dir).resolve() if args.reports_dir else None
        success = orchestrator.run_all(report_dir=rep_dir)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
