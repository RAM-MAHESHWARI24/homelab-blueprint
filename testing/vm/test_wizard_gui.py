#!/usr/bin/env python3
"""
GUI end-to-end test: fresh Multipass VM -> bootstrap -> Setup Wizard in a real
browser (Playwright) -> static-IP change confirmed from the new address ->
Control Hub indexer picker -> wiring checks inside the VM.

Runs on the host (Windows, macOS or Linux) with Multipass and Playwright:

    pip install playwright && python -m playwright install chromium
    python testing/vm/test_wizard_gui.py                    # install the pushed branch via bootstrap.sh
    python testing/vm/test_wizard_gui.py --source local     # install the local HEAD (unpushed commits)
    python testing/vm/test_wizard_gui.py --headed --keep-vm # watch it, keep the VM afterwards

Screenshots, the wizard log and a JSON summary land in testing/vm/reports/gui/<timestamp>/.
The VM is deleted at the end unless --keep-vm is given. No other VM is touched.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_SLUG = "RAM-MAHESHWARI24/homelab-blueprint"
WIZARD_URL_RE = re.compile(r"http://(\d+\.\d+\.\d+\.\d+):8000/\?token=([A-Za-z0-9_\-]+)")
REVERT_WINDOW_SEC = 120


class Step(Exception):
    """A failed check; the message is the finding."""


class GuiTest:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.vm = args.vm_name or f"hb-gui-{time.strftime('%m%d-%H%M')}"
        self.mp = shutil.which("multipass") or r"C:\Program Files\Multipass\bin\multipass.exe"
        self.report_dir = REPO_ROOT / "testing" / "vm" / "reports" / "gui" / time.strftime("%Y%m%d-%H%M%S")
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[dict] = []
        self.shot_no = 0
        self.vm_ip = ""
        self.new_ip = ""
        self.started = time.time()

    # ------------------------------------------------------------------ utils
    def log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        with open(self.report_dir / "run.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append({"step": name, "ok": ok, "detail": detail})
        self.log(f"{'PASS' if ok else 'FAIL'}  {name}{' - ' + detail if detail else ''}")
        if not ok:
            raise Step(f"{name}: {detail}")

    def multipass(self, *args: str, timeout: int = 600, check: bool = True, cwd: str = None) -> subprocess.CompletedProcess:
        # stdin=DEVNULL: `multipass exec` forwards stdin and otherwise waits on a pipe that never closes.
        res = subprocess.run([self.mp, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                             timeout=timeout, encoding="utf-8", errors="replace", cwd=cwd)
        if check and res.returncode != 0:
            raise Step(f"multipass {' '.join(args[:3])} failed: {res.stderr.strip() or res.stdout.strip()}")
        return res

    def vm_sh(self, script: str, timeout: int = 600, check: bool = True) -> subprocess.CompletedProcess:
        """Short commands only: on Windows, `multipass exec` stalls once stdout passes 4 KB. Use vm_read for files."""
        return self.multipass("exec", self.vm, "--", "sudo", "bash", "-c", script, timeout=timeout, check=check)

    def vm_read(self, path: str) -> str:
        """Reads a VM file through `multipass transfer` (no output-size limit). Empty string if missing."""
        self.vm_sh(f"test -f {path} && install -m 0644 {path} /tmp/hb-read.tmp || rm -f /tmp/hb-read.tmp", check=False, timeout=60)
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / "read.tmp"
            # Relative destination: multipass would read "C:" in a Windows path as an instance name.
            res = self.multipass("transfer", f"{self.vm}:/tmp/hb-read.tmp", "read.tmp", check=False, timeout=120, cwd=td)
            # On Windows multipass exits 2 after copying ("cannot set permissions for local file"); the file is fine.
            if dst.exists():
                return dst.read_text(encoding="utf-8", errors="replace")
            if res.returncode != 0 and "No such file" not in res.stderr:
                self.log(f"(transfer of {path} failed: {res.stderr.strip()[:200]})")
            return ""

    def shot(self, page, label: str) -> None:
        self.shot_no += 1
        path = self.report_dir / f"{self.shot_no:02d}-{label}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
        except Exception as e:  # a navigation in progress can make screenshots fail
            self.log(f"(screenshot {label} failed: {e})")

    @staticmethod
    def host_can_reach(ip: str) -> bool:
        flag = "-n" if platform.system() == "Windows" else "-c"
        wait = ["-w", "1000"] if platform.system() == "Windows" else ["-W", "1"]
        res = subprocess.run(["ping", flag, "1", *wait, ip], capture_output=True, text=True)
        return res.returncode == 0 and "TTL=" in res.stdout.upper()

    @staticmethod
    def http_ok(url: str, timeout: float = 3.0) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    # ------------------------------------------------------------------- VM
    def launch_vm(self) -> None:
        self.log(f"Launching fresh VM '{self.vm}' (Ubuntu 24.04, {self.args.cpus} CPU, {self.args.memory}, {self.args.disk})...")
        self.multipass("launch", "24.04", "--name", self.vm, "--cpus", str(self.args.cpus),
                       "--memory", self.args.memory, "--disk", self.args.disk, "--timeout", "900", timeout=1200)
        self.vm_ip = self.current_vm_ip()
        self.record("VM launched", bool(self.vm_ip), self.vm_ip)

    def current_vm_ip(self) -> str:
        info = json.loads(self.multipass("info", self.vm, "--format", "json").stdout)
        ips = info["info"][self.vm].get("ipv4", [])
        return next((ip for ip in ips if not ip.startswith(("172.17.", "172.18.", "172.19."))), ips[0] if ips else "")

    def read_wizard_log(self) -> str:
        """multipass exec occasionally hangs on Windows; keep each read short and retry."""
        try:
            return self.vm_read("/var/log/hb-wizard.log")
        except subprocess.TimeoutExpired:
            self.log("(multipass exec timed out reading the wizard log; retrying)")
            return ""

    def start_wizard(self) -> str:
        """Starts bootstrap (or setup.sh for --source local) detached, returns the printed wizard URL."""
        if self.args.reuse_vm:
            m = WIZARD_URL_RE.search(self.read_wizard_log())
            running = self.vm_sh("systemctl is-active hb-wizard || true", check=False, timeout=60).stdout.strip()
            if m and running == "active":
                self.record("Reusing the wizard already running in the VM", True)
                return m.group(0).replace(m.group(1), self.vm_ip)
        env = "--setenv=SUDO_USER=ubuntu --setenv=DEBIAN_FRONTEND=noninteractive"
        out = "--property=StandardOutput=file:/var/log/hb-wizard.log --property=StandardError=file:/var/log/hb-wizard.log"
        if self.args.source == "github":
            raw = f"https://raw.githubusercontent.com/{REPO_SLUG}/{self.args.branch}/bootstrap.sh"
            self.log(f"Installing via bootstrap.sh --branch {self.args.branch} (clones from GitHub)...")
            self.vm_sh(f"curl -fsSL {raw} -o /tmp/bootstrap.sh && "
                       f"systemd-run --unit hb-wizard {env} {out} bash /tmp/bootstrap.sh --branch {self.args.branch}")
        else:
            self.log("Installing the local HEAD (git archive) with setup.sh...")
            with tempfile.TemporaryDirectory() as td:
                tar = Path(td) / "blueprint.tar.gz"
                subprocess.run(["git", "-C", str(REPO_ROOT), "archive", "--format=tar.gz", "-o", str(tar), "HEAD"], check=True)
                self.multipass("transfer", tar.name, f"{self.vm}:/tmp/blueprint.tar.gz", cwd=td)
            self.vm_sh("mkdir -p /opt/homelab-blueprint && tar -xzf /tmp/blueprint.tar.gz -C /opt/homelab-blueprint && "
                       f"cd /opt/homelab-blueprint && systemd-run --unit hb-wizard --working-directory=/opt/homelab-blueprint "
                       f"{env} {out} bash ./setup.sh")

        deadline = time.time() + 1200
        while time.time() < deadline:
            log = self.read_wizard_log()
            m = WIZARD_URL_RE.search(log)
            if m:
                url = m.group(0)
                self.record("Wizard printed its token URL", True, url.split("token=")[0] + "token=<redacted>")
                if m.group(1) != self.vm_ip:
                    self.log(f"note: wizard printed {m.group(1)}, VM reports {self.vm_ip}; using the VM address")
                    url = url.replace(m.group(1), self.vm_ip)
                return url
            if "Error" in log and "Traceback" in log:
                break
            time.sleep(10)
        self.save_wizard_log()
        raise Step("wizard did not print a token URL within 20 minutes (see wizard.log)")

    def save_wizard_log(self) -> None:
        try:
            log = self.vm_read("/var/log/hb-wizard.log")
            token_re = re.compile(r"(token=|token: *|Control Hub token: *)[A-Za-z0-9_\-]{12,}")
            (self.report_dir / "wizard.log").write_text(token_re.sub(r"\1<redacted>", log), encoding="utf-8")
        except Exception as e:
            self.log(f"(could not save wizard log: {e})")

    def pick_new_ip(self) -> str:
        """A free address in the VM's /24 that the host cannot ping (the wizard renders a /24)."""
        base = ipaddress.ip_address(self.vm_ip)
        last = int(str(base).split(".")[-1])
        for delta in (100, 110, 120, -100, -110, 50, -50):
            cand_last = last + delta
            if not 10 <= cand_last <= 250:
                continue
            cand = ".".join(str(base).split(".")[:3] + [str(cand_last)])
            if not self.host_can_reach(cand):
                return cand
        raise Step("no free address found next to the VM's address")

    # -------------------------------------------------------------- browser
    def run_browser(self, wizard_url: str) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not self.args.headed)
            ctx = browser.new_context(viewport={"width": 1366, "height": 900},
                                      record_video_dir=str(self.report_dir) if self.args.video else None)
            page = ctx.new_page()
            console: List[str] = []
            page.on("console", lambda m: console.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
            try:
                self.wizard_flow(page)
                self.dashboard_flow(page)
            finally:
                (self.report_dir / "browser-console.log").write_text("\n".join(console), encoding="utf-8")
                self.log("Closing the browser (finalising the video)...")
                for closer in (ctx.close, browser.close):
                    try:
                        closer()
                    except Exception as e:
                        self.log(f"(browser close failed: {e})")

    def wizard_flow(self, page) -> None:
        url = self._wizard_url
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_function("document.getElementById('snap-ip') && /\\d+\\.\\d+/.test(document.getElementById('snap-ip').innerText)",
                               timeout=60_000)
        self.record("Wizard loads and probes the host", True, page.inner_text("#snap-ip"))
        self.shot(page, "wizard-loaded")

        page.click("#tab-btn-express")
        detected = page.input_value("#exp-server-ip")
        self.record("Express mode pre-fills the server's current IP", detected == self.vm_ip, f"field={detected} vm={self.vm_ip}")
        self.record("Express master password is empty (no shipped default)", page.input_value("#exp-admin-pass") == "")
        self.record("Static IP is off by default", not page.is_checked("#exp-static-ip-toggle"))

        if not self.args.no_static_ip:
            self.new_ip = self.pick_new_ip()
            self.log(f"Changing the server address {self.vm_ip} -> {self.new_ip} through the wizard")
            page.check("#exp-static-ip-toggle")
            page.fill("#exp-server-ip", self.new_ip)
        # Real install, not the default dry run
        page.uncheck("#exp-dry-run-toggle")
        self.shot(page, "express-filled")

        page.click("#btn-deploy-express")
        self.log("Deploy clicked; waiting for the install to finish (first install pulls several GB)...")
        t0 = time.time()
        deadline = t0 + self.args.deploy_timeout * 60
        while time.time() < deadline:
            if page.is_visible("#deploy-success-section"):
                break
            term = page.inner_text("#deploy-terminal")
            if "[ERROR] Deployment finished with errors" in term or "[FATAL ERROR]" in term:
                self.shot(page, "deploy-error")
                (self.report_dir / "deploy-terminal.txt").write_text(term, encoding="utf-8")
                raise Step(f"deploy reported an error in the browser after {int(time.time() - t0)}s: {term.strip()[-300:]}")
            time.sleep(5)
        else:
            self.shot(page, "deploy-timeout")
            raise Step(f"no deploy result in the browser after {self.args.deploy_timeout} min")
        self.deploy_done = time.time()
        (self.report_dir / "deploy-terminal.txt").write_text(page.inner_text("#deploy-terminal"), encoding="utf-8")
        self.record("Deploy result reached the browser", True, f"{int(self.deploy_done - t0)}s")
        self.shot(page, "deploy-success")

        body = page.inner_text("body")
        tok = re.search(r"Control Hub token:\s*([A-Za-z0-9_\-]{20,})", body)
        self.record("Credentials are shown once (Control Hub token present)", bool(tok))
        self.hub_token = tok.group(1) if tok else ""
        self.record("Wizard points at the indexer picker", "pick your indexers" in body.lower())

        if self.args.no_static_ip:
            page.wait_for_url(re.compile(r":7575/"), timeout=60_000)
            return

        self.record("Static-IP confirm box is shown", page.is_visible("#btn-netplan-confirm"))
        page.wait_for_function("!document.getElementById('btn-netplan-confirm').disabled", timeout=90_000)
        self.record("Old page detects the server on the new address", True, page.inner_text("#netplan-confirm-status"))
        self.shot(page, "netplan-reachable")
        page.click("#btn-netplan-confirm")
        page.wait_for_url(re.compile(re.escape(self.new_ip) + r":8000/"), timeout=30_000)
        page.wait_for_function("(document.getElementById('netplan-page-status')||{}).innerText && "
                               "/confirmed|No static-IP change/i.test(document.getElementById('netplan-page-status').innerText) "
                               "|| !(document.getElementById('btn-netplan-keep')||{disabled:true}).disabled", timeout=30_000)
        if page.is_visible("#btn-netplan-keep") and not page.is_disabled("#btn-netplan-keep"):
            self.shot(page, "netplan-confirm-page")
            page.click("#btn-netplan-keep")
        page.wait_for_function("/confirmed/i.test((document.getElementById('netplan-page-status')||{}).innerText||'')", timeout=30_000)
        self.record("Static IP confirmed from the new address", True, page.inner_text("#netplan-page-status"))
        self.shot(page, "netplan-confirmed")
        page.wait_for_url(re.compile(re.escape(self.new_ip) + r":7575/"), timeout=30_000)

    def dashboard_flow(self, page) -> None:
        host = self.new_ip or self.vm_ip
        self.record("Browser handed over to the Control Hub", f"{host}:7575" in page.url, page.url.split("?")[0])
        page.wait_for_selector("#indexer-banner", state="visible", timeout=90_000)
        self.record("Dashboard shows the one-time indexer banner", True)
        self.shot(page, "dashboard")
        page.click("#btn-indexer-banner-open")
        page.wait_for_selector("#indexer-modal", state="visible", timeout=15_000)
        page.wait_for_function("document.querySelectorAll('#indexer-list .indexer-check').length > 50", timeout=90_000)
        total = page.locator("#indexer-list .indexer-check").count()
        ticked = page.locator("#indexer-list .indexer-check:checked").count()
        self.record("Picker lists Prowlarr's definitions", total > 50, f"{total} shown")
        self.record("Nothing is pre-selected", ticked == 0, f"{ticked} ticked")
        self.record("Add button disabled until something is picked", page.is_disabled("#indexer-modal-add"))
        self.shot(page, "indexer-picker")
        page.click("#indexer-modal-cancel")
        page.click("#btn-indexer-banner-skip")
        self.record("Indexer step can be skipped", not page.is_visible("#indexer-banner"))
        self.shot(page, "dashboard-after-skip")

    # ------------------------------------------------------------ after GUI
    def verify_static_ip_stuck(self) -> None:
        wait = REVERT_WINDOW_SEC + 30 - (time.time() - self.deploy_done)
        if wait > 0:
            self.log(f"Waiting {int(wait)}s past the revert window to prove the change stuck...")
            time.sleep(wait)
        self.record("Control Hub still answers on the new address after the revert window",
                    self.http_ok(f"http://{self.new_ip}:7575/api/health"))
        self.record("Old address no longer answers", not self.http_ok(f"http://{self.vm_ip}:7575/api/health", timeout=2))
        addr = self.vm_sh("ip -4 -o addr show", check=False, timeout=120)
        self.record("VM interface carries the new address", self.new_ip in addr.stdout, addr.stdout.strip().replace("\n", " | ")[:200])
        timers = self.vm_sh("systemctl list-timers --all --no-legend | grep homelab-netplan-revert || true", check=False)
        self.record("Revert timer is gone", not timers.stdout.strip(), timers.stdout.strip())

    def verify_wiring(self) -> None:
        self.multipass("transfer", "check_wiring.sh", f"{self.vm}:/tmp/check_wiring.sh", cwd=str(REPO_ROOT / "testing" / "vm"))
        # The Windows checkout has CRLF line endings; bash needs LF.
        res = self.vm_sh("sed -i 's/\\r$//' /tmp/check_wiring.sh && bash /tmp/check_wiring.sh --photos > /tmp/check_wiring.txt 2>&1; echo rc=$?",
                         check=False, timeout=300)
        out = self.vm_read("/tmp/check_wiring.txt")
        (self.report_dir / "check_wiring.txt").write_text(out, encoding="utf-8")
        failed = next((ln for ln in reversed(out.splitlines()) if ln.startswith("+ ")), "")
        passed = "rc=0" in res.stdout and "WIRING OK" in out
        self.record("Apps wired inside the VM (check_wiring.sh)", passed, "" if passed else f"last check: {failed}")

    # ------------------------------------------------------------------ run
    def run(self) -> int:
        ok = False
        try:
            if self.args.reuse_vm:
                self.vm_ip = self.current_vm_ip()
            else:
                self.launch_vm()
            self._wizard_url = self.start_wizard()
            self.deploy_done = time.time()
            self.hub_token = ""
            self.run_browser(self._wizard_url)
            if self.new_ip:
                self.verify_static_ip_stuck()
            self.verify_wiring()
            ok = True
        except Step as e:
            self.log(f"STOPPED: {e}")
        except Exception as e:  # Playwright timeouts and the like
            self.log(f"STOPPED: {type(e).__name__}: {str(e).splitlines()[0][:300]}")
            self.results.append({"step": "unexpected error", "ok": False, "detail": str(e)[:500]})
        finally:
            self.save_wizard_log()
            summary = {"vm": self.vm, "old_ip": self.vm_ip, "new_ip": self.new_ip, "source": self.args.source,
                       "branch": self.args.branch, "passed": ok, "minutes": round((time.time() - self.started) / 60, 1),
                       "results": self.results}
            (self.report_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            self.log(f"{'ALL CHECKS PASSED' if ok else 'FAILED'} - report: {self.report_dir}")
            if self.args.keep_vm or not ok and self.args.keep_on_failure:
                self.log(f"VM kept: multipass shell {self.vm}")
            elif not self.args.reuse_vm:
                self.multipass("delete", "--purge", self.vm, check=False, timeout=300)
                self.log(f"VM '{self.vm}' deleted.")
        return 0 if ok else 1


def current_branch() -> str:
    res = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
    return res.stdout.strip() or "main"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=["github", "local"], default="github",
                   help="github: bootstrap.sh --branch <branch> (default); local: install the local HEAD")
    p.add_argument("--branch", default=current_branch(), help="Branch for --source github (default: current)")
    p.add_argument("--vm-name", default="", help="Name for the new VM (default: hb-gui-<date>)")
    p.add_argument("--reuse-vm", action="store_true", help="Use an existing VM named by --vm-name instead of launching one")
    p.add_argument("--cpus", type=int, default=4)
    p.add_argument("--memory", default="6G")
    p.add_argument("--disk", default="40G")
    p.add_argument("--no-static-ip", action="store_true", help="Skip the address change")
    p.add_argument("--deploy-timeout", type=int, default=45, help="Minutes to wait for the install")
    p.add_argument("--headed", action="store_true", help="Show the browser")
    p.add_argument("--video", action="store_true", help="Record a video of the browser session")
    p.add_argument("--keep-vm", action="store_true", help="Keep the VM afterwards")
    p.add_argument("--keep-on-failure", action="store_true", help="Keep the VM only if the test fails")
    args = p.parse_args()
    if args.reuse_vm and not args.vm_name:
        p.error("--reuse-vm needs --vm-name")
    return GuiTest(args).run()


if __name__ == "__main__":
    sys.exit(main())
