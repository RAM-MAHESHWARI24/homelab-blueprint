"""
Install manifest: the single source of truth for what the installer put on
the host, so `teardown.sh` removes exactly that and nothing else.

Stored as JSON at /var/lib/homelab/installed.json (see core.config_core.paths).
Also usable as a CLI from shell scripts:

    python3 setup/installer/manifest.py list files      # one path per line
    python3 setup/installer/manifest.py list units
    python3 setup/installer/manifest.py list crons
    python3 setup/installer/manifest.py list compose     # module compose dirs
    python3 setup/installer/manifest.py show
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Allow running as a script from the repository root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import setup  # noqa: F401  (adds apps/control-hub to sys.path)
from core.config_core.paths import MANIFEST_FILE

MANIFEST_VERSION = 2


class InstallManifest:
    """Accumulates created artefacts during an install and persists them."""

    def __init__(self, path: Path = MANIFEST_FILE):
        self.path = Path(path)
        self.data: Dict[str, Any] = {
            "manifest_version": MANIFEST_VERSION,
            "blueprint_version": "",
            "installed_at": "",
            "install_dir": "",
            "service_user": "",
            "modules": [],
            "files": [],       # absolute paths of files written outside the checkout
            "dirs": [],        # directories created outside the checkout (not data!)
            "units": [],       # systemd unit names enabled
            "crons": [],       # /etc/cron.d/<name> files
            "compose": [],     # {"module": id, "dir": path, "env_file": path}
            "users": [],       # system users created
        }
        if self.path.exists():
            try:
                existing = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    self.data.update({k: v for k, v in existing.items() if k in self.data})
            except (json.JSONDecodeError, OSError):
                pass

    # -- recording -----------------------------------------------------------
    def _add(self, key: str, value: Any) -> None:
        bucket: List[Any] = self.data.setdefault(key, [])
        if value not in bucket:
            bucket.append(value)

    def add_file(self, path) -> None:
        self._add("files", str(path))

    def add_dir(self, path) -> None:
        self._add("dirs", str(path))

    def add_unit(self, unit_name: str) -> None:
        self._add("units", unit_name)

    def add_cron(self, path) -> None:
        self._add("crons", str(path))
        self._add("files", str(path))

    def add_compose(self, module_id: str, directory, env_file) -> None:
        entry = {"module": module_id, "dir": str(directory), "env_file": str(env_file)}
        if entry not in self.data["compose"]:
            self.data["compose"].append(entry)

    def add_module(self, module_id: str) -> None:
        self._add("modules", module_id)

    def add_user(self, username: str) -> None:
        self._add("users", username)

    def set_meta(self, *, install_dir: str, service_user: str, blueprint_version: str) -> None:
        self.data["install_dir"] = install_dir
        self.data["service_user"] = service_user
        self.data["blueprint_version"] = blueprint_version
        self.data["installed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    # -- persistence ---------------------------------------------------------
    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)
        return self.path

    @classmethod
    def load(cls, path: Path = MANIFEST_FILE) -> "InstallManifest":
        return cls(path)


def _cli(argv: List[str]) -> int:
    manifest = InstallManifest.load()
    if not manifest.path.exists():
        print(f"No install manifest found at {manifest.path}", file=sys.stderr)
        return 2

    if len(argv) >= 1 and argv[0] == "show":
        print(json.dumps(manifest.data, indent=2))
        return 0

    if len(argv) >= 2 and argv[0] == "list":
        key = argv[1]
        if key == "compose":
            for entry in manifest.data.get("compose", []):
                print(f"{entry['module']}\t{entry['dir']}\t{entry['env_file']}")
            return 0
        for item in manifest.data.get(key, []):
            print(item)
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
