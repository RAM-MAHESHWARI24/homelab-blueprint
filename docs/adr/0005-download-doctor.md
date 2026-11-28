# ADR-0005: A Native Download Doctor Replaces Stuck Downloads Through the Apps

## Status
**Accepted** (2026-11-29). Part 1 (stuck downloads, cutoff sweep, blocklist pruning) and part 2 (compact replacement of oversized TV, weekly space report) are implemented.

## Context
Radarr and Sonarr grab a release and then wait for it forever. Nothing marks a torrent as failed when its swarm is dead, when it never gets past "downloading metadata", or when 4 MB of it exist nowhere among the peers. On the live server this blueprint was built for, 20 managed torrents sat in exactly those states, some for six days, while healthier releases of the same titles were available.

Removing such a torrent in qBittorrent does not help: the app neither blocklists the release nor searches again, so its next search can grab the same dead torrent. Removing it through the app's queue with "blocklist" does both. The app then picks the next-best release with its own rules ([plan section 8.1](../../Media%20Pipeline%20Reliability%20Plan.md#81-how-a-safe-replacement-works-inside-the-stack)).

The host sleeps every night and has little RAM to spare, so a fix must not count sleep as waiting time, and must not add an always-on service. Its Python must stay standard-library only like the rest of the module.

## Decision
The mediaserver module ships `scripts/download_doctor.py`, a scheduled job (cron, no daemon) with three jobs:

1. **`stuck`, every 10 minutes.** A managed torrent (one a Radarr or Sonarr queue owns, in that app's category) collects strikes while it is in a bad state: metadata stuck (2 h), dead swarm with availability below 1 (12 h), stalled with a full copy reachable (re-announce at 1 h, replace at 12 h), crawling at more than 3 days left (24 h), client error (1 h, removed without blocklist), permanently import-blocked (6 h), queued forever (24 h, alert only). Patience is counted in **awake** time: a check counts at most 15 minutes, and there are no strikes for 30 minutes after a wake-up, while qBittorrent is disconnected or while DHT has fewer than 50 nodes. New bytes reset the count. Strikes persist in `state.json`.
2. **Replacement goes through the app's queue**: `DELETE /api/v3/queue/{id}?removeFromClient=true&blocklist=true&skipRedownload=false`, or one bulk call for a season pack's records.
3. **Safety rails**: seeding, completed, private and `keep`-tagged torrents are never touched; a circuit breaker stops when at least 60% of torrents (minimum 5) turn bad in the same check; at most 3 replacements per run and 15 per day; three replacements of one title in 7 days mark it "needs attention" and stop; torrents at 90% or more with a full copy reachable get a re-announce and twice the patience. The first 7 days are **watch-only**: decisions are logged as "would …" and nothing changes. `MEDIA_STUCK_DOWNLOADS=off` switches the Doctor off.
4. **`sweep`, daily**: searches up to 10 titles whose files are below their profile's upgrade-until score or quality, oversized ones first, none searched in the last 14 days. It reads each file's custom-format score itself, because Radarr 7's own "Cutoff Unmet" list ignores the custom-format cutoff (7 titles listed against 53 such files on the live server).
5. **`prune`, monthly**: deletes blocklist entries older than 60 days for titles that still have no file, because dead swarms do revive.
6. **`compact`, hourly** (a new pick every 6 hours, one title in flight): oversized TV seasons on `1080p Compact` are replaced by Sonarr's own search results that are 1080p, at least 35% smaller per minute, free of junk, still in the second language where the files have it, and rejected by Sonarr only as "not an upgrade". Season packs need 10 seeders, otherwise episodes with 4 each. It grabs with `POST /api/v3/release`, imports with Sonarr's `ManualImport` after verifying the files, and checks that every episode got a new, smaller file. It needs the release size plus 20 GB free and pauses while a video is open on the Samba share.
7. **`space`, weekly**: a report of torrent-folder files nothing uses, the recycle bin and orphaned resume files; it deletes nothing.
8. **Outputs**: `status.json` (for the Control Hub card in a later phase), `actions.jsonl` (an audit line per decision) and `overrides.json` (protect or extend a torrent, written by the Control Hub), under `/var/lib/homelab/download-doctor/`.

## Alternatives Considered
* **Cleanuparr:**
  * *Rejected:* the richest feature set, but another always-on .NET service on a 7 GB host, configured in its own UI rather than by the installer.
* **Decluttarr:**
  * *Rejected:* light and capable, but strikes live in memory, it has no wake-up grace or per-title cap, and no Control Hub integration.
* **Huntarr:**
  * *Rejected:* the project disappeared in February 2026 after reports of authentication bypasses that exposed *arr API keys.
* **Remove dead torrents in qBittorrent (by hand or with the Control Hub's delete button):**
  * *Rejected:* nothing is blocklisted and nothing is searched, so the same dead release comes back.

## Consequences
### Positive
* Dead downloads are replaced by the next-best release the apps themselves choose, without anyone watching the queue.
* Sleep, network outages and wake-ups do not cause false replacements; the first week shows what it would do before it acts.
* No RAM is used between runs; the installer sets it up with no extra steps, and `teardown.sh` removes it through the install manifest.
* The daily sweep makes the profiles' upgrades (dual audio, compact films) actually happen: the apps only notice older uploads when asked.

### Negative / Trade-offs
* A blocklisted release that would have revived is lost until the monthly prune (60 days).
* Replacements and sweeps add indexer searches; the rate limits keep them to a few per hour.
* Compact replacement relies on two Sonarr behaviours: grabbing a release it rejected as "not an upgrade", and a manual import over existing files that sends the old ones to the recycle bin. Both are tested on a live server ([plan Appendix K](../../Media%20Pipeline%20Reliability%20Plan.md#appendix-k-verify-before-relying-on-it), items 4 and 5). A Sonarr change could break them, so the job verifies every import.
* Replacing a season means downloading it again; with packs of 10 seeders and one title at a time, a large show takes days, not hours.
* Never run it together with another cleaner (Cleanuparr, Decluttarr): two owners would race each other.

## References
* [Download Doctor guide](../DOWNLOAD_DOCTOR.md)
* [download_doctor.py](../../apps/mediaserver/scripts/download_doctor.py) -> `Doctor.run_stuck()`, `Doctor.run_sweep()`, `Doctor.run_prune()`
* [Media Pipeline Reliability Plan, section 8](../../Media%20Pipeline%20Reliability%20Plan.md#8-stuck-downloads-the-download-doctor)
* [ADR-0004: Repo-Owned Release Profiles Replace Recyclarr](0004-repo-owned-release-profiles.md)
* [ADR-0003: ACPI S3 Suspend-to-RAM with RTC Wake vs Continuous Idle](0003-acpi-s3-sleep-guard-power-automation.md)
