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
| **Packaging & Distribution** | **SemVer 2.0.0**, GitHub Releases, Checksums | Pinned release tags (`v1.1.0`), version-pinned `bootstrap.sh`, clean uninstaller `teardown.sh` | **A-** | Offline tarball bundle, SHA-256 installer verification, official GitHub Releases pages. |
| **Security & Supply Chain** | **CIS Linux Benchmark**, SLSA L1/2, Principle of Least Privilege | Unprivileged `homelab` systemd user, sudoers whitelist, Gitleaks, Trivy vulnerability scan in CI | **A-** | Docker socket proxy (`tecnativa/docker-socket-proxy`), Control Hub LAN authentication guard. |
| **Configuration** | **The Twelve-Factor App (III. Config)**, Strict Schema | Master `.env` sync + automated schema migrator (`schema_migrator.py`) with backups | **A+** | Strict Pydantic/JSON schema validation for `.env` types. |
| **API & Interfaces** | **OpenAPI 3.1**, RFC 7807 (Problem Details), REST | Full OpenAPI 3.1 spec, embedded Swagger UI (`:7575/api/docs`), `/livez` & `/readyz` probes | **A+** | RFC 7807 standard error schemas, Prometheus metrics endpoint (`/metrics`). |
| **Testing & CI/CD** | **Test Pyramid**, Multi-Environment Simulation | 4 automated test suites in CI matrix (Ubuntu 22/24, Py3.10-12), 30 tests 100% green | **A** | Real container smoke test in CI (`docker compose up -d control-hub`), Tier 2 Hardware-in-the-Loop VM runs. |
| **Documentation** | **Diátaxis Framework**, ADRs (Nygard), Docs-as-Code | Colocated READMEs, 3 ADRs, CI link integrity test (280 links, 0 broken) | **A+** | Interactive terminal GIFs (vhs/asciinema), disaster recovery runbooks (`backup.sh`/`restore.sh`). |

---

## 1. Pillar 1: Package Delivery & Versioning

### The Industry Standard
* **[SemVer 2.0.0](https://semver.org/):** `MAJOR.MINOR.PATCH`. Major = breaking config/storage changes; Minor = new services/widgets; Patch = bugfixes.
* **Reproducible Asset Distribution:** Deployers download immutable release bundles (`homelab-blueprint-v1.1.0.tar.gz`) accompanied by cryptographic SHA-256 checksums (`checksums.txt.sha256`).
* **Safe 1-Line Bootstrap:** Installers must allow pinning a specific release or branch:
  ```bash
  curl -sSL https://raw.githubusercontent.com/.../bootstrap.sh | sudo bash -s -- --version v1.1.0
  ```

### Current Status (High Compliance: A-)
* **Pass:** Inaugural production releases cut and tagged on `main`: `v1.0.0`, `v1.0.1`, and `v1.1.0`.
* **Pass:** `bootstrap.sh` supports `--version <tag>` and `--branch <name>` pinning.
* **Pass:** Clean cluster uninstaller [`teardown.sh`](../teardown.sh) implemented with `--dry-run`, `--purge-data`, and `--force` flags.
* **Pass:** Pre-flight diagnostic doctor CLI [`setup/doctor.py`](../setup/doctor.py) wired into `./setup.sh --doctor`.

### Next Actions
1. Generate and verify SHA-256 checksums during bootstrap.
2. Publish official GitHub Release notes on GitHub with downloadable source tarballs.

---

## 2. Pillar 2: Security & Supply Chain Hardening

### The Industry Standard
* **CIS Ubuntu Linux Benchmark & Least Privilege:** No long-running daemon should execute as `root` unless strictly required for kernel ring operations.
* **Docker Socket Isolation:** Direct exposure of `/var/run/docker.sock` gives container processes unmitigated root access to the host.
* **SLSA Level 1 & Vulnerability Scanning:** Every container image and dependency must be scanned for CVEs before deployment.

### Current Status (High Compliance: A-)
* **Pass:** Clean Git history verified via Gitleaks CI action on every commit and PR.
* **Pass:** Container file permissions mapped strictly to unprivileged user (`PUID=1000`, `PGID=1000`, `UMASK=002`).
* **Pass:** Control Hub systemd daemon restricted to unprivileged system user `homelab` (`User=homelab`, `Group=homelab`, `SupplementaryGroups=docker`).
* **Pass:** Granular sudoers drop-in whitelist at [`system/systemd/homelab-sudoers.example`](../system/systemd/homelab-sudoers.example) restricting `homelab` user to `/usr/sbin/rtcwake` and systemctl commands.
* **Pass:** Container and repository filesystem vulnerability scanning integrated into CI via `aquasecurity/trivy-action`.

### Next Actions
1. **Control Hub LAN Auth Guard:** Add optional HTTP Basic Auth or session PIN lock (`CONTROL_HUB_PASSWORD` in `.env`) for shared household Wi-Fi / VPN networks.
2. **Docker Socket Proxy:** Introduce `tecnativa/docker-socket-proxy` to restrict API calls to read-only container inspection.

---

## 3. Pillar 3: Configuration & Schema Migration

### The Industry Standard
* **The Twelve-Factor App:** Configuration stored strictly in the environment, separated cleanly from application logic.
* **Schema Evolution & Zero-Downtime Upgrades:** When new releases introduce new `.env` keys, an automated migrator upgrades legacy configs without user intervention or manual copy-pasting.

### Current Status (High Compliance: A+)
* **Pass:** Dynamic synchronization between root `.env` and downstream stacks (`apps/mediaserver/.env`, `apps/noodle-gallery/.env`, `apps/control-hub/.env`) via `setup/config_core/env_manager.py`.
* **Pass:** Automated schema migrator implemented at [`setup/config_core/schema_migrator.py`](../setup/config_core/schema_migrator.py). Automatically detects schema diffs against `.env.example`, injects missing keys with defaults, creates timestamped backups (`.env.backup.<timestamp>`), and preserves user secrets.
* **Pass:** Integrated tooling exposed via `./setup.sh --migrate` (with `--check` and `--dry-run` flags) and integrated into pre-flight diagnostic prober (`./setup.sh --doctor`).
* **Pass:** Verified with regression test `TC-MIGRATOR-01` in `testing/test_e2e_regression.py`.

### Next Actions
1. Strict type checking and value validation for `.env` parameters (e.g. validating integer ports, valid IP formatting).

---

## 4. Pillar 4: API Architecture & Observability

### The Industry Standard
* **OpenAPI 3.1 Specification:** Machine-readable API contracts defining every route, request schema, and response payload.
* **Kubernetes-Style Health Probing:**
  * **Liveness Probe (`/livez`):** Is the web process responding to socket connections?
  * **Readiness Probe (`/readyz`):** Are downstream storage mounts attached, databases reachable, and network interfaces online?

### Current Status (High Compliance: A+)
* **Pass:** Control Hub exposes 20+ REST endpoints cleanly split into modular blueprints.
* **Pass:** Complete OpenAPI 3.1.0 contract published at [`apps/control-hub/docs/openapi.yaml`](../apps/control-hub/docs/openapi.yaml).
* **Pass:** Interactive dark-theme Swagger UI embedded and served at `http://localhost:7575/api/docs`.
* **Pass:** Kubernetes-standard `/api/livez`, `/api/readyz`, and `/api/health` endpoints implemented and verified with regression test `TC-FLOW-09` in `testing/test_lifecycle_handoff.py`.

### Next Actions
1. RFC 7807 (Problem Details for HTTP APIs) standard error schema formatting.
2. Prometheus metrics exporter endpoint (`/metrics`) for CPU, RAM, and network counters.

---

## 5. Pillar 5: Testing Pyramid & Quality Gates

### The Industry Standard
* **Shift-Left Quality Testing:** Unit tests -> Integration tests -> System/Handoff tests -> Container smoke tests in ephemeral environments.

### Current Status (High Compliance: A)
* **Pass:** 4 automated test suites running in CI matrix across Ubuntu 22.04 & 24.04 and Python 3.10, 3.11, 3.12 (30 test cases, 100% pass):
  * **`testing/test_docs_integrity.py`:** Validates 280 relative links, images, anchors, and domain READMEs with 0 broken links.
  * **`setup/test_setup.py`:** Validates zero-dependency wizard, hardware probe, hardlinks, secrets, and dry-run deploy.
  * **`testing/test_e2e_regression.py`:** Multi-tier hardware emulation, compose syntax, Netplan rollback safety, uninstaller, unprivileged security, doctor, and schema migrator.
  * **`testing/test_lifecycle_handoff.py`:** Complete unmocked Phase 1 (:8099) -> Phase 2 (:7575) runtime handoff, vitals, config center, and OpenAPI contracts.
* **Pass:** Multi-arch container image availability verified for `amd64` and `arm64` via QEMU.

### Next Actions
1. Add an ephemeral Docker container startup test in GitHub Actions to verify real container network binding and healthchecks (`docker compose up -d control-hub`, curl `:7575/api/livez`, compose down).
2. Execute Tier 2 Hardware-in-the-Loop VM integration tests from [`testing/README.md`](../testing/README.md) (`TC-MEDIA-E2E-01..06`, `TC-FACE-E2E-01..06`, `TC-BACKUP-E2E-01..05`).

---

## 6. Pillar 6: Documentation & Developer Experience

### The Industry Standard
* **Diátaxis Framework:** Tutorials (getting started), How-To Guides (runbooks), Reference (port/env tables), and Architecture (ADRs).
* **Automated Drift Prevention:** CI tests preventing dead links and missing component documentation.

### Current Status (High Compliance: A+)
* **Pass:** Master documentation portal at [`docs/README.md`](README.md).
* **Pass:** Colocated `README.md` in every functional component directory.
* **Pass:** Architecture Decision Records in [`docs/adr/`](adr/README.md).
* **Pass:** Authoritative operating standards for AI coding agents in [`AGENTS.md`](../AGENTS.md).
* **Pass:** Standalone repository published at [github.com/RAM-MAHESHWARI24/control-hub](https://github.com/RAM-MAHESHWARI24/control-hub) with independent CI.

### Next Actions
1. Unified disaster recovery runbooks and scripts (`backup.sh` and `restore.sh`).
2. Interactive terminal GIFs (vhs / asciinema) for Setup Wizard and Control Hub.

---

## 🚀 Actionable Implementation Roadmap

```
PHASE 1 (Package Foundation) [100% COMPLETE]:
├── [x] 1. Cut Git Release Tag: v1.0.0 & v1.0.1
├── [x] 2. Implement teardown.sh (clean uninstaller & rollback with --dry-run & --purge-data)
├── [x] 3. Update bootstrap.sh with release tag pinning & branch flags
└── [x] 4. Implement pre-flight diagnostic prober (setup/doctor.py & ./setup.sh --doctor)

PHASE 2 (Security Hardening) [100% COMPLETE]:
├── [x] 5. Restrict Control Hub systemd service to unprivileged user (homelab)
├── [x] 6. Add sudoers drop-in for rtcwake and systemctl (system/systemd/homelab-sudoers.example)
└── [x] 7. Integrate Trivy container & repo vulnerability scanner in CI (.github/workflows/ci.yml)

PHASE 3 (Developer & Upgrade Experience) [100% COMPLETE]:
├── [x] 8. Build setup/config_core/schema_migrator.py (.env auto-upgrade & ./setup.sh --migrate)
├── [x] 9. Publish apps/control-hub/docs/openapi.yaml & Swagger UI (:7575/api/docs)
├── [x] 10. Split /api/health into /api/livez and /api/readyz
├── [x] 11. Extract standalone control-hub repo with independent CI matrix
└── [x] 12. Cut Git Release Tag: v1.1.0

PHASE 4 (Zero-Trust Security & Disaster Recovery) [UPCOMING]:
├── 13. Implement Control Hub LAN Auth Guard (PIN/Password via .env)
├── 14. Build unified backup.sh & restore.sh disaster recovery engine
└── 15. Introduce tecnativa/docker-socket-proxy for read-only Docker socket isolation

PHASE 5 (Full E2E Integration & Observability) [UPCOMING]:
├── 16. Ephemeral Docker container startup smoke test in GitHub Actions
├── 17. Prometheus metrics exporter endpoint (/metrics) for Control Hub
└── 18. Official GitHub Release notes publication with downloadable tarballs & SHA-256
```
