# Homelab Blueprint - Industry Standards & Engineering Maturity Model 🏛️📊

> Comprehensive audit of technical standards, architectural benchmarks, current monorepo compliance, and prioritized engineering roadmap for public distribution.

---

## 📑 Table of Contents
1. [Executive Summary & Purpose](#-executive-summary--purpose)
2. [Comparative Standards Matrix](#-comparative-standards-matrix)
3. [Pillar 1: Package Delivery & Versioning](#1-pillar-1-package-delivery--versioning)
4. [Pillar 2: Security & Supply Chain Hardening](#2-pillar-2-security--supply-chain-hardening)
5. [Pillar 3: Configuration & Schema Migration](#3-pillar-3-configuration--schema-migration)
6. [Pillar 4: API Architecture & Observability](#4-pillar-4-api-architecture--observability)
7. [Pillar 5: Testing Pyramid & Quality Gates](#5-pillar-5-testing-pyramid--quality-gates)
8. [Pillar 6: Documentation & Developer Experience](#6-pillar-6-documentation--developer-experience)
9. [Actionable Implementation Roadmap](#-actionable-implementation-roadmap)

---

## 🧭 Executive Summary & Purpose

When moving a project from a private/bespoke homelab setup to a **public, reusable open-source package**, ad-hoc practices must be replaced with recognized engineering standards.

This document establishes the **Target Maturity Model** for the Homelab Blueprint, scoring our current implementation against formal industry specifications (SemVer, CIS, Twelve-Factor, SLSA, OpenAPI, Diátaxis) and laying out what must be built next.

---

## 📊 Comparative Standards Matrix

| Engineering Discipline | Recognized Industry Standard | Our Current Implementation | Current Grade | What We Must Build (Gaps) |
| :--- | :--- | :--- | :---: | :--- |
| **Packaging & Distribution** | **SemVer 2.0.0**, GitHub Releases, Checksums | 1-line `curl \| sudo bash`, pulling raw git `main` HEAD | **C+** | Pinned release tags (`v1.0.0`), SHA-256 installer verification, offline tarball bundle, `uninstall.sh`. |
| **Security & Supply Chain** | **CIS Linux Benchmark**, SLSA L1/2, Principle of Least Privilege | Gitleaks, PUID/PGID `1000:1000`, CSPRNG token generator | **B-** | Unprivileged daemon user (remove `root` from Control Hub systemd), Docker socket proxy, Trivy vulnerability scan. |
| **Configuration** | **The Twelve-Factor App (III. Config)**, Strict Schema | Master `.env` synchronized across sub-stacks | **B+** | Config migration engine (`config_migrator.py`) for zero-downtime upgrades; strict schema validation. |
| **API & Interfaces** | **OpenAPI 3.1**, RFC 7807 (Problem Details), REST | Thread-safe Flask endpoints, Vanilla JS cyber-HUD | **B** | Formal `openapi.yaml` specification, interactive Swagger UI (`:7575/api/docs`), `/livez` & `/readyz` probes. |
| **Testing & CI/CD** | **Test Pyramid**, Multi-Environment Simulation | 4 automated test suites in CI matrix (Ubuntu 22/24, Py3.10-12) | **A-** | Container integration tests in CI (ephemeral Docker daemon), automated container image pruning checks. |
| **Documentation** | **Diátaxis Framework**, ADRs (Nygard), Docs-as-Code | Colocated READMEs, 3 ADRs, CI link integrity test | **A** | Interactive terminal GIFs (vhs/asciinema), complete step-by-step uninstallation guide. |

---

## 1. Pillar 1: Package Delivery & Versioning

### The Industry Standard
* **[SemVer 2.0.0](https://semver.org/):** `MAJOR.MINOR.PATCH`. Major = breaking config/storage changes; Minor = new services/widgets; Patch = bugfixes.
* **Reproducible Asset Distribution:** Deployers download immutable release bundles (`homelab-blueprint-v1.0.0.tar.gz`) accompanied by cryptographic SHA-256 checksums (`checksums.txt.sha256`).
* **Safe 1-Line Bootstrap:** Installers must allow pinning a specific release:
  ```bash
  curl -sSL https://raw.githubusercontent.com/.../install.sh | sudo bash -s -- --version v1.0.0
  ```

### Current Status
* Pulls directly from the moving tip of `main`.
* No Git release tags or release tarballs exist yet.

### Required Actions
1. Cut the inaugural release tag: **`v1.0.0`**.
2. Update `bootstrap.sh` to accept optional `--version <tag>` argument (defaulting to the latest tagged release via GitHub API).
3. Generate and verify SHA-256 checksums during bootstrap.
4. Implement `teardown.sh` for clean, non-destructive cluster uninstallation.

---

## 2. Pillar 2: Security & Supply Chain Hardening

### The Industry Standard
* **CIS Ubuntu Linux Benchmark & Least Privilege:** No long-running daemon should execute as `root` unless strictly required for kernel ring operations.
* **Docker Socket Isolation:** Direct exposure of `/var/run/docker.sock` gives container processes unmitigated root access to the host.
* **SLSA Level 1 & Vulnerability Scanning:** Every container image must be scanned for CVEs before deployment.

### Current Status
* **Pass:** Clean Git history verified via Gitleaks CI action.
* **Pass:** Container file permissions mapped strictly to unprivileged user (`PUID=1000`, `PGID=1000`, `UMASK=002`).
* **Deficit:** `system/systemd/control-hub.service` executes as `User=root`.
* **Deficit:** Docker socket is directly accessed by Control Hub.

### Required Actions
1. **Unprivileged Daemon User:** Create a dedicated system user (`homelab` or `controlhub`) without login shell.
2. **Sudoers Whitelist:** Grant granular sudo permissions *only* for necessary commands via `/etc/sudoers.d/homelab`:
   ```sudoers
   homelab ALL=(ALL) NOPASSWD: /usr/sbin/rtcwake, /usr/bin/systemctl restart docker
   ```
3. **Docker Socket Proxy:** Introduce `tecnativa/docker-socket-proxy` to restrict API calls to read-only container inspection.
4. **Vulnerability Scanning:** Add `aquasecurity/trivy-action` to GitHub Actions CI to flag vulnerable container base images.

---

## 3. Pillar 3: Configuration & Schema Migration

### The Industry Standard
* **The Twelve-Factor App:** Configuration stored strictly in the environment, separated cleanly from application logic.
* **Schema Evolution & Zero-Downtime Upgrades:** When new releases introduce new `.env` keys, an automated migrator upgrades legacy configs without user intervention or manual copy-pasting.

### Current Status
* **Pass:** Dynamic synchronization between root `.env` and downstream stacks (`apps/mediaserver/.env`, `apps/noodle-gallery/.env`) via `setup/config_core/env_manager.py`.
* **Deficit:** No automated schema migrator. Upgrading from v1.0 to v1.1 requires manual comparison with `.env.example`.

### Required Actions
1. Create `setup/config_core/schema_migrator.py`:
   * Reads existing `.env`.
   * Compares against updated `.env.example` schema.
   * Injects newly required parameters with sensible defaults while preserving existing user secrets.
   * Produces an automated backup (`.env.backup.<timestamp>`).

---

## 4. Pillar 4: API Architecture & Observability

### The Industry Standard
* **OpenAPI 3.1 Specification:** Machine-readable API contracts defining every route, request schema, and response payload.
* **Kubernetes-Style Health Probing:**
  * **Liveness Probe (`/livez`):** Is the web process responding to socket connections?
  * **Readiness Probe (`/readyz`):** Are downstream storage mounts attached, databases reachable, and network interfaces online?

### Current Status
* Control Hub exposes ~15 REST endpoints cleanly split into blueprints (`system_vitals`, `storage_ops`, `network_speed`, `config_center`, `services_status`, `downloads_status`).
* Missing machine-readable contract and distinct liveness/readiness separation.

### Required Actions
1. Author `apps/control-hub/docs/openapi.yaml` cataloging all endpoints.
2. Embed lightweight Swagger UI at `http://localhost:7575/api/docs`.
3. Split `/api/health` into `/api/livez` and `/api/readyz`.

---

## 5. Pillar 5: Testing Pyramid & Quality Gates

### The Industry Standard
* **Shift-Left Quality Testing:** Unit tests -> Integration tests -> System/Handoff tests -> Container smoke tests in ephemeral environments.

### Current Status (High Compliance: A-)
* **`testing/test_docs_integrity.py`:** Validates 265+ relative links, images, anchors, and domain READMEs.
* **`setup/test_setup.py`:** Validates zero-dependency wizard, hardware probe, hardlinks, secrets, and dry-run deploy.
* **`testing/test_e2e_regression.py`:** Multi-tier hardware emulation, compose syntax, Netplan rollback safety.
* **`testing/test_lifecycle_handoff.py`:** Complete unmocked Phase 1 (:8099) -> Phase 2 (:7575) runtime handoff.
* **CI Matrix:** Automated across Ubuntu 22.04 & 24.04 and Python 3.10, 3.11, 3.12.

### Required Actions
1. Add an ephemeral Docker container startup test in GitHub Actions to verify real container network binding and healthchecks.

---

## 6. Pillar 6: Documentation & Developer Experience

### The Industry Standard
* **Diátaxis Framework:** Tutorials (getting started), How-To Guides (runbooks), Reference (port/env tables), and Architecture (ADRs).
* **Automated Drift Prevention:** CI tests preventing dead links and missing component documentation.

### Current Status (High Compliance: A)
* Master portal at [`docs/README.md`](README.md).
* Colocated `README.md` in every single functional folder.
* Architecture Decision Records in [`docs/adr/`](adr/README.md).
* Operating standards in [`AGENTS.md`](../AGENTS.md).

---

## 🚀 Actionable Implementation Roadmap

```
PHASE 1 (Immediate - Package Foundation):
├── 1. Cut Git Release Tag: v1.0.0
├── 2. Implement teardown.sh (clean uninstaller & rollback)
└── 3. Update bootstrap.sh with release tag pinning & SHA-256 verification

PHASE 2 (Security Hardening):
├── 4. Restrict Control Hub systemd service to unprivileged user (homelab)
├── 5. Add sudoers drop-in for rtcwake and systemctl
└── 6. Integrate Trivy container vulnerability scanner in CI

PHASE 3 (Developer & Upgrade Experience):
├── 7. Build setup/config_core/schema_migrator.py (.env auto-upgrade)
├── 8. Publish apps/control-hub/docs/openapi.yaml & Swagger UI (:7575/api/docs)
└── 9. Split /api/health into /api/livez and /api/readyz
```
