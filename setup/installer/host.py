"""
Host-level installation primitives: system user, rendered systemd units,
cron files, sudoers drop-ins and helper scripts.

Every file written here is recorded in the InstallManifest so teardown can
remove exactly what was installed. Templates use `{{KEY}}` placeholders;
files without placeholders are copied unchanged.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .manifest import InstallManifest

SYSTEMD_DIR = Path(os.getenv("HOMELAB_SYSTEMD_DIR", "/etc/systemd/system"))
CRON_DIR = Path(os.getenv("HOMELAB_CRON_DIR", "/etc/cron.d"))
SUDOERS_DIR = Path(os.getenv("HOMELAB_SUDOERS_DIR", "/etc/sudoers.d"))
SBIN_DIR = Path(os.getenv("HOMELAB_SBIN_DIR", "/usr/local/sbin"))


class CommandResult(dict):
    """dict with .ok for readability: {'success', 'stdout', 'stderr', 'returncode'}"""

    @property
    def ok(self) -> bool:
        return bool(self.get("success"))


def run_command(cmd: List[str], cwd: Optional[str] = None, timeout: int = 300, env: Optional[Dict[str, str]] = None) -> CommandResult:
    """Runs a command with an explicit timeout and captures output."""
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return CommandResult(
            success=proc.returncode == 0,
            stdout=proc.stdout.strip(),
            stderr=proc.stderr.strip(),
            returncode=proc.returncode,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(success=False, stdout="", stderr=f"timed out after {timeout}s: {' '.join(cmd)}", returncode=-1)
    except FileNotFoundError as e:
        return CommandResult(success=False, stdout="", stderr=str(e), returncode=-1)


def render_template(text: str, variables: Dict[str, str]) -> str:
    """Replaces {{KEY}} placeholders. Unknown placeholders are left untouched."""
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def install_file(src: Path, dst: Path, manifest: InstallManifest, mode: int = 0o644, variables: Optional[Dict[str, str]] = None) -> Path:
    """Renders (if variables given) or copies src to dst with the given mode, recording it."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if variables is not None:
        content = render_template(src.read_text(encoding="utf-8"), variables)
        tmp = dst.with_name(dst.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.chmod(tmp, mode)
        tmp.replace(dst)
    else:
        shutil.copy2(src, dst)
        os.chmod(dst, mode)
    manifest.add_file(dst)
    return dst


def ensure_group(group: str) -> CommandResult:
    res = run_command(["getent", "group", group], timeout=10)
    if res.ok:
        return res
    return run_command(["groupadd", "--system", group], timeout=30)


def ensure_system_user(username: str, manifest: InstallManifest, extra_groups: Optional[List[str]] = None) -> CommandResult:
    """Creates a nologin system account (idempotent) and adds it to extra groups."""
    extra_groups = extra_groups or []
    for grp in extra_groups:
        ensure_group(grp)

    exists = run_command(["id", "-u", username], timeout=10)
    if not exists.ok:
        cmd = ["useradd", "--system", "--shell", "/usr/sbin/nologin", "--no-create-home", username]
        if extra_groups:
            cmd += ["--groups", ",".join(extra_groups)]
        created = run_command(cmd, timeout=30)
        if not created.ok:
            return created
        manifest.add_user(username)
    else:
        for grp in extra_groups:
            run_command(["usermod", "-aG", grp, username], timeout=30)
    return CommandResult(success=True, stdout="", stderr="", returncode=0)


def install_systemd_unit(src: Path, unit_name: str, manifest: InstallManifest, variables: Dict[str, str], enable_now: bool = True) -> CommandResult:
    """Renders a unit file into /etc/systemd/system, reloads and enables it."""
    dst = SYSTEMD_DIR / unit_name
    install_file(src, dst, manifest, mode=0o644, variables=variables)
    reload = run_command(["systemctl", "daemon-reload"], timeout=60)
    if not reload.ok:
        return reload
    manifest.add_unit(unit_name)
    if enable_now:
        return run_command(["systemctl", "enable", "--now", unit_name], timeout=120)
    return run_command(["systemctl", "enable", unit_name], timeout=60)


def install_cron(src: Path, name: str, manifest: InstallManifest, variables: Optional[Dict[str, str]] = None) -> Path:
    """Installs a cron.d file (0644, root-owned as cron requires)."""
    dst = CRON_DIR / name
    install_file(src, dst, manifest, mode=0o644, variables=variables)
    manifest.add_cron(dst)
    return dst


def install_sudoers(src: Path, name: str, manifest: InstallManifest, variables: Optional[Dict[str, str]] = None) -> CommandResult:
    """Installs a sudoers drop-in after validating it with visudo."""
    dst = SUDOERS_DIR / name
    tmp = dst.with_name(dst.name + ".tmp")
    content = render_template(src.read_text(encoding="utf-8"), variables or {})
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content, encoding="utf-8")
    os.chmod(tmp, 0o440)

    check = run_command(["visudo", "-cf", str(tmp)], timeout=30)
    if not check.ok and shutil.which("visudo"):
        tmp.unlink(missing_ok=True)
        return check
    tmp.replace(dst)
    manifest.add_file(dst)
    return CommandResult(success=True, stdout="", stderr="", returncode=0)


def install_helper_script(src: Path, manifest: InstallManifest, name: Optional[str] = None) -> Path:
    """Copies an executable helper into /usr/local/sbin."""
    dst = SBIN_DIR / (name or src.name)
    return install_file(src, dst, manifest, mode=0o755)


def write_private_file(dst: Path, content: str, manifest: InstallManifest, mode: int = 0o600, owner_group: Optional[str] = None) -> Path:
    """Writes a root-owned secrets file; optionally group-readable by `owner_group`."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(dst)
    if owner_group and hasattr(os, "chown"):
        try:
            import grp

            os.chown(dst, 0, grp.getgrnam(owner_group).gr_gid)
        except (KeyError, PermissionError, ImportError):
            pass
    manifest.add_file(dst)
    return dst
