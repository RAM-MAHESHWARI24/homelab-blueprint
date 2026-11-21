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
* **The Rule:** The Phase 1 Setup Wizard (`setup/`) and its configuration core (`apps/control-hub/core/config_core/`) must use **Python 3 standard library only**.
* **Prohibited:** Never add third-party Python packages (`Flask`, `requests`, `pydantic`, `fastapi`, `yaml`) to `setup/`. The wizard must boot on a pristine, minimal, offline Linux install with zero `pip install` steps.

### 1.3. Universal Hardware Neutrality & Probing
* **The Rule:** Never hardcode CPU models, core counts, RAM capacities, network interface names (`eth0`), or disk block devices (`sda`).
* **Implementation:** Always discover capabilities dynamically via `apps/control-hub/core/config_core/system_prober.py` and `apps/control-hub/core/telemetry_sampler.py`.

### 1.4. Network Safety & Netplan Rollback ([`docs/NETPLAN_STATIC_IP_QUIRKS.md`](docs/NETPLAN_STATIC_IP_QUIRKS.md))
* **The Rule:** Never invoke raw `netplan apply` over remote SSH.
* **Implementation:** Always validate with `netplan generate` first, then apply through `config_core/netplan_manager.py`, which arms the `homelab-netplan-revert` timer and restores the backup unless the change is confirmed from the new address.

### 1.5. Sleep Guard & Power Deferral ([`ADR-0003`](docs/adr/0003-acpi-s3-sleep-guard-power-automation.md))
* **The Rule:** Never remove or bypass active condition guards in `apps/control-hub/host/server-suspend.sh`.
* **Guards:** Active qBittorrent downloads, active LAN SMB file streams, and `/run/server-suspend.skip` UI flags must defer S3 suspend.

### 1.6. Modules Stay Self-Contained ([`docs/RELEASING.md`](docs/RELEASING.md))
* **The Rule:** Each `apps/<module>/` folder with `"publish": true` in its `module.json` is published as its own repository. Code in it must never reach another module's folder or a path outside its own, and its README must not link outside it (use absolute GitHub URLs to the blueprint instead).
* **Allowed:** `setup/` may import from `apps/control-hub` (the shared `config_core` library). The installer's env renderer, `config_core/env_manager.py`, is the one file that knows every module.
* **Standalone files:** a published module keeps its own `install.sh`, `ci.sh`, `.github/workflows/ci.yml`, README, LICENSE and example config. Run `python testing/test_module_contract.py` after touching any of them.

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
  * Link to the file: `[system_prober.py](apps/control-hub/core/config_core/system_prober.py)`
  * Link to semantic symbol/function: `[system_prober.py](apps/control-hub/core/config_core/system_prober.py) -> probe_cpu_info()`
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

# 5. Module Contract
# Validates each module's standalone files and that no module reaches outside its folder
python testing/test_module_contract.py

# 6. Version Consistency
# Validates that every reported version matches the newest release in CHANGELOG.md
python testing/test_version_consistency.py
```

### Testing Rules for Agents:
1. **Never mock out failing assertions** to make tests pass artificially. Always solve the root-cause bug in the production code.
2. If introducing a new feature or endpoint, write corresponding test cases in `testing/` or `setup/test_setup.py`.
3. If creating or moving `.md` files, run `python testing/test_docs_integrity.py` before completing the turn.
4. For UI changes in `apps/control-hub/`, run `python -m unittest discover -s apps/control-hub/tests -p "test_*.py" -v` (including Playwright + `axe-core` WCAG 2.2 AA across all workspace views, viewports, and Dark/Light themes).

### 4.1. Live Production Server Testing & Safety Protocol

When an agent is asked to deploy, test, or verify changes against a live homelab server (via SSH alias `<ssh-host>` and LAN dashboard `http://<server-lan-ip>:7575`), **data safety is paramount—the server holds real family photos, media libraries, backups, and active streams**:

1. **Read-Only Network Mounts:** If the server filesystem is mounted on the dev workstation over SMB/NFS for inspection, treat that mount as **strictly read-only**. Never edit files, run Git commands, or execute scripts across the network mount.
2. **Local & Pre-Push Gates First:** All 6 monorepo verification gates and the Control Hub unit + Playwright + `axe-core` suite must pass locally before deploying to the server.
3. **Git-Driven Deployment Only (Instant Rollback):** Never hand-edit tracked files inside `/opt/homelab-blueprint` on the server. Push the verified branch to `origin` (passing Tier 1 pre-commit and Tier 2 pre-push hooks), then update the server via SSH (`sudo git -C /opt/homelab-blueprint fetch origin` and checkout/pull). This guarantees a 1-command rollback to `develop`.
4. **Real-Data & Secret Protection Invariants:**
   * **Never** run destructive commands (`teardown.sh`, `docker compose down -v`, `rm -rf`, database drops) on a live server or touch `/var/lib/homelab/*`, `/etc/homelab/*`, photo libraries, or media pools destructively.
   * **Never** print or log secret values (`CONTROL_HUB_TOKEN`, passwords, API keys, `rclone.conf`) in command output, commit messages, or docs. Remember `/etc/homelab/homelab.env` is `0600 root:root` while `/etc/homelab/control-hub.env` is `0640 root:homelab` (readable by the `homelab` daemon).
   * **Never** apply unconfirmed network changes or restart media/database containers while active streams, downloads, or backups are running.
   * **Never** sanitize or hardcode personal server identifiers (LAN IPs, hostnames, rclone remote names, drive letters, usernames) into tracked repository files.
5. **Systemd Unit & Host Script Sync:** When `system/systemd/*`, cron definitions, or host scripts (`apps/control-hub/host/server-suspend.sh`) change, render/install them with proper permissions (`0755` scripts, `0644` units), run `sudo systemctl daemon-reload`, and restart `control-hub.service`.
6. **Live On-Server & Browser Verification:**
   * Run the Linux-native test suites directly on the Ubuntu host using `/opt/homelab-blueprint/apps/control-hub/venv/bin/python3` (`test_e2e_regression.py` including Linux bash/systemd tests, `test_lifecycle_handoff.py`, `test_docs_integrity.py`, `test_version_consistency.py`, `setup/test_setup.py`, and `apps/control-hub/tests/test_*.py`).
   * Probe all live Control Hub API endpoints (`/api/health`, `/api/livez`, `/api/readyz`, `/api/system/vitals`, `/api/network/speed`, `/api/storage/operations`, `/api/downloads/active`, `/api/backup/status`, `/api/services/status`, `/api/tv-updater/status`, `/api/sleep/status`, `/api/cron/status`, `/api/alerts`, `/api/config/current`, `/api/config/ports`, `/api/config/ai-diagnostics`, `/api/config/netplan-status`) and inspect `sudo journalctl -u control-hub.service -n 30 --no-pager` for zero tracebacks or `sudo` polling spam.
   * Run a live Playwright + `axe-core` WCAG 2.2 AA visual and accessibility check against `http://<server-lan-ip>:7575` across all views and Dark/Light themes.
7. **GitHub Actions CI & Post-Merge Sync:** Confirm all GitHub Actions CI checks pass on the PR before merging into `develop`. Immediately after merging, switch `/opt/homelab-blueprint` on the server to `develop` (`sudo git -C /opt/homelab-blueprint checkout develop && sudo git -C /opt/homelab-blueprint pull --ff-only origin develop`) and restart `control-hub.service` so the live server stays cleanly aligned with `origin/develop`.

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

