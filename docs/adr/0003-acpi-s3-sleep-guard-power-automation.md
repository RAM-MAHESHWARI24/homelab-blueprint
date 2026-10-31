# ADR-0003: ACPI S3 Suspend-to-RAM with RTC Wake vs Continuous Idle

## Status
**Accepted**

## Context
Homelab servers operated at home frequently sit completely idle for 6 to 8 hours during the night (e.g. 00:00 midnight to 06:00 AM).
* Running a low-power Intel or AMD mini-PC 24/7 at an idle 15W–35W consumes unnecessary electricity (~130–300 kWh/year), generates continuous heat, and causes mechanical wear on storage drive bearings.
* However, abruptly shutting down the machine (ACPI S5) or using deep disk hibernation (ACPI S4) makes automated scheduled waking unreliable across consumer motherboard BIOSes, introduces slow resume times, and can corrupt memory states during container restarts.
* Crucially, a naive sleep schedule can interrupt active media streams, ongoing torrent downloads, or LAN file transfers.

## Decision
We adopt **ACPI S3 Suspend-to-RAM orchestrated by a multi-guard daemon script (`server-suspend.sh`) and hardware CMOS RTC alarms (`rtcwake`)**:
1. **ACPI S3 Target State:** The machine enters Suspend-to-RAM (`mem`), cutting host power consumption down to ~1.2W while keeping RAM powered.
2. **Scheduled Hardware Alarm:** The motherboard RTC (Real-Time Clock) is programmed using `rtcwake -m mem -s <seconds>` to awaken the server automatically at 06:00 AM.
3. **Multi-Condition Sleep Guard:**
   * **UI Skip Override:** If `/run/server-suspend.skip` exists (toggled from Control Hub UI), sleep is aborted for tonight.
   * **Active Torrent Guard:** Checks qBittorrent download bandwidth; if active downloads exceed minimum threshold, sleep is deferred.
   * **Active SMB Guard:** Inspects `smbstatus` to confirm no remote machines are actively streaming or writing files.
4. **Post-Wake Self-Healing:** Resumes in < 2 seconds, re-verifies network connectivity, and restarts Docker services if necessary.

## Alternatives Considered
* **Continuous 24/7 Idle (No Sleep):**
  * *Rejected:* Wastes 30–50% of annual electricity consumption with zero benefit when all household members are asleep.
* **ACPI S4 Hibernation (Suspend-to-Disk):**
  * *Rejected:* Requires large swap partition, subjects SSD to excessive TBW write wear on every sleep cycle, and has high failure rates on Linux consumer hardware.
* **ACPI S5 Complete Shutdown (Wake-on-LAN):**
  * *Rejected:* Cannot wake automatically on an internal timer without external hardware (e.g. smart plug or secondary always-on Raspberry Pi sending WOL magic packets).

## Consequences
### Positive
* **Huge Power Savings:** Drops idle power from ~25W to ~1.2W for 6 hours nightly (~55 kWh/year saved per node).
* **Instant Resume:** Machine wakes and recovers all network connections and container ports in under 3 seconds.
* **Zero Interruption Risk:** Active downloads, SMB streams, or manual UI overrides reliably block sleep.

### Negative / Trade-offs
* Motherboard BIOS must support ACPI S3 state (standard on 99% of x86 hardware).
* CMOS battery must be functional to maintain RTC clock state.

## References
* [Power Management & RTC Wake Guide](../POWER_MANAGEMENT_RTCWAKE.md)
* [Server Suspend Script](../../system/power/server-suspend.sh)
* [System Host Daemons](../../system/README.md)

