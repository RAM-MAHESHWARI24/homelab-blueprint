# Homelab System Architecture & Hardware Optimization 📐

## 1. System Specifications & Constraints
* **Platform:** Intel Core i3-4005U (Haswell 2C/4T @ 1.70GHz, 15W TDP)
* **Memory:** 7.2 GiB DDR3 1600 MHz SODIMM
* **Storage Architecture:**
  - **SSD (240 GB):** OS root (`/`), Docker overlays, PostgreSQL containers, thumbnail caches.
  - **HDD (1 TB Mechanical 5400 RPM):** Media libraries (`/mnt/hdd/data`) and family photos (`/mnt/hdd/Memories`).
* **Operating System:** Ubuntu 26.04.1 LTS (Linux Kernel 7.0.0-generic)

## 2. Architectural Principles

### Zero-Overhead Management
Traditional homelab management tools often consume hundreds of megabytes of RAM. Control Hub was engineered with a widget-slice architecture in Python Flask that keeps total idle consumption under **25 MB RAM** and **0.2% CPU**.

### Single-Mount Ext4 Hardlinks
All media pipeline containers share `/mnt/hdd/data:/data`. File transfers between download completion directories and library paths are 100% atomic (inode pointer creation), resulting in 0 additional disk usage and 0 disk I/O.

### Automated RTC S3 Sleep
To protect hardware longevity and conserve power:
* Server suspends to RAM (S3) at **12:00 AM**.
* System wakes via hardware RTC alarm at **06:00 AM**.
* Dynamic deferral checks ensure running backups never get interrupted.
* Self-healing routine post-resume validates network and resets indexer timers.
