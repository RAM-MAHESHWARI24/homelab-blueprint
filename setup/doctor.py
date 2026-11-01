#!/usr/bin/env python3
"""
Homelab Blueprint - Pre-Flight Diagnostic Prober (Homelab Doctor) 🩺
Zero-dependency host readiness checker for bare-metal, mini-PCs, and virtual machines.
Validates CPU architecture, memory headroom, storage hardlinks, port collisions, and Docker.
"""

import os
import sys
import socket
import platform
import subprocess
from pathlib import Path

# Add config_core to path
SETUP_DIR = Path(__file__).resolve().parent
REPO_ROOT = SETUP_DIR.parent
sys.path.insert(0, str(SETUP_DIR))

from config_core.system_prober import probe_cpu_info, probe_ram_info, probe_hardware_acceleration
from config_core.port_manager import check_port, get_default_ports
from config_core.storage_manager import test_atomic_hardlink, get_disk_partitions
from config_core.schema_migrator import detect_schema_diff, find_all_environment_targets

# Safe UTF-8 console output for cross-platform terminals (Windows cp1252 & Linux UTF-8)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Terminal ANSI formatting (cross-platform safe)
USE_COLOR = sys.stdout.isatty() and os.name != "nt" or (os.name == "nt" and os.environ.get("ANSICON") or os.environ.get("WT_SESSION"))
GREEN = "\033[92m" if USE_COLOR else ""
YELLOW = "\033[93m" if USE_COLOR else ""
RED = "\033[91m" if USE_COLOR else ""
CYAN = "\033[96m" if USE_COLOR else ""
BOLD = "\033[1m" if USE_COLOR else ""
RESET = "\033[0m" if USE_COLOR else ""


def check_docker_engine():
    """Validates Docker daemon status and compose v2 availability"""
    result = {"installed": False, "running": False, "compose_v2": False, "version": "", "error": None}
    try:
        proc = subprocess.run(["docker", "--version"], capture_output=True, text=True, timeout=3)
        if proc.returncode == 0:
            result["installed"] = True
            result["version"] = proc.stdout.strip().replace("Docker version ", "").split(",")[0]
        else:
            result["error"] = "docker CLI returned non-zero"
            return result
    except Exception as e:
        result["error"] = str(e)
        return result

    # Check daemon ping
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5)
        result["running"] = (proc.returncode == 0)
    except Exception:
        result["running"] = False

    # Check compose v2
    try:
        proc = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, timeout=3)
        result["compose_v2"] = (proc.returncode == 0)
    except Exception:
        result["compose_v2"] = False

    return result


def run_doctor():
    """Executes full diagnostic sweep and prints formatted terminal report"""
    print(f"\n{BOLD}{CYAN}============================================================{RESET}")
    print(f"{BOLD}{CYAN}  🩺 Homelab Blueprint - Pre-Flight Diagnostic Doctor{RESET}")
    print(f"{BOLD}{CYAN}============================================================{RESET}\n")

    issues_found = 0
    warnings_found = 0

    # 1. Host OS & Architecture
    os_name = platform.system()
    arch = platform.machine()
    print(f"{BOLD}1. Host Platform & Operating System:{RESET}")
    print(f"   Platform:     {os_name} ({arch})")
    print(f"   Kernel:       {platform.release()}")
    if os_name == "Linux":
        print(f"   Status:       {GREEN}[OK]{RESET} Linux kernel detected")
    else:
        print(f"   Status:       {YELLOW}[NOTE]{RESET} Non-Linux OS ({os_name}). Production deployment targets Ubuntu.")

    # 2. CPU Architecture & Playback Tier
    print(f"\n{BOLD}2. Processor & Media Transcoding Capability:{RESET}")
    cpu = probe_cpu_info()
    print(f"   CPU Model:    {cpu['model']}")
    print(f"   Cores/Threads:{cpu['cores']} physical cores / {cpu['threads']} threads")
    if cpu.get("is_low_power"):
        print(f"   Hardware Tier:{YELLOW} Tier 1 (Low-Power / Legacy CPU){RESET}")
        print(f"   Recommendation:{YELLOW} Direct Play CPU Protection Mode (<1.5% CPU){RESET}")
    else:
        print(f"   Hardware Tier:{GREEN} Tier 2/3 (Modern Multi-Core CPU){RESET}")
        print(f"   Recommendation:{GREEN} High-Performance Direct Stream / Hardware Transcode{RESET}")

    # 3. Memory Headroom
    print(f"\n{BOLD}3. Physical RAM & Swap Headroom:{RESET}")
    ram = probe_ram_info()
    print(f"   Total RAM:    {ram['total_gib']:.1f} GiB")
    print(f"   Available:    {ram['free_gib']:.1f} GiB")
    if ram["total_gib"] < 3.5:
        print(f"   Status:       {RED}[FAIL]{RESET} Insufficient RAM (< 4 GiB). Media containers may run OOM.")
        issues_found += 1
    elif ram["total_gib"] < 7.5:
        print(f"   Status:       {YELLOW}[WARNING]{RESET} 4-8 GiB RAM detected. Suitable for core media stack, schedule ML workers.")
        warnings_found += 1
    else:
        print(f"   Status:       {GREEN}[OK]{RESET} Ample physical memory headroom (>= 8 GiB).")

    # 4. Storage & Atomic Hardlinks (0-I/O)
    print(f"\n{BOLD}4. Storage Hierarchy & Atomic Hardlink Verification:{RESET}")
    target_data_dir = os.getenv("HDD_DATA", "/mnt/hdd/data")
    if not Path(target_data_dir).exists():
        target_data_dir = str(REPO_ROOT)
        print(f"   Notice:       Default data path '/mnt/hdd/data' not yet mounted. Testing repository directory: '{target_data_dir}'")
    else:
        print(f"   Target Mount: '{target_data_dir}'")

    hl = test_atomic_hardlink(target_data_dir)
    if hl.get("supported"):
        print(f"   Hardlinks:    {GREEN}[PASS]{RESET} Microsecond atomic inode linking supported (latency: {hl.get('latency_ms', 0):.2f}ms)")
        print(f"   Performance:  {GREEN}[0-I/O]{RESET} Torrent-to-media imports will consume 0 extra disk space and 0 disk I/O.")
    else:
        print(f"   Hardlinks:    {RED}[FAIL]{RESET} Inode hardlinks failed: {hl.get('error')}")
        print(f"   Impact:       {RED}Filesystem does not support hardlinks! Media imports will fall back to slow file copy.{RESET}")
        issues_found += 1

    # 5. Docker Engine & Compose v2
    print(f"\n{BOLD}5. Docker Engine & Container Orchestration:{RESET}")
    docker = check_docker_engine()
    if not docker["installed"]:
        print(f"   Docker:       {RED}[FAIL]{RESET} Docker Engine is not installed.")
        print(f"   Remedy:       Run './setup.sh' to automatically install Docker Engine & Compose v2.")
        issues_found += 1
    else:
        print(f"   Docker:       {GREEN}[OK]{RESET} Docker {docker['version']}")
        if not docker["running"]:
            print(f"   Daemon:       {RED}[FAIL]{RESET} Docker service is stopped or socket permissions missing.")
            print(f"   Remedy:       Run 'sudo systemctl start docker' or 'sudo usermod -aG docker $USER'.")
            issues_found += 1
        else:
            print(f"   Daemon:       {GREEN}[OK]{RESET} Docker daemon active and responsive")

        if docker["compose_v2"]:
            print(f"   Compose:      {GREEN}[OK]{RESET} Docker Compose v2 active ('docker compose')")
        else:
            print(f"   Compose:      {YELLOW}[WARNING]{RESET} Compose v2 not found. Legacy 'docker-compose' might be needed.")
            warnings_found += 1

    # 6. Core Port Availability Check (13 Services)
    print(f"\n{BOLD}6. Port Conflict & Socket Collision Scan:{RESET}")
    core_ports = {
        "Setup Wizard": 8000,
        "Control Hub": 7575,
        "Jellyfin": 8096,
        "Seerr": 5055,
        "Sonarr": 8989,
        "Radarr": 7878,
        "Prowlarr": 9696,
        "Bazarr": 6767,
        "qBittorrent Web": 8080,
        "Immich Web": 2283,
        "Dozzle": 8888,
    }

    port_collisions = []
    for service, port in core_ports.items():
        is_free = check_port(port)
        if not is_free:
            port_collisions.append((service, port))

    if not port_collisions:
        print(f"   Port Scan:    {GREEN}[OK]{RESET} All core homelab ports are free and available.")
    else:
        print(f"   Port Scan:    {YELLOW}[NOTICE]{RESET} Found {len(port_collisions)} occupied port(s):")
        for s, p in port_collisions:
            print(f"                 - Port {p} ({s}) is currently in use.")
        print(f"                 (If an existing service is already running on this port, you can customize it in Setup Wizard)")

    # 7. GPU Render Node Acceleration
    print(f"\n{BOLD}7. Hardware Video Acceleration (Intel VAAPI/QSV):{RESET}")
    hw = probe_hardware_acceleration()
    if hw.get("has_vaapi_dri"):
        print(f"   Render Node:  {GREEN}[OK]{RESET} /dev/dri render node available. Hardware transcode ready.")
    else:
        print(f"   Render Node:  {YELLOW}[NOTICE]{RESET} Dedicated /dev/dri render node not detected.")
        print(f"                 (Direct Play streaming mode will be enforced for maximum CPU efficiency)")

    # 8. Configuration Schema & Environment Upgrades (.env)
    print(f"\n{BOLD}8. Configuration Environment & Schema Status (.env):{RESET}")
    env_targets = find_all_environment_targets(REPO_ROOT)
    env_outdated = 0
    for env_file, example_file in env_targets:
        rel = env_file.relative_to(REPO_ROOT) if env_file.is_relative_to(REPO_ROOT) else env_file
        diff = detect_schema_diff(env_file, example_file)
        if not env_file.exists():
            print(f"   • {rel}: {YELLOW}[PENDING]{RESET} Not created yet (will seed from template)")
        elif diff["is_up_to_date"]:
            print(f"   • {rel}: {GREEN}[UP TO DATE]{RESET} ({len(diff['synced_keys'])} parameters synchronized)")
        else:
            env_outdated += 1
            print(f"   • {rel}: {YELLOW}[OUTDATED]{RESET} Missing {len(diff['missing_keys'])} new parameter(s): {', '.join(diff['missing_keys'].keys())}")

    if env_outdated > 0:
        print(f"   Remedy:       Run './setup.sh --migrate' to safely auto-upgrade environment files.")
        warnings_found += 1
    else:
        print(f"   Schema Sync:  {GREEN}[OK]{RESET} All active environments match current template versions.")

    # Final Summary Verdict
    print(f"\n{BOLD}{CYAN}============================================================{RESET}")
    if issues_found == 0 and warnings_found == 0:
        print(f"{BOLD}{GREEN}  🎉 PRE-FLIGHT VERDICT: SYSTEM IS 100% READY FOR DEPLOYMENT!{RESET}")
    elif issues_found == 0:
        print(f"{BOLD}{GREEN}  ✓ PRE-FLIGHT VERDICT: READY FOR DEPLOYMENT (with {warnings_found} notice/warnings){RESET}")
    else:
        print(f"{BOLD}{RED}  ❌ PRE-FLIGHT VERDICT: {issues_found} CRITICAL ISSUE(S) MUST BE RESOLVED{RESET}")
    print(f"{BOLD}{CYAN}============================================================{RESET}\n")

    return 0 if issues_found == 0 else 1


if __name__ == "__main__":
    sys.exit(run_doctor())
