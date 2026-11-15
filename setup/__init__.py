"""
Homelab Blueprint installer package (Setup Wizard, headless deployer, doctor).

The wizard uses only the Python standard library (ADR-0002). It shares the
host-probing library with the Control Hub, which owns the single copy under
apps/control-hub/core/config_core. Importing this package makes that library
importable as `core.config_core`.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_CONTROL_HUB_DIR = REPO_ROOT / "apps" / "control-hub"

if str(_CONTROL_HUB_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTROL_HUB_DIR))
