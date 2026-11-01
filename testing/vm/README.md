# Automated VM End-to-End (E2E) Testing Harness 🧪🖥️

> Isolated, offline-capable Hardware-in-the-Loop test harness that validates the complete homelab deployment lifecycle—from bare-metal Ubuntu bootstrap to real torrent ingestion, atomic hardlinks, and media discovery—executed strictly inside an ephemeral VM on the Windows host machine.

---

## 📑 Quick Navigation
- **[Architectural Plan & Specifications](../../docs/VM_E2E_TESTING_PLAN.md)**
- **[Full Verification & Simulation Report](../../docs/VM_E2E_TESTING_REPORT.md)**
- **[Hardware Simulation Benchmarks](reports/hardware_matrix_benchmark.md)**
- **[Latest JUnit Test Results](reports/vm_test_results.xml)**

---

## 🛡️ Host Isolation Guarantee
All test commands, Docker containers, loopback ext4 volume mounts, and test assertions run exclusively inside a guest micro-VM on the Windows host machine (via Canonical Multipass or WSL2 Ubuntu 24.04). **Zero modifications, Docker containers, or commands are ever executed against the live physical homelab server (`192.168.1.31`).**

---

## 🚀 Quickstart Commands

All commands are executed from the repository root on the Windows host:

### 1. Run Live 6-Container Pipeline Integration Test
Validates the entire Seerr -> Radarr/Sonarr -> Prowlarr -> Mock Torznab -> qBittorrent -> Atomic Hardlink -> Jellyfin pipeline:
```powershell
python testing/vm/orchestrator.py --run-pipeline
```

### 2. Run Immich Photo, Facial Recognition & Cloud Mirror Suite
Validates 4-person photo ingestion, ML face detection, API tagging, MWG XMP sidecar export, PostgreSQL dump, and simulated Google Drive sync via rclone:
```powershell
python testing/vm/orchestrator.py --run-photo
```

### 3. Run Complete VM Lifecycle & Assertion Suite
Executes storage topology mounting, unattended headless bootstrap, mock protocol checks, hardlink verification, and disaster recovery archive tests:
```powershell
python testing/vm/orchestrator.py --run-all
```

### 3. Keep VM State Active for Interactive Inspection
Retains the VM and containers running after test completion so you can access Web UIs:
```powershell
python testing/vm/orchestrator.py --run-all --keep-vm
```
* Access the guest shell: `wsl -d Ubuntu-24.04` or `multipass shell homelab-e2e-test`

---

## ⚡ Simulating Varied Hardware Configurations

You can simulate how the homelab stack performs across different hardware tiers:

### Hardware Matrix
| Profile | vCPUs | RAM | Disk | Target Hardware |
| :--- | :---: | :---: | :---: | :--- |
| **Low-Spec** | 2 | 4 GB | 20 GB | Intel N100 / Thin Clients / Mini-PCs |
| **Mid-Range** | 4 | 8 GB | 40 GB | Quad-Core Haswell / Skylake / Core i5 |
| **High-Performance** | 8 | 16 GB | 80 GB | Modern Multi-Core Homelab Servers |

### Running with Multipass:
```powershell
# Simulate Low-Spec Intel N100
python testing/vm/orchestrator.py --engine multipass --cpus 2 --memory 4G --disk 20G --run-all

# Simulate Mid-Range Quad-Core
python testing/vm/orchestrator.py --engine multipass --cpus 4 --memory 8G --disk 40G --run-all

# Simulate High-Performance Multi-Core Server
python testing/vm/orchestrator.py --engine multipass --cpus 8 --memory 16G --disk 80G --run-all
```

### Running with WSL2 Micro-VM:
Configure `%USERPROFILE%\.wslconfig`:
```ini
[wsl2]
processors=2
memory=4GB
swap=2GB
```
Restart WSL and run:
```powershell
wsl --shutdown
python testing/vm/orchestrator.py --run-pipeline
```

---

## 📦 Docker Image Caching (100% Offline Runs)

All container images are persistently cached inside the virtual machine's VHDX storage disk:
- `ghcr.io/seerr-team/seerr:latest` (1.34 GB)
- `ghcr.io/thephaseless/byparr:latest` (3.47 GB)
- `lscr.io/linuxserver/jellyfin:latest` (1.28 GB)
- `lscr.io/linuxserver/bazarr:latest` (641 MB)
- `lscr.io/linuxserver/qbittorrent:latest` (343 MB)
- `lscr.io/linuxserver/radarr:latest` (313 MB)
- `lscr.io/linuxserver/sonarr:latest` (302 MB)
- `lscr.io/linuxserver/prowlarr:latest` (277 MB)

Repeat test runs consume **0 KB external internet bandwidth** and launch all containers in ~4 seconds.

---

## 📁 Harness Architecture & File Map

```
testing/vm/
├── benchmark_hardware_matrix.py   # Multi-tier hardware benchmarking engine
├── orchestrator.py                # Host-side VM lifecycle orchestrator (Multipass & WSL2)
├── test_full_container_pipeline.py# 8-stage live 6-container integration pipeline test
├── test_vm_lifecycle.py           # 7-gate headless bootstrap and atomic hardlink test runner
├── fixtures/
│   ├── dummy_movie.mkv            # 2.0 MB genuine 120s H.264/AAC test video file
│   ├── e2e_deploy_config.json     # Headless deployment configuration fixture
│   └── generate_dummy_mkv.py      # Matroska synthesizer & ffmpeg test video generator
├── mocks/
│   └── mock_torznab.py            # Zero-dependency Python Torznab & BEP 19 Web Seed server
└── reports/
    ├── hardware_matrix_benchmark.json
    ├── hardware_matrix_benchmark.md
    ├── vm_test_results.json       # Structured JSON test verdict
    ├── vm_test_results.xml        # Standard JUnit XML for CI/CD integration
    └── VM_E2E_TESTING_REPORT.md   # Comprehensive validation report
```
