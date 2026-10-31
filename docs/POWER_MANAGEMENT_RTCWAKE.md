# Power Management & Scheduled S3 Suspend / RTC Wake Blueprint ⚡

## 1. Overview
Running a home server 24/7 when all household members are asleep wastes electricity and generates unnecessary heat. This blueprint implements an automated **Suspend-to-RAM (S3)** routine that reduces power consumption to **<1.2 Watts** between 12:00 AM and 06:00 AM.

## 2. Dynamic Safety Guards
Rather than blindly suspending the system, `/usr/local/sbin/server-suspend.sh` checks live system state before sleep:
1. **Active Backup Detection:**
   ```bash
   pgrep -f "immich_backup_gdrive.sh" || pgrep -f "rclone sync" || pgrep -f "pg_dumpall"
   ```
   If a database snapshot or cloud backup is running, suspend is automatically deferred until the following check.
2. **One-Off Shift Buttons (`/run/server-suspend.override`):**
   Users can delay sleep by `+1h` or `+2h` from Control Hub. The script respects the override and automatically clears it upon waking up.
3. **Inhibition Toggle (`/run/server-suspend.skip`):**
   A simple touch flag disables sleep for the night.

## 3. Hardware RTC Wake Mechanism
The Linux kernel alarm is armed using `/usr/sbin/rtcwake`:
```bash
/usr/sbin/rtcwake -m mem -s 21600
```
This suspends the OS to RAM and programs the motherboard hardware Real-Time Clock to wake up the system precisely 6 hours later (06:00 AM).

## 4. Post-Wake Self-Healing Routine
When the system resumes from S3:
1. Pings public DNS (`1.1.1.1`) up to 30s until network link and DHCP recover.
2. Waits 5 seconds for daemon sockets to bind.
3. **Prowlarr Reset:** Calls `/api/v1/indexer/testall` to reset any backoff penalty timers accumulated during sleep.
4. **Sonarr/Radarr Sync:** Triggers `CheckHealth` and `RssSync` commands to immediately pick up any new releases uploaded overnight.

## 5. Dry-Run Testing & CI Simulation Mode
To test suspension deferral, override parsing, and duration calculation in CI or regression harnesses without invoking hardware Real-Time Clock sleep:
```bash
/usr/local/sbin/server-suspend.sh --dry-run
# or
DRY_RUN=1 /usr/local/sbin/server-suspend.sh
```

In test environments, all default file paths can be redirected to isolated sandbox paths via environment variables:
* `SERVER_SUSPEND_LOG`: Destination log file (default: `/var/log/server-suspend.log`)
* `SERVER_SUSPEND_SKIP`: Inhibition flag (default: `/run/server-suspend.skip`)
* `SERVER_SUSPEND_OVERRIDE`: Temporary override config (default: `/run/server-suspend.override`)
* `SERVER_SUSPEND_CONF`: Permanent schedule config (default: `/etc/server-suspend.conf`)

