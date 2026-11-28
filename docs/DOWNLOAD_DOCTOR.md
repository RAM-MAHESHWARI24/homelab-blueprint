# Download Doctor

The Download Doctor finds downloads that will never finish and replaces them through Radarr or Sonarr, so the app blocklists the dead release and grabs the next-best one by its own rules. It also asks the apps to look for upgrades every day and clears old blocklist entries once a month. It is a scheduled job in the mediaserver module ([`download_doctor.py`](../apps/mediaserver/scripts/download_doctor.py)), not a service: nothing runs between checks. Why it works this way: [ADR-0005](adr/0005-download-doctor.md).

## Contents

1. [What it does](#what-it-does)
2. [When a download counts as stuck](#when-a-download-counts-as-stuck)
3. [What it never touches](#what-it-never-touches)
4. [The first week: watch-only](#the-first-week-watch-only)
5. [Daily upgrade sweep](#daily-upgrade-sweep)
6. [Files it writes](#files-it-writes)
7. [Commands](#commands)
8. [Switching it off](#switching-it-off)
9. [Troubleshooting](#troubleshooting)

## What it does

| Job | When | What |
| :--- | :--- | :--- |
| `stuck` | Every 10 minutes | Counts strikes for each download an app owns. Past its patience, removes it **through the app's queue** with "remove from client", "blocklist" and "search again", so the app picks the next release itself |
| `sweep` | Daily at 07:15 | Searches up to 10 titles whose file is below its profile's upgrade-until score (for example an English-only film when a Hindi + English release would be preferred), oversized ones first |
| `prune` | 07:45 on the 1st | Deletes blocklist entries older than 60 days for titles that still have no file: dead swarms do come back |

Removing a dead torrent in qBittorrent, or with the Control Hub's delete button, is not the same: the app neither blocklists it nor searches again, so its next search can grab the same dead torrent.

## When a download counts as stuck

Patience counts **awake** time only: the server sleeps at night, so 12 hours of patience is about a calendar day. A check counts at most 15 minutes, and any new downloaded bytes reset the count.

| State in qBittorrent | Patience | Then |
| :--- | ---: | :--- |
| Stuck fetching metadata | 2 h | Replace |
| Stalled, and some pieces exist nowhere in the swarm (availability below 1) | 12 h | Replace |
| Stalled, but a full copy is reachable | 1 h, then 12 h | Re-announce at 1 hour, replace at 12 |
| Downloading, but more than 3 days left | 24 h | Replace, unless it is past 90% |
| Error or missing files | 1 h | Remove without blocklist and search again |
| Finished, but the app can never import it ("No files found are eligible", sample only, no audio tracks) | 6 h | Replace |
| Queued and never started | 24 h | Alert only (a settings problem, not a bad release) |

A download at 90% or more with a full copy reachable is re-announced first and gets twice the patience.

No strikes are counted:
* for 30 minutes after the server wakes up (a gap of more than 25 minutes between checks);
* while qBittorrent is disconnected or has fewer than 50 DHT nodes;
* when at least 60% of the downloads (and at least 5) turn bad in the same check: that is a network problem, not bad releases (the **circuit breaker**).

Limits: at most 3 replacements per check and 15 per day. When the same movie, or the same season, has been replaced 3 times in 7 days, the Doctor stops and marks it **needs attention**: usually no healthy release exists on your indexers yet. Search it by hand, wait, or move it to another profile (for example `1080p Family`, which also takes 720p releases with the second language).

## What it never touches

* Downloads that no Radarr or Sonarr queue owns, or that are in another category: anything you added by hand.
* Completed and seeding torrents.
* Torrents tagged `keep` in qBittorrent.
* Private-tracker torrents (their ratio rules apply); they are listed in the status as skipped.

## The first week: watch-only

For 7 days after its first run, the Doctor only writes what it **would** do (`would_replace`, `would_reannounce`, `would_search`, `would_prune`) to its audit log and status file. Read them, compare them with what you would have done, and let it act on day 8. Each "would" decision is logged once per download, not every 10 minutes.

## Daily upgrade sweep

The apps only find better releases of titles you already have when someone asks. The sweep asks for up to 10 titles a day:
* titles whose file scores below its profile's upgrade-until score, or whose quality is below the cutoff;
* oversized files first (films above 55 MB per minute, TV above 30), then the longest unsearched;
* never the same title twice within 14 days.

It reads each file's score itself, because Radarr's own "Cutoff Unmet" list leaves out files that are only below the custom-format cutoff. With the [release profiles](MEDIA_RELEASE_PROFILES.md), this is what turns "Hindi preferred" into actual upgrades.

## Files it writes

Under `/var/lib/homelab/download-doctor/`:

| File | What |
| :--- | :--- |
| `status.json` | The latest summary: mode, downloads with problems and how long they have been stuck, actions in the last 24 hours, titles that need attention, alerts, and the last sweep and prune. The Control Hub will show it as a card |
| `actions.jsonl` | One line per decision: time, app, title, reason, hours stuck, indexer, action and result. Rotated at 1 MB |
| `state.json` | Strikes and history; survives restarts and updates |
| `overrides.json` | Optional, written by you or (later) the Control Hub: `{"protect": ["<hash>"], "extend": {"<hash>": <unix time>}}` exempts a torrent, or gives it unlimited patience until a time |
| `cron.log` | Output of the scheduled runs |

## Commands

```bash
cd /opt/homelab-blueprint/apps/mediaserver
# What it would do, without changing anything. Use a scratch state folder: a run updates its
# state, and the real one belongs to the scheduled job.
sudo python3 scripts/download_doctor.py --job stuck,sweep --config-dir /srv/homelab/appdata/mediaserver \
  --env-file /etc/homelab/mediaserver.env --state-dir /tmp/doctor-test --dry-run --json
# The latest status and the audit log
sudo cat /var/lib/homelab/download-doctor/status.json
sudo tail -n 20 /var/lib/homelab/download-doctor/actions.jsonl
```

The schedule is `/etc/cron.d/mediaserver-download-doctor`. Adding `--watch-days 0` to its `stuck` line skips the watch-only week. A standalone mediaserver install has no installer: add the three lines from [`host/cron/mediaserver-download-doctor`](../apps/mediaserver/host/cron/mediaserver-download-doctor) to root's crontab with your paths.

## Switching it off

Set `MEDIA_STUCK_DOWNLOADS=off` in `/etc/homelab/mediaserver.env` (the Setup Wizard's "Stuck downloads: Off"). The jobs keep running but do nothing, and the status says so. Never run it together with another cleaner such as Cleanuparr or Decluttarr: both would replace the same downloads.

## Troubleshooting

* **Nothing happens.** Check `status.json`: `mode` (`watch-only` for the first 7 days, `off` when switched off), `grace` (just woke up, qBittorrent offline, thin DHT, circuit breaker) and `errors` (an app or qBittorrent unreachable).
* **A download I want to keep was flagged.** Tag it `keep` in qBittorrent, or add its hash to `protect` in `overrides.json`.
* **The same title keeps failing.** After 3 replacements in 7 days it shows under `needs_attention`. Search it interactively in the app: every result shows why it was rejected. See [Why isn't it downloading?](MEDIA_RELEASE_PROFILES.md#why-isnt-it-downloading).
* **Too many searches.** The sweep is capped at 10 titles a day; replacements at 3 per check and 15 per day.

## Related

* [Release profiles and dual audio](MEDIA_RELEASE_PROFILES.md)
* [mediaserver module README](../apps/mediaserver/README.md)
* [Media Pipeline Reliability Plan, section 8](../Media%20Pipeline%20Reliability%20Plan.md#8-stuck-downloads-the-download-doctor)
