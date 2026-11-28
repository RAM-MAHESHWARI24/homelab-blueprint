# Media Pipeline Reliability Plan

> **Status:** Phase 0 was applied on the live server on 2026-11-28 ([record](#phase-0-record-applied-2026-11-28)). Phase 1 was merged ([#89](https://github.com/RAM-MAHESHWARI24/homelab-blueprint/pull/89)) and deployed on the live server on 2026-11-28 ([record](#phase-1-implementation-notes)). Later phases are not implemented yet.
> **Revision 2 (2026-11-28):** updated with the owner's decisions (summarised just below), including NFO metadata for Nova and automatic compact replacement of oversized titles.
> **Revision 3 (2026-11-28):** made self-contained for implementation in a new session: [section 0](#0-implementation-handoff-start-here) (handoff) and appendices F–K (live baseline, API cheat-sheet, test corpus, fixtures, safe observation, verification list).
> **Revision 4 (2026-11-28):** the owner's decisions on the profiles and on scoring ([record](#revision-4-owner-decisions-on-profiles-and-scoring-2026-11-28)): `1080p Compact` is 1080p only, `1080p Family` replaces `Dual Audio First` and requires Hindi, and small tie-breakers never trigger an upgrade. Applied throughout this plan and in Phase 1 ([notes](#phase-1-implementation-notes)).
> **Scope:** Prowlarr, Radarr, Sonarr, qBittorrent, Bazarr, Jellyfin, the Control Hub and the Setup Wizard. It also covers replacing Recyclarr.
> **Evidence:** a read-only snapshot of the live server taken on 2026-11-28: API `GET` calls, a read-only look at config files, and two interactive searches (Radarr's "search without grabbing" endpoint). Server addresses, host names and account names are deliberately left out of this file.

What this plan sets out to achieve:

1. **Pick a healthy, good release the first time**, using the apps' own settings.
2. **When a download still gets stuck**, detect it and replace it with the next-best release automatically, without risking the library.
3. **Get Hindi + English dual audio** whenever it exists, and get the **best quality for the disk space** everywhere else.
4. **Make the Control Hub more useful**, and keep everything installable by anyone in a few clicks.

Owner decisions (2026-11-28):

| Topic | Decision | Effect on the plan |
| :--- | :--- | :--- |
| Profiles | Two profiles. **`1080p Compact`**: the best 1080p (1080p only), dual audio preferred. **`1080p Family`**: Hindi required, English a bonus, 720p allowed, English-only rejected (revision 4; it replaced `Dual Audio First`) | [Section 5.2](#52-two-profiles) |
| Playback | Over **SMB with Nova Video Player** on Android TVs | The TVs decode everything and the server never transcodes. HEVC is preferred; AV1 and Dolby Vision without a fallback are blocked. Jellyfin only stays as Seerr's backend ([section 7](#7-playback-over-smb-with-nova-video-player)) |
| Seeding | Seed if it helps, otherwise a little. Bandwidth is plentiful; **disk, CPU and RAM are tight** | "Seed while it helps" policy ([section 5.7](#57-qbittorrent)); every component avoids new always-on services |
| Build or adopt | Whatever is best for this setup and for a **few-click public installer** | Native Download Doctor ([section 8](#8-stuck-downloads-the-download-doctor)); **Recyclarr replaced by a repo-owned profile pack** ([section 5.9](#59-replacing-recyclarr-with-a-repo-owned-profile-pack)); a Setup Wizard step for these choices ([section 5.10](#510-any-second-language-and-a-setup-wizard-step)) |
| Library metadata | Nova reads (and can write) NFO files | Radarr and Sonarr own the NFO files and artwork; Nova reads them instead of guessing from file names ([section 7](#7-playback-over-smb-with-nova-video-player)) |
| Oversized titles | Keep looking for more compact versions (for example *Succession*), download them, and delete the old files only after a proper import | Compact replacement ([section 8.6](#86-compact-replacement-keep-hunting-for-smaller-versions)) |
| Documentation | Document everything | [Section 12](#12-documentation-plan) lists every guide, ADR and README change |

## Contents

0. [Implementation handoff (start here)](#0-implementation-handoff-start-here)
1. [Summary](#1-summary)
2. [How this was investigated](#2-how-this-was-investigated)
3. [Live snapshot](#3-live-snapshot)
4. [Root causes](#4-root-causes)
5. [Target configuration](#5-target-configuration)
6. [Dual audio, end to end](#6-dual-audio-end-to-end)
7. [Playback over SMB with Nova Video Player](#7-playback-over-smb-with-nova-video-player)
8. [Stuck downloads: the Download Doctor](#8-stuck-downloads-the-download-doctor)
9. [Control Hub: a more useful dashboard](#9-control-hub-a-more-useful-dashboard)
10. [Other defects found](#10-other-defects-found)
11. [Rollout plan](#11-rollout-plan)
12. [Documentation plan](#12-documentation-plan)
13. [Success metrics](#13-success-metrics)
14. [Decisions](#14-decisions)
15. [Risks](#15-risks)
16. [References](#16-references)
17. [Appendices](#appendices): A seeders · B custom formats · C profile pack layout · D evidence · E Decluttarr · [F live baseline](#appendix-f-live-baseline-2026-11-28) · [G API cheat-sheet](#appendix-g-api-cheat-sheet) · [H test corpus](#appendix-h-release-title-test-corpus) · [I Doctor fixtures](#appendix-i-download-doctor-test-fixtures) · [J observing the server](#appendix-j-observing-the-live-server-safely) · [K verify first](#appendix-k-verify-before-relying-on-it)
18. [Revision 4: owner decisions on profiles and scoring](#revision-4-owner-decisions-on-profiles-and-scoring-2026-11-28)

---

## 0. Implementation handoff (start here)

This plan is meant to be implemented in fresh sessions, one phase at a time. Everything needed is in this file; nothing depends on the conversation that produced it. Start here, then read the sections listed for your phase.

### Phase status

Update this table when a phase lands.

| Phase | Scope | Status | Branch / PR |
| :--- | :--- | :--- | :--- |
| 0 | Manual fixes on the live server ([section 11](#11-rollout-plan)) | Done 2026-11-28 (steps 1–9, 11–12 applied by an agent with approval; see the [Phase 0 record](#phase-0-record-applied-2026-11-28)). The owner still does steps 10 and 11 on the TVs (Nova). 2-hour check pending | `docs/phase0-live-fixes` |
| 1 | Profile pack replacing Recyclarr, plus the Setup Wizard step | Done 2026-11-28: merged with revision 4 and the untagged-language fix, deployed and migrated on the live server by an agent with the owner's approval (live record in the [notes](#phase-1-implementation-notes)) | `feat/mediaserver-profile-pack`, [PR #89](https://github.com/RAM-MAHESHWARI24/homelab-blueprint/pull/89) |
| 2 | Download Doctor: stuck downloads, compact replacement, sweeps | Not started | — |
| 3 | Control Hub (six PRs) | Not started | — |
| 4 | Housekeeping | Not started | — |

### What to read for each phase

| Phase | Read | Reference |
| :--- | :--- | :--- |
| 0 | Sections 4, 5.4–5.7, 8.9 and 11 (Phase 0) | [Appendix F](#appendix-f-live-baseline-2026-11-28) for current values and rollback; [Appendix J](#appendix-j-observing-the-live-server-safely) |
| 1 | Sections 4.1, 5, 6, 11 (Phase 1) and 12 | Appendices B and C; [G](#appendix-g-api-cheat-sheet), [H](#appendix-h-release-title-test-corpus), [K](#appendix-k-verify-before-relying-on-it) |
| 2 | Sections 8, 11 (Phase 2) and 12 | Appendices [G](#appendix-g-api-cheat-sheet), [I](#appendix-i-download-doctor-test-fixtures), [J](#appendix-j-observing-the-live-server-safely), [K](#appendix-k-verify-before-relying-on-it) |
| 3 | Sections 9, 10, 11 (Phase 3) and 12 | Appendices [F](#appendix-f-live-baseline-2026-11-28), [G](#appendix-g-api-cheat-sheet), [K](#appendix-k-verify-before-relying-on-it) |
| 4 | Sections 7, 10 and 11 (Phase 4) | [Appendix F](#appendix-f-live-baseline-2026-11-28) |

### Ground rules

From [AGENTS.md](AGENTS.md) and the decisions in this plan:

- **Branches.** Work on a topic branch off `develop` (`feat/…`, `fix/…`, `docs/…`) with Conventional Commits. Never commit to `main`.
- **Standard library only** in `setup/`, `apps/control-hub/core/config_core/` and the mediaserver scripts (`wire_arr.py`, `auto_import.py`, and the new pack and Doctor code). Pack data is JSON; the standard library has no YAML parser.
- **Module boundaries** ([AGENTS.md](AGENTS.md) §1.6):
  - The Control Hub never imports from `apps/mediaserver/`. It runs mediaserver scripts through a path passed in env (the `MEDIA_BACKUP_SCRIPT` pattern) and reads their status JSON.
  - Module READMEs link outside their folder only with absolute GitHub URLs.
  - Run `python testing/test_module_contract.py`.
- **No personal identifiers** in tracked files: no LAN IPs, host names, user names, rclone remote names or drive letters. Use placeholders such as `<server-lan-ip>`.
- **Secrets** are never printed, logged or committed. Read API keys into variables ([Appendix J](#appendix-j-observing-the-live-server-safely)).
- **The live server is read-only for agents** unless the owner approves a specific change. Deployment is git-driven ([AGENTS.md](AGENTS.md) §4.1): push the branch, then update the checkout on the server.
- **Never delete app-managed torrents directly in qBittorrent.** Always go through the app queue (section 8.1). **Never run two cleaners at once.**
- **Docs ship with code** (section 12). Add new guides to the [docs index](docs/README.md) and the root README runbook table, and ADRs to the [ADR index](docs/adr/README.md).
- **Check before relying** on anything listed in [Appendix K](#appendix-k-verify-before-relying-on-it).

### Tests to run before every PR

```bash
python testing/test_docs_integrity.py
python setup/test_setup.py
python testing/test_e2e_regression.py
python testing/test_lifecycle_handoff.py
python testing/test_module_contract.py
python testing/test_version_consistency.py
python -m unittest discover -s apps/control-hub/tests -p "test_*.py" -v    # includes Playwright + axe-core
python -m unittest discover -s apps/mediaserver/tests -p "test_*.py" -v
```

### Repo touch-points by phase

**Phase 1**

- **Create:**
  - `apps/mediaserver/profiles/` ([Appendix C](#appendix-c-profile-pack-layout));
  - `apps/mediaserver/tests/test_profile_pack.py`, including the [Appendix H](#appendix-h-release-title-test-corpus) corpus;
  - `docs/adr/0004-repo-owned-release-profiles.md`;
  - `docs/MEDIA_RELEASE_PROFILES.md` and `docs/SMB_PLAYBACK_WITH_NOVA.md`;
  - `.github/workflows/trash-sync.yml` (weekly TRaSH upstream check).
- **Change:**
  - [wire_arr.py](apps/mediaserver/scripts/wire_arr.py):
    - add `profiles apply|check|migrate`;
    - replace `ensure_restriction_term()` (its endpoint is gone);
    - make `wire_prowlarr()` enforce Full Sync on existing app links;
    - fix `QBit.ensure_categories()`;
    - add the qBittorrent preferences.
  - [deployer.py](setup/installer/deployer.py): call `_wire_script("profiles", …)` after wiring.
  - [setup/static/index.html](setup/static/index.html) and [setup.js](setup/static/js/setup.js): the "Release preferences" step, next to the existing Byparr, TMDB and DNS options.
  - [setup/server.py](setup/server.py): validation.
  - [schema_migrator.py](setup/installer/schema_migrator.py): new keys on upgrades.
  - [env_manager.py](apps/control-hub/core/config_core/env_manager.py): render the new mediaserver keys and drop `RECYCLARR_LOG_FILE`. [cron_tasks.py](apps/control-hub/widgets/cron_tasks.py) already hides Recyclarr when it isn't installed.
  - [mediaserver README](apps/mediaserver/README.md): the Recyclarr section, and the "+50k Hindi" and Ozlem claims.
  - [setup/README.md](setup/README.md), the indexes and CHANGELOG.
- **Remove:**
  - the `apps/mediaserver/recyclarr/` example (keep a short "using Recyclarr instead" note);
  - `apps/mediaserver/scripts/setup_sonarr_season_preference.py` (removed in Phase 1).

### Phase 1 implementation notes

What changed from the plan while implementing Phase 1, and what was found. Section 14's defaults were used for every open question.

**Code layout.**
- Pure logic (loading, rendering, payloads, diffs) is in `apps/mediaserver/scripts/profile_pack.py`; the HTTP side is `PackRunner` in `wire_arr.py`. `profiles check` exits 0 in sync, 1 on drift, 2 on errors; `--json` prints `changes`, `notes` and `errors`.
- `wire_arr.py seerr` is a new subcommand. With the pack on, the installer runs `wire --skip-seerr`, then `profiles apply`, then `seerr --profile <default>`, so Seerr's default points at a pack profile on a fresh install. `install.sh` (standalone) does the same.
- The weekly upstream check is `scripts/trash_sync.py` (`--check`/`--write`), run by `.github/workflows/trash-sync.yml`, which opens a PR into `develop`.

**Naming and ownership.**
- Every pack format carries a prefix, including the vendored TRaSH ones, so ownership is decided by prefix alone. TRaSH formats are renamed: `Eff · HEVC` (x265 (HD)), `Compat · AV1`, `Compat · DV w/o HDR fallback`, `Junk · BR-DISK`, `Junk · 3D`, `Junk · Extras`, `Junk · Upscaled`, `Fix · Repack/Proper`, `Fix · Repack2`, `Fix · Repack3`, `TV · Season Pack`. Two prefixes were added for this: `Fix ·` and `TV ·`.
- `migrate` also deletes the Recyclarr-made `x265 (HD)` format, which `Eff · HEVC` supersedes; otherwise HEVC would be scored twice.
- Inside the pack's own profiles, a user's own format keeps its score; formats with pack prefixes get the pack's scores. Legacy formats keep their score until `migrate` deletes them, and `check` lists them as notes.

**Behaviour choices.**
- Without a second language: no `1080p Family`, no `Lang · {LANG}` formats, and a `Lang · Not Original` format (−10000) instead of `Not Original or {LANG}`. `1080p Compact`'s upgrade-until score drops to 3200 in Radarr (1080p in the compact band, or HEVC) and 3000 in Sonarr (any 1080p episode): without a language, no file at or above those scores can be upgraded any more.
- Players that can't decode HEVC (HEVC unticked in the wizard) score `Eff · HEVC` −10000. Ticking AV1 or DV sets their `Compat ·` formats to 0.
- A language an app doesn't know is matched by title tokens only (Sonarr has no Telugu, Kannada, Bengali or Marathi, and its Arabic id differs from Radarr's).
- Short language tokens (`tel`, `mal`, `kan`) count only within 1–4 separator characters of another language marker, written without look-behind so the same regex runs in .NET and Python.
- Prowlarr: rather than separate "Public – strict" and "Public – live" profiles, the default app profile gets minimum seeders 4, and a `Live seeders` app profile (minimum 2) is created for the owner to assign per indexer.
- `apply` sets the recycle bin only when none is set, and creates `<data-dir>/media/.recycle` on the host when `--data-dir` is passed. It also sets the default delay profile's "bypass if score ≥ 4000" (sections 5.5 and 6). It does not touch metadata (Kodi NFO), naming, minimum availability or the blackhole clients: those stay Phase 0 steps and Phase 4.
- qBittorrent `alt_up_limit` is written in bytes per second (1 MiB/s = 1048576), which Phase 0 confirmed (Appendix K item 14).
- `migrate` also deletes the interim Radarr release profile **"Phase 0 bans (until profile pack)"** (Phase 0 step 12), because `Junk · Banned uploaders` and `Junk · Commentary editions` replace it. Release profiles with any other name are left alone.
- `migrate` copes with what Phase 0 already did: profile 9's merged group (ID 1002) is replaced by the pack's `HD` group in the same profile, the deleted `1080p Balanced` profiles are simply not found, and the commented-out Recyclarr cron line needs nothing.
- A new key, `MEDIA_PUBLIC_TRACKERS` (headless config `media_public_trackers`), turns the tracker list off for private trackers.
- Express mode in the wizard asks for the second language too; the other release preferences use their defaults there.
- **Upgrades:** the schema migrator adds `MEDIA_PROFILES=off` to an existing `mediaserver.env`, and the installer keeps an existing install's `MEDIA_*` values when its config has no `media_*` keys. An upgraded server therefore keeps its current profiles until its owner opts in, which avoids two owners (Recyclarr and the pack) on servers other than this one.

**Revision 4, applied** ([record](#revision-4-owner-decisions-on-profiles-and-scoring-2026-11-28)). It settles both findings first raised here (kept below, struck through). What applying it changed:
- `Dual Audio First` is renamed `1080p Family`: files `profiles/{radarr,sonarr}-1080p-family.json`, slug `family` for `MEDIA_DEFAULT_PROFILE`, and the wizard, installer and `install.sh` follow. Nothing was released under the old name, so there is no alias for it.
- `1080p Compact`'s `HD` group holds only the four 1080p qualities, the same group Phase 0 set on the live server. Movies: HEVC +250. TV in both profiles: HEVC +150, season pack +150, sources +40/+30/+20.
- `1080p Family`: dual audio +3000, Hindi only +1500, `Res · 1080p` +1000, HEVC +150, oversized −500, compact band 0; minimum score 1400, upgrade until 4000, step 400.
- Upgrade-until scores sit where a file that can still be upgraded is below the line and one that can't is at or above it. Radarr Compact: 4700 with a language (1080p dual audio in the compact band, so an out-of-band dual-audio x264 file can still move into the band, +450) and 3200 without. Sonarr Compact: 4500 and 3000. Family: 4000.
- `wire_arr.py` takes "needs a second language" from the profile's `requires_language` instead of a hard-coded slug.
- New tests: the tie-breakers add at most 317 (Radarr Compact), 217 (Radarr Family) and 347 (Sonarr), all under the 400 step; Family's order, with the best English-only release at 1217 (1347 for a Sonarr season pack) under its minimum; Compact rejects 720p; codec changes never upgrade TV episodes.

**Untagged Hindi-original titles** (found while applying revision 4, decided by the owner the same day: a film whose original audio is Hindi has Hindi audio whether or not the release name says so; Hindi as well is only wanted for foreign films):
- Before: the language formats needed a Hindi token, so an untagged release of a Hindi film (corpus #20, and many international WEB-DLs) scored like English-only in Family (1040, rejected) and 1500 below a tagged copy in Compact, which would have "upgraded" to a tagged copy with the same audio.
- Now: a new format, `Lang · {LANG} original (untagged)`, matches when the parsed language is `{LANG}` and the name has no `{LANG}` token. It is scored like dual audio: +3000 in Family, +1500 in Compact. Both Radarr and Sonarr give an untagged release the title's original language (`AggregateLanguages.cs` on develop: "fallback to movie/series original language"), so it covers Hindi series too.
- Guard: without its language condition the format would match every release, so an app that does not know `{LANG}` (Sonarr has no Telugu, Kannada, Bengali or Marathi) gets neither the format nor its score (`needs_app_language` in the format file; `to_api_format` returns no payload).
- Tests: tagged and untagged releases of a Hindi film score the same in both profiles; a Hindi series pack passes Family; English films never match; an app without the language converges with no drift.

**Findings settled by revision 4** (for the record):
1. ~~**720p Hindi-only releases are rejected in both profiles.**~~ Compact now takes no 720p, and Family scores a Hindi-only dub +1500 against a minimum of 1400. The original finding: `Lang · Hindi only` (−500) plus source and band leaves a 720p dub at −240 (Compact) or −440 (Dual Audio First), under the minimum score of 0. At 1080p a Hindi-only dub is accepted (2500 in Compact, 500 in Dual Audio First). If a 720p dub should be a last resort in `Dual Audio First`, its `Lang · Hindi only` score needs to be about −50 or the minimum score lowered.
2. ~~**A bigger HEVC file can still count as an upgrade.**~~ HEVC is now +250 (Compact movies) or +150, and the tie-breakers together stay under the 400 step. The original finding: section 5.3 says an HEVC file bigger than the current one never does (+140 or less). With `Eff · HEVC` +400 and an upgrade step of 400, HEVC alone equals the step. A bigger HEVC release in the same size band as the current x264 file (both within 6 GB, or both between 6 and 10 GB) is therefore an upgrade; it is held back only when it leaves the compact band (+400 − 200). Setting the step to 401 or HEVC to +350 would fix this, but the latter also stops the x264 → HEVC episode upgrades that section 5.3 wants in Sonarr.

**Verification done.**
- Corpus test (`apps/mediaserver/tests/test_profile_pack.py`): all 39 Appendix H titles (plus variants for #24 and #25 with and without the original language parsed) give the expected formats. Regexes run for real in Python's `re`; what the apps parse (resolution, source, languages, size, release type) is recorded per title. TRaSH's three variable-width look-behinds (BR-DISK, Sonarr Extras and Upscaled) are rewritten into equivalents for Python. *Goldfinger* #1 is the top pick in both profiles (5010 in Compact and 4210 in Family since revision 4), packs outrank single episodes, and the section 5.3 space-reclaim numbers (3050 → 3500) hold.
- `apply` then `check` against in-memory fakes reports no drift, `migrate` keeps profile ID 9, and an offline replay against the sanitised live snapshot (all apps' real objects) planned and applied cleanly with no drift afterwards.
- **Live `profiles migrate --dry-run`** (2026-11-28, with the owner's OK; run before the release-profile cleanup above was added, so that deletion was not in its plan): run from a throwaway copy of `scripts/` and `profiles/` in `/tmp` on the server (removed afterwards), `--language Hindi --skip qbittorrent`, GET requests only. Exit 0, **60 planned changes**: 46 custom formats to create (24 Radarr, 22 Sonarr); `1080p Compact` updated in place in both apps (upgrade-until 10000 → 4500, increment 1 → 400, Radarr language Original → Any, one merged `HD` group including 720p, all pack scores); `Dual Audio First` created in both; the default delay profile's bypass in both; Sonarr's recycle bin; Prowlarr's `Live seeders` app profile; and 6 legacy formats deleted (`Hindi Audio` and `x265 (HD)` in both apps, `Season Complete` and `Multi Episode` in Sonarr). Already in place on the server at that time, so not planned: the size limits, Radarr's subtitle whitelist and recycle bin, Prowlarr Full Sync and minimum seeders, and removal of both `1080p Balanced` profiles (see the [Phase 0 record](#phase-0-record-applied-2026-11-28)). qBittorrent was not checked (its password is in the root-only env file). Revision 4 changes this plan: `1080p Family` instead of `Dual Audio First`, Radarr Compact upgrade-until 4700 instead of 4500, and Compact keeps the four 1080p qualities Phase 0 set. Run the dry run again before applying.
- **Live deploy (2026-11-28, done by an agent with the owner's approval):**
  1. Backups first: Radarr and Sonarr `Backup` commands (HTTP 201) and a copy of `mediaserver.env`.
  2. Recyclarr's commented-out cron line deleted from the server user's crontab.
  3. `/opt/homelab-blueprint` pulled to `develop` at the #89 merge (clean tree).
  4. Schema migrator run: 7 `MEDIA_*` keys added to `mediaserver.env` and 3 photo-backup keys to `control-hub.env` (their default paths exist on the server). Then `MEDIA_PROFILES=on` and `MEDIA_SECOND_LANGUAGE=Hindi`.
     - **Incident:** the migrator rewrote `mediaserver.env` as `0644` (world-readable) and `control-hub.env` without its `homelab` group. Modes were restored by hand within about a minute (`0600 root:root` and `0640 root:homelab`), and the backups were made `0600`. Root cause and fix: [#91](https://github.com/RAM-MAHESHWARI24/homelab-blueprint/pull/91).
  5. `profiles migrate --dry-run`: 64 planned changes (48 formats, 25 in Radarr and 23 in Sonarr, including the untagged-language one; both profiles, delay-profile bypass, Sonarr recycle bin, Prowlarr `Live seeders`, qBittorrent excluded files, 6 legacy formats and the interim release profile deleted). No quality-order change: Phase 0's 1080p group already matched. Then `profiles migrate` (exit 0, no failures) and `profiles check`: **0 drift**.
  6. Checks:
     - *Goldfinger* interactive search: the `[Hindi English]` 1080p BDRip ranks first at 5010, as the tests predict.
     - *Slow Horses* season search: season packs rank first (3330). Season 1 on disk is not re-grabbed ("within Custom Format score increment: 400"), so codec alone does not upgrade.
  7. `control-hub.service` restarted: active, `/api/health`, `/api/livez` and `/api/readyz` return 200, no errors in the journal.

**Phase 2**

- **Create:**
  - `apps/mediaserver/scripts/download_doctor.py`;
  - `apps/mediaserver/host/cron/mediaserver-download-doctor`;
  - `apps/mediaserver/tests/test_download_doctor.py` ([Appendix I](#appendix-i-download-doctor-test-fixtures) fixtures);
  - `docs/adr/0005-download-doctor.md` and `docs/DOWNLOAD_DOCTOR.md`.
- **Change:**
  - [deployer.py](setup/installer/deployer.py): `install_cron()` the Doctor (recorded in the install manifest, so teardown removes it) and create its state directory.
  - The mediaserver `.env.example` and [env_manager.py](apps/control-hub/core/config_core/env_manager.py): Doctor settings and the status-file path.
  - The mediaserver README, the indexes and CHANGELOG.

**Phase 3**

- **Create:** Control Hub widgets (for example `widgets/download_doctor.py`, `widgets/release_profiles.py`, `widgets/library_insights.py`, `widgets/media_events.py`) and their front-end modules under `static/js/widgets/`.
- **Change:**
  - [env_manager.py](apps/control-hub/core/config_core/env_manager.py) and [config.py](apps/control-hub/config.py): media keys and script/status paths.
  - [current_downloads.py](apps/control-hub/widgets/current_downloads.py): delete through the app queue, `html.unescape`, health.
  - [telemetry_sampler.py](apps/control-hub/core/telemetry_sampler.py): torrent fields, and open files from `smbstatus --json`.
  - [alerts.py](apps/control-hub/core/alerts.py): the new rules.
  - [server-suspend.sh](apps/control-hub/host/server-suspend.sh): the SMB open-file check.
  - [homelab-sudoers.example](system/systemd/homelab-sudoers.example): allow the new `smbstatus` arguments (today only `-S`).
  - `static/index.html`, `docs/openapi.yaml`, the Control Hub README and tests.

**Phase 4**

- **Change:**
  - [tv_updater.py](apps/tv-autoupdater/tv_updater.py): add Nova to `MANAGED_APPS` with a pinned signing certificate; update its README.
  - Jellyfin and Bazarr settings, through `wire_arr.py` or documented manual steps.
- **Remove:** the stale files on the server listed in [Appendix F](#appendix-f-live-baseline-2026-11-28), after the owner confirms.

---

## 1. Summary

### Why downloads get stuck today

All seven causes were confirmed on the live server.

| # | Root cause | Effect |
| :--- | :--- | :--- |
| RC1 | The `1080p Compact` profile ranks qualities **upside down**: `HDTV-1080p` is the highest and `Bluray-1080p` the lowest. Radarr and Sonarr give the `HDTV-1080p` label to any title that says "1080p" but names no source. Recyclarr re-applies this order every morning at 06:30. | Old, untagged peer-to-peer uploads beat every BluRay and WEB release before seeders are even looked at. All 17 stuck movies are `HDTV-1080p` grabs. |
| RC2 | Seeders are a late tie-breaker and are compared in powers of ten. Minimum seeders is 1. Public indexers report stale seeder counts. | A listing showing 31 seeders with zero real peers is treated as healthy. |
| RC3 | Prowlarr syncs to the apps in "Add and Remove Only" mode. | Indexer priorities set in Prowlarr never reach Radarr or Sonarr, where every indexer sits at 25. |
| RC4 | Size caps are 42–50 MB/min (about 5–6 GB for a two-hour film), and the minimum is 0. | Healthy WEB-DL and BluRay encodes are rejected as too large, while 0.7–1.2 GB "HD" files get in. |
| RC5 | Parser quirks: `ESub` is read as burned-in subtitles, and "Hin" and "Dual Audio" are not recognised as languages. The Radarr profile language is set to `Original`. | Many Hindi dual-audio releases are rejected without any visible sign. |
| RC6 | Old seasons are fetched as single-episode torrents. | Single old episodes are the deadest torrents of all. |
| RC7 | Nothing marks a stalled torrent as failed. | Items wait forever in "stalled with no connections" or "downloading metadata". |

### What the plan does

1. **Two profiles** (revision 4).
   - **`1080p Compact`** (default): the best 1080p, and 1080p only. HEVC preferred, file sizes kept in a compact band, oversized files penalised, and dual audio preferred among 1080p releases; English-only is fine.
   - **`1080p Family`**: Hindi is required and English is a bonus, for family members who only understand Hindi. 1080p dual audio, then 720p dual audio, then 1080p and 720p Hindi-only; English-only releases are rejected.
2. **Both profiles fix the ranking.** One merged HD quality group with explicit scores, so language and efficiency can matter more than an untagged "1080p" (RC1, RC4). Small tie-breakers such as HEVC never trigger an upgrade on their own.
3. **A repo-owned profile pack replaces Recyclarr.**
   - The installer applies it, and the Control Hub re-applies it and shows any drift.
   - TRaSH formats are vendored with a weekly upstream check.
   - The daily sync that silently reverts fixes goes away (RC1).
4. **Language formats for any second language** (Hindi here), plus `ESub` whitelisted and the Radarr profile language set to `Any` (RC5).
5. **Prowlarr:** switch to Full Sync, set minimum seeders to 4 on broad public indexers, and set priorities from measured success (RC2, RC3).
6. **Size limits that match TV playback**, and **automatic compact replacement**. Oversized titles keep being searched until a smaller version imports, and the old files are deleted only after the new ones are in place. That is about 140 GB here, mostly *Succession*.
7. **Playback rules for SMB and Nova:**
   - HEVC preferred.
   - AV1 and Dolby Vision without an HDR fallback blocked by default.
   - Subtitles as SRT files next to the video.
   - Preferred audio language set in Nova on each TV.
   - NFO metadata and artwork written by Radarr and Sonarr, so Nova shows the right title and poster.
8. **qBittorrent:**
   - A public tracker list on new torrents.
   - "Seed while it helps": ratio 1.0, 24 hours, or 60 idle minutes, whichever comes first.
   - Evening upload limits so seeding never makes SMB streams stutter on the shared disk.
9. **A native Download Doctor** (scheduled job, no new service):
   - Strikes only count while the server is awake.
   - It replaces dead downloads through Radarr/Sonarr (remove, blocklist, automatic search), so the stack itself picks the next-best release.
   - It has caps, a circuit breaker and alerts (RC7).
10. **Sonarr prefers season packs** (RC6), and a weekly **cutoff-unmet sweep** drives dual-audio and compact upgrades.
11. **Control Hub:**
    - Switch on the media views (keys are missing).
    - A unified queue with health, and the Download Doctor card.
    - Profile drift checks with a "re-apply" button, and a per-title `1080p Family` switch.
    - **"Now playing on the TVs"** from SMB, plus space-reclaim and indexer insights.

**Expected result:**
- Stuck downloads drop from 20 to none lasting more than 12 awake hours.
- First-attempt success for movies rises from 31% to at least 80%.
- Dual-audio coverage of English-language films climbs from 18%.
- About 140 GB of disk comes back over a few weeks without anyone deleting anything by hand.

---

## 2. How this was investigated

- **APIs, read only.** Read with `GET` requests from Radarr, Sonarr, Prowlarr, qBittorrent, Bazarr, Seerr and the Control Hub: profiles, custom formats, size limits, indexers, queues, history, library, torrent states, trackers and preferences.
- **Config files.** The live Recyclarr config, its cron schedule and sync log, the Jellyfin encoding settings, the Bazarr settings and the Control Hub env file. Secret values were never printed.
- **Host facts.** Running containers and their memory use, compose project, CPU, RAM and disk.
- **Two interactive searches.** One for a stuck movie and one for a stuck season. These rank the releases Radarr and Sonarr can see and why each would be rejected. Nothing was grabbed.
- **Research:**
  - Radarr and Sonarr **source code**, for exact behaviour: release ranking, queue removal, automatic re-search after a failed download, language parsing, the hardcoded-subtitle check.
  - **TRaSH Guides** (language formats, quality sizes, qBittorrent).
  - Docs for **Recyclarr, Configarr, Profilarr/Dictionarry, Cleanuparr, Decluttarr, Seerr and Nova Video Player**.

Sources are listed in [section 16](#16-references).

---

## 3. Live snapshot

### 3.1 Stack, host and playback path

| Component | Version / state | RAM (live) | Notes |
| :--- | :--- | ---: | :--- |
| Radarr | 7.0.3 | 198 MB | Only warning is "Allowed Hosts not configured" |
| Sonarr | 4.0.20 | 214 MB | Same warning |
| Prowlarr | 3.0.2 | 179 MB | 5 public indexers: 1337x (through Byparr), EZTV, LimeTorrents, The Pirate Bay, YTS |
| qBittorrent | 5.3.0 (libtorrent 2.1.2) | **22 MB** | Connectable, 363 DHT nodes, no VPN. DHT, PeX and LSD on |
| Byparr | 3.1.1 | **353 MB** | Only needed for Cloudflare-protected indexers (1337x here) |
| Jellyfin | lsio 12.4 | 351 MB | **Not used for playback**; Seerr needs it as its media server |
| Bazarr | 1.6.2 | 209 MB | OpenSubtitles.com, YIFY Subtitles, Subdl. 18 episodes and 7 movies missing subtitles |
| Seerr | 3.5.2 | 151 MB | Requests go to `1080p Compact` for both movies and TV |
| Recyclarr | Native binary, user crontab, daily 06:30 | — | Config is identical to the repo's example file, `apps/mediaserver/recyclarr/mediaserver-profiles.example.yml` (removed in Phase 1) |
| Host | Intel i3-4005U (2 cores / 4 threads), 7.2 GiB RAM | 3.8 GiB free | The photo app and its database use about 1.2 GB more |
| Media disk | 916 GB, **86% used**, 132 GB free | — | Movies 164 GB, TV 332 GB, in-flight torrents 12 GB |
| **Playback** | **Samba share → Nova Video Player on Android TVs** | — | The TV decodes; the server only serves files. Nova writes resume files beside the media |

### 3.2 The stuck queue right now

All 20 torrents in qBittorrent are incomplete and downloading at 0 B/s.

| Group | Count | State in qBittorrent | Age | What the swarm looks like |
| :--- | ---: | :--- | ---: | :--- |
| Bond films (one 2012-era uploader, plus two others) | 11 | `metaDL`: can't even fetch the file list | 39 h | 0 seeds; 1–3 peers that also lack the data |
| Bond films | 4 | `stalledDL` at 94–99.7% | 39 h | Availability 0.94–0.996: the missing pieces exist nowhere in the swarm |
| Bond film | 1 | `stalledDL` at 0% | 39 h | 0 seeds, 1 peer |
| Bond film ("Live and Let Die") | 1 | `forcedDL` at 99.8% | 39 h | Availability 0.998: 4 MB short, and those pieces exist nowhere in the swarm. 3 peers, no data for 8.4 h |
| Slow Horses S01E03, E05, E06 (`[TGx]` re-uploads) | 3 | `forcedDL` / `metaDL` | 145 h | 0 seeds in the whole swarm for 6 days |

How it happened:

- **The Bond films.** On 2026-11-26, Radarr grabbed 26 Bond films within five minutes.
  - The Pirate Bay: all 5 of its grabs imported.
  - 1337x: 4 of its 21 grabs imported; the other **17 are dead** and still in the queue.
- **Slow Horses.** 1337x currently lists `Slow.Horses.S01E03…MeGusta[TGx]` with **31 seeders**. qBittorrent has found **0 seeds and 0 peers** for it in 6 days.

### 3.3 Track record (baseline)

This counts unique downloads in the available history (movies since 2026-08-26, TV since 2026-10-03). A grab counts as a success if it reached import.

| App | Indexer | Grabs | Imported | Still stuck | Gone without import | Import rate |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| Radarr | 1337x | 50 | 12 | 17 | 21 | **24%** |
| Radarr | The Pirate Bay | 49 | 17 | 0 | 32 | **35%** |
| Radarr | YTS | 2 | 2 | 0 | 0 | 100% |
| Sonarr | LimeTorrents | 20 | 20 | 0 | 0 | 100% |
| Sonarr | 1337x | 5 | 2 | 3 | 0 | 40% |
| Sonarr | The Pirate Bay | 1 | 1 | 0 | 0 | 100% |

**Movies: 31 of 101 grabs (31%) ever imported.** "Gone without import" means the torrent was deleted by hand or vanished, which is the manual work this plan removes.

### 3.4 Library

- **Movies.** 76 movies, 52 with files: 163 GB, averaging 3.1 GB. Original languages: 68 English, 8 Hindi.
- **Series.** 27 series, 347 GB. Original languages: 22 English, 3 Hindi, 1 German, 1 Korean.
- **Dual audio.** 8 of 44 English-language films on disk have Hindi + English audio tracks (**18%**).
- **Low-bitrate files** got in because the minimum size is 0:
  - *The Godfather Part II*: 1.19 GB for 202 minutes (720p).
  - *A Few Good Men*: 0.73 GB for 138 minutes (720p).
- **Wrong language.** *Quantum of Solace* came from the "Ozlem" uploader, whom the README says is blocked, and has **German-only** audio.
- **Third-language picks.** Several new films are Italian + English releases. The x265 bonus outranked plain English releases.
- **A series that can never download.** *Bhay: The Gaurav Tiwari Mystery* (0 of 8 episodes) sits on a profile whose minimum score (200,000) no release can reach.
- **Where the space went.** Estimates assume compact HEVC releases exist at about 35 MB/min for films and 18 MB/min for TV.

  | Titles | Now | Compact estimate | Could be reclaimed |
  | :--- | ---: | ---: | ---: |
  | *Succession* (39 episodes: 23 x264, 16 already x265; 35–88 MB/min, median 65) | 137 GB | about 45 GB | **about 90 GB** |
  | *Mr. Robot* (x265, 32 MB/min), *Andor* (mostly H.264), *12 Monkeys* (HEVC, 35 MB/min) | 68 GB | about 38 GB | about 30 GB |
  | Six films at 57–87 MB/min: *Schindler's List*, *Jaws*, *Project Hail Mary*, *Obsession*, *The Usual Suspects*, *Supergirl* | 55 GB | about 28 GB | about 27 GB |
  | **Total** | | | **about 140 GB** |

---

## 4. Root causes

### 4.1 How Radarr and Sonarr choose between releases

From `DownloadDecisionComparer` in each app's source code: the first comparison that differs decides.

| Step | Radarr | Sonarr |
| ---: | :--- | :--- |
| 1 | Quality (position in the profile; Proper/Repack only if "prefer" is on) | Quality |
| 2 | Custom format score | Custom format score |
| 3 | Protocol preferred by the delay profile | Protocol |
| 4 | Indexer priority (**lower number wins**) | Episode count (full-season packs first) |
| 5 | Indexer flags (only if "Prefer Indexer Flags" is on) | Lowest episode number |
| 6 | **Seeders, then peers** (torrents) | Indexer priority |
| 7 | Age (usenet) | **Seeders, then peers** |
| 8 | Size: closest to "preferred", rounded to 200 MB | Age (usenet), then size |

Seeders are compared as `round(log10(seeders))`, so they fall into buckets:

| Seeders reported | Bucket | Consequence |
| :--- | ---: | :--- |
| 1–3 | 0 | Same as 0 seeders |
| 4–31 | 1 | 4 and 31 seeders are **equal** |
| 32–316 | 2 | |
| 317+ | 3 | |

**Takeaway:** seeders can't rescue a bad choice. The only levers above them are quality order, custom-format score, protocol and indexer priority, plus the Minimum Seeders filter that removes candidates outright.

### 4.2 RC1: quality ranking is inverted (critical)

In the live `1080p Compact` profile, both Radarr and Sonarr (75 of 76 movies, 25 of 27 series, and every Seerr request), the API lists the qualities lowest to highest like this:

```text
Bluray-1080p  <  WEBRip-1080p  <  WEBDL-1080p  <  HDTV-1080p   (highest)
```

**Where it comes from.** `apps/mediaserver/recyclarr/mediaserver-profiles.example.yml` (removed in Phase 1) lists `HDTV-1080p` first in each `qualities:` list. Recyclarr writes qualities in the order listed, so the first entry becomes the top of the profile. The live config is byte-for-byte this example. Its log says *"All quality profiles are up to date"* every morning, so **any fix made in the UI is reverted at 06:30**.

**Why it hurts.** Radarr labels any title that says "1080p" without a source as `HDTV-1080p`, for example `Goldfinger (1964)-JAMES BOND-Sean Connery-1080p-H264-AC 3 … nickarad`. Those old uploads therefore beat every BluRay and WEB-DL release at step 1, before score or seeders count.

**Evidence from the interactive search for *Goldfinger*** (76 results; excerpt in [Appendix D](#appendix-d-evidence-excerpts)):
- Results came back ranked `HDTV-1080p` first, then `WEBDL`, `WEBRip`, and `Bluray` last.
- The best match for what you want ranked only **#6**: `Goldfinger (1964) … 1080p BDRip HEVC [Hindi English] DDP 5.1`, Bluray-1080p, **8 seeders**, score 50,250.
- The dead `HDTV-1080p` torrent in the queue blocks it.

### 4.3 RC2: seeder counts are weak and often stale

- Minimum Seeders is **1** in Prowlarr's only app profile, so on every indexer in both apps.
- Public sites show cached counts. Old `[TGx]` re-uploads and 2012-era uploads on 1337x list 6–31 seeders but have none. The 1337x import rate (24%) matches this.
- With the log10 buckets, a fake "31 seeders" ties with a real 31.

**Consequence:** a seeder threshold helps but can't be the whole answer. Automatic replacement of dead torrents (section 8) is required.

### 4.4 RC3: indexer priorities never reach the apps

Both Prowlarr app links use sync level **"Add and Remove Only"**. Prowlarr has The Pirate Bay at priority 45, set by [wire_arr.py](apps/mediaserver/scripts/wire_arr.py) `deprioritize_unmoderated_indexers()`, but Radarr and Sonarr still show 25. Every indexer ties at step 4. Minimum seeders and seed goals set in Prowlarr also stop propagating.

### 4.5 RC4: size limits too tight at the top, missing at the bottom

The current limits are in MB per minute (×120 for a two-hour film):

| Quality | Min | Max | Max for a 2-hour film |
| :--- | ---: | ---: | ---: |
| WEBDL-1080p | 0 | 42 | 5.0 GB |
| Bluray-1080p | 0 | 50 | 6.0 GB |

In the *Goldfinger* search:
- A Netflix WEB-DL at 5.17 GB with **23 seeders** was rejected as "larger than maximum allowed 4.5 GB".
- About a dozen BluRay encodes between 5.5 and 8.6 GB were also rejected.

A minimum of 0 lets in files around 5 MB/min (well under 1 Mbit/s).

### 4.6 RC5: Hindi releases filtered out by parser quirks

Verified against Radarr's source code:

- **`ESub` counts as burned-in subtitles.** The hardcoded-subtitle regex `\w+(?<!SOFT|MULTI|HORRIBLE)SUBS?` matches `Esub`, `ESubs` and `MSubs`. In Indian release names these mean soft English or multi-language subtitles. With "Allow Hardcoded Subs" off and the whitelist empty, they are rejected, for example `James Bond Goldfinger (1964) 720p BluRay Hindi DD 2.0 Esub` → *"Hardcode subs found: Esub"*.
- **Hindi is recognised only by the word "hindi".** "Hin" is missed, English is matched by `\beng\b` or "english", and **"Dual Audio" maps to no language**. Titles without a language fall back to the film's original language.
- **The profile language is `Original`.** So for an English film, `…[Dual Audio] [Hindi-…` parses as Hindi only and is rejected: *"Original Language (English) is wanted, but found Hindi"*. TRaSH notes the profile language and language custom formats don't mix; use `Any` with custom formats.
- **The current `Hindi Audio` format is too broad and too blunt.** Its regex `\b(hindi|hin|dual[- .]?(audio)?)\b` gives +50,000 to *any* "dual" (Italian/English, Japanese/English). It also scores Hindi-only dubs the same as Hindi + English.

### 4.7 RC6: single old episodes instead of season packs

Sonarr grabbed `Slow Horses S01E03/E05/E06` individually, from 2022 uploads. It does prefer full-season packs, but only at step 4, *after* score. The season-pack formats in use are title regexes (`season.complete`, `S01E01…S01E02`) that most packs don't contain.

### 4.8 RC7: nothing handles a stalled torrent

- **Radarr and Sonarr never fail a stalled torrent on their own.** They show *"The download is stalled with no connections"* or *"qBittorrent is downloading metadata"* indefinitely.
- **The Control Hub's delete button bypasses them.** It removes the torrent directly in qBittorrent ([current_downloads.py](apps/control-hub/widgets/current_downloads.py) `torrent_action()`). That neither blocklists the release nor triggers a search, so the next search can grab the **same** dead torrent again.

---

## 5. Target configuration

### 5.1 Principles

1. **Merge quality tiers and score preferences.** Put every acceptable HD quality in one group so it ties at step 1, then express preferences with custom-format scores. This is TRaSH's "merge quality" idea taken to its end, and it is the only way to make language or efficiency matter more than an untagged "1080p".
2. **Hard filters versus soft preferences.** Junk and incompatible formats get −10,000 (rejected, because the minimum score is 0). Everything else is a positive or negative preference.
3. **Seeder health comes from filters and indexer priority**, because seeders are compared late and in buckets.
4. **Size limits are global** in Radarr and Sonarr (one table per app, shared by every profile). Per-profile size behaviour therefore comes from custom formats.
5. **One owner of profile state: the repo's profile pack.** The installer applies it; the Control Hub re-applies it and shows drift. No daily sync silently overwrites fixes.
6. **Works for anyone.** The second language, default profile, codec support, seeding and auto-replace are wizard choices. Hindi is this household's setting, not a hard-coded assumption.
7. **No new always-on services.** RAM, CPU and disk are the constraints, so new logic runs as short scheduled jobs.

### 5.2 Two profiles

Both profiles exist in Radarr and Sonarr. `1080p Family` is only created when a second language is chosen. Revision 4 ([record](#revision-4-owner-decisions-on-profiles-and-scoring-2026-11-28)) replaced the earlier `Dual Audio First` profile with `1080p Family` and made Compact 1080p-only.

| Setting | `1080p Compact` (default) | `1080p Family` |
| :--- | :--- | :--- |
| Purpose | The best 1080p. Dual audio preferred among 1080p releases; English-only is fine | Hindi is required and English is a bonus: the owner understands both, the parents only Hindi |
| Qualities | One group `HD`: Bluray-1080p, WEBDL-1080p, WEBRip-1080p, HDTV-1080p | The same plus Bluray-720p, WEBDL-720p, WEBRip-720p |
| Order | Dual audio first, then the most efficient 1080p release | 1080p Hindi + English, then 720p Hindi + English, then 1080p Hindi only, then 720p Hindi only. English-only: rejected |
| No suitable release | A title with no healthy 1080p release goes to "needs attention" ([section 8.5](#85-escalation-sweeps-and-blocklist-hygiene)); the owner can switch it to `1080p Family` | The title stays missing and the weekly sweep keeps searching; switch it to `1080p Compact` to get English meanwhile |
| Upgrade until quality | `HD` | `HD` |
| Upgrade until score | 4700 in Radarr (1080p dual audio in the compact band), 4500 in Sonarr (1080p dual audio) | 4000 (1080p dual audio) |
| Minimum score | 0 | **1400**: a 720p Hindi-only release (about 1,500) passes; the best English-only release (1,217 for a film, 1,347 for a season pack) fails |
| Minimum score increment to upgrade | 400 | 400 |
| Radarr profile language | Any | Any |

**Which titles use which profile:**

| Where | How |
| :--- | :--- |
| Default for everything | `1080p Compact`: Seerr's default and the installer default. Hindi-language films are fine here: their releases count as Hindi even without a language tag |
| Per request | In Seerr, users with the "Advanced Requests" permission pick `1080p Family` when requesting |
| Per title, later | Control Hub `1080p Family` switch (section 9.3). It moves the title to `1080p Family` and searches. Radarr's mass editor does the same in bulk |
| Defaults for others | A household where most people need the second language can make `1080p Family` the default in the Setup Wizard ([section 5.10](#510-any-second-language-and-a-setup-wizard-step)) |

Housekeeping:
- **Delete `1080p Balanced` and `1080p Balanced (Hindi)`** after moving their three titles. Their minimum score is unreachable.
- Stop managing `720p Compact` and `4K Compact`; nothing uses them.

### 5.3 Custom formats and scores

Specifications are in [Appendix B](#appendix-b-custom-format-specifications). Language formats are generated from the chosen language: `Hindi` here, `{Lang}` in the pack.

| Custom format | `1080p Compact` | `1080p Family` | What it matches |
| :--- | ---: | ---: | :--- |
| Res · 1080p | **+3000** | +1000 | Resolution 1080 (every release Compact accepts has it) |
| Lang · Hindi + Original (named) | +1500 | **+3000** | A Hindi token, and the parsed languages include the original |
| Lang · Hindi + Dual/Multi tag | +1500 | **+3000** | A Hindi token plus `Dual Audio`, `Dual` or `Multi`, when the original isn't named |
| Lang · Hindi original (untagged) | +1500 | **+3000** | A Hindi-original title released without a language in its name (the apps assume the original language): its audio is Hindi |
| Lang · Hindi only (original missing) | −500 | **+1500** | A Hindi dub without the original track: a last resort in Compact, accepted in Family |
| Lang · Not Original or Hindi | −10000 | −10000 | Third-language-only releases, such as German-only or Italian-only |
| Eff · HEVC (TRaSH "x265 (HD)") | **+250** (TV +150) | +150 | Efficient codec for 720p and 1080p; a tie-breaker |
| Size · Compact band (movies, ≤ 6 GB) | +200 | 0 | Keeps the last mile of the size preference in Compact |
| Size · Oversized (movies, > 10 GB) | **−2000** | −500 | Compact never picks a bulky file just for dual audio |
| Src · Bluray / WEB-DL / WEBRip | +60 / +50 / +40 (TV +40 / +30 / +20) | same | Gentle source preference inside the merged group |
| Season Pack (TRaSH, Sonarr) | +150 | +150 | Complete-season releases |
| Repack/Proper, Repack2, Repack3 (TRaSH) | +5 / +6 / +7 | +5 / +6 / +7 | Fixed releases |
| Compat · AV1 (TRaSH "AV1") | −10000 | −10000 | Many TV chips can't decode AV1 in hardware. Wizard switch to allow it |
| Compat · DV without HDR10 fallback (TRaSH) | −10000 | −10000 | Wrong colours on players or TVs without Dolby Vision |
| Junk · Line/cam audio (language-adjacent) | −10000 | −10000 | Hindi `LiNE`, cleaned or camera audio, AI or fan dubs |
| Junk · Cam / PreDVD / S-Print | −10000 | −10000 | Mislabelled theatre recordings that would otherwise parse as `HDTV-1080p` |
| Junk · Banned uploaders | −10000 | −10000 | `Ozlem` (mangled names, wrong audio); replaces the broken restriction |
| Junk · Commentary editions | −10000 | −10000 | `RiffTrax` joke-commentary releases (*Casino Royale (2006) 1080p Rifftrax* was imported on 2026-11-26) |
| BR-DISK, 3D, Extras, Upscaled (TRaSH) | −10000 | −10000 | Formats nobody wants here |

**Tie-breakers never upgrade on their own** (revision 4). Only language, resolution, leaving the oversized range or moving into the compact band can reach the 400 upgrade step. HEVC, source, season pack and repack together add at most 317 (Compact movies), 217 (Family movies) or 347 (TV), and the tests enforce it.

**Remove** the old `Hindi Audio` (+50,000) format and Sonarr's regex-based `Season Complete` and `Multi Episode` formats.

**Worked example: *Goldfinger* (1964) in each profile.**

| Release | Seeders | `1080p Compact` score | `1080p Family` score |
| :--- | ---: | ---: | ---: |
| `… 1080p BDRip HEVC [Hindi English] DDP 5.1`, 5.7 GB | 8 | 3000 + 1500 + 250 + 200 + 60 = **5010 (#1)** | 1000 + 3000 + 150 + 60 = **4210 (#1)** |
| `… 1080p NF WEB-DL DDP5 1 Atmos H 264`, 5.2 GB | 23 | 3000 + 200 + 50 = 3250 | 1000 + 50 = 1050: rejected (under 1400) |
| `… 720p BluRay x264 Dual Audio [English + Hindi]`, 1.0 GB | 0 | Not wanted (720p) | Filtered out by minimum seeders; would score 3000 + 60 = 3060 |
| `… 1080p H264 AC3 … nickarad` (untagged), dead | — | 3000 + 200 = 3200 | 1000: rejected |
| `007 James Bond Goldfinger … -Ozlem` | 104 | Rejected | Rejected |

Two more patterns:
- **When no 1080p dual-audio release exists:** Compact takes the efficient 1080p English release. Family takes a seeded 720p dual-audio release, then a 1080p or 720p Hindi-only one, and otherwise waits.
- **Both profiles** upgrade automatically when a 1080p dual-audio release appears.

**Space reclaim by design (Compact).** Scores are also evaluated for files already on disk:
- A 9.7 GB x264 film scores 3050.
- A 4.3 GB HEVC release of it scores 3500. HEVC moving into the band is +450, over the 400 increment, so it counts as an upgrade, and the new file is always the smaller one.
- An 11 GB file (−2000) is upgraded as soon as any sensible release exists.
- An HEVC file that is *bigger* than the current one never counts as an upgrade: +250 at most in the same band, +50 when it leaves the band.
- TV episodes are never upgraded for the codec: x264 to HEVC is +150, or +300 as a season pack.

These are ordinary upgrades: the app searches, grabs and imports, and only then moves the old file to the recycle bin.

TV is left to the compact replacement job entirely. Sonarr's size condition can't measure a season pack per episode, and codec alone no longer counts, so oversized episodes, x264 or HEVC (all 39 of *Succession*'s), are replaced there ([section 8.6](#86-compact-replacement-keep-hunting-for-smaller-versions)).

To keep a particular big file, tag it `keep` or move it to a profile you control.

### 5.4 Size limits (quality definitions, global)

Units are MB per minute. One MB/min is about 0.13 Mbit/s.

**Movies (Radarr):**

| Quality | Min | Preferred | Max | Two-hour film |
| :--- | ---: | ---: | ---: | :--- |
| Bluray-1080p | 12 | 40 | 75 | 1.4–9.0 GB, aiming near 4.8 GB |
| WEBDL-1080p | 12 | 35 | 75 | 1.4–9.0 GB |
| WEBRip-1080p | 12 | 35 | 70 | 1.4–8.4 GB |
| HDTV-1080p (untagged) | 12 | 30 | 65 | 1.4–7.8 GB |
| Bluray-720p | 6 | 20 | 40 | 0.7–4.8 GB |
| WEBDL / WEBRip-720p | 6 | 18 | 35 | 0.7–4.2 GB |

**TV (Sonarr):**

| Quality | Min | Preferred | Max | 50-minute episode |
| :--- | ---: | ---: | ---: | :--- |
| Bluray-1080p | 6 | 22 | 45 | 0.3–2.25 GB |
| WEBDL-1080p | 5 | 18 | 40 | 0.25–2.0 GB |
| WEBRip-1080p / HDTV-1080p | 4–5 | 15 | 35 | 0.2–1.75 GB |
| 720p (all) | 3 | 10 | 22 | 0.15–1.1 GB |

Why these numbers:
- The maximum still fits **two audio tracks** (0.3–0.9 GB extra per film) and blocks remux-sized files.
- The minimum stops sub-1.5 Mbit/s "1080p".
- "Preferred" nudges the last tie-break towards compact files.
- Compact's extra pressure on size comes from the HEVC, band and oversized formats. These limits are shared with `1080p Family`, the only profile that uses the 720p rows.

### 5.5 Radarr and Sonarr settings

| Setting | Now | Target | Why |
| :--- | :--- | :--- | :--- |
| Indexers → Whitelisted Hardcoded Subs (Radarr) | empty | `ESub,ESubs,MSub,MSubs,EngSub,EngSubs` | RC5. "Allow Hardcoded Subs" stays off, so real burned-in releases (`HC`, `KORSUB`) stay blocked |
| Profile language (Radarr) | Original | Any | RC5; custom formats handle language |
| Download clients → Redownload Failed (both options) | on | **keep on** | Required for automatic replacement (section 8) |
| Download clients → Remove Completed | on | **keep on** | Removes the torrent once its seeding goal is met; the media file stays |
| Delay profile | 6 h torrent delay, no bypass | Keep 6 h; **bypass if score ≥ 4000** | New releases gather seeders; a perfect release grabs at once |
| Media management → Recycle bin | none | `/data/media/.recycle`, **7 days** (disk is tight) | Upgrades and deletions become undoable. Same filesystem, so a move is instant ([ADR-0001](docs/adr/0001-single-mount-atomic-hardlinks.md)) |
| Media management → Import extra files | srt, ass, ssa, vtt | keep | Subtitles travel with the video for Nova |
| Movie minimum availability | 18 titles on `tba` | `Released` | No early searches that invite theatre recordings |
| Download clients → "Usenet Blackhole" | enabled, into `/data/media/blackhole` | remove | No usenet indexers; folder sits inside the media tree |
| Connect → Webhook | none | Control Hub endpoint (section 9.6) | Real-time grabbed, imported, failed and health events |
| Metadata → Kodi (XBMC) / Emby | Sonarr on; **Radarr off** | Radarr on (movie NFO and images); keep Sonarr on | Nova reads NFO files, so titles, posters and IDs come from the apps rather than from file-name guessing. Especially useful for Hindi titles |
| Naming | Long names with score and format tokens | Keep `Title (Year)` folders; drop the `[Custom Formats]` token; optionally add an audio-languages token | With NFO files, names matter less to Nova; shorter names are still easier to browse over SMB |
| Allowed Hosts | not set | LAN name/IP, container names, localhost | Clears the warning. Include `radarr`, `sonarr` and `prowlarr` or internal calls break |

### 5.6 Prowlarr

| Setting | Now | Target |
| :--- | :--- | :--- |
| Apps → Radarr and Sonarr sync level | Add and Remove Only | **Full Sync** (Prowlarr becomes the single source of truth) |
| App profile minimum seeders | 1 | **4** on broad public indexers ("Public – strict" profile); 2 on indexers with live, accurate counts ("Public – live" profile) |
| Indexer priority (lower wins, compared before seeders) | 25 everywhere in the apps | Start: EZTV 10 and LimeTorrents 15 for TV, YTS 20, 1337x 25, The Pirate Bay 40. Then adjust monthly from the [indexer scoreboard](#94-library-insights-and-indexer-scoreboard) |
| Seed goals per indexer | none | Leave empty; qBittorrent's "seed while it helps" policy covers public trackers (section 5.7) |

Why 4 seeders: the log10 buckets make 1–3 identical to zero, so 4 is the natural cut. Rare old Hindi titles may have fewer; the Download Doctor's "needs attention" list ([section 8.5](#85-escalation-sweeps-and-blocklist-hygiene)) catches those.

### 5.7 qBittorrent

**Seeding: what it gives you.** On public trackers there is no ratio requirement, so seeding after a download finishes has no direct reward. What it does give:
- **Faster downloads now.** Peers trade with peers that upload to them, and that happens *while* downloading regardless of seeding limits. So don't cap upload during downloads.
- **Healthier swarms for older titles.** Dead swarms are exactly the problem here; leechers who quit at 100% cause them.
- **Ready for a private tracker.** If you ever join one (they are the best source of well-seeded Indian content), seeding becomes mandatory and the policy is already in place.

**What it costs:**

| Resource | Cost |
| :--- | :--- |
| Disk | Nothing while the film is in the library, because of hardlinks. Up to 24 h of extra space if the film is upgraded mid-seed |
| RAM and CPU | Small (qBittorrent uses 22 MB today) |
| Disk I/O | Seeding reads compete with SMB playback on the same hard disk. Hence the evening limit below |
| Exposure | Uploading on public trackers without a VPN is more visible (decision 9) |

| Setting | Now | Target | Why |
| :--- | :--- | :--- | :--- |
| Seeding limits | ratio 0.1 or 1 minute, then stop | **Ratio 1.0, or 24 h, or 60 idle minutes**, whichever first, then stop | Seeds while someone wants the data; stops when nobody does |
| Evening upload limit (scheduler) | off | 18:00–24:00 daily: upload 1 MiB/s, download unlimited | Protects SMB streams from disk contention during family viewing |
| Upload limit otherwise | none | none | Bandwidth is not a constraint |
| Queueing | on, limits 99999 | Downloads 8, torrents 20, **active uploads 5**, **don't count slow torrents** (4 KiB/s, 300 s) | Dead torrents can't block new ones; seeding stays bounded |
| Automatically append trackers from URL (5.x) | off | on, ngosang `trackers_best.txt` | Peers found through working trackers when a torrent's bundled ones are dead. **Never with private trackers**, which TRaSH warns against. Turn this off if a private tracker is ever added |
| Re-announce when the address changes | off | on | Helps after wake-up if the public IP changed |
| Excluded file names | 8 executable patterns | Add `*.msi`, `*.ps1`, `*.js`, `*.jar`, `*.apk`, `*.zipx` | Malware-bait torrents end up empty and get replaced |
| Web API key (5.2+) | not used | Create one for the Control Hub and Download Doctor | No password logins and no lockouts from failed logins |
| Categories | `movies`/`radarr` and `tv`/`tv-sonarr` both exist | Keep `radarr` and `tv-sonarr`; drop the duplicates in [wire_arr.py](apps/mediaserver/scripts/wire_arr.py) `ensure_categories()` | Less confusion |

Connectivity is already good (connectable, healthy DHT). No port or UPnP change is needed.

### 5.8 Choosing indexers for Hindi content

This project ships no tracker list, so this section sets criteria rather than names:

1. **Live seeder data.** Prefer indexers whose counts match reality. Measure it with the dead-on-arrival rate in the Download Doctor.
2. **Indian release coverage.** Hindi or dual-audio categories, or language tags in titles.
3. **Real `.torrent` files** (no metadata stage), or magnets that resolve quickly.
4. **Private trackers.** Ratio rules apply: turn off the tracker append, and set the Download Doctor's private handling to "leave in client".
5. **Cloudflare cost.** Byparr is the largest optional RAM user in the media stack (about 350 MB). Keep it only while a Cloudflare-protected indexer earns its place; the indexer picker should say which indexers need it.

Process: add a candidate at priority 30 with the strict profile, watch the scoreboard for two weeks, then promote or demote it.

### 5.9 Replacing Recyclarr with a repo-owned profile pack

**Why replace it.** Recyclarr itself works; the problems are fit and ownership:

| Problem | Detail |
| :--- | :--- |
| It can't hold the language formats | Recyclarr syncs TRaSH formats by ID but cannot define custom formats in YAML. The Hindi formats would need a second tool, and two owners of one profile already caused trouble (`reset_unmatched_scores`, daily re-application) |
| It isn't "few clicks" | Users install a binary, copy YAML and paste API keys by hand (current module README). The installer doesn't manage it; here it runs from a personal crontab |
| It reverts fixes silently | A daily re-application of a wrong file looks like the apps misbehaving |

**Options compared:**

| Option | Strengths | Weaknesses for this repo |
| :--- | :--- | :--- |
| Recyclarr (today) | Follows TRaSH automatically; mature | No custom formats; manual install; silent daily overwrite |
| [Configarr](https://configarr.de/docs/configuration/config-file/) | Recyclarr-compatible plus local custom formats in YAML | Another runtime (Node container) and YAML-with-keys to manage; still a separate owner |
| Profilarr with the Dictionarry database | Curated profiles and group tiers; web UI | Another always-on container and database. Its profiles penalise x265 at HD (TRaSH reasoning) and have no Indian-language handling. Active maintenance of the database is unclear |
| **Repo-owned profile pack (recommended)** | Applied by the installer with zero extra steps; one owner; drift shown in the Control Hub; standard library only; testable in CI | We vendor TRaSH formats, so upstream changes arrive by PR rather than overnight (mitigated below) |

**Design:**

| Piece | Location | Notes |
| :--- | :--- | :--- |
| Data | `apps/mediaserver/profiles/` | JSON only (parsed with the standard library). Contains: custom formats; profiles per app; size tables; language token table; vendored TRaSH formats under `trash/` with source paths and the upstream commit (TRaSH Guides is MIT-licensed; keep attribution) |
| Apply | `wire_arr.py profiles apply` | Idempotent. Upserts only objects with the pack's prefixes (`Lang ·`, `Res ·`, `Src ·`, `Eff ·`, `Size ·`, `Compat ·`, `Junk ·`, vendored TRaSH names) and the profiles it owns. Never touches user-made formats or profiles. Also sets the related app settings: Radarr language `Any`, hardcoded-subtitle whitelist, Prowlarr sync and minimum seeders, recycle bin, qBittorrent seeding, queue, trackers and exclusions |
| Check | `wire_arr.py profiles check --json` | Diff of live versus pack. The Control Hub's drift card runs it through a script path passed in env, the same pattern as the media backup button ([AGENTS.md](AGENTS.md) §1.6) |
| Migrate | `wire_arr.py profiles migrate` | One-off, explicit. Removes the legacy `Hindi Audio`, `Season Complete` and `Multi Episode` formats; moves titles off `1080p Balanced`/`(Hindi)`, then deletes them; reorders `1080p Compact`. Prints a plan first (`--dry-run`) |
| Upstream sync | Weekly GitHub Actions job | Fetches the vendored TRaSH JSON from upstream and opens a PR when any differ. Reviewed like Dependabot updates |
| Tests | `apps/mediaserver/tests/` | Pack files parse; quality order invariants (no unknown-source quality above Bluray/WEB unless grouped); every minimum score is reachable; a **release-title corpus test** for every regex ([section 11](#11-rollout-plan)) |

**Migration on the live server** (Phase 1):
1. Remove the Recyclarr crontab line.
2. Run `profiles migrate --dry-run`, review it, then run it for real.
3. Delete the stale Recyclarr files in appdata and the user's config directory.
4. Remove the Recyclarr section and example file from the mediaserver module (keep a short "using Recyclarr instead" note for people who prefer it, with a switch that disables the pack).

### 5.10 Any second language and a Setup Wizard step

**Language table.** The pack keeps one entry per supported language: the app's language name (IDs are resolved at runtime; Hindi is 26 in Radarr and 27 in Sonarr) and safe title tokens. Short tokens that collide with ordinary words are only used next to other language markers.

| Language | Title tokens | Notes |
| :--- | :--- | :--- |
| Hindi | `hindi`, `hin` | Radarr itself only recognises `hindi` |
| Tamil / Telugu / Malayalam / Kannada | `tamil`/`tam`, `telugu`/`tel`, `malayalam`/`mal`, `kannada`/`kan` | `tel`, `mal`, `kan` only next to other language markers |
| Bengali / Marathi | `bengali`, `marathi` | Full words only |
| Spanish (incl. Latin) | `spanish`, `spa`, `esp`, `castellano`, `latino` | |
| French | `french`, `fre`, `fra`, `vff`, `truefrench` | |
| German / Italian / Portuguese | `german`/`ger`, `italian`/`ita`, `portuguese`/`por`/`dublado` | German `DL` releases already parse as original + German |
| Japanese / Korean / Arabic | `japanese`/`jpn`, `korean`/`kor`, `arabic`/`ara` | |

Every token set ships with corpus tests, including known false positives such as *The Thin Red Line*, *Ben-Hur* and *Mar Adentro*.

**Setup Wizard step "Release preferences"** (standard-library HTML form, [ADR-0002](docs/adr/0002-zero-dependency-setup-wizard.md)):

| Question | Choices (default first) |
| :--- | :--- |
| Second audio language | None · Hindi · Tamil · … |
| Default profile for new titles | `1080p Compact` · `1080p Family` (only when a second language is set) |
| What can your TVs and players decode? | HEVC ✔ · AV1 ☐ · Dolby Vision ☐ |
| Seeding | Seed while it helps · Don't seed after downloading |
| Stuck downloads | Replace automatically (watch-only for the first 7 days) · Off |

The answers go to the installer config. `wire_arr.py profiles apply` runs at the end of install. The Control Hub shows the same choices later and re-applies the pack when they change.

---

## 6. Dual audio, end to end

| Stage | What happens | Where |
| :--- | :--- | :--- |
| Detect | Title tokens (`Hindi`/`Hin`, `Eng`, `Dual Audio`, `Multi`) plus parsed languages | Section 5.3 |
| Don't lose it to quirks | `ESub` whitelisted; profile language `Any`; dual tag counts even when English isn't named | Section 5.5 |
| Rank | **Compact:** 1080p only, dual audio preferred, then efficiency. **Family:** Hindi required; dual audio first (1080p, then 720p), then Hindi only | Section 5.2 |
| Grab when perfect | Delay profile bypass at score 4000 | Section 5.5 |
| Upgrade later | English 1080p to dual 1080p is +1500 in Compact. In Family, Hindi-only to dual is +1500 and 720p to 1080p is +1000. All are well over the 400 increment. **Needs a search:** the apps only notice older uploads when asked, so a weekly cutoff-unmet sweep runs (10 titles a day, oldest-searched first) | Section 8.5 |
| Verify after import | Check real audio tracks from media info (`hin`, `eng`, `und`). Flag files with neither the original nor Hindi, and files tagged Hindi that carry no Hindi track. Offer "replace" | Section 9.4 |
| Play | Nova's **preferred audio language** on each TV (Hindi on one, English on another), so dual files open in the right language. Subtitles: Bazarr keeps English always and Hindi only for Hindi audio (already set) | Section 7 |

Three notes:
- **No language in the title.** For releases without a language in the title, the apps assume the original language. A mislabelled file can therefore only be caught after import, which is why the media-info check exists. Example: *Quantum of Solace* is German-only. The same rule lets `Lang · Hindi original (untagged)` recognise an untagged release of a Hindi film as Hindi, so it scores like a tagged one in both profiles.
- **`und` tracks.** Treat `und` ("undetermined") audio as unknown, not wrong. Many Hindi encodes don't tag their tracks.
- **South Indian films.** `Hindi + Tamil` (or `Multi Audio`) releases count as dual audio. A Hindi-only dub of a Tamil film scores −500 in Compact, so the Tamil original wins there unless a dual release exists. Family accepts the dub (+1500), because Hindi is what it needs.

---

## 7. Playback over SMB with Nova Video Player

**What changes because playback is SMB and Nova:**

| Topic | Consequence |
| :--- | :--- |
| Transcoding | **None on the server.** Nova decodes on the TV (hardware first, software fallback), so the Haswell CPU stops limiting codec choice |
| HEVC (x265, 10-bit) | **Preferred.** About 30–50% smaller than H.264 at the same quality, and Android TVs from roughly 2016 onwards decode it in hardware |
| AV1 | **Blocked by default.** Many TV chips lack hardware AV1, and Nova's software fallback can stutter at 1080p. The wizard can allow it for newer TVs |
| HDR / Dolby Vision | Block "DV without HDR10 fallback" (wrong colours on non-DV players). HDR10 at 1080p is neutral |
| Audio | Nova decodes or passes through AC3, EAC3 and DTS; no profile change needed |
| Subtitles | Nova reads SRT, ASS and SUB, and PGS since 6.4.1. Bazarr writes `.srt` next to the video (`subfolder: current`), which Nova picks up by name. Add more Bazarr providers (Podnapisi, Embedded Subtitles, Gestdown/Addic7ed for TV) and turn on subtitle upgrades |
| Audio language | Set Nova's preferred audio and subtitle language on each TV. Older builds had bugs applying it (fixed in 2024 releases), so keep Nova updated |
| Resume files | Nova writes `….archos.resume.xml` beside media files. After an upgrade the old resume file is left behind (harmless; the space-reclaim report lists them) |
| Library in Nova | Nova reads NFO files, and can also write them. Let **Radarr and Sonarr own the NFO files and artwork** (Kodi metadata; Sonarr already writes them, Radarr needs switching on, section 5.5). Their files carry the TMDb/TVDb IDs the stack uses and are rewritten on every upgrade. In Nova, turn off NFO export (or keep it to local storage) so it doesn't overwrite them, and let it prefer local NFO data |
| Keeping Nova current | Add Nova to the [TV auto-updater](apps/tv-autoupdater/README.md)'s managed apps, with its signing certificate pinned like SmartTube and CloudStream. Recent releases fixed SMB playback |

**Jellyfin's reduced role:**
- Seerr's setup expects a media server, so Jellyfin stays as Seerr's backend.
- It isn't used for playback, and it is already lean: trickplay and chapter-image extraction are off for both libraries.
- It doesn't write NFO files (`SaveLocalMetadata` off). Keep it that way so it never competes with Radarr/Sonarr's NFO files.
- Remaining trims, after checking: real-time monitoring (not set explicitly in the library options, so Jellyfin's default applies) and a single nightly library scan.
- Hardware acceleration (VAAPI) only matters if someone streams through Jellyfin remotely, so it's low priority now ([VAAPI/QSV guide](docs/HARDWARE_ACCELERATION_VAAPI_QSV.md)).

**Size sweet spot.** On a 1080p or 4K TV at normal distance, 1080p HEVC looks good at 3–6 Mbit/s (about 3–5 GB for two hours). H.264 needs roughly 5–9 Mbit/s for the same result. Gains above about 11 Mbit/s are hard to see at 1080p, and below about 1.6 Mbit/s banding shows. The limits and Compact scores follow this.

**Disk budget.**
- 132 GB is free today.
- Compact upgrades and the compact replacement job should win back about 140 GB over a few weeks ([section 3.4](#34-library), [section 8.6](#86-compact-replacement-keep-hunting-for-smaller-versions)).
- After that, the cleanup suggestions (section 9.7) and the space-reclaim report (section 8.5) keep it healthy without a new disk.

---

## 8. Stuck downloads: the Download Doctor

### 8.1 How a safe replacement works inside the stack

Remove the download through the app that owns it, **not** through qBittorrent:

```text
DELETE /api/v3/queue/{id}?removeFromClient=true&blocklist=true&skipRedownload=false
```

From the source code:

1. The app removes the torrent and its partial files from qBittorrent.
2. It marks the download failed and adds that exact release to its blocklist.
3. It publishes a "download failed" event. The redownload handler then searches again **unless** one of these applies:
   - redownload was explicitly skipped;
   - "Redownload Failed" is off;
   - the release came from an interactive search and "Redownload Failed from Interactive Search" is off.
4. What it searches for:
   - **Radarr** searches that movie.
   - **Sonarr** searches the episode, or the whole season when the failed download covered a full season.
5. The decision engine picks the best remaining release, which excludes the blocklisted one. **That is the "second best per the stack", chosen by the stack itself.**

Season packs appear as one queue record per episode sharing a download ID. Remove them once with the bulk endpoint (`DELETE /api/v3/queue/bulk`) to avoid several searches.

### 8.2 Detection rules

The Doctor checks every 10 minutes. Patience is measured in **awake** time (the server sleeps 00:00–06:00), so 12 awake hours is about one calendar day. Completed and seeding torrents are never touched.

| Condition | Strike when | Patience | Action |
| :--- | :--- | ---: | :--- |
| Metadata stuck | qBittorrent state `metaDL`/`forcedMetaDL` and size 0 | 2 h | Replace |
| Dead swarm | `stalledDL` (or forced with 0 B/s), no seeds connected, availability < 1, no new bytes. Availability below 1 means some pieces exist nowhere among connected peers; at 99.8% done with availability 0.998 the torrent can never finish | 12 h | Replace |
| Stalled, but a full copy is reachable | Stalled with availability ≥ 1 | 1 h, then 12 h | Re-announce at 1 h, replace at 12 h |
| Crawling | Downloading, but projected time left > 3 days for 6 straight hours | 24 h | Replace, unless ≥ 90% done and still moving |
| Client error | `error` / `missingFiles` | 1 h | Remove without blocklist, search, alert |
| Import blocked (after [auto_import.py](apps/mediaserver/scripts/auto_import.py) had its chance) | `importBlocked` for over 6 h with a known permanent message ("No files found are eligible…", sample-only, no audio tracks) | 6 h | Remove, blocklist, search |
| Queued forever | `queuedDL` for over 24 h | — | Alert only (a configuration problem, not a bad release) |

### 8.3 Strike accounting

- A strike is one 10-minute check in a bad state. Any new bytes **reset** the count.
- No strikes are given while:
  - qBittorrent isn't connected, or DHT has fewer than 50 nodes;
  - fewer than 30 minutes have passed since wake-up (detected as a gap of more than 25 minutes since the previous check);
  - the internet check fails.
- Strikes are **persisted** to a state file, so restarts and updates don't reset them.
- **Not covered:** off-the-shelf tools count strikes in memory and have no post-wake grace period.

### 8.4 Safety rails

| Rail | Rule |
| :--- | :--- |
| Scope | Only torrents that appear in a Radarr or Sonarr queue (matched by download ID) in the `radarr` or `tv-sonarr` category. Manual torrents are never touched |
| Protection | qBittorrent tag `keep`, or "Protect" in the Control Hub, exempts a torrent |
| Private torrents | Skipped by default. Optionally "remove from the app queue only, keep seeding" |
| Dry run | The first 7 days log "would replace" and show it on the dashboard without acting |
| Circuit breaker | If at least 60% of managed torrents (minimum 5) look bad at once, suspect the network: act on nothing and alert |
| Rate limits | At most 3 replacements per run and 15 per day, so indexers and Cloudflare aren't hammered |
| Near-complete | At ≥ 90% with availability ≥ 1, re-announce first and double the patience |
| Audit | Every decision goes to a JSON Lines log: title, indexer, reason, strikes, action, and what was grabbed next |

### 8.5 Escalation, sweeps and blocklist hygiene

- **Per-item cap.** Three replacements of the same movie or episode within 7 days marks it **"needs attention"**. Auto-replacement stops and an alert is sent. Usually no healthy release exists on your indexers yet. The dashboard offers an interactive-search link, "try again in 7 days", and "switch to `1080p Family`", which also accepts 720p when it has Hindi.
- **Cutoff-unmet sweep** (weekly, at most 10 titles a day, skipping anything searched in the last 14 days). This drives dual-audio upgrades and Compact's space reclaim. Oversized titles are searched first and more often ([section 8.6](#86-compact-replacement-keep-hunting-for-smaller-versions)).
- **Blocklist pruning.** A monthly job deletes blocklist entries older than 60 days for titles that are still missing. Swarms do revive, and a permanent blocklist would hide them.
- **Space-reclaim report** (weekly, report only; deletions are confirmed in the dashboard):
  - files under `/data/torrents` that no torrent references and that aren't hardlinked into the library;
  - leftovers in the incomplete folder;
  - recycle bin size;
  - orphaned Nova resume files.

### 8.6 Compact replacement: keep hunting for smaller versions

Goal (owner's request): for oversized titles on `1080p Compact`, keep looking for a more compact version, download it, and delete the old files **only after the new ones have imported properly**.

**Which titles count as oversized:**
- Films: above 55 MB/min at 1080p (about 6.6 GB for two hours).
- TV: above 30 MB/min at 1080p (about 1.35 GB for 45 minutes).
- Only titles on `1080p Compact`, not tagged `keep`, measured from media info (size ÷ runtime).

**Two paths:**

| Path | When | Who does the work |
| :--- | :--- | :--- |
| Native upgrade | Films only (size formats see per-file sizes for releases and files alike) | Radarr: an HEVC release moving into the compact band scores +450, so the sweep's search grabs it and the app imports it as an upgrade. The old file is removed only after the new file imports |
| Compact replacement job | All oversized TV episodes, x264 or HEVC. Since revision 4 codec alone never upgrades, and Sonarr's size condition can't measure season packs per episode | The Download Doctor, as below |

**The compact replacement job** (part of the Download Doctor, every 6 hours, one title in flight at a time):

1. **Pick** the oversized title with the most reclaimable GB that hasn't been searched in the last 3 days.
2. **Search** with the app's own interactive search (season search for TV, so packs come back). The app's parsing and rejections are reused, not reimplemented.
3. **Accept a candidate only if all of these hold:**
   - at least **35% smaller** per minute than the files it replaces, and above the section 5.4 minimum (no starved encodes);
   - same or higher resolution;
   - language no worse: if the current files have Hindi audio, the candidate must carry the Hindi token;
   - no `Junk ·`/`Compat ·` match and at least 4 seeders;
   - for TV, a full-season pack covering every episode on disk for that season (single episodes only when no pack exists);
   - the app's only objection is "not an upgrade".
4. **Grab** it (`POST /api/v3/release` with the candidate's ID). Tag the torrent `compact-replace` and record the expected file list.
5. **Import safely.** The app blocks the finished download as "not an upgrade". The job then runs the same verified manual import as [auto_import.py](apps/mediaserver/scripts/auto_import.py): file count matches the episodes, title match, no samples, sizes as expected. Sonarr/Radarr replace each old file **during** import, so an old file goes to the recycle bin only after its replacement is in place.
6. **Verify.** New files exist, audio languages are as expected (media info), total size is smaller. Record the GB saved. On a mismatch, alert and offer "restore" from the recycle bin (kept 7 days).
7. **Retry.** If the download stalls, the normal stuck-download rules replace it with the next candidate. After three failed candidates, stop and retry the title in 14 days.

**Guardrails:**
- Only start when free space is at least the candidate size plus 20 GB. The new files exist before the old ones are deleted.
- At most one compact replacement downloading at a time, and at most 2 searches per hour.
- Pause while a TV is streaming (section 9.5).
- Watch-only for the first 7 days, like the rest of the Doctor.

**Succession, walked through:**
- All 39 episodes go through the job, season by season: the 23 x264 ones and the 16 bloated HEVC ones alike. A compact HEVC season pack is only +300 over x264, under the 400 step.
- With healthy releases available, the four seasons finish in about a week. The dashboard shows *"Succession: S1 replaced (−22 GB), S2 downloading, S3–S4 queued"*.
- Expected result: about 137 GB down to about 45 GB.

### 8.7 Build or adopt: decided, native

| Option | Why not for this setup |
| :--- | :--- |
| [Cleanuparr](https://github.com/Cleanuparr/Cleanuparr) v2.11 | The richest feature set, but another always-on .NET service on a 7.2 GB box, configured in its own UI (not by the installer) |
| [Decluttarr](https://github.com/ManiMatter/decluttarr) v2 | Light and capable (stalled, metadata, slow, failed-import and bad-file jobs, blocklist and re-search, protected tag, dry run). But strikes live in memory, it has no post-wake grace or per-item cap, and no Control Hub integration |
| Huntarr | **Avoid.** The project vanished in February 2026 after reports of authentication bypasses exposing *arr API keys |

**Native Download Doctor:**
- A standard-library scheduled job, so no RAM is used between runs.
- The installer sets it up with no extra steps.
- It is sleep-aware, has caps, a circuit breaker, persisted state, alerts, and buttons in the dashboard.
- It follows the same pattern as [auto_import.py](apps/mediaserver/scripts/auto_import.py) and the media backup card.

Estimated 500–700 lines plus tests. Decluttarr stays documented as an alternative for other setups ([Appendix E](#appendix-e-decluttarr-for-other-setups)). **Never run two cleaners at once.**

### 8.8 Implementation outline

| Piece | Location | Notes |
| :--- | :--- | :--- |
| Engine | `apps/mediaserver/scripts/download_doctor.py` | Standard library. Stuck-download rules plus the compact replacement job. Reuses the `ArrClient` pattern and verified manual import from [auto_import.py](apps/mediaserver/scripts/auto_import.py). qBittorrent through an API key (5.2+) with a cookie-login fallback. Options: `--once`, `--dry-run`, `--verbose`, `--job stuck,compact,sweep` |
| Schedule | `apps/mediaserver/host/cron/mediaserver-download-doctor` | Stuck rules every 10 minutes; compact replacement every 6 hours; weekly sweep and space report; monthly blocklist prune |
| State | Under the installer's state directory (`/var/lib/homelab/download-doctor/`) | `state.json` (strikes, history), `status.json` (dashboard summary), `actions.jsonl` (audit), `overrides.json` (protect or extend, written by the Control Hub) |
| Dashboard | Control Hub widget reading `status.json` (path from env) | Same pattern as the media backup card. The module boundary stays intact ([AGENTS.md](AGENTS.md) §1.6) |
| Alerts | New rules in [alerts.py](apps/control-hub/core/alerts.py) | See section 9.8 |
| Tests | `apps/mediaserver/tests/test_download_doctor.py` | Fixtures from [Appendix I](#appendix-i-download-doctor-test-fixtures): metadata stuck 39 h → replace; 99.8% done with availability 0.998 (pieces missing from the swarm) → replace; a synthetic 99% torrent with availability ≥ 1 → re-announce first, patience doubled; healthy torrent right after wake → no strike; seeding torrent → ignored; private → skip; season pack → one bulk delete; dry run → no calls; circuit breaker trips. Compact replacement: rejects candidates under 35% smaller, lower resolution, or missing Hindi when the current file has it; refuses to start without free-space headroom; imports only after the download completes; a verification failure raises an alert and a restore offer |

### 8.9 Until it exists: the manual procedure

- **Do:** in Radarr or Sonarr → Activity → Queue → select → **Remove** → tick "Remove from download client" and "Add release to blocklist". Leave redownload on.
- **Don't:** delete the torrent in qBittorrent, or with the Control Hub's delete button. Nothing gets blocklisted and nothing is searched, so the next search can grab the same dead torrent.
- **Order matters:** fix the profiles first (Phase 0). Otherwise the re-search picks the next untagged `HDTV-1080p` upload and the problem repeats.

---

## 9. Control Hub: a more useful dashboard

Everything here keeps to the Control Hub budget (under 25 MB RAM, under 0.2% CPU idle):
- Heavy aggregation happens in the mediaserver jobs (`status.json`) or is cached for 1–6 hours.
- Every view gets Playwright plus axe-core WCAG 2.2 AA checks, per [AGENTS.md](AGENTS.md).

### 9.1 Switch on what's already built (quick win)

- [media_hub.py](apps/control-hub/widgets/media_hub.py) already builds the calendar, wanted list, Seerr requests and "recently added". On the live server **every one reports `configured: false`**: `control-hub.env` has no Radarr, Sonarr, Seerr or Jellyfin keys.
- The renderer in [env_manager.py](apps/control-hub/core/config_core/env_manager.py) never writes them, so this affects every install.
- **Fix:** render `RADARR_API_KEY`, `SONARR_API_KEY`, `SEERR_API_KEY` (read from Seerr's settings) and `JELLYFIN_API_KEY` into `control-hub.env`. Create the Jellyfin key during wiring; `wire_arr.py` already logs into Jellyfin.
- **This also matters for other users.** [server-suspend.sh](apps/control-hub/host/server-suspend.sh) only defers suspend for Jellyfin playback when `JELLYFIN_API_KEY` is set. It never is, so **any install that plays through Jellyfin can suspend mid-movie at midnight**. This household plays over SMB, which the SMB guard already protects.

### 9.2 Unified queue with the Download Doctor

Replace the raw qBittorrent list in **Apps → Current Downloads** with one queue joined on download ID. Today that list shows HTML entities like `&amp;` in names and counts 20 dead torrents as "active".

| Column | Source |
| :--- | :--- |
| Clean title (movie or episode, not the torrent name) and profile | Radarr/Sonarr queue |
| Quality, score, language badges (`HI+EN`) | Queue item custom formats and languages |
| Indexer, size, progress, time left | Queue and qBittorrent |
| Swarm: seeds/peers connected, availability, last activity | qBittorrent |
| Health: OK / watching / striking (e.g. "auto-replace in 3 h 20 m") / needs attention | Doctor `status.json` |
| Actions: Replace now, Remove only, Protect, Give 24 h more, Interactive search link | *arr queue API; qBittorrent tag; `overrides.json` |

Also show a **"Recently replaced"** list with the outcome: did the replacement import, and how fast.

### 9.3 Release profiles card

- **Status:** profile pack version, last apply, and **drift checks** with a "Re-apply" button.
- **What drift covers:**
  - quality order;
  - every minimum score reachable;
  - Radarr language `Any`; hardcoded-subtitle whitelist;
  - Prowlarr Full Sync; minimum seeders;
  - Redownload Failed on; recycle bin set;
  - no orphan profiles or blackhole cruft.
- **Wizard choices editable here:** language, default profile, codec support, seeding and auto-replace.
- **Per-title `1080p Family` switch**, shown in the queue, wanted and library lists. It moves a title between `1080p Compact` and `1080p Family` and starts a search.

These checks would have caught RC1, RC3, the unreachable profiles and the dead Ozlem block.

### 9.4 Library insights and indexer scoreboard

- **Dual-audio coverage.** The percentage of English films with `hin` + `eng` tracks, and the "upgrade candidates" list.
- **Space reclaim:**
  - oversized titles and estimated savings (*Succession*: about 90 GB);
  - compact replacement progress per title (searched, downloading, imported, GB saved);
  - "find compact version now" and "never compact this title" buttons.
- **Wrong-language files.** Files with neither the original language nor Hindi (from media info). Action: replace.
- **Low-bitrate files** below the section 5.4 minimum. Action: "find better".
- **TV compatibility.** Files in AV1 or Dolby Vision without HDR10 fallback, which Nova may not play well.
- **Missing subtitles** (Bazarr) and a **disk forecast** ("full in about N days at the current ingest rate").
- **Indexer scoreboard.** Per indexer:
  - grabs, import rate, dead-on-arrival rate (Doctor replacements), median grab-to-import time;
  - Prowlarr failures.

  Suggested priority changes come with a one-click apply behind a confirmation. Section 3.3 is the first version.

### 9.5 Now playing on the TVs (SMB)

- **Today:** the Control Hub already reads `smbstatus` sessions ([telemetry_sampler.py](apps/control-hub/core/telemetry_sampler.py) `get_smb_sessions()`).
- **Extend it with open files** (`smbstatus --json`, Samba 4.15+). Match the client address to the TV fleet's names and show *"Living Room TV is playing Dune: Part Two (2024)"*.
- **The same signal fixes Sleep Guard.** It should defer only for open media files, not for any connected share (defect D6).
- **It also protects playback.** It can pause seeding and the Download Doctor's heavy jobs while a TV is streaming.

### 9.6 Activity feed and family notifications

- **Feed.** Radarr and Sonarr Connect → Webhook to a new token-protected endpoint (`POST /api/media/events`). The **Overview → Live Activity** card then shows grabbed, imported, upgraded, failed, health-issue and manual-interaction-required events as they happen.
- **Optional family channel.** Through the existing ntfy and Telegram plumbing, separate from admin alerts: *"Ready to watch on the TV: Dune: Part Two (Hindi + English)"*. With SMB playback there is no Jellyfin "recently added", so this becomes the household's "what's new".

### 9.7 Request tracker and cleanup suggestions

- **Request tracker.** For each Seerr request, show the pipeline stage: requested → searching → downloading (with health) → imported. When nothing passes the filters, show the **top rejection reasons** from an interactive search ("all 12 candidates below minimum seeders", "profile minimum score unreachable").
- **Cleanup suggestions.** With 86% used, suggest titles that are watched (from Nova resume files or a manual "watched" mark), older than N days and not protected. The user confirms every deletion, which goes through Radarr/Sonarr and lands in the recycle bin.

### 9.8 New alert rules

| Rule | Severity | Fires when |
| :--- | :--- | :--- |
| `download_needs_attention` | warning | An item hits the replacement cap |
| `download_doctor_paused` | warning | The circuit breaker trips (likely a network problem) |
| `profile_drift` | warning | The pack check fails for more than 1 h |
| `indexer_degraded` | warning | Import rate under 30% over the last 20 grabs, or Prowlarr failures |
| `library_language_mismatch` | info | New import with neither the original language nor Hindi |
| `library_tv_incompatible` | info | New import in AV1 or Dolby Vision without fallback (if allowed) |
| `disk_forecast` | warning | Projected full within 30 days |

New endpoints, to document in `apps/control-hub/docs/openapi.yaml`:
- `GET /api/media/queue`
- `GET /api/media/doctor`
- `POST /api/media/doctor/{download_id}/{action}`
- `GET /api/media/profiles`
- `POST /api/media/profiles/apply`
- `PUT /api/media/profiles/preferences`
- `POST /api/media/titles/{kind}/{id}/profile`
- `GET /api/media/library-insights`
- `GET /api/media/indexers/scoreboard`
- `GET /api/media/now-playing`
- `POST /api/media/events`
- `GET /api/media/activity`
- `POST /api/media/search/{kind}` (missing or cutoff; rate-limited)

---

## 10. Other defects found

| ID | Finding | Evidence | Fix | Priority |
| :--- | :--- | :--- | :--- | :--- |
| D1 | `1080p Balanced` profiles need a score of 200,000 | *Bhay* 0/8 can never download; *Khauf* can never upgrade | Pack `migrate` step | High |
| D2 | The Ozlem block is a silent no-op | `/api/v3/restriction` → 404; 0 release profiles; a German-only *Quantum of Solace* | `Junk · Banned uploaders` format; replace that file | High |
| D3 | Media views (and the Jellyfin sleep guard for others) switched off | No media keys in `control-hub.env` (renderer gap) | Section 9.1 | High |
| D4 | Dashboard delete bypasses the apps | `torrent_action()` deletes in qBittorrent | Use the app queue removal for app-managed torrents; plain delete only for manual torrents | High |
| D5 | Sleep Guard treats any connected SMB share as activity | A PC with the share mapped deferred sleep at 00:00 on 2026-11-28; idle TVs can do the same | Check open media files instead (section 9.5) | High |
| D6 | Download list cosmetics | `&amp;` and `&#039;` in names; dead torrents counted as active | Decode names with `html.unescape`; count by health | Medium |
| D7 | No recycle bin in Radarr or Sonarr | 145 episode and 43 movie file deletions in the history window | Section 5.5 | Medium |
| D8 | Recyclarr runs outside the repo; README asks users to set it up by hand; a second, unused `recyclarr.yml` in appdata uses unsupported inline syntax | User crontab line; module README; stale file | Section 5.9 | Medium |
| D9 | Jellyfin background work for a server nobody plays from | Trickplay and chapter-image extraction already off; `SaveLocalMetadata` off; real-time monitoring not set explicitly | Check real-time monitoring and the scan schedule; keep `SaveLocalMetadata` off | Low |
| D10 | Nova isn't kept up to date | Not in the TV auto-updater's managed apps | Section 7 | Medium |
| D16 | Radarr doesn't write NFO files for Nova | Kodi (XBMC) / Emby metadata disabled in Radarr (enabled in Sonarr) | Turn it on (section 5.5) | Medium |
| D17 | Two films on disk have the wrong audio | *Quantum of Solace*: German-only (Ozlem upload). *Casino Royale*: a RiffTrax commentary release (three English tracks) | Replace both after the profiles are fixed (Phase 0) | Medium |
| D11 | Usenet Blackhole clients pointing into the media tree | Radarr and Sonarr download clients | Remove | Low |
| D12 | 18 movies with minimum availability `tba` | Radarr movie list | Set `Released` | Low |
| D13 | Allowed Hosts warnings in all three apps | Health endpoints | Section 5.5 | Low |
| D14 | `setup_sonarr_season_preference.py` (removed in Phase 1) uses `requests` and regex season formats | Script source | Retire it (TRaSH Season Pack in the pack) | Low |
| D15 | Jellyfin hardware acceleration off with a render node present | `encoding.xml` says `none`; compose `devices:` commented out | Only if Jellyfin playback is used | Low |

---

## 11. Rollout plan

### Phase 0: same-day fixes on the live server (manual, about 45 minutes)

Do these in order. Nothing here needs code, and each step can be undone.

1. **Back up.** Control Hub → Backups → "Back up now" (media settings), plus a manual backup in Radarr and Sonarr (System → Backup).
2. **Stop Recyclarr.** Remove (or comment out) its line in the server user's crontab, or the 06:30 sync reverts steps 3–4. It won't be needed again once the pack ships.
3. **Merge the 1080p qualities** in `1080p Compact` (Radarr and Sonarr) into one group at the top: Bluray, WEBDL, WEBRip and HDTV-1080p.
   - Keep the existing `Hindi Audio` format and Radarr's profile language `Original` for now. Switching to `Any` waits for the Phase 1 language formats, otherwise Hindi-only dubs of English films would win.
   - The second profile (`1080p Family` since revision 4) arrives with the pack in Phase 1.
4. **Set the size limits** from section 5.4 (both apps).
5. **Radarr:** fill in Whitelisted Hardcoded Subs (section 5.5).
6. **Prowlarr:** Full Sync for both apps; app profile minimum seeders 4; priorities from section 5.6.
7. **Move the stranded titles.** Move *Bhay* and *Khauf* (Sonarr) and *The Dark Knight* (Radarr) to `1080p Compact`, then delete both `1080p Balanced` profiles.
8. **qBittorrent:** seeding limits, evening upload schedule, queue limits, the tracker list from URL and re-announce on address change (section 5.7).
9. **Clear the stuck items** through the app queues (section 8.9). That includes *Live and Let Die* (99.8%) and *A View To A Kill* (99.7%): their availability is 0.998 and 0.996, so the last pieces exist nowhere in the swarm and they can't finish. A single forced re-announce after step 8 (new tracker list) is worth one try before removing them.
10. **On each TV,** set Nova's preferred audio and subtitle language.
11. **NFO metadata:** in Radarr → Settings → Metadata, enable Kodi (XBMC) / Emby (movie metadata and images). On each TV, turn off Nova's NFO export so it doesn't overwrite the apps' files.
12. **Replace the two wrong files (D17).** In Radarr, for *Quantum of Solace* and *Casino Royale*: Movie → Files → delete the file → Search. Add `rifftrax` and `Ozlem` as "must not contain" terms in a release profile until the Phase 1 formats exist.
13. **Verify:**
    - An interactive search for *Goldfinger* lists the `[Hindi English]` 1080p BDRip first.
    - The re-searches grab tagged, seeded releases.
    - Nothing new sits at 0 B/s after 2 h.

#### Phase 0 record (applied 2026-11-28)

Applied by an agent through the APIs with the owner's approval. [Appendix F](#appendix-f-live-baseline-2026-11-28) stays the **pre-Phase-0** baseline.

**Backups (step 1):**
- A media settings archive (Control Hub "Back up now"), and manual Radarr, Sonarr and Prowlarr backups (`Backups/manual/` in each app's appdata).
- An exact JSON snapshot of every object Phase 0 touched, in `~/phase0-backup-20261128/` on the server (mode `0700`; it contains keys, so it stays there).

**What changed, by step:**

| Step | Result |
| :--- | :--- |
| 2 | Recyclarr's crontab line is commented out (marked `# phase0 2026-11-28 disabled`). Its binary, config and log are untouched |
| 3 | Profile 9 in both apps (ID kept): the four 1080p qualities form one allowed group, `HD 1080p` (group ID 1002), at the top; `cutoff` = 1002. Scores, `Hindi Audio` and Radarr's `Original` language unchanged |
| 4 | Section 5.4 sizes in both apps. Sonarr's "4–5" row: WEBRip-1080p 5, HDTV-1080p 4. Radarr HDTV-720p (not in 5.4) left at 0/8/20 |
| 5 | Radarr whitelist `ESub,ESubs,MSub,MSubs,EngSub,EngSubs`; Allow Hardcoded Subs stays off |
| 6 | Prowlarr: both apps on Full Sync; profile "Standard" minimum seeders 4; priorities EZTV 10, LimeTorrents 15, YTS 20, 1337x 25, The Pirate Bay 40. Synced to both apps; the indexer set didn't change |
| 7 | *The Dark Knight*, *Bhay* and *Khauf* moved to profile 9; profiles 7 and 8 deleted in both apps. Radarr also needed *The Dark Knight Collection* (unmonitored) moved from 8 to 9 first: "QualityProfile [8] is in use" |
| 8 | qBittorrent: ratio 1.0 / 1440 min / 60 idle min, then stop; scheduler 18:00–00:00 daily, alternative limits upload 1 MiB/s and download unlimited; queue 8 / 20 / 5 uploads, slow torrents not counted (4 KiB/s, 300 s); trackers from the ngosang `trackers_best.txt` URL; re-announce on address change. Excluded file names and the API key were left for Phase 1 |
| 9 | All 20 stuck items removed through the app queues with blocklist and redownload (Radarr 17, Sonarr 3). The one try for *Live and Let Die* and *A View To A Kill* (the tracker list added to each, forced re-announce): 6 working trackers, still 0 seeds in the swarm, so both were removed too. Every re-search grabbed a tagged release: Bluray or WEB-DL, almost all HEVC, 4 with Hindi + English (*Goldfinger*, *From Russia with Love*, *Thunderball*, *Spectre*) |
| 10 | Owner, on each TV (Nova preferred audio and subtitle language) |
| 11 | Radarr Kodi (XBMC) / Emby metadata enabled with its existing fields (`useMovieNfo` off, so `<file>.nfo`). Turning off Nova's NFO export on each TV is for the owner |
| 12 | **The release profile was created before step 9**, not after: without it the re-searches would pick the Ozlem *Goldfinger* (104 seeders, untagged). Radarr release profile 1, "Phase 0 bans (until profile pack)", ignores `rifftrax` and `Ozlem`. Radarr's recycle bin was turned on (`/data/media/.recycle`, 7 days; section 5.5) before deleting, so both files can be restored until 2026-12-05. *Casino Royale* now has `… Uncut 1080p BluRay DD+ 5.1 x265-edge2020` and *Quantum of Solace* `… REPACK 1080p BluRay HDR10 DDP 5 1 x265-edge2020` downloading |
| 13 | Results in the next table |

**Step 13 checks:**

| Check | Result |
| :--- | :--- |
| *Goldfinger* interactive search | Pass. `Goldfinger (1964) DS4K 1080p BDRip HEVC [Hindi English] DDP 5.1 — PeruGuy` ranked first (score 50,250, 8 seeders). The 5.17 GB Netflix WEB-DL is no longer rejected for size, and Ozlem is rejected by the ignored term |
| Re-searches grab tagged, seeded releases | Pass. All 22 replacements are tagged; 8 of them were downloading at 0.3–4.3 MiB/s within minutes. The rest waited in the new 8-download queue |
| Nothing new at 0 B/s after 2 h | PENDING |

**Appendix K items cleared:**
- **2:** the whitelist works. ESub, ESubs and MSubs titles (*Drishyam 2*, *3 Idiots*) no longer get "Hardcode subs found", and `Drishyam 2 (2022) - Hindi - 1080p HDRip - x264 - AAC - 2.9GB - ESub` is approved. Hyphenated `E-SuB`/`M-SuB` were never matched by the parser. `NLSub` (Dutch, really burned in) is still rejected, as intended. Exact versus substring matching is untested, because the list names every variant seen.
- **14:** the API uses bytes/s. Setting `alt_up_limit` to 1048576 stores `AlternativeGlobalUPSpeedLimit=1024` (KiB) in `qBittorrent.conf`, so the Control Hub's assumption is right.
- **16:** `qBittorrent.conf` has no `ShareLimitAction` override, so the default (Stop) applies, and the API reports it as `max_ratio_act` 0.

**For Phase 1 (`profiles migrate`):**
- Profile 9 already holds the merged group 1002, and profiles 7 and 8 no longer exist; migrate must handle both.
- Remove Radarr release profile 1 once the `Junk ·` formats are in.
- Recyclarr's cron line is already commented out.

### Phase 1: profile pack and wizard step (PR `feat(mediaserver): repo-owned release profiles replace Recyclarr`)

- `apps/mediaserver/profiles/` data (formats, both profiles, sizes, language table, vendored TRaSH formats with attribution).
- `wire_arr.py profiles apply|check|migrate`; fix `ensure_restriction_term()` and the categories.
- Setup Wizard "Release preferences" step and the config keys it writes; the installer runs `profiles apply`.
- Remove the Recyclarr example and README section (keep a short "using Recyclarr instead" note and the switch that disables the pack).
- Weekly TRaSH upstream-check workflow.
- **Tests:**
  - Pack parsing; profile invariants; reachable minimum scores.
  - The **release-title corpus test**, using real titles from this analysis. Examples: `[Hindi English]` and `Dual Audio [Hindi 2.0 Eng 5.1]` match dual; `Hindi DD 2.0 Esub` matches Hindi; `Hindi LiNE` is rejected; `The Thin Red Line … Hindi Dual Audio` is **not** rejected; AV1 and DV-without-fallback are rejected.
  - Wizard tests in `setup/test_setup.py`.
- **Docs:** see [section 12](#12-documentation-plan).
- **Gate:**
  - All six repo suites plus the new tests.
  - On the live server, `profiles migrate --dry-run` reviewed, then applied.
  - Phase 0 step 13 checks pass in both profiles.
  - A Slow Horses season search ranks packs first.

### Phase 2: Download Doctor (PR `feat(mediaserver): download doctor for stalled and dead torrents`)

- Engine with the stuck-download rules and the compact replacement job, schedule, state files, weekly sweep and space report, monthly blocklist prune; tests from section 8.8.
- **Seven days in dry run.** Compare its "would replace" and "would compact" lists against what a human would have done, then go live.
- **Gate:**
  - No false "would replace" on healthy torrents across at least one wake-up cycle; caps and circuit breaker covered by tests.
  - The first compact replacement (one *Succession* season) imports, is verified, and its old files are in the recycle bin.

### Phase 3: Control Hub (PRs in this order)

1. Wire the media keys into `control-hub.env` (section 9.1), and fix the delete path and name decoding (D4, D6).
2. Unified queue and Download Doctor card (section 9.2).
3. Release profiles card with drift checks and the per-title switch (section 9.3), plus the alert rules (section 9.8).
4. Now playing on the TVs, with the Sleep Guard open-file check (section 9.5, D5).
5. Library insights and indexer scoreboard (section 9.4).
6. Activity feed and family notifications (section 9.6); request tracker and cleanup suggestions (section 9.7).

Each PR runs the Control Hub unit, Playwright and axe-core suites and updates the OpenAPI file.

### Phase 4: housekeeping

- Jellyfin trimming (D9); Nova in the TV auto-updater (D10); Bazarr providers.
- Usenet cruft, `tba` availability, Allowed Hosts (D11–D13); retire the season-preference script (D14).
- Optional VPN with port forwarding (decision 9).

---

## 12. Documentation plan

Every change ships with its documentation, following [AGENTS.md](AGENTS.md) §3:
- Diátaxis index and runbook table updates.
- ADR numbering and mandatory sections.
- Module READMEs that link outside their folder only with absolute GitHub URLs.

| Deliverable | Phase | Location | Content |
| :--- | :--- | :--- | :--- |
| ADR-0004: repo-owned release profiles | 1 | `docs/adr/0004-repo-owned-release-profiles.md` | Why merged groups plus scores; why the pack replaces Recyclarr; options considered |
| ADR-0005: automatic replacement of stalled downloads | 2 | `docs/adr/0005-download-doctor.md` | Rules, sleep-aware strikes, safety rails, why native rather than Cleanuparr/Decluttarr; compact replacement and why it uses the verified manual-import path |
| Guide: release profiles and dual audio | 1 | `docs/MEDIA_RELEASE_PROFILES.md` | How ranking works (section 4.1 tables); the two profiles; changing language; switching titles; "why isn't it downloading?" checklist; using Recyclarr instead |
| Guide: Download Doctor | 2 | `docs/DOWNLOAD_DOCTOR.md` | What it does and when; compact replacement (thresholds, progress, "never compact this title"); protect and extend; reading the audit log; dry run; restoring from the recycle bin; troubleshooting |
| Guide: playing over SMB with Nova | 1 | `docs/SMB_PLAYBACK_WITH_NOVA.md` | Adding the share in Nova; NFO files (Radarr/Sonarr own them; Nova reads, export off); preferred audio and subtitle language; codec checks (HEVC, AV1, Dolby Vision); resume files; naming |
| Seeding and qBittorrent policy | 1 | Section in `docs/MEDIA_RELEASE_PROFILES.md` | What seeding gives and costs (section 5.7); evening limit; private trackers |
| Indexes | 1–2 | [docs/README.md](docs/README.md), [README.md](README.md) runbook table, [docs/adr/README.md](docs/adr/README.md) | One line per new guide and ADR |
| mediaserver README | 1–2 | [apps/mediaserver/README.md](apps/mediaserver/README.md) | Replace the Recyclarr section with the profile pack and Download Doctor sections |
| Setup README | 1 | [setup/README.md](setup/README.md) | The "Release preferences" step and the config keys it writes |
| Control Hub README and OpenAPI | 3 | [apps/control-hub/README.md](apps/control-hub/README.md), `apps/control-hub/docs/openapi.yaml` | New cards and endpoints |
| TV auto-updater README | 4 | [apps/tv-autoupdater/README.md](apps/tv-autoupdater/README.md) | Nova as a managed app and its pinned certificate |
| Changelog | each | [CHANGELOG.md](CHANGELOG.md) | One entry per PR (the version-consistency test checks it) |
| This plan | each | here | Mark phases done; record anything that changed during implementation |

---

## 13. Success metrics

| Metric | Baseline (2026-11-28) | Target | Measured by |
| :--- | ---: | ---: | :--- |
| App-managed torrents with no progress for more than 12 awake hours | 20 | 0 | Download Doctor `status.json` |
| Movie grabs that import without a replacement | 31% | ≥ 80% | History join (section 3.3) |
| English films with Hindi + English audio | 8 of 44 (18%) | Rising every week while releases exist | Media info audit |
| Disk used by media | 496 GB (86% of the disk) | About 140 GB less after the Compact sweep and compact replacement, with no manual deletions | Space-reclaim report |
| *Succession* on disk | 137 GB | About 45 GB, every episode verified after import | Compact replacement progress |
| Median 1080p film size in `1080p Compact` | 2.5–3 GB (mixed quality) | 3–5 GB, HEVC where available, nothing under 12 MB/min | Library insights |
| Files Nova can't play well (AV1, DV without fallback) | not tracked | 0 new | Library insights |
| Profile drift | not tracked | Release profiles card all green | Section 9.3 |

---

## 14. Decisions

| # | Question | Answer (2026-11-28) |
| ---: | :--- | :--- |
| 1 | Should a 720p dual-audio release beat a 1080p English one? | **Only in the separate `1080p Family` profile**, which since revision 4 requires Hindi and rejects English-only releases. `1080p Compact` is 1080p only |
| 2 | 4K? | No: 1080p (disk) |
| 3 | Do the players handle HEVC? | **Yes: SMB with Nova Video Player** on Android TVs |
| 4 | Seeding | **Seed while it helps** (ratio 1.0 / 24 h / 60 idle minutes), with the evening upload limit |
| 5 | Patience before replacing | Defaults: metadata 2 h, dead swarm 12 h, crawling 24 h (awake time) |
| 6 | Build or adopt the cleaner? | **Native Download Doctor**, plus the repo-owned profile pack instead of Recyclarr |
| 7 | Library metadata for Nova | **Nova reads and writes NFO files.** Radarr/Sonarr own them; Nova's export off |
| 8 | Oversized titles such as *Succession* | **Keep hunting for compact versions;** delete old files only after a verified import (section 8.6) |
| 14 | Who is the second profile for? ([revision 4](#revision-4-owner-decisions-on-profiles-and-scoring-2026-11-28)) | **`1080p Family`: Hindi required, English a bonus.** The owner understands both, the parents only Hindi. 1080p dual > 720p dual > 1080p Hindi only > 720p Hindi only; English-only rejected (minimum score 1400) |
| 15 | May HEVC or other small extras trigger an upgrade? ([revision 4](#revision-4-owner-decisions-on-profiles-and-scoring-2026-11-28)) | **No.** Only language, resolution, leaving the oversized range or moving into the compact band; the extras together stay under the 400 step. TV size savings go through the compact replacement job |

Still open, with the default the plan uses:

| # | Question | Default |
| ---: | :--- | :--- |
| 9 | VPN for torrent traffic? | None. If wanted, use a VPN with port forwarding, or connectability (and thin swarms) get worse |
| 10 | Do any TVs decode AV1 in hardware, or have Dolby Vision? | Assume no: AV1 and DV without fallback are blocked; the wizard can allow them |
| 11 | Make `1080p Family` the default for some Seerr users (for example, parents' accounts)? | No: `1080p Compact` for everyone, with per-request choice for users with Advanced Requests |
| 12 | More storage? | Not needed for now if the Compact sweep and compact replacement reclaim about 140 GB |
| 13 | Compact replacement thresholds | Films above 55 MB/min, TV above 30 MB/min, replacement at least 35% smaller |

---

## 15. Risks

| Risk | Mitigation |
| :--- | :--- |
| Minimum seeders 4 hides rare Hindi titles | Two Prowlarr profiles (strict and live); "needs attention" list; per-title switch to `1080p Family` (which also accepts 720p, with Hindi) |
| A title's original language is recorded wrongly in TMDB, so an untagged release counts as Hindi when it isn't | Rare; the media-info check after import (section 6) flags files without a Hindi track |
| Regex false positives (`Line` in titles, `Hin`, short language tokens) | Adjacency rules in the regexes, a corpus test, Radarr's custom format test tool, and monitoring rejection reasons |
| Compact's space-reclaim upgrades swap a source-quality file for a re-encode | Only when the re-encode is in the compact band and scores at least 400 more; `keep` tag; recycle bin |
| Compact replacement swaps in a worse encode | Only when at least 35% smaller per minute **and** above the size floor; same or higher resolution; language no worse; verified after import; restore from the recycle bin; `keep` tag and "never compact this title" |
| A replacement download fills the disk before the old files are removed | Starts only with free space ≥ candidate size + 20 GB; one replacement at a time |
| Forcing an import the app calls "not an upgrade" | Only for candidates that passed the section 8.6 checks, through the verified manual-import path, logged in the audit file |
| Vendored TRaSH formats go stale | Weekly upstream check opens PRs; the pack records the upstream commit |
| The pack overwrites a user's hand-made change | It only manages objects with its prefixes and its own profiles; drift is shown before re-apply; a switch turns the pack off |
| Replacement churn or indexer bans | Rate limits, per-item cap, circuit breaker, dry-run week |
| Blocklisting a torrent that would have revived | Monthly blocklist pruning (60 days) |
| Deleting a 99% torrent | Near-complete rule (re-announce first, double patience) |
| Seeding makes SMB playback stutter | Evening upload limit, 5 active uploads; the now-playing signal can pause seeding (section 9.5) |
| Nova changes behaviour (preferred language, SMB) | Keep it updated through the TV auto-updater; document the settings in the SMB guide |
| Legal and privacy exposure on public trackers without a VPN | Your call (decision 9). This project ships no indexer list ([README](README.md#indexers-and-your-responsibility)) |

---

## 16. References

Radarr and Sonarr source code (exact behaviour):
- [Radarr `DownloadDecisionComparer`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/DecisionEngine/DownloadDecisionComparer.cs)
- [Sonarr `DownloadDecisionComparer`](https://github.com/Sonarr/Sonarr/blob/develop/src/NzbDrone.Core/DecisionEngine/DownloadDecisionComparer.cs)
- [Radarr `QueueController`](https://github.com/Radarr/Radarr/blob/develop/src/Radarr.Api.V3/Queue/QueueController.cs)
- [Radarr `FailedDownloadService`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/Download/FailedDownloadService.cs) and [`RedownloadFailedDownloadService`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/Download/RedownloadFailedDownloadService.cs)
- [Sonarr `RedownloadFailedDownloadService`](https://github.com/Sonarr/Sonarr/blob/develop/src/NzbDrone.Core/Download/RedownloadFailedDownloadService.cs)
- [Radarr `Parser.cs`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/Parser/Parser.cs) (hardcoded-subtitle regex) and [`LanguageParser.cs`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/Parser/LanguageParser.cs)
- [Radarr `AggregateLanguages.cs`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/Download/Aggregation/Aggregators/AggregateLanguages.cs) (original-language fallback)
- [Sonarr `ReleaseTypeSpecification`](https://github.com/Sonarr/Sonarr/blob/develop/src/NzbDrone.Core/CustomFormats/Specifications/ReleaseTypeSpecification.cs)

Guides and tools:
- [TRaSH: language custom formats (Radarr)](https://trash-guides.info/Radarr/Tips/How-to-setup-language-custom-formats) and [(Sonarr)](https://trash-guides.info/Sonarr/Tips/How-to-setup-language-custom-formats)
- [TRaSH: quality profiles](https://trash-guides.info/Radarr/radarr-setup-quality-profiles), [merge quality](https://trash-guides.info/Radarr/Tips/Merge-quality), [Radarr sizes](https://trash-guides.info/Radarr/Radarr-Quality-Settings-File-Size), [Sonarr sizes](https://trash-guides.info/Sonarr/Sonarr-Quality-Settings-File-Size), [Sonarr custom formats (Season Pack)](https://trash-guides.info/Sonarr/sonarr-collection-of-custom-formats)
- [TRaSH: qBittorrent basic setup](https://trash-guides.info/Downloaders/qBittorrent/Basic-Setup)
- [TRaSH Guides repository](https://github.com/TRaSH-Guides/Guides) (custom-format JSON; MIT licence)
- [Servarr wiki: Radarr settings](https://wiki.servarr.com/radarr/settings)
- [Recyclarr: quality profiles](https://recyclarr.dev/reference/configuration/quality-profiles/) and [custom formats](https://recyclarr.dev/reference/configuration/custom-formats/)
- [Configarr: config file (local custom formats)](https://configarr.de/docs/configuration/config-file/)
- [Dictionarry/Profilarr database (mirror)](https://github.com/Dumpstarr/Database)
- [Cleanuparr](https://github.com/Cleanuparr/Cleanuparr) and its [queue cleaner docs](https://cleanuparr.github.io/Cleanuparr/docs/configuration/queue-cleaner)
- [Decluttarr](https://github.com/ManiMatter/decluttarr)
- [ngosang/trackerslist](https://github.com/ngosang/trackerslist); [qBittorrent forum: add trackers from URL](https://forum.qbittorrent.org/viewtopic.php?p=37662)
- Seerr: [adding users (local users)](https://docs.seerr.dev/using-seerr/users/adding-users/)
- Nova Video Player: [source](https://github.com/nova-video-player/aos-AVP), [release notes](https://www.apkmirror.com/apk/courville-software/nova-video-player/)
- Huntarr status: [ElfHosted, 2026-02-24](https://store.elfhosted.com/blog/2026/02/24/huntarr-ends-its-hunt-newtarr-takes-it-up/), [PiunikaWeb, 2026-02-24](https://piunikaweb.com/2026/02/24/huntarr-security-vulnerability-arr-api-keys-exposed/)

Repo documents this plan builds on:
- [ADR-0001 single mount and hardlinks](docs/adr/0001-single-mount-atomic-hardlinks.md)
- [ADR-0002 zero-dependency setup wizard](docs/adr/0002-zero-dependency-setup-wizard.md)
- [ADR-0003 Sleep Guard](docs/adr/0003-acpi-s3-sleep-guard-power-automation.md)
- [Control Hub alerts](docs/CONTROL_HUB_ALERTS.md)
- [Control Hub Improvement Plan](Control%20Hub%20Improvement%20Plan.md)
- [mediaserver README](apps/mediaserver/README.md)

---

## Appendices

### Appendix A: how much seeders matter

Radarr and Sonarr compute `Math.Round(Math.Log10(seeders))`. .NET rounds half to even, but `log10` of a whole number never lands exactly on .5.

| Seeders | log10 | Bucket |
| ---: | ---: | ---: |
| 1 | 0.00 | 0 |
| 3 | 0.48 | 0 |
| 4 | 0.60 | 1 |
| 31 | 1.49 | 1 |
| 32 | 1.51 | 2 |
| 316 | 2.50 (2.4997) | 2 |
| 317 | 2.50 (2.5011) | 3 |

Peers are compared the same way, only when seeder buckets tie, and only after quality, score, protocol and indexer priority.

### Appendix B: custom format specifications

The format is tool-neutral; field names follow the *arr API. Within one format, every `required: true` condition must match. Conditions of the same type that aren't required are alternatives, and different types must all match. Regexes are case-insensitive. `{LANG}` is the language name and `{TOKENS}` its title tokens from the section 5.10 table (Hindi: `hindi|hin`).

```yaml
# Language ids: resolve by name from GET /api/v3/language (Radarr Hindi 26, Sonarr Hindi 27, both: Original -2).
- name: "Lang · {LANG} + Original (named)"
  specifications:
    - {implementation: ReleaseTitleSpecification, required: true,  negate: false, value: '\b({TOKENS})\b'}
    - {implementation: LanguageSpecification,     required: true,  negate: false, value: Original}

- name: "Lang · {LANG} + Dual/Multi tag"          # only when the original is not parsed
  specifications:
    - {implementation: ReleaseTitleSpecification, required: true,  negate: false, value: '\b({TOKENS})\b'}
    - {implementation: ReleaseTitleSpecification, required: true,  negate: false, value: '\b(dual[ ._-]?audio|multi[ ._-]?audio|dual|multi)\b'}
    - {implementation: LanguageSpecification,     required: true,  negate: true,  value: Original}

- name: "Lang · {LANG} original (untagged)"        # left out when the app does not know {LANG}
  specifications:
    - {implementation: LanguageSpecification,     required: true,  negate: false, value: "{LANG}"}
    - {implementation: ReleaseTitleSpecification, required: true,  negate: true,  value: '\b({TOKENS})\b'}

- name: "Lang · {LANG} only (original missing)"
  specifications:
    - {implementation: ReleaseTitleSpecification, required: true,  negate: false, value: '\b({TOKENS})\b'}
    - {implementation: ReleaseTitleSpecification, required: true,  negate: true,  value: '\b(dual[ ._-]?audio|multi[ ._-]?audio|dual|multi)\b'}
    - {implementation: LanguageSpecification,     required: true,  negate: true,  value: Original}

- name: "Lang · Not Original or {LANG}"
  specifications:
    - {implementation: LanguageSpecification,     required: true,  negate: true,  value: Original}
    - {implementation: LanguageSpecification,     required: true,  negate: true,  value: "{LANG}"}
    - {implementation: ReleaseTitleSpecification, required: true,  negate: true,  value: '\b({TOKENS})\b'}
    - {implementation: ReleaseTitleSpecification, required: true,  negate: true,  value: '\b(dual[ ._-]?audio|multi[ ._-]?audio|dual|multi)\b'}

- name: "Junk · Line/cam audio"                   # "line" only counts next to a language token or "audio"
  specifications:
    - {implementation: ReleaseTitleSpecification, required: true, negate: false,
       value: '\b({TOKENS})[ ._-]*\(?[ ._-]*(line|cleaned|clean)\b|\b(line|cleaned|clean)[ ._-]*(audio|aud)\b|\bhq[ ._-]?line\b|\b(ai|fan)[ ._-]?dub(bed)?\b'}

- name: "Junk · Cam / PreDVD / S-Print"
  specifications:
    - {implementation: ReleaseTitleSpecification, required: true, negate: false,
       value: '\b(pre[ ._-]?dvd(rip)?|hq[ ._-]?(cam|ts|tc|s[ ._-]?print)|s[ ._-]?print|hd[ ._-]?(cam|ts|tc)|cam[ ._-]?rip|hdts|hdtc|telesync|telecine)\b'}

- name: "Junk · Banned uploaders"                 # list lives in the pack data
  specifications:
    - {implementation: ReleaseTitleSpecification, required: true, negate: false, value: '\b(ozlem)\b'}

- name: "Junk · Commentary editions"
  specifications:
    - {implementation: ReleaseTitleSpecification, required: true, negate: false, value: '\b(rifftrax)\b'}

- name: "Res · 1080p"
  specifications:
    - {implementation: ResolutionSpecification, required: true, negate: false, value: 1080}

- name: "Src · Bluray"                            # WEB-DL and WEBRip: same shape, other source value
  specifications:
    - {implementation: SourceSpecification, required: true, negate: false, value: Bluray}

- name: "Size · Compact band"                     # Radarr only; absolute GB
  specifications:
    - {implementation: SizeSpecification, required: true, negate: false, value: {min: 0, max: 6}}

- name: "Size · Oversized"                        # Radarr only; absolute GB
  specifications:
    - {implementation: SizeSpecification, required: true, negate: false, value: {min: 10, max: 1000}}

# Vendored from TRaSH by trash_id (not redefined here): x265 (HD) as "Eff · HEVC", AV1, DV (w/o HDR fallback),
# BR-DISK, 3D, Extras, Upscaled, Repack/Proper, Repack2, Repack3, Season Pack (Sonarr).
```

Check every regex with Radarr's built-in custom format test and the corpus test from Phase 1 before turning it on.

### Appendix C: profile pack layout

```text
apps/mediaserver/profiles/
├── pack.json                    # pack version, prefixes it owns, upstream TRaSH commit
├── languages.json               # language -> app language name + title tokens (section 5.10)
├── custom_formats/              # blueprint formats; {LANG}/{TOKENS} filled in at apply time
│   ├── lang-plus-original.json
│   ├── lang-dual-tag.json
│   └── ...
├── trash/                       # vendored TRaSH JSON (MIT, with source path + commit)
│   ├── radarr/x265-hd.json
│   ├── radarr/av1.json
│   └── sonarr/season-pack.json
├── profiles/
│   ├── radarr-1080p-compact.json
│   ├── radarr-1080p-family.json
│   ├── sonarr-1080p-compact.json
│   └── sonarr-1080p-family.json
└── quality_definitions/
    ├── radarr.json
    └── sonarr.json
```

Profile file shape. Qualities are listed **highest first**; the tests enforce it.

```json
{
  "name": "1080p Family",
  "requires_language": true,
  "language": "Any",
  "upgrade": {"allowed": true, "until_quality": "HD", "until_score": 4000},
  "min_format_score": 1400,
  "min_upgrade_format_score": 400,
  "qualities": [
    {"group": "HD", "qualities": ["Bluray-1080p", "WEBDL-1080p", "WEBRip-1080p", "HDTV-1080p", "Bluray-720p", "WEBDL-720p", "WEBRip-720p"]}
  ],
  "scores": {
    "Lang · {LANG} + Original (named)": 3000,
    "Lang · {LANG} + Dual/Multi tag": 3000,
    "Res · 1080p": 1000,
    "Lang · {LANG} only (original missing)": 1500,
    "Lang · Not Original or {LANG}": -10000,
    "Eff · HEVC": 150,
    "Size · Oversized": -500
  }
}
```

### Appendix D: evidence excerpts

*Goldfinger*, interactive search on 2026-11-28, top of Radarr's own ranking. Every result was blocked by the dead torrent already in the queue.

```text
#  seed  GB     quality        score  title
0     1  3.22   HDTV-1080p         0  Goldfinger 1964 REPACK MULTi VFi 1080p HDLight AC3 ...   (French, rejected)
2    23  5.17   WEBDL-1080p        0  Goldfinger 1964 1080p NF WEB-DL DDP5 1 Atmos ...          (rejected: 4.8 GB > 4.5 GB max)
5    34  3.58   WEBRip-1080p     250  Agente 007 Missione Goldfinger ... HEVC AAC ITA ENG ...
6     8  5.67   Bluray-1080p   50250  Goldfinger (1964) DS4K 1080p BDRip HEVC [Hindi English] DDP 5.1
14  100  1.87   Bluray-1080p       0  Goldfinger (1964) 1080p BRRip x264 -YTS
35    0  1.40   Bluray-720p    50000  James Bond Goldfinger (1964) 720p BluRay Hindi DD 2.0 Esub   (rejected: "Hardcode subs found: Esub")
39    1  1.02   Bluray-480p    50000  James Bond Goldfinger (1964) BRRip x264 AC3 [Dual Audio] [Hindi-   (rejected: original language wanted, found Hindi)
```

*Slow Horses* season 1 search: `Slow.Horses.S01E03.1080p.HEVC.x265-MeGusta[TGx]` is listed with **31 seeders** on 1337x. In qBittorrent the same torrent has had 0 seeds and 0 peers in the swarm for 6 days.

### Appendix E: Decluttarr for other setups

Not used on this server (see section 8.7). It is documented for people who would rather run an off-the-shelf cleaner. Key names follow the Decluttarr v2 README; check them against its `config_example.yaml`.

```yaml
general:
  test_run: true            # start in dry run; flip to false after a few days
  timer: 10                 # minutes between runs
  protected_tag: keep
  private_tracker_handling: skip
jobs:
  remove_metadata_missing: {max_strikes: 12}   # about 2 h
  remove_stalled:          {max_strikes: 72}   # about 12 h
  remove_slow:             {min_speed: 20, max_strikes: 144}
  remove_failed_imports:   {message_patterns: ["*No files found are eligible*", "*sample*"]}
  remove_bad_files: {}
  search_unmet_cutoff:     {min_days_between_searches: 14, max_concurrent_searches: 2}
```

Its strikes live in memory and it doesn't know about sleep. If you use it, turn off the Download Doctor's replacement rules. **Never run two cleaners at once.**

### Appendix F: Live baseline (2026-11-28)

The live configuration as captured, for reference and rollback. Secrets were never read into this file. Values come from the read-only snapshot described in [Appendix J](#appendix-j-observing-the-live-server-safely).

**F.1 Host and stack**

| Item | Value |
| :--- | :--- |
| OS | Ubuntu 26.04.1 LTS, kernel 7.0.0-38 |
| Tools on the host | Samba 4.23.6 (`smbstatus --json` available), jq 1.8.1, Python 3.14.4 |
| CPU / RAM | Intel i3-4005U (Haswell, 2 cores / 4 threads, HD 4400 with `/dev/dri/renderD128`); 7.2 GiB RAM, about 3.8 GiB available |
| Disks | OS logical volume 232 GB (65 GB used); media disk at `/mnt/hdd` 916 GB (776 GB used, 132 GB free) |
| Compose project | `mediaserver`, from `/opt/homelab-blueprint/apps/mediaserver/docker-compose.yml` |
| Paths | `CONFIG_DIR=/srv/homelab/appdata/mediaserver`, `DATA_DIR=/mnt/hdd/data`, `COMPOSE_PROFILES=byparr` |
| Seerr | `NODE_OPTIONS` includes the TMDB interceptor (`ENABLE_TMDB_BYPASS` on) |
| Images | qbittorrent `5.3.0_v2.1.2-ls487`, prowlarr `3.0.2.5780-ls169`, radarr `7.0.3.10918-ls328`, sonarr `4.0.20.3014-ls5`, bazarr `v1.6.2-ls372`, jellyfin `12.4ubu2604-ls59`, seerr `v3.5.2`, byparr `3.1.1` |
| RAM per container | photo server 827 MB, photo database 389 MB, Byparr 353 MB, Jellyfin 351 MB, Sonarr 214 MB, Bazarr 209 MB, Radarr 198 MB, Prowlarr 179 MB, Seerr 151 MB, qBittorrent 22 MB, Dozzle 13 MB |

**F.2 Files, schedules and keys**

| What | Where |
| :--- | :--- |
| API keys (Radarr, Sonarr, Prowlarr) and qBittorrent login | `/etc/homelab/mediaserver.env` (root-only). Also each app's `config.xml` (`ApiKey`) |
| Wizard answers | `/etc/homelab/config.json` |
| Control Hub token and env | `/etc/homelab/control-hub.token`, `/etc/homelab/control-hub.env` |
| Bazarr API key | `<appdata>/bazarr/config/config.yaml` (`auth.apikey`) |
| Seerr API key and settings | `<appdata>/seerr/settings.json` (`main.apiKey`) |
| qBittorrent config | `<appdata>/qbittorrent/qBittorrent/qBittorrent.conf` |
| Recyclarr (outside the repo) | Binary in the server user's `~/bin`; config `~/.config/recyclarr/configs/mediaserver-profiles.yml` (identical to the repo example); log `~/.config/recyclarr/logs/cron.log`. User crontab: `30 6 * * * /usr/bin/flock -n /tmp/recyclarr.lock <home>/bin/recyclarr sync --config <home>/.config/recyclarr/configs/mediaserver-profiles.yml >> <home>/.config/recyclarr/logs/cron.log 2>&1` |
| Auto-import | `/etc/cron.d/mediaserver-autoimport`, every 3 minutes |
| Media settings backup | `/etc/cron.d/media-backup`, 21:30 daily |
| Sleep Guard | Suspend at 00:00 for 6 h (RTC wake); log `/var/log/server-suspend.log`; post-wake hook `/etc/server-suspend.d/50-mediaserver.sh`. On 2026-11-28 the 00:00 suspend was deferred by an SMB session |

**F.3 Quality profiles and custom formats**

**Radarr quality profiles** (API order is lowest to highest):

| ID | Name | Used by | Cutoff | Min score | Upgrade-until score | Min increment | Language | Allowed qualities, low to high | Scores |
| ---: | :--- | ---: | :--- | ---: | ---: | ---: | :--- | :--- | :--- |
| 1 | Any | 0 | Bluray-480p | 0 | 0 | 1 | Original | WORKPRINT < CAM < TELESYNC < TELECINE < REGIONAL < DVDSCR < SDTV < DVD < DVD-R < [WEB 480p: WEBDL-480p, WEBRip-480p] < Bluray-480p < Bluray-576p < HDTV-720p < [WEB 720p: WEBDL-720p, WEBRip-720p] < Bluray-720p < HDTV-1080p < [WEB 1080p: WEBDL-1080p, WEBRip-1080p] < Bluray-1080p < Remux-1080p < HDTV-2160p < [WEB 2160p: WEBDL-2160p, WEBRip-2160p] < Bluray-2160p < Remux-2160p < BR-DISK | Hindi Audio +100 |
| 2 | SD | 0 | Bluray-480p | 0 | 0 | 1 | Original | WORKPRINT < CAM < TELESYNC < TELECINE < REGIONAL < DVDSCR < SDTV < DVD < [WEB 480p: WEBDL-480p, WEBRip-480p] < Bluray-480p < Bluray-576p | Hindi Audio +100 |
| 3 | HD-720p | 0 | Bluray-720p | 0 | 0 | 1 | Original | HDTV-720p < [WEB 720p: WEBDL-720p, WEBRip-720p] < Bluray-720p | Hindi Audio +100 |
| 4 | HD-1080p | 0 | Bluray-1080p | 0 | 1000 | 1 | Original | HDTV-1080p < [WEB 1080p: WEBDL-1080p, WEBRip-1080p] < Bluray-1080p < Remux-1080p | Hindi Audio +1000 |
| 5 | Ultra-HD | 0 | Remux-2160p | 0 | 0 | 1 | Original | HDTV-2160p < [WEB 2160p: WEBDL-2160p, WEBRip-2160p] < Bluray-2160p < Remux-2160p | Hindi Audio +100 |
| 6 | HD - 720p/1080p | 0 | Bluray-720p | 0 | 0 | 1 | Original | HDTV-720p < [WEB 720p: WEBDL-720p, WEBRip-720p] < Bluray-720p < HDTV-1080p < [WEB 1080p: WEBDL-1080p, WEBRip-1080p] < Bluray-1080p < Remux-1080p | Hindi Audio +100 |
| 7 | 1080p Balanced | 0 | group 1001 | 200000 | 1000000 | 1 | Hindi | [1080p Balanced: SDTV, HDTV-720p, HDTV-1080p, DVD, WEBDL-480p, Bluray-480p, Bluray-576p, WEBRip-720p, WEBDL-720p, Bluray-720p, WEBDL-1080p, Bluray-1080p] | — |
| 8 | 1080p Balanced (Hindi) | 1 | group 1001 | 200000 | 1000000 | 1 | Hindi | [1080p Balanced: SDTV, HDTV-720p, HDTV-1080p, DVD, WEBDL-480p, Bluray-480p, Bluray-576p, WEBRip-720p, WEBDL-720p, Bluray-720p, WEBDL-1080p, Bluray-1080p] | Hindi Audio +10000 |
| 9 | 1080p Compact | 75 | WEBDL-1080p | 0 | 10000 | 1 | Original | Bluray-1080p < WEBRip-1080p < WEBDL-1080p < HDTV-1080p | x265 (HD) +250, Hindi Audio +50000 |
| 10 | 720p Compact | 0 | WEBDL-720p | 0 | 0 | 1 | Original | Bluray-720p < WEBRip-720p < WEBDL-720p < HDTV-720p | x265 (HD) +250, Hindi Audio +50000 |
| 11 | 4K Compact | 0 | WEBDL-2160p | 0 | 0 | 1 | Original | Bluray-2160p < WEBRip-2160p < WEBDL-2160p < HDTV-2160p | x265 (HD) +250, Hindi Audio +50000 |

**Radarr custom formats:**

| ID | Name | Rename tag | Conditions |
| ---: | :--- | :--- | :--- |
| 1 | Hindi Audio | False | ReleaseTitle = `(?i)\b(hindi\|hin\|dual[- .]?(audio)?)\b` |
| 146 | x265 (HD) | False | ReleaseTitle (required) = `[xh][ ._-]?265\|\bHEVC(\b\|\d)`; Resolution (required, negated) = `2160` |

**Sonarr quality profiles** (API order is lowest to highest):

| ID | Name | Used by | Cutoff | Min score | Upgrade-until score | Min increment | Allowed qualities, low to high | Scores |
| ---: | :--- | ---: | :--- | ---: | ---: | ---: | :--- | :--- |
| 1 | Any | 0 | SDTV | 0 | 0 | 1 | SDTV < [WEB 480p: WEBRip-480p, WEBDL-480p] < DVD < Bluray-480p < Bluray-576p < HDTV-720p < HDTV-1080p < [WEB 720p: WEBRip-720p, WEBDL-720p] < Bluray-720p < [WEB 1080p: WEBRip-1080p, WEBDL-1080p] < Bluray-1080p | — |
| 2 | SD | 0 | SDTV | 0 | 0 | 1 | SDTV < [WEB 480p: WEBRip-480p, WEBDL-480p] < DVD < Bluray-480p < Bluray-576p | — |
| 3 | HD-720p | 0 | HDTV-720p | 0 | 0 | 1 | HDTV-720p < [WEB 720p: WEBRip-720p, WEBDL-720p] < Bluray-720p | — |
| 4 | HD-1080p | 0 | HDTV-1080p | 0 | 0 | 1 | HDTV-1080p < [WEB 1080p: WEBRip-1080p, WEBDL-1080p] < Bluray-1080p | — |
| 5 | Ultra-HD | 0 | HDTV-2160p | 0 | 0 | 1 | HDTV-2160p < [WEB 2160p: WEBRip-2160p, WEBDL-2160p] < Bluray-2160p | — |
| 6 | HD - 720p/1080p | 0 | HDTV-720p | 0 | 0 | 1 | HDTV-720p < HDTV-1080p < [WEB 720p: WEBRip-720p, WEBDL-720p] < Bluray-720p < [WEB 1080p: WEBRip-1080p, WEBDL-1080p] < Bluray-1080p | — |
| 7 | 1080p Balanced | 2 | group 1001 | 200000 | 1000000 | 1 | [1080p Balanced: SDTV, HDTV-720p, HDTV-1080p, DVD, WEBDL-480p, Bluray-480p, Bluray-576p, WEBRip-720p, WEBDL-720p, Bluray-720p, WEBDL-1080p, Bluray-1080p] | — |
| 8 | 1080p Balanced (Hindi) | 0 | group 1001 | 200000 | 1000000 | 1 | (same group) | — |
| 9 | 1080p Compact | 25 | WEBDL-1080p | 0 | 10000 | 1 | Bluray-1080p < WEBRip-1080p < WEBDL-1080p < HDTV-1080p | x265 (HD) +250, Multi Episode +50, Season Complete +100, Hindi Audio +50000 |
| 10 | 720p Compact | 0 | WEBDL-720p | 0 | 0 | 1 | Bluray-720p < WEBRip-720p < WEBDL-720p < HDTV-720p | Multi Episode +50, Season Complete +100, x265 (HD) +250, Hindi Audio +50000 |
| 11 | 4K Compact | 0 | WEBDL-2160p | 0 | 0 | 1 | Bluray-2160p < WEBRip-2160p < WEBDL-2160p < HDTV-2160p | Multi Episode +50, Season Complete +100, x265 (HD) +250, Hindi Audio +50000 |

**Sonarr custom formats:**

| ID | Name | Rename tag | Conditions |
| ---: | :--- | :--- | :--- |
| 131 | Hindi Audio | True | Language = `27` (Hindi); ReleaseTitle = `(?i)\b(hindi\|hin\|dual[- .]?(audio)?)\b` |
| 140 | x265 (HD) | False | ReleaseTitle (required) = `[xh][ ._-]?265\|\bHEVC(\b\|\d)`; Resolution (required, negated) = `2160` |
| 149 | Season Complete | False | ReleaseTitle = `(?i)(season.complete\|season.pack\|complete.season\|full.season)` |
| 150 | Multi Episode | False | ReleaseTitle = `(?i)(s\d{2}e\d{2}).*(s\d{2}e\d{2})` |

The pack's `migrate` step must **update profile 9 in place** (keep the ID), because Seerr points at profile ID 9 in both apps. Then it moves the titles on profiles 7 and 8 (2 series, 1 movie) to 9 and deletes 7 and 8.

**F.4 Size limits (MB/min), current**

| Quality | Radarr min | Radarr preferred | Radarr max | Sonarr min | Sonarr preferred | Sonarr max |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| HDTV-720p | 0 | 8 | 20 | 0 | 5 | 15 |
| WEBRip-720p | 0 | 10 | 25 | 0 | 7 | 20 |
| WEBDL-720p | 0 | 10 | 25 | 0 | 7 | 20 |
| Bluray-720p | 0 | 12 | 28 | 0 | 8 | 22 |
| HDTV-1080p | 0 | 15 | 32 | 0 | 10 | 25 |
| WEBRip-1080p | 0 | 20 | 42 | 0 | 14 | 35 |
| WEBDL-1080p | 0 | 20 | 42 | 0 | 14 | 35 |
| Bluray-1080p | 0 | 25 | 50 | 0 | 18 | 40 |
| Remux-1080p | 102 | — | — | — | — | — |
| HDTV-2160p | 0 | 40 | 80 | 0 | 30 | 60 |
| WEBRip-2160p | 0 | 55 | 120 | 0 | 40 | 85 |
| WEBDL-2160p | 0 | 55 | 120 | 0 | 40 | 85 |
| Bluray-2160p | 0 | 70 | 140 | 0 | 50 | 100 |
| Remux-2160p | 187.4 | — | — | — | — | — |

**F.5 Prowlarr and indexers**

| Prowlarr ID | Indexer | Definition | Priority in Prowlarr | Tags | Sync profile | Queries / grabs (Prowlarr stats) | Synced to |
| ---: | :--- | :--- | ---: | :--- | :--- | :--- | :--- |
| 4 | 1337x | `1337x` | 25 | byparrtag | Standard | 98 / 30 | Radarr, Sonarr |
| 5 | EZTV | `eztv` | 25 | byparrtag | Standard | 8 / 0 | Sonarr |
| 3 | LimeTorrents | `limetorrents` | 25 | — | Standard | 8 / 20 | Sonarr |
| 2 | The Pirate Bay | `thepiratebay` | 45 | — | Standard | 36 / 5 | Radarr, Sonarr |
| 1 | YTS | `yts` | 25 | — | Standard | 29 / 1 | Radarr |

- **App links.**
  - Radarr: base `http://radarr:7878`, Prowlarr URL `http://prowlarr:9696`, sync level **addOnly**, categories 2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060, 2070, 2080, 2090.
  - Sonarr: base `http://sonarr:8989`, **addOnly**, categories 5000, 5010, 5020, 5030, 5040, 5045, 5050, 5090; anime 5070.
- **App profile "Standard" (ID 1):** RSS, automatic and interactive search on; minimum seeders **1**.
- **Proxy "Byparr"** (FlareSolverr type): `http://byparr:8191`, timeout 60 s, tag `byparrtag` (ID 2).
- **In Radarr and Sonarr**, every indexer has priority 25 and minimum seeders 1, with no seed ratio or time set. Categories:

  | App | Indexer | Categories | Anime categories |
  | :--- | :--- | :--- | :--- |
  | Radarr | 1337x | 2000, 2070, 2030, 2010, 2040, 2060, 2045 | — |
  | Radarr | The Pirate Bay | 2000, 2020, 2040, 2060, 2030, 2045 | — |
  | Radarr | YTS | 2000, 2040, 2045, 2060 | — |
  | Sonarr | 1337x | 5000, 5040, 5030 | 5070 |
  | Sonarr | EZTV | 5000 | — |
  | Sonarr | LimeTorrents | 5000 | 5070 |
  | Sonarr | The Pirate Bay | 5000, 5050, 5040, 5045 | — |

**F.6 Download clients and download handling** (both apps unless noted)

- **qBittorrent client:**
  - host `qbittorrent:8080`, category `radarr` / `tv-sonarr`, client priority 1;
  - recent and older priority 0 (last), initial state 0 (start), sequential off, first/last off, content layout 0 (default);
  - remove completed **on**, remove failed **on**.
- **"Usenet Blackhole" client:** enabled, priority 1, folders `/data/media/blackhole/movies/` and `/data/media/blackhole/tv/`. No usenet indexers exist.
- **Download handling:**
  - completed download handling on; check every 1 minute (Radarr);
  - Redownload Failed on, including from interactive search;
  - working folders `_UNPACK_|_FAILED_`.
- **Delay profile (ID 1, default):** usenet and torrent enabled, preferred torrent, both delays 360 minutes, both bypasses off, minimum score 0.
- **Indexer settings:**
  - Radarr: minimum age 0, maximum size 0 (unlimited), retention 0, RSS every 30 minutes, prefer indexer flags off, availability delay 0, allow hardcoded subs off, whitelist empty.
  - Sonarr: RSS every 15 minutes, maximum size 0.

**F.7 Media management, naming and metadata**

- **Both apps:** hardlinks on; propers "do not prefer"; media info on; import extra files on (`srt,ass,ssa,vtt`); recycle bin **none** (cleanup 7 days); minimum free space 100 MB; delete empty folders on; rescan "always".
- **Sonarr also:** episode title required "always"; create empty series folders on.
- **Radarr naming:**
  - movie: `{Movie CleanTitle} {(Release Year)} {tmdb-{TmdbId}} {edition-{Edition Tags}} {[Custom Formats]}{[Quality Full]}{[MediaInfo 3D]}{[MediaInfo VideoDynamicRangeType]}{[Mediainfo AudioCodec}{ Mediainfo AudioChannels]}{[Mediainfo VideoCodec]}{-Release Group}`
  - folder: `{Movie CleanTitle} ({Release Year})`
- **Sonarr naming:**
  - episode: `{Series TitleYear} - S{season:00}E{episode:00} - {Episode CleanTitle} {[Custom Formats]}{[Quality Full]}{[MediaInfo VideoDynamicRangeType]}{[Mediainfo AudioCodec}{ Mediainfo AudioChannels]}{[MediaInfo VideoCodec]}{-Release Group}`
  - season folder: `Season {season:0}`; series folder: `{Series TitleYear}`
- **Metadata:**
  - Radarr "Kodi (XBMC) / Emby" is **disabled**. Its fields: movie metadata on, `useMovieNfo` off (so `<file>.nfo`), language English, metadata URL off, add collection name on, images on. Emby (Legacy), Roksbox and WDTV are disabled.
  - Sonarr "Kodi (XBMC) / Emby" is **enabled**: series metadata, episode guide, series URL, episode metadata, episode thumbs, and series, season and episode images. Kometa, Plex, Roksbox and WDTV are disabled.

**F.8 qBittorrent 5.3.0 (Web API 2.16.2)**

| Preference | Value |
| :--- | :--- |
| `listen_port`, `random_port`, `upnp` | 6881, false, false |
| `dht`, `pex`, `lsd`, `encryption`, `anonymous_mode` | true, true, true, 0 (allow), false |
| `max_connec`, `max_connec_per_torrent`, `max_uploads`, `max_uploads_per_torrent` | 500, 100, 20, 4 |
| `queueing_enabled`, `max_active_downloads`, `max_active_torrents`, `max_active_uploads` | true, 99999, 100000, 50 |
| `dont_count_slow_torrents`, slow thresholds (dl / ul KiB/s, inactive timer s) | false, 2 / 2, 60 |
| `add_trackers_enabled`, `add_trackers_from_url_enabled` | false, false (URL empty) |
| `announce_to_all_trackers`, `announce_to_all_tiers` | false, true |
| `max_ratio_enabled` / `max_ratio` | true / 0.1 |
| `max_seeding_time_enabled` / `max_seeding_time` (min) | true / 1 |
| `max_inactive_seeding_time_enabled` | false |
| `max_ratio_act` | 0 (stop) |
| `dl_limit`, `up_limit`, `alt_dl_limit`, `alt_up_limit`, `scheduler_enabled` | 0, 0, 10240, 10240, false. The Control Hub treats the alternative limits as bytes/s |
| `save_path`, `temp_path_enabled`, `temp_path` | `/data/torrents`, true, `/data/torrents/incomplete` |
| `auto_tmm_enabled`, `torrent_content_layout`, `torrent_stop_condition`, `add_stopped_enabled` | true, Original, None, false |
| `excluded_file_names_enabled` / list | true / `*.exe *.bat *.cmd *.scr *.lnk *.pif *.com *.vbs` |
| `reannounce_when_address_changed`, `enable_embedded_tracker`, `ip_filter_enabled`, `proxy_type` | false, false, false, None |
| `memory_working_set_limit`, `disk_cache`, `async_io_threads`, `hashing_threads` | 512 MiB, -1 (auto), 10, 1 |

- **Categories:** `movies` and `radarr` both point to `/data/torrents/movies`; `tv` and `tv-sonarr` both point to `/data/torrents/tv`. No tags.
- **Transfer:** connection status `connected`, 363 DHT nodes, no external IPv6 (Docker bridge).

**F.9 Bazarr 1.6.2**

- **Providers:** `opensubtitlescom`, `yifysubtitles`, `subdl`.
- **Language profile 1 "English":** English always; Hindi only when the audio is Hindi; no cutoff. It is the default for series and movies.
- **Settings:**
  - use embedded subs on; PGS, VobSub and ASS not ignored; adaptive searching on;
  - upgrade subs **off**;
  - minimum score 90 (series) / 70 (movies); wanted search every 6 h;
  - subfolder `current`; single language off.
- **SignalR** to Sonarr and Radarr is live.
- **Missing subtitles:** 18 episodes, 7 movies.

**F.10 Seerr 3.5.2**

- **Radarr:** default server, profile ID 9 `1080p Compact`, root `/data/media/movies`, minimum availability `released`, sync on.
- **Sonarr:** default server, profile ID 9 `1080p Compact`, anime profile `HD-1080p`, root `/data/media/tv`, sync off.
- **General:** media server Jellyfin; local login on; partial requests on.
- **Notification agents:** webhook only.

**F.11 Jellyfin**

- **Transcoding:** hardware acceleration `none`, even though the VAAPI device is set to `/dev/dri/renderD128`; the device isn't passed to the container.
  - Decoding list: h264, vc1. 10-bit HEVC decode allowed.
  - Hardware encoding on, HEVC encoding off, tone mapping off, throttling off.
- **Libraries `Movies` and `Shows`:** trickplay and chapter images off, `SaveLocalMetadata` off, automatic refresh 0.

**F.12 Control Hub env (names only)**

- **Present:**
  - `CONTROL_HUB_HOST/PORT/TOKEN`, `ACTIVE_NIC`, `LINK_SPEED_MBPS`, `HDD_DATA`, `HDD_MEMORIES`, `TZ`;
  - `QBITTORRENT_URL/USER/PASS`, `PROWLARR_URL`, `PROWLARR_API_KEY`;
  - `TV_UPDATER_*`, `TV_AUTOUPDATER_*`;
  - `SUSPEND_SKIP_FILE`, `SUSPEND_OVERRIDE_FILE`, `SUSPEND_CONFIG_FILE`, `SUSPEND_CRON_FILE`, `SERVER_SUSPEND_LOG_FILE`;
  - `BACKUP_LOG_FILE`, `BACKUP_DIR`, `IMMICH_ML_LOG_FILE`, `RECYCLARR_LOG_FILE`, `SPEEDTEST_BIN`, `SPEEDTEST_CACHE_FILE`, `GDRIVE_REMOTE`, `MEDIA_BACKUP_SCRIPT`.
- **Missing:** `RADARR_URL/API_KEY`, `SONARR_URL/API_KEY`, `SEERR_URL/API_KEY`, `JELLYFIN_URL/API_KEY`.

**F.13 Library and history**

- **Movies:** 76 (52 with files, 163 GB). Originals: 68 English, 8 Hindi. Minimum availability: `released` 58, `tba` 18. Missing: the 17 queued Bond films plus *Bond 26*, *Avengers: Doomsday*, *Clayface*, and unmonitored *Pulp Fiction*, *Eclipse*, *Breaking Dawn – Part 1*, *The Dark Knight*.
- **Files:**
  - Quality: WEBDL-1080p 28, HDTV-1080p 7, Bluray-1080p 7, HDTV-720p 3, WEBDL-720p 3, WEBRip-1080p 3, SDTV 1.
  - Codecs: h264 19, x264 15, x265 12, h265 5, HEVC 1.
  - Audio sets: eng 20, und 12, hin/eng 8, ita/eng 5, hin 2, others 5.
- **Series:** 27 (347 GB), all monitored.
  - Nine have no monitored aired episodes: *Silo*, *Reacher*, *Harry Potter*, *PLUR1BUS*, *Modern Family*, *Dark*, *House*, *Love to Hate You*, *House of the Dragon*.
  - On `1080p Balanced`: *Bhay* (0/8) and *Khauf* (8/8).
- **File deletions in the history window:** movies 32 missing from disk and 11 upgrades; TV 133 missing from disk and 12 upgrades.

**F.14 Stale or legacy items on the server**

Do not delete these without the owner's confirmation:
- in appdata: a legacy `docker-compose.yml` (old `/opt/mediaserver/config` paths, `latest` tags), `recyclarr/recyclarr.yml` (unused, unsupported inline syntax), an empty `jellyseerr` file, `jellyseerr_backup_20261018_093550/` and `arr-backups/`;
- `/data/media/blackhole/`;
- a stray Nova resume file in `/data/torrents/`.

### Appendix G: API cheat-sheet

**Authentication:**

| App | How |
| :--- | :--- |
| Radarr, Sonarr (`/api/v3`), Prowlarr (`/api/v1`) | Header `X-Api-Key` |
| Bazarr | Header `X-API-KEY` |
| Seerr | Header `X-Api-Key` |
| Jellyfin | `X-Emby-Token` |
| qBittorrent (`/api/v2`) | `POST /auth/login` (form) returns 204 and a `QBT_SID` cookie on 5.x. Repeated failed logins trigger a temporary IP ban. 5.2+ also supports an API key (Appendix K) |

**Radarr and Sonarr endpoints** used by the plan:

| Purpose | Endpoint |
| :--- | :--- |
| Profiles | `GET /qualityprofile`, `PUT /qualityprofile/{id}` (send the whole object) |
| Custom formats | `GET/POST/PUT/DELETE /customformat`; `GET /customformat/schema` (allowed values for Source, Language, Resolution, Release Type) |
| Sizes | `GET /qualitydefinition`; `PUT /qualitydefinition/update` (bulk) |
| Languages | `GET /language` |
| Settings | `GET/PUT /config/indexer`, `/config/mediamanagement`, `/config/downloadclient`, `/config/naming`; `GET/PUT /delayprofile/{id}`, `/metadata/{id}`, `/downloadclient/{id}` |
| Queue | `GET /queue?pageSize=…&includeMovie=true` (Sonarr: `includeSeries=true&includeEpisode=true`); `DELETE /queue/{id}?removeFromClient=true&blocklist=true&skipRedownload=false`; `DELETE /queue/bulk` with body `{"ids": […]}` and the same query parameters |
| Searching | `GET /release?movieId=` · `?seriesId=&seasonNumber=` · `?episodeId=` (ranked, with rejections; grabs nothing); `POST /release` with `{guid, indexerId}` grabs a cached result |
| Commands | `POST /command` with `MoviesSearch {movieIds}`, `SeasonSearch {seriesId, seasonNumber}`, `EpisodeSearch {episodeIds}`, `RssSync`, `ManualImport {importMode, files}` (see `auto_import.py`) |
| Import helpers | `GET /manualimport?downloadId=…` |
| Wanted | `GET /wanted/cutoff`, `GET /wanted/missing` |
| Blocklist | `GET/DELETE /blocklist`, `DELETE /blocklist/bulk` |
| Library | `GET /movie`, `GET /series`, `GET /episodefile?seriesId=`, `PUT /movie/editor {movieIds, qualityProfileId}`, `PUT /series/editor {seriesIds, qualityProfileId}` |
| Other | `GET /history`, `GET /health`, `GET /system/status` |

**Prowlarr:**
- `GET/PUT /applications/{id}` (`syncLevel: "fullSync"`)
- `GET/POST/PUT /appprofile` (`minimumSeeders`)
- `GET/PUT /indexer/{id}` (`priority`, `appProfileId`)
- `GET /indexerstats`
- `POST /command {"name": "ApplicationIndexerSync"}`
- `POST /indexer/testall`

**qBittorrent:**
- `GET /app/preferences`, `POST /app/setPreferences` (form field `json=`)
- `GET /torrents/info?filter=all`, `GET /torrents/trackers?hash=`, `GET /torrents/properties?hash=`
- `POST /torrents/reannounce`, `POST /torrents/addTags`
- `POST /torrents/stop|start` (5.x; `pause|resume` on 4.x)
- `GET /transfer/info` (`connection_status`, `dht_nodes`)

**Payload shapes:**

```json
{"name": "Eff · HEVC", "includeCustomFormatWhenRenaming": false,
 "specifications": [
   {"name": "x265/HEVC", "implementation": "ReleaseTitleSpecification", "negate": false, "required": true,
    "fields": [{"name": "value", "value": "[xh][ ._-]?265|\\bHEVC(\\b|\\d)"}]},
   {"name": "Not 2160p", "implementation": "ResolutionSpecification", "negate": true, "required": true,
    "fields": [{"name": "value", "value": 2160}]}]}
```

- **Condition fields:**
  - Language: `value` (language ID) plus `exceptLanguage` (bool).
  - Resolution: `value` (int).
  - Source and Release Type: `value` (enum int; resolve by name from `/customformat/schema`).
  - Size: `min` and `max` in GB (min exclusive, max inclusive). For Sonarr releases the size passed in may be the whole season pack (Appendix K).
- **Quality profile object:**
  - `items` lists **every** quality, lowest to highest; disallowed ones carry `allowed: false`.
  - Groups use IDs from 1000 upward, with their own `name`, `allowed` and `items`.
  - `cutoff` is a quality ID or group ID.
  - `formatItems` is `[{format, name, score}]`; `minFormatScore`, `cutoffFormatScore` and `minUpgradeFormatScore` are plain fields.
  - Radarr also has `language` (`{"id": -1}` = Any).
- **Language IDs:** `Any` -1, `Original` -2, English 1. Hindi is **26 in Radarr and 27 in Sonarr**. Radarr: Tamil 43, Telugu 45, Malayalam 48, Kannada 49, Bengali 34, Marathi 52. Sonarr has Tamil 43 and Malayalam 29 but **no Telugu or Kannada**, so those use title tokens only.
- **Quality IDs:** resolve by name from `/qualitydefinition`; don't hard-code them.
- **Matching:** qBittorrent hashes are lower case and the apps' `downloadId` is upper case. A Sonarr season pack appears as one queue record per episode, all sharing one `downloadId`.
- **qBittorrent states:**
  - downloading side: `metaDL`, `forcedMetaDL`, `stalledDL`, `downloading`, `forcedDL`, `queuedDL`, `stoppedDL` (`pausedDL` on 4.x), `checkingDL`;
  - errors: `error`, `missingFiles`;
  - seeding side: `uploading`, `stalledUP`, `forcedUP`, `queuedUP`, `stoppedUP`, `checkingUP`;
  - other: `moving`, `checkingResumeData`.
- **qBittorrent preferences the plan sets:**
  - trackers: `add_trackers_from_url_enabled`, `add_trackers_url`;
  - seeding: `max_ratio_enabled`/`max_ratio`, `max_seeding_time_enabled`/`max_seeding_time` (minutes), `max_inactive_seeding_time_enabled`/`max_inactive_seeding_time` (minutes), keep `max_ratio_act` 0;
  - queue: `max_active_downloads`, `max_active_torrents`, `max_active_uploads`, `dont_count_slow_torrents`, `slow_torrent_dl_rate_threshold`, `slow_torrent_ul_rate_threshold`, `slow_torrent_inactive_timer`;
  - scheduler: `scheduler_enabled`, `schedule_from_hour/min`, `schedule_to_hour/min`, `scheduler_days` (0 = every day), `alt_dl_limit`, `alt_up_limit`;
  - other: `reannounce_when_address_changed`, `excluded_file_names_enabled`/`excluded_file_names` (newline-separated).
- **Samba:** `smbstatus --json` (Samba 4.23 here) returns sessions, tree connects and open files. The Control Hub currently runs `sudo -n /usr/bin/smbstatus -S`, and sudoers allows exactly that, so new arguments need a new sudoers line.

**Gotchas:**
- The Servarr wiki renders with JavaScript, so it reads as empty to fetch tools; use the source code instead.
- Radarr 7 and Sonarr 4 removed `/restriction`; use release profiles or custom formats.
- Custom-format regexes are case-insensitive.
- Within one custom format, conditions of the same type that aren't required are alternatives, and different types must all match.
- Interactive-search results expire after about 30 minutes, so grab soon after searching.

### Appendix H: Release-title test corpus

Real titles seen on 2026-11-28 (plus marked synthetic ones). The Phase 1 corpus test must reproduce the "Expected" column with Hindi as the chosen language. *Dual* means exactly one of `Lang · Hindi + Original (named)` / `Lang · Hindi + Dual/Multi tag` matches, never both.

| # | Title | Source | Expected |
| ---: | :--- | :--- | :--- |
| 1 | `Goldfinger (1964) DS4K 1080p BDRip HEVC [Hindi English] DDP 5.1 – PeruGuy` | Radarr search | Dual (named), Res · 1080p, Eff · HEVC, Src · Bluray. **Top pick in both profiles** |
| 2 | `Goldfinger 1964 BDRip 1080p Dual Audio [ Hindi 2.0 Eng 5.1] Tariq Qureshi.mkv` | Radarr search | Dual (named; "Eng" parses as English), Res · 1080p, Src · Bluray |
| 3 | `James Bond   Goldfinger (1964) 720p BluRay x264 Dual Audio [English + Hindi]   Bond93   TBI` | Radarr search | Dual (named), Src · Bluray. 720p, so only `1080p Family` takes it |
| 4 | `Goldfinger (1964) \| m-HD \| 720p \| Hindi \| Eng \| BHATTI87` | Radarr search | Dual (named). Parses as HDTV-720p, which is outside the profile group |
| 5 | `James Bond Goldfinger (1964) BRRip x264 AC3 [Dual Audio] [Hindi-` | Radarr search (title cut off by the indexer) | Dual (tag; original not parsed). 480p, so rejected by quality |
| 6 | `James Bond   Goldfinger (1964) 720p BluRay Hindi DD 2.0   Esub ~AbhiSona~` | Radarr search | Lang · Hindi only, Src · Bluray. 720p, so only `1080p Family` takes it (1560). **Must not** be rejected as hardcoded subs once `ESub` is whitelisted |
| 7 | `James Bond 007-GoldFinger(1964)HDTVrip[Dual audio][Eng Hindi]Cur` | Radarr search | Dual (named). Quality unknown, so rejected |
| 8 | `Goldfinger (James Bond 3) (1964) [MicroHD 1080p][DUAL]` | Radarr search | No language match: `DUAL` without a Hindi token is not Hindi |
| 9 | `007 James Bond Goldfinger 1964 1080p BluRay x264 AC3 -Ozlem` | Radarr search | Junk · Banned uploaders, so rejected |
| 10 | `Goldfinger 1964 1080p UHD Bluray OPUS 7 1 SDR AV1-WhiskeyJack` | Radarr search | Compat · AV1, so rejected |
| 11 | `Goldfinger.1964.1080p.BluRay.DV.HDR.X265.DDP.7.1-Chivaman` | Radarr search | Eff · HEVC, Src · Bluray. **Not** Compat · DV (HDR10 is present) |
| 12 | `Goldfinger 1964 1080p UHD BluRay DD 5 1 Atmos DV HDR x265-HiDt` (25.7 GB) | Radarr search | Eff · HEVC, Size · Oversized; also above the size limit |
| 13 | `Goldfinger 1964 1080p NF WEB-DL DDP5 1 Atmos H 264-HDSWEB` (5.17 GB) | Radarr search | Res · 1080p, Src · WEB-DL, Size · Compact band. Rejected by the old 4.5 GB cap, allowed now |
| 14 | `Agente 007   Missione Goldfinger (1964) WEBRip 1080p HEVC AAC ITA ENG SUB ENG` | Radarr search | Eff · HEVC, Src · WEBRip. No language rejection (original present) |
| 15 | `Goldfinger 1964 REPACK MULTi VFi 1080p HDLight AC3 5 1 H264-LiHDL` | Radarr search | Repack/Proper. No language rejection (MULTi tag) |
| 16 | `Goldfinger (1964) 1080p BRRip x264 -YTS` | Radarr search | Res · 1080p, Src · Bluray. Neutral, no penalty |
| 17 | `Goldfinger (1964)-JAMES BOND-Sean Connery-1080p-H264-AC 3 (DolbyDigital-5.1) & nickarad` | The dead torrent in the queue | No source, so HDTV-1080p (untagged): Res · 1080p only. Ranks below tagged releases |
| 18 | `Goldfinger.1964.1080p.BluRay.REMUX-DDB` | Radarr search | Remux, not in profile |
| 19 | `Casino Royale (2006) 1080p Rifftrax 6ch 2ch v2` | Radarr history (imported) | Junk · Commentary editions, so rejected |
| 20 | `Drishyam the Conclusion (2026) 1080p WEBRip 5.1 x264 -YTS` | Radarr history (Hindi original) | Lang · Hindi original (untagged): the language falls back to Hindi, the original, so it scores like a tagged release. Src · WEBRip |
| 21 | `Drishyam 2 (2022) Hindi 1080p WEB-DL DD5.1 ESub` | synthetic (Hindi original) | Dual (named: Hindi is the original), Src · WEB-DL |
| 22 | `Oppenheimer (2023) 1080p BluRay [Hindi DD5.1 + English DD5.1] x264 ESubs` | synthetic | Dual (named), Src · Bluray |
| 23 | `Movie.2023.1080p.AMZN.WEB-DL.DDP5.1.Hindi.English.x264-GRP` | synthetic | Dual (named), Src · WEB-DL |
| 24 | `Kantara (2022) Dual Audio [Hindi + Kannada] 1080p WEB-DL` | synthetic (Kannada original) | Dual (named if Kannada parses, otherwise tag) |
| 25 | `Pushpa 2 (2024) Multi Audio [Hindi Tamil Telugu Malayalam Kannada] 1080p WEB-DL` | synthetic (Telugu original) | Dual (named or tag) |
| 26 | `Vikram (2022) Hindi Dubbed 1080p WEB-DL` | synthetic (Tamil original) | Lang · Hindi only (−500 in Compact, +1500 in Family) |
| 27 | `Movie (2023) Hindi LiNE 1080p HQ HDTC x264` | synthetic | Junk · Line/cam audio and Junk · Cam, so rejected |
| 28 | `Movie 2024 Hindi (Cleaned) 720p PreDVDRip` | synthetic | Junk · Line/cam audio and Junk · Cam, so rejected |
| 29 | `The Thin Red Line (1998) Hindi Dual Audio 1080p BluRay` | synthetic guard | Dual. **Not** Junk · Line |
| 30 | `Ben-Hur (1959) 1080p BluRay x264` | guard | No language match (no Bengali from "Ben") |
| 31 | `Mar Adentro (2004) 1080p WEB-DL` | guard | No language match (no Marathi from "Mar") |
| 32 | `Movie.2023.iTALiAN.1080p.WEB-DL.x264` | synthetic (English original) | Lang · Not Original or Hindi, so rejected |
| 33 | `Movie.2023.German.DL.1080p.BluRay.x264` | synthetic (English original) | No language match (`DL` adds the original), allowed |
| 34 | `Movie.2023.1080p.WEB-DL.DV.H265` | synthetic (DV without HDR10) | Compat · DV without HDR10 fallback (per TRaSH's logic), so rejected |
| 35 | `Slow.Horses.S01E03.1080p.HEVC.x265-MeGusta[TGx]` | Sonarr history (dead) | Eff · HEVC, Res · 1080p (single episode) |
| 36 | `Slow Horses S04 1080p x265-ELiTE` | Sonarr search | Season Pack, Eff · HEVC. Packs rank first |
| 37 | `NCIS.Origins.S01.1080p.x265-ELiTE` | Sonarr history | Season Pack, Eff · HEVC |
| 38 | `The Office US S06E26 Whistleblower 1080p HEVC x265 MeGusta` | Sonarr history | Eff · HEVC |
| 39 | `Slow Horses S01E01-02 [1080p Ita Eng Spa h265 10Bit SubS][MirCrewRelease]` | Sonarr history | Eff · HEVC, multi-episode. No language rejection (English present) |

### Appendix I: Download Doctor test fixtures

The 20 torrents in qBittorrent at the time of the snapshot (2026-11-28, about 11:20 IST). "Idle" is hours since the last activity. The last column is what section 8.2 expects.

| # | State | Progress | Availability | Seeds conn. / swarm | Peers conn. / swarm | Size GB | Added h | Idle h | Category | Name | Expected action |
| ---: | :--- | ---: | ---: | :--- | :--- | ---: | ---: | ---: | :--- | :--- | :--- |
| 1 | forcedDL | 0.1% | 0.00 | 0 / 0 | 0 / 3 | 0.41 | 144.7 | 144.7 | tv-sonarr | Slow.Horses.S01E03.1080p.HEVC.x265-MeGusta[TGx] | Replace: dead swarm |
| 2 | forcedDL | 0.0% | 0.00 | 0 / 0 | 0 / 3 | 0.44 | 144.7 | 144.7 | tv-sonarr | Slow.Horses.S01E05.1080p.HEVC.x265-MeGusta[TGx] | Replace: dead swarm |
| 3 | metaDL | 0.0% | 0.00 | 0 / 1 | 0 / 1 | 0.00 | 144.7 | 144.7 | tv-sonarr | Slow.Horses.S01E06.1080p.HEVC.x265-MeGusta[TGx] | Replace: metadata stuck |
| 4 | metaDL | 0.0% | 0.00 | 0 / 0 | 0 / 2 | 0.00 | 39.2 | 39.2 | radarr | Goldfinger (1964)-JAMES BOND-Sean Connery-1080p-H264-AC 3 … nickarad | Replace: metadata stuck |
| 5 | metaDL | 0.0% | 0.00 | 0 / 0 | 0 / 2 | 0.00 | 39.2 | 39.2 | radarr | Thunderball (1965)-JAMES BOND-Sean Connery-1080p-H264-AC 3 … | Replace: metadata stuck |
| 6 | metaDL | 0.0% | 0.00 | 0 / 0 | 0 / 1 | 0.00 | 39.2 | 39.2 | radarr | From Russia with Love (1963) 1080p 5.1 - 2.0 x264 Phun Psyz | Replace: metadata stuck |
| 7 | metaDL | 0.0% | 0.00 | 0 / 0 | 0 / 2 | 0.00 | 39.2 | 39.2 | radarr | On Her Majesty's Secret Service (1969)-George Lazenby-1080p … | Replace: metadata stuck |
| 8 | metaDL | 0.0% | 0.00 | 0 / 0 | 0 / 1 | 0.00 | 39.2 | 39.2 | radarr | Diamonds.Are.Forever.1971.1080p - Full Hd - MKV - G&U | Replace: metadata stuck |
| 9 | forcedDL | 99.8% | 0.998 | 0 / 0 | 3 / 5 | 2.45 | 39.2 | 8.4 | radarr | Live and let die (1973)-JAMES BOND-Roger Moore -1080p … | Replace: dead swarm (4 MB missing from the swarm) |
| 10 | metaDL | 0.0% | 0.00 | 0 / 1 | 0 / 1 | 0.00 | 39.2 | 39.2 | radarr | The Man With The Golden Gun (1974) 1080p-H264-AC 3 … nickarad | Replace: metadata stuck |
| 11 | metaDL | 0.0% | 0.00 | 0 / 0 | 0 / 3 | 0.00 | 39.2 | 39.2 | radarr | The Spy Who Loved Me (1977)-JAMES BOND-Roger Moore-1080p … | Replace: metadata stuck |
| 12 | stalledDL | 93.7% | 0.936 | 0 / 0 | 1 / 3 | 2.46 | 39.2 | 34.7 | radarr | Moonraker (1979)-JAMES BOND-Roger Moore-1080p … | Replace: dead swarm |
| 13 | stalledDL | 98.3% | 0.982 | 0 / 0 | 3 / 3 | 2.46 | 39.2 | 36.1 | radarr | For Your Eyes Only (1981)-JAMES BOND-Roger Moore-1080p … (last seen complete 159 h ago) | Replace: dead swarm |
| 14 | metaDL | 0.0% | 0.00 | 0 / 1 | 0 / 3 | 0.00 | 39.2 | 39.2 | radarr | Never Say Never Again (1983)-JAMES BOND-Sean Connery-1080p … | Replace: metadata stuck |
| 15 | metaDL | 0.0% | 0.00 | 0 / 0 | 0 / 2 | 0.00 | 39.2 | 39.2 | radarr | Octopussy (1983)-JAMES BOND-Roger Moore-1080p … | Replace: metadata stuck |
| 16 | stalledDL | 99.7% | 0.996 | 0 / 0 | 1 / 2 | 2.53 | 39.2 | 34.5 | radarr | A View To A Kill (1985)-JAMES BOND-Roger Moore-1080p … | Replace: dead swarm (8 MB missing from the swarm) |
| 17 | stalledDL | 93.8% | 0.938 | 0 / 0 | 1 / 2 | 2.72 | 39.2 | 33.8 | radarr | Licence to Kill (1989)-JAMES BOND-Timothy Dalton-1080p … | Replace: dead swarm |
| 18 | stalledDL | 0.0% | 0.00 | 0 / 0 | 0 / 1 | 4.06 | 39.2 | 39.2 | radarr | GoldenEye.1995.1080p - Full Hd - MKV - G&U | Replace: dead swarm |
| 19 | metaDL | 0.0% | 0.00 | 0 / 0 | 0 / 2 | 0.00 | 39.2 | 39.2 | radarr | The World Is Not Enough (1999)-JAMES BOND-Pierce Brosnan-1080p … | Replace: metadata stuck |
| 20 | metaDL | 0.0% | 0.00 | 0 / 0 | 0 / 2 | 0.00 | 39.2 | 39.2 | radarr | Spectre (2015)-JAMES BOND-Daniel Craig-1080p … | Replace: metadata stuck |

The snapshot also gives the circuit-breaker case: all 20 managed torrents are bad at once. The rule (section 8.4) would pause *if* qBittorrent were disconnected or DHT were low. Here qBittorrent is connected with 363 DHT nodes, so the Doctor acts within its rate limits: 3 per run, 15 per day, so the backlog clears over two days.

Synthetic cases to add:
- a healthy torrent that shows `stalledDL` for 5 minutes after wake, then downloads (no strike);
- a seeding torrent (`uploading`; ignored);
- a private torrent (skipped);
- a season pack with 10 queue records sharing one `downloadId` (one bulk delete);
- `queuedDL` for 30 h (alert only);
- a 99% torrent with availability ≥ 1 (re-announce first);
- compact-replacement candidates that fail each check in section 8.6.

### Appendix J: Observing the live server safely

- **Rules.**
  - Read only ([AGENTS.md](AGENTS.md) §4.1).
  - Never write through a mounted share.
  - No destructive commands; never print secrets.
  - Any change to the live apps needs the owner's explicit go-ahead.
- **Access.** Use the SSH alias for the server from your own SSH config. The workstation may also have the server's filesystem mounted read-only.
- **Keep keys on the server.** Run probes on the server itself, so API keys never leave the host:

```bash
# On the server: read a key into a variable without printing it, then query read-only
KEY=$(sudo awk -F= '$1=="RADARR_API_KEY"{print $2}' /etc/homelab/mediaserver.env)
curl -s -H "X-Api-Key: $KEY" "http://127.0.0.1:7878/api/v3/queue?pageSize=200&includeMovie=true" \
  | jq '.records[] | {title, status, trackedDownloadState, errorMessage}'
# Interactive search: ranks releases and shows rejections; grabs nothing
curl -s -H "X-Api-Key: $KEY" "http://127.0.0.1:7878/api/v3/release?movieId=<id>" \
  | jq '.[:20][] | {title, q: .quality.quality.name, score: .customFormatScore, seeders, rejections}'
```

- **Snapshot used for this plan.**
  - Radarr and Sonarr: `system/status`, `health`, `indexer`, `downloadclient`, `qualityprofile`, `customformat`, `qualitydefinition`, `config/{indexer,downloadclient,mediamanagement,naming}`, `delayprofile`, `releaseprofile`, `language`, `movie` / `series`, `history`, `queue`, `blocklist`, `rootfolder`, `metadata`, `episodefile`.
  - Prowlarr: `indexer`, `appprofile`, `indexerproxy`, `applications`, `indexerstats`, `history`.
  - qBittorrent: `app/preferences`, `transfer/info`, `torrents/info`, `torrents/categories`, plus `torrents/trackers` and `torrents/properties` per incomplete torrent.
  - Before saving any JSON, blank fields whose `privacy` isn't `normal`, and any key matching pass, key, token, secret, cookie or webhook.
- **Baseline metrics method** (section 3.3). Join history by `downloadId`:
  - a `grabbed` event with a later `downloadFolderImported` for the same ID counts as imported;
  - an ID still in the queue counts as stuck;
  - anything else is "gone without import".
- **Windows note.** `python -I` ignores `PYTHONIOENCODING`, so write UTF-8 files explicitly when titles contain non-ASCII characters.

### Appendix K: Verify before relying on it

Check each of these before building on it. Items 1, 2, 11, 12 and 13 were cleared on 2026-11-28 for Phase 1 (results below the table); items 2, 14 and 16 were also confirmed live in the [Phase 0 record](#phase-0-record-applied-2026-11-28).

| # | Item | How to check |
| ---: | :--- | :--- |
| 1 | ~~TRaSH IDs for the vendored formats.~~ **Cleared** (K.1) | TRaSH repository `docs/json/{radarr,sonarr}/cf/*.json` |
| 2 | ~~How "Whitelisted Hardcoded Subs" matches (exact or substring, case)~~ **Cleared** from the source (K.2) and live in Phase 0 | Set the list, re-run the *Goldfinger* interactive search: corpus #6 must lose "Hardcode subs found" |
| 3 | Whether Sonarr passes a season pack's total or per-episode size to the Size condition | Sonarr source: callers of `ParseCustomFormat(RemoteEpisode, size)` |
| 4 | `POST /release` grabbing a release rejected as "not an upgrade" | One test episode, Doctor in dry-run mode first |
| 5 | `ManualImport` over an existing file sends the old file to the recycle bin and imports the new one | One test episode, recycle bin enabled |
| 6 | qBittorrent 5.2+ API key: where it's created and the request header | qBittorrent WebUI options and release notes |
| 7 | Field name for private torrents in `torrents/info` | Inspect a known private torrent, or the qBittorrent source |
| 8 | Nova setting names (preferred audio and subtitle language, NFO export) and which NFO name it reads (`movie.nfo` or `<file>.nfo`) | On a TV. Match Radarr's `useMovieNfo` |
| 9 | Which Seerr permission lets users pick a quality profile per request | Seerr user permissions ("Advanced Requests") |
| 10 | Jellyfin's real-time monitoring default when the library options don't set it | Jellyfin dashboard → Libraries |
| 11 | ~~Radarr's audio-languages naming token~~ **Cleared** (K.11) | Naming UI preview |
| 12 | ~~Source and Release Type enum values~~ **Cleared** (K.12) | `GET /api/v3/customformat/schema` |
| 13 | ~~TRaSH Guides licence (MIT)~~ **Cleared** (K.13) | `LICENSE` in the official repository, before vendoring |
| 14 | ~~Units of qBittorrent's `alt_dl_limit`/`alt_up_limit` (the Control Hub assumes bytes/s)~~ **Cleared** in Phase 0: bytes/s | Set a known value in the WebUI and read it back through the API |
| 15 | A sudoers line for `smbstatus --json` (sudoers matches arguments exactly) | `sudo -n /usr/bin/smbstatus --json` as the `homelab` user |
| 16 | ~~`max_ratio_act` 0 means "stop torrent" on 5.3~~ **Cleared** in Phase 0: yes | qBittorrent WebUI shows the action next to the seeding limits |
| 17 | Decluttarr key names | Only if Appendix E is used: its `config_example.yaml` |

**K.1 TRaSH IDs** (upstream commit `1b0f1de51f85f7fcd6abdbf60f788d3f3cf9edfd`, 2026-11-28; files vendored byte-for-byte under `apps/mediaserver/profiles/trash/`):

| Format | Radarr `trash_id` | Sonarr `trash_id` |
| :--- | :--- | :--- |
| x265 (HD) | `dc98083864ea246d05a42df0d05f81cc` | `47435ece6b99a0b477caf360e79ba0bb` |
| AV1 | `cae4ca30163749b891686f95532519bd` | `15a05bc7c1a36e2b57fd628f8977e2fc` |
| DV (w/o HDR fallback) | `923b6abef9b17f937fab56cfcf89e1f1` | `9b27ab6498ec0f31a3353992e19434ca` |
| BR-DISK | `ed38b889b31be83fda192888e2286d83` | `85c61753df5da1fb2aab6f2a47426b09` |
| 3D | `b8cd450cbfa689c0259a01d9e29ba3d6` | (no Sonarr format) |
| Extras | `0a3f082873eb454bde444150b70253cc` | `fbcb31d8dabd2a319072b84fc0b7249c` |
| Upscaled | `bfd8eb01832d646a0a89c4deb46f8564` | `23297a736ca77c0fc8e70f8edd7ee56c` |
| Repack/Proper | `e7718d7a3ce595f289bfee26adc178f5` | `ec8fa7296b64e8cd390a1600981f3923` |
| Repack2 | `ae43b294509409a6a13919dedd4764c4` | `eb3d5cc0a2be0db205fb823640db6a3c` |
| Repack3 | `5caaaa1c08c1742aa4342d8c4cc463f2` | `44e7c4de10ae50265753082e5dc76047` |
| Season Pack | (Sonarr only) | `3bc5f395426614e155e585a2f056cdf1` |

Notes: TRaSH's "DV (w/o HDR fallback)" only matches WEB-DL and WEBRip sources (BluRay DV always carries HDR10), and excludes titles with `HDR` and the `Flights` group. "Season Pack" is a Release Type condition (value 3), not a title regex. BR-DISK, Sonarr Extras and Sonarr Upscaled use variable-width look-behinds that .NET accepts and Python's `re` does not.

**K.2 Whitelisted Hardcoded Subs** (Radarr `HardcodeSubsSpecification.cs`, develop): the setting is split on `,` with **no trimming**, and a release passes when the parsed hard-sub tag contains any entry, **case-insensitively** (`hardcodeSubs.ToLower().Contains(t.ToLower())`). So `ESub` alone also covers `Esub` and `ESubs`, an entry with a leading space never matches, and a short entry such as `sub` would whitelist everything. The pack writes `ESub,ESubs,MSub,MSubs,EngSub,EngSubs` without spaces; the corpus test checks that `KORSUB` stays blocked. Phase 0 set the same list live and confirmed it ([record](#phase-0-record-applied-2026-11-28)).

**K.11 Audio-languages naming token:** `{MediaInfo AudioLanguages}` (and `{MediaInfo AudioLanguagesAll}`) exist in both Radarr 7.0.3 and Sonarr 4.0.20. Previewed read-only with `GET /api/v3/config/naming/examples?id=1&standardMovieFormat=...` (with `id=0` the endpoint ignores the query and shows the saved format): `[{MediaInfo AudioLanguages}]` renders `[[DE]]`, so the token brings its own brackets. Per `FileNameBuilder.cs`, `AudioLanguages` omits a list that is only `EN`; `AudioLanguagesAll` always shows it.

**K.12 Enum values** (live `GET /api/v3/customformat/schema`, read-only):

| Condition | Radarr 7.0.3 | Sonarr 4.0.20 |
| :--- | :--- | :--- |
| Source | 0 UNKNOWN, 1 CAM, 2 TELESYNC, 3 TELECINE, 4 WORKPRINT, 5 DVD, 6 TV, 7 WEBDL, 8 WEBRIP, 9 BLURAY | 0 Unknown, 1 Television, 2 TelevisionRaw, 3 Web, 4 WebRip, 5 DVD, 6 Bluray, 7 BlurayRaw |
| Release Type | (none) | 0 Unknown, 1 Single Episode, 2 Multi-Episode, 3 Season Pack |
| Resolution | 0, 360, 480, 540, 576, 720, 1080, 2160 | same |
| Quality modifier | 0 NONE, 1 REGIONAL, 2 SCREENER, 3 RAWHD, 4 BRDISK, 5 REMUX | (none) |
| Language | Any −1, Original −2, Hindi 26, Tamil 43, Telugu 45, Malayalam 48, Kannada 49, Bengali 34, Marathi 52, Arabic 31 | Original −2 (no Any), Hindi 27, Tamil 43, Malayalam 29, Arabic 26; **no Telugu, Kannada, Bengali or Marathi** |

The pack keeps language names and resolves ids at runtime; source values are stored per app (`custom_formats/src-*.json`).

**K.13 Licence:** TRaSH Guides is MIT (`Copyright (c) 2021 TRaSH`), confirmed from `LICENSE` at the commit above; a copy is kept as `apps/mediaserver/profiles/trash/LICENSE`.

---

## Revision 4: owner decisions on profiles and scoring (2026-11-28)

These decisions **supersede** the earlier text in sections 5.2, 5.3, 8.6 and 14 and Appendices B and C. Whoever implements or reviews Phase 1 (PR #89) applies them there.

**1. `1080p Compact` = the best 1080p.**
- 1080p only: the 720p qualities are removed from its group.
- Dual audio (Hindi + English) is preferred among 1080p releases; English-only is fine.
- A title with no healthy 1080p release goes to "needs attention", and the owner can switch it to `1080p Family`.

**2. `1080p Family` replaces "Dual Audio First". Hindi is required, English is a bonus.**
- Why: the owner understands both languages, but the parents only understand Hindi.
- Order:

  | Rank | Release |
  | ---: | :--- |
  | 1 | 1080p Hindi + English |
  | 2 | 720p Hindi + English |
  | 3 | 1080p Hindi only |
  | 4 | 720p Hindi only |
  | — | English-only: **rejected** |

- Scores:

  | Format | Score |
  | :--- | ---: |
  | Dual audio (named or tag) | +3000 |
  | Hindi only | **+1500** |
  | Res · 1080p | +1000 |
  | HEVC | +150 |
  | Size · Oversized | −500 |

- Profile settings:
  - **Minimum score 1400.** A 720p Hindi-only release (about 1,500) passes; the best English-only release (about 1,217) fails.
  - Upgrade until 4000; minimum upgrade step 400.
- If no Hindi release exists yet, the title stays missing and the weekly sweep keeps searching. To get English meanwhile, switch the title to `1080p Compact`.

**3. HEVC and the other tie-breakers can never trigger an upgrade on their own.**

Only language, resolution, leaving the oversized range, or moving into the compact size band may cause an upgrade. The small extras (HEVC, source, season pack, repack) together must stay below the 400 upgrade step.

| Format | Compact (movies) | Family (movies) | TV (both profiles) |
| :--- | ---: | ---: | ---: |
| HEVC | +250 | +150 | +150 |
| Size · Compact band (≤ 6 GB) | +200 | 0 | — |
| Season Pack | — | — | +150 |
| Source | +60 / +50 / +40 | +60 / +50 / +40 | +40 / +30 / +20 |
| Repack | +5 to +7 | +5 to +7 | +5 to +7 |
| Largest sum of extras | 317 | 217 | 347 |

- **Movies (Compact):** HEVC moving into the band adds +450, so it upgrades, and the new file is always smaller. A bigger HEVC file in the same band never upgrades.
- **TV:** all size savings, including x264 → HEVC (for example *Succession*), go only through the compact replacement job (section 8.6, at least 35% smaller). Codec alone never triggers an upgrade.

**Tests to add:**
- a profile invariant: the tie-breaker sum is below `min_upgrade_format_score` in every profile;
- Family's order above, with English-only rejected;
- Compact rejects 720p.
