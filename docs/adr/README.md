# Architecture Decision Records (ADR) 🏛️📐

> Architectural decisions for the **Homelab Blueprint** monorepo, capturing the business context, alternatives considered, chosen approach, and operational consequences.

---

## 📑 What is an ADR?

An **Architecture Decision Record (ADR)** is a lightweight software engineering document that captures an important architectural decision made along with its context and consequences.

ADRs prevent **architecture amnesia**—ensuring future maintainers, operators, and AI coding agents understand *why* a particular design was chosen instead of repeatedly revisiting solved problems or introducing breaking regressions.

---

## 📋 Status Taxonomy

* **Proposed**: Under review; not yet accepted or implemented.
* **Accepted**: Formally approved and implemented across the blueprint.
* **Superseded**: Replaced by a newer decision (with a link to the successor).
* **Deprecated**: No longer relevant or actively maintained.

---

## 🗂️ Decision Index

| ADR ID | Title | Status | Date | Decision Summary |
| :--- | :--- | :--- | :--- | :--- |
| **[ADR-0001](0001-single-mount-atomic-hardlinks.md)** | Single ext4 Mount for Atomic 0-I/O Hardlinks | **Accepted** | 2026-10-15 | Enforces a single filesystem boundary (`/data`) across qBittorrent and *arr apps to eliminate slow duplicate disk copies. |
| **[ADR-0002](0002-zero-dependency-setup-wizard.md)** | Zero-Dependency Standard-Library-Only Setup Wizard | **Accepted** | 2026-10-18 | Bootstrap web wizard and config engine use pure Python 3 stdlib with zero pip or third-party dependencies before server is provisioned. |
| **[ADR-0003](0003-acpi-s3-sleep-guard-power-automation.md)** | ACPI S3 Suspend-to-RAM with RTC Wake vs Continuous Idle | **Accepted** | 2026-10-20 | Implements night-time ACPI S3 suspend (~1.2W) with hardware CMOS RTC wakeup and active SMB/download safety guards. |

---

## ✍️ How to Propose a New ADR

To propose a new architecture decision:
1. Copy the standard template below into `docs/adr/NNNN-your-decision-title.md`.
2. Assign the next sequential number.
3. Submit a pull request with status set to `Proposed`.
4. Update the index table in this file.

```markdown
# ADR-NNNN: [Short Title of Decision]

## Status
[Proposed | Accepted | Superseded | Deprecated]

## Context
What is the problem or architectural challenge we are facing?
What constraints or requirements exist?

## Decision
What is the change or approach we are committing to?

## Alternatives Considered
* Option A: ... (Why was this rejected?)
* Option B: ... (Why was this rejected?)

## Consequences
### Positive
* Benefits gained.

### Negative / Trade-offs
* Operational complexities or limitations to be aware of.
```

