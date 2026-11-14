"""
Installer orchestration: turns a wizard/headless configuration into a
running homelab (directories, env files, Docker stacks, host units) and
records everything it created in an install manifest for teardown.
"""

from .deployer import deploy_homelab_stack
from .manifest import InstallManifest

__all__ = ["deploy_homelab_stack", "InstallManifest"]
