# AI Coding Agent Master Operating Standards 🤖📐

> **Target Audience:** All AI coding assistants, autonomous agents, and LLMs (Antigravity, Cursor, Claude Code, GitHub Copilot, Windsurf, Aider) operating on the **Homelab Blueprint** monorepo.  
> **Mission:** Maintain production-grade quality, zero regressions, unbreakable documentation, and rock-solid architectural invariants.

---

## 📑 Table of Contents
1. [Core Principles & Architectural Invariants](#1-core-principles--architectural-invariants)
2. [How to Code (Software Engineering Standards)](#2-how-to-code-software-engineering-standards)
3. [How to Document (Documentation Standards)](#3-how-to-document-documentation-standards)
4. [How to Test & Verify (Verification Gates)](#4-how-to-test--verify-verification-gates)
5. [Git Discipline & Commit Standards](#5-git-discipline--commit-standards)

---

## 1. Core Principles & Architectural Invariants

Every agent proposing modifications must honor these five non-negotiable invariants:

### 1.1. Single-Mount Storage & Atomic Hardlinks ([`ADR-0001`](docs/adr/0001-single-mount-atomic-hardlinks.md))
* **The Rule:** All downloaders (`qbittorrent`) and library managers (`radarr`, `sonarr`, `bazarr`) must mount `${HDD_DATA}:/data`.
* **Prohibited:** Never split downloads and media into separate Docker volume mounts (e.g. `/downloads` and `/movies`). Separate mounts force cross-device file copies (`EXDEV`), burning 100% disk I/O, doubling disk consumption, and stalling playback streams.
* **Storage Hierarchy:** Standardize on `/data/torrents/{movies,tv}` and `/data/media/{movies,tv}`.

### 1.2. Zero-Dependency Bootstrap Wizard ([`ADR-0002`](docs/adr/0002-zero-dependency-setup-wizard.md))
* **The Rule:** The Phase 1 Setup Wizard (`setup/`) and its configuration core (`setup/config_core/`) must use **Python 3 standard library only**.
* **Prohibited:** Never add third-party Python packages (`Flask`, `requests`, `pydantic`, `fastapi`, `yaml`) to `setup/`. The wizard must boot on a pristine, minimal, offline Linux install with zero `pip install` steps.

### 1.3. Universal Hardware Neutrality & Probing
* **The Rule:** Never hardcode CPU models, core counts, RAM capacities, network interface names (`eth0`), or disk block devices (`sda`).
* **Implementation:** Always discover capabilities dynamically via `setup/config_core/system_prober.py` and `apps/control-hub/core/telemetry_sampler.py`.

### 1.4. Network Safety & Netplan Rollback ([`docs/NETPLAN_STATIC_IP_QUIRKS.md`](docs/NETPLAN_STATIC_IP_QUIRKS.md))
* **The Rule:** Never invoke raw `netplan apply` over remote SSH.
* **Implementation:** Always validate with `netplan generate` first, followed by `netplan try --timeout 45` to guarantee automatic rollback if connectivity drops.

### 1.5. Sleep Guard & Power Deferral ([`ADR-0003`](docs/adr/0003-acpi-s3-sleep-guard-power-automation.md))
* **The Rule:** Never remove or bypass active condition guards in `system/power/server-suspend.sh`.
* **Guards:** Active qBittorrent downloads, active LAN SMB file streams, and `/run/server-suspend.skip` UI flags must defer S3 suspend.

---

## 2. How to Code (Software Engineering Standards)

### 2.1. Cross-Platform Compatibility (Windows Dev + Linux Prod)
* The development host may run Windows (PowerShell/SMB), while the production server and CI run Ubuntu Linux (`22.04` and `24.04`).
* **Path Handling:** Always use `pathlib.Path` or `os.path.join`. Never hardcode raw forward or backward slash strings in path operations.
* **File Encoding:** Always specify `encoding="utf-8"` when reading or writing text files (`open(..., encoding="utf-8")`).
* **Subprocess Hygiene:** Set explicit `timeout=` parameters on all `subprocess.run` calls to prevent zombie hangs.

### 2.2. Python Code Quality
* **Resource Ceiling:** Keep background daemons ultra-lean. `apps/control-hub` must consume `< 25 MB RAM` and `< 0.2% CPU` at idle.
* **Thread Safety:** Protect shared telemetry state across threads using `threading.Lock()`.
* **Atomic File Updates:** When updating configuration files (`.env`), write to a temporary file in the same directory first (`.env.tmp`), then atomically replace using `os.replace` to prevent file corruption during power cuts or crashes.
* **Standard Library First:** Prefer standard library solutions (`urllib`, `json`, `ctypes`, `dataclasses`, `secrets`) before reaching for third-party dependencies.

### 2.3. Shell Scripting Standards
* Every `.sh` script must begin with:
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  ```
* Quote all variables: `"$VARIABLE"`, not `$VARIABLE`.
* Ensure scripts pass `shellcheck` with zero warnings before committing.

### 2.4. Docker & Compose Standards
* All service volumes must use permission mapping: `PUID=1000`, `PGID=1000`, `UMASK=002`.
* Specify explicit container names and healthcheck probes for orchestrated services.
* Provide clean `.env.example` templates alongside every `docker-compose.yml`.

---

## 3. How to Document (Documentation Standards)

We adhere to the **Diátaxis framework** and a **Docs-as-Code** philosophy. Documentation is treated as a tested, first-class citizen.

### 3.1. Colocated Component `README.md`
* Every functional directory (`setup/`, `apps/<app>/`, `system/`, `testing/`, `docs/adr/`) must have its own `README.md`.
* **Do NOT use custom names** like `detailed.md`—GitHub, GitLab, and IDEs only auto-render `README.md` when browsing directories.
* Component READMEs must cover:
  1. Purpose & Architecture Overview.
  2. Directory layout & component manifest.
  3. How to run, test, and configure locally.
  4. Cross-references back to `docs/` and root `README.md`.

### 3.2. Link Hygiene: Semantic Symbols, NOT Line Numbers
* **Strictly Prohibited:** Never link to line numbers in documentation (e.g. `file.py#L45-L60`). Line numbers break on subsequent commits, leading to immediate doc rot.
* **Permitted:**
  * Link to the file: `[system_prober.py](setup/config_core/system_prober.py)`
  * Link to semantic symbol/function: `[system_prober.py](setup/config_core/system_prober.py) -> probe_cpu_info()`
  * Link to markdown header slug: `[Storage Guide](docs/STORAGE_AND_HARDLINKS.md#atomic-hardlinks)`

### 3.3. Relative Links Only
* Always use standard relative paths for internal references (e.g. `../docs/README.md` or `apps/control-hub/README.md`).
* Never commit absolute machine paths (`/opt/homelab-blueprint` or `Z:\opt\...`) inside markdown links.

### 3.4. Updating Indexes & Catalogs
* When adding a new guide or runbook to `docs/`:
  1. Add it to the Diátaxis index in **[`docs/README.md`](docs/README.md)**.
  2. Add it to the runbook summary table in the root **[`README.md`](README.md)**.
* When adding a new architectural decision, create an ADR in `docs/adr/` and index it in **[`docs/adr/README.md`](docs/adr/README.md)**.

### 3.5. Architecture Decision Records (ADRs)
* Number all ADRs with 4-digit zero padding: `docs/adr/NNNN-title.md` (e.g. `0004-new-decision.md`).
* Mandatory sections: `## Status`, `## Context`, `## Decision`, `## Alternatives Considered`, `## Consequences`, and `## References`.

---

## 4. How to Test & Verify (Verification Gates)

**Never declare a task complete, propose changes, or merge code without executing the automated test suites.**

The monorepo contains four automated test suites that must pass with **100% success**:

```bash
# 1. Documentation Integrity & Link Verification
# Validates all relative links, images, anchors, and required component READMEs
python testing/test_docs_integrity.py

# 2. Setup Wizard Verification Suite
# Validates healthcheck, hardware probe, hardlink check, secrets generator, and dry-run deploy
python setup/test_setup.py

# 3. E2E Pipeline Regression Suite
# Validates compose syntax, multi-tier hardware detection, Netplan safety, and power logic
python testing/test_e2e_regression.py

# 4. Full Lifecycle Handoff Suite
# Validates unmocked end-to-end handoff from Setup Wizard (:8099) to Control Hub (:7575)
python testing/test_lifecycle_handoff.py
```

### Testing Rules for Agents:
1. **Never mock out failing assertions** to make tests pass artificially. Always solve the root-cause bug in the production code.
2. If introducing a new feature or endpoint, write corresponding test cases in `testing/` or `setup/test_setup.py`.
3. If creating or moving `.md` files, run `python testing/test_docs_integrity.py` before completing the turn.

---

## 5. Git Discipline & Commit Standards

### 5.1. Dual-Branch Release Architecture (`main` vs `develop`)
* **`main` (Stable Public Release):**
  * Production-ready, release-tagged branch.
  * What end-users clone or run via `curl -sSL .../bootstrap.sh`.
  * Must **always** be 100% stable, fully tested, and releasable. Direct experimental commits are prohibited.
* **`develop` (Active Integration & Staging):**
  * Primary working branch for ongoing development, agent tasks, and feature staging.
  * All topic branches (`feat/...`, `fix/...`, `docs/...`) branch off and merge into `develop`.
  * Merged into `main` only when cutting verified releases or milestone tags.

### 5.2. Conventional Commits & Clean Tree
* Follow the **Conventional Commits** specification:
  * `feat(...)`: New feature, endpoint, or hardware capability
  * `fix(...)`: Bugfix or error resolution
  * `docs(...)`: Documentation additions, runbook updates, or ADR records
  * `test(...)`: New test cases, regression coverage, or test harness updates
  * `refactor(...)`: Code restructuring without functional changes
  * `chore(...)`: Maintenance, dependency updates, or git configuration
* Keep commits **atomic**: do not combine unrelated refactors with bug fixes.
* Ensure working tree is clean and `git status` reports zero unintended untracked files before concluding.

