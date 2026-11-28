# Release Profiles and Dual Audio

How the media stack decides which release to download, the two profiles it installs, and how to change them. The profiles are data in [`apps/mediaserver/profiles/`](../apps/mediaserver/profiles/README.md), applied by `wire_arr.py profiles apply`. Why they replaced Recyclarr: [ADR-0004](adr/0004-repo-owned-release-profiles.md).

## Contents

1. [How Radarr and Sonarr rank releases](#how-radarr-and-sonarr-rank-releases)
2. [The two profiles](#the-two-profiles)
3. [What each custom format does](#what-each-custom-format-does)
4. [Size limits](#size-limits)
5. [Choosing and changing your settings](#choosing-and-changing-your-settings)
6. [Moving a title to the other profile](#moving-a-title-to-the-other-profile)
7. [Commands](#commands)
8. [Moving from Recyclarr](#moving-from-recyclarr)
9. [Using Recyclarr instead](#using-recyclarr-instead)
10. [Why isn't it downloading?](#why-isnt-it-downloading)
11. [Seeding and qBittorrent](#seeding-and-qbittorrent)

## How Radarr and Sonarr rank releases

For each candidate release, the apps compare these in order. The first one that differs decides.

| Step | Radarr | Sonarr |
| ---: | :--- | :--- |
| 1 | Quality (position in the profile) | Quality |
| 2 | Custom format score | Custom format score |
| 3 | Protocol preferred by the delay profile | Protocol |
| 4 | Indexer priority (lower number wins) | Episode count (full-season packs first) |
| 5 | Indexer flags (only if "Prefer Indexer Flags" is on) | Lowest episode number |
| 6 | Seeders, then peers | Indexer priority |
| 7 | Age (usenet) | Seeders, then peers |
| 8 | Size: closest to "preferred" | Age (usenet), then size |

Seeders are compared as `round(log10(seeders))`: 1–3 seeders count the same as 0, and 4–31 are all equal. So seeders cannot rescue a bad choice; quality position and score come first.

Two consequences shape the pack:

* **Quality position beats everything.** The apps label any title that says "1080p" without a source as `HDTV-1080p`. If that quality sits above BluRay in a profile, old untagged uploads win before score or seeders are looked at. The pack therefore puts every acceptable quality in **one group** (`HD`), so they tie at step 1, and expresses preferences as scores.
* **Minimum seeders matter more than seeder counts.** Prowlarr's minimum-seeders filter removes candidates outright, so the pack sets it to 4 (see [Seeding and qBittorrent](#seeding-and-qbittorrent) for the rest of the torrent policy).

## The two profiles

Both profiles exist in Radarr and Sonarr. `1080p Family` is created only when a second language is chosen.

| | `1080p Compact` (default) | `1080p Family` |
| :--- | :--- | :--- |
| Goal | The best 1080p. Dual audio is preferred among 1080p releases; English-only is fine | The second language is **required**, for viewers who only understand it; the original language is a bonus |
| Qualities | One group `HD`: Bluray, WEB-DL, WEBRip and HDTV at 1080p. **No 720p** | The same group plus Bluray, WEB-DL and WEBRip at 720p |
| Order | Dual audio first, then the most efficient 1080p release | 1. 1080p dual audio · 2. 720p dual audio · 3. 1080p with only the second language · 4. 720p with only the second language. Releases without the second language are rejected |
| Upgrade until score | 4700 in Radarr (1080p dual audio in the compact band), 4500 in Sonarr (1080p dual audio). Without a second language: 3200 in Radarr (1080p in the compact band, or HEVC) and 3000 in Sonarr | 4000 (1080p dual audio) |
| Minimum score / upgrade step | 0 / 400 | **1400** / 400 |
| Radarr profile language | Any (custom formats handle language) | Any |

Worked example, *Goldfinger* (1964), with Hindi as the second language:

| Release | `1080p Compact` | `1080p Family` |
| :--- | ---: | ---: |
| `1080p BDRip HEVC [Hindi English] DDP 5.1`, 5.7 GB | 3000 + 1500 + 250 + 200 + 60 = **5010** | 1000 + 3000 + 150 + 60 = **4210** |
| `1080p NF WEB-DL DDP5 1 Atmos H 264`, 5.2 GB | 3000 + 200 + 50 = 3250 | 1000 + 50 = 1050, under 1400: rejected |
| `720p BluRay x264 Dual Audio [English + Hindi]`, 1.0 GB | not wanted (720p) | 3000 + 60 = 3060 |
| `720p BluRay Hindi DD 2.0 Esub`, 1.4 GB | not wanted (720p) | 1500 + 60 = 1560 |
| `1080p H264 AC3 ... nickarad` (no source named) | 3000 | 1000: rejected |
| `... -Ozlem` (banned uploader) | rejected | rejected |

Both profiles upgrade on their own when a 1080p dual-audio release appears. To keep one particular big file, tag the title `keep` (used by the Download Doctor in a later release) or move it to a profile of your own.

## What each custom format does

The pack's formats all start with a prefix, so you can tell them from your own. `{Lang}` is the second language you chose.

| Format | `1080p Compact` | `1080p Family` | Matches |
| :--- | ---: | ---: | :--- |
| `Res · 1080p` | +3000 | +1000 | Resolution 1080 |
| `Lang · {Lang} + Original (named)` | +1500 | +3000 | A `{Lang}` token in the title, and the parsed languages include the original |
| `Lang · {Lang} + Dual/Multi tag` | +1500 | +3000 | A `{Lang}` token plus `Dual Audio`, `Dual` or `Multi`, when the original isn't named |
| `Lang · {Lang} only (original missing)` | −500 | +1500 | A `{Lang}` dub without the original track |
| `Lang · Not Original or {Lang}` | −10000 | −10000 | Third-language-only releases (German-only, Italian-only). Without a second language it is `Lang · Not Original` |
| `Eff · HEVC` | +250 movies, +150 TV | +150 | x265/HEVC at 720p or 1080p (TRaSH "x265 (HD)") |
| `Size · Compact band` (Radarr) | +200 | 0 | Movies up to 6 GB |
| `Size · Oversized` (Radarr) | −2000 | −500 | Movies above 10 GB |
| `Src · Bluray` / `WEB-DL` / `WEBRip` | +60 / +50 / +40 movies, +40 / +30 / +20 TV | same | Gentle source preference inside the group |
| `TV · Season Pack` (Sonarr) | +150 | +150 | Complete seasons (single old episodes are the deadest torrents) |
| `Fix · Repack/Proper`, `Repack2`, `Repack3` | +5 / +6 / +7 | same | Fixed releases |
| `Compat · AV1` | −10000 | −10000 | AV1; many TV chips cannot decode it. Allowed when you say your players can |
| `Compat · DV w/o HDR fallback` | −10000 | −10000 | Dolby Vision WEB releases without HDR10: wrong colours on non-DV screens |
| `Junk · Line/cam audio` | −10000 | −10000 | Theatre-recorded (`LiNE`), cleaned audio, AI or fan dubs. "line" only counts next to a language token or "audio" |
| `Junk · Cam / PreDVD / S-Print` | −10000 | −10000 | Theatre recordings that would otherwise parse as `HDTV-1080p` |
| `Junk · Banned uploaders` | −10000 | −10000 | Uploaders with mangled names or wrong audio (`Ozlem`) |
| `Junk · Commentary editions` | −10000 | −10000 | Joke-commentary releases (`RiffTrax`) |
| `Junk · BR-DISK`, `3D`, `Extras`, `Upscaled` | −10000 | −10000 | Formats nobody wants here (TRaSH) |

Notes on language matching:

* The apps recognise a language only by its full name ("hindi"); "Hin" and "Dual Audio" map to nothing, and a title without a language falls back to the film's original language. The pack's title tokens fill that gap.
* Short tokens that are also ordinary words (`tel`, `mal`, `kan`) only count next to another language marker, so *Malcolm X* is not Malayalam.
* Radarr reads `ESub`, `ESubs` and `MSubs` as burned-in subtitles; in Indian release names they mean soft subtitles. The pack adds them to Radarr's **Whitelisted Hardcoded Subs** (Settings → Indexers). Radarr matches that list as case-insensitive substrings and does not trim spaces, so the list is written without spaces.
* A Hindi-only dub scores −500 in Compact: a 1080p dub still clears the minimum score (2500 and up), so it is a last resort below any English 1080p release. In Family it scores +1500: a 1080p dub (2500) and a 720p dub (1500) are both accepted, below the dual-audio releases.
* Family needs the language **in the release name**. An untagged release of a film whose original language is the second language (many international WEB releases of Hindi films carry no language tag) counts as having no second language and is rejected. Hindi-language films belong in Compact anyway: their original audio is Hindi.
* Upgrades of files already on disk use the same scores, with an upgrade step of 400. Language, resolution (Family only), leaving the oversized range and moving into the compact band can reach it. HEVC, source, season pack and repack together add at most 317 (Compact movies), 217 (Family movies) or 347 (TV), so none of them causes an upgrade on its own.
* Example: a 9.7 GB x264 film (3050) is replaced by a 4.3 GB HEVC release (3500, +450), and the new file is always the smaller one. A bigger HEVC file in the same band (+250) is not an upgrade. TV episodes are never upgraded for the codec alone (+150, or +300 as a season pack); making oversized episodes smaller is the compact replacement job of the Download Doctor (a later release).

## Size limits

Size limits are global in each app (shared by every profile), in MB per minute; 1 MB/min is about 0.13 Mbit/s.

| Quality | Radarr min / preferred / max | Two-hour film | Sonarr min / preferred / max | 50-minute episode |
| :--- | :--- | :--- | :--- | :--- |
| Bluray-1080p | 12 / 40 / 75 | 1.4–9.0 GB | 6 / 22 / 45 | 0.3–2.25 GB |
| WEBDL-1080p | 12 / 35 / 75 | 1.4–9.0 GB | 5 / 18 / 40 | 0.25–2.0 GB |
| WEBRip-1080p | 12 / 35 / 70 | 1.4–8.4 GB | 5 / 15 / 35 | 0.25–1.75 GB |
| HDTV-1080p (untagged) | 12 / 30 / 65 | 1.4–7.8 GB | 4 / 15 / 35 | 0.2–1.75 GB |
| Bluray-720p | 6 / 20 / 40 | 0.7–4.8 GB | 3 / 10 / 22 | 0.15–1.1 GB |
| WEBDL / WEBRip-720p | 6 / 18 / 35 | 0.7–4.2 GB | 3 / 10 / 22 | 0.15–1.1 GB |

The maximum leaves room for two audio tracks and blocks remux-sized files; the minimum stops sub-1.5 Mbit/s "1080p". The 720p rows only matter for `1080p Family`; `1080p Compact` takes no 720p.

## Choosing and changing your settings

The Setup Wizard's **Release preferences** step asks five questions and writes the answers to `/etc/homelab/mediaserver.env` (or the module's `.env` when installed on its own):

| Question | Key | Values (default first) |
| :--- | :--- | :--- |
| Second audio language | `MEDIA_SECOND_LANGUAGE` | empty, `Hindi`, `Tamil`, `Telugu`, `Malayalam`, `Kannada`, `Bengali`, `Marathi`, `Spanish`, `French`, `German`, `Italian`, `Portuguese`, `Japanese`, `Korean`, `Arabic` |
| Default profile for new titles | `MEDIA_DEFAULT_PROFILE` | `compact`, `family` (`1080p Family`, needs a language) |
| What your TVs and players decode | `MEDIA_CODECS` | `hevc`; add `av1` and/or `dv` if they decode them; remove `hevc` if they cannot (HEVC is then blocked) |
| Seeding | `MEDIA_SEEDING` | `while-it-helps`, `off` |
| Stuck downloads | `MEDIA_STUCK_DOWNLOADS` | `replace`, `off` (used by the Download Doctor, a later release) |
| Manage release profiles | `MEDIA_PROFILES` | `on`, `off` |

Two more keys are not wizard questions: `MEDIA_PUBLIC_TRACKERS` (`on`/`off`, see below).

To change an answer later, edit the file and re-apply:

```bash
sudoedit /etc/homelab/mediaserver.env          # e.g. MEDIA_SECOND_LANGUAGE=Tamil
sudo python3 /opt/homelab-blueprint/apps/mediaserver/scripts/wire_arr.py profiles apply \
  --config-dir /srv/homelab/appdata/mediaserver --env-file /etc/homelab/mediaserver.env
```

Changing the language creates the new language's formats and rescores both profiles; the previous language's formats stay (they are just scored 0) and can be deleted in the apps.

Languages the app itself doesn't know (Sonarr has no Telugu, Kannada, Bengali or Marathi) are matched by title tokens only.

## Moving a title to the other profile

Which profile a title should use:

| Profile | Use it for |
| :--- | :--- |
| `1080p Compact` | Everything by default, including films in your second language (their original audio already is that language) |
| `1080p Family` | Titles in another language that someone needs in your second language: it waits for a release with that language instead of downloading English-only. While none exists, the title stays missing and keeps being searched; switch it to `1080p Compact` to get English meanwhile |

A title with no healthy 1080p release gets nothing in `1080p Compact`, which takes no 720p. If a 720p release with your second language exists, `1080p Family` will take it.

| Where | How |
| :--- | :--- |
| New request in Seerr | Users with the **Advanced Requests** permission pick the profile when requesting |
| Existing title | Radarr/Sonarr → the title → Edit → Quality Profile, then search. For many titles, use the mass editor (Movies → Select) |
| Default for everyone | `MEDIA_DEFAULT_PROFILE` (Seerr's default on a fresh install) |

## Commands

All commands run on the server; API keys are read from each app's `config.xml` under `--config-dir`.

```bash
cd /opt/homelab-blueprint/apps/mediaserver
# Apply (idempotent; safe to re-run)
sudo python3 scripts/wire_arr.py profiles apply --config-dir /srv/homelab/appdata/mediaserver \
  --env-file /etc/homelab/mediaserver.env --data-dir /mnt/hdd/data
# Drift: what differs from the pack (exit 0 in sync, 1 drift, 2 error); --json for scripts
sudo python3 scripts/wire_arr.py profiles check --config-dir /srv/homelab/appdata/mediaserver \
  --env-file /etc/homelab/mediaserver.env
# One-off cleanup of an older setup; prints the plan and changes nothing with --dry-run
sudo python3 scripts/wire_arr.py profiles migrate --config-dir /srv/homelab/appdata/mediaserver \
  --env-file /etc/homelab/mediaserver.env --dry-run
```

`--skip qbittorrent` (or any app) leaves one app out. Without a qBittorrent password (`--qbit-pass` or `QBITTORRENT_PASS` in the env file) the qBittorrent settings are skipped.

What `apply` changes, and nothing else:

* custom formats with the pack's prefixes (created or updated);
* the `1080p Compact` and `1080p Family` profiles (updated in place, so Seerr's profile IDs stay valid);
* size limits for the qualities listed above;
* Radarr's soft-subtitle whitelist (merged, never shrunk); the recycle bin (`/data/media/.recycle`, 7 days) only if none is set; the default delay profile's "bypass if score ≥ 4000";
* Prowlarr: Full Sync on the Radarr and Sonarr links, minimum seeders 4 on the default app profile, and a `Live seeders` app profile (minimum 2) to assign to indexers with accurate counts;
* qBittorrent: the seeding, queue, schedule, tracker and excluded-file settings below, and the `radarr` and `tv-sonarr` categories.

## Moving from Recyclarr

An existing install keeps `MEDIA_PROFILES=off` after an upgrade, so nothing changes until you opt in:

1. Back up: Control Hub → Backups → **Back up now**, plus System → Backup in Radarr and Sonarr.
2. Remove the Recyclarr line from the crontab that runs it (`crontab -l`, then `crontab -e`), or its next sync puts the old profiles back.
3. Set `MEDIA_PROFILES=on` and your `MEDIA_SECOND_LANGUAGE` in the env file.
4. Run `profiles migrate --dry-run` and read the plan. It lists the formats it will create, the profile changes, and the legacy cleanup: the old `Hindi Audio`, `x265 (HD)`, `Season Complete` and `Multi Episode` formats are deleted, titles on `1080p Balanced` or `1080p Balanced (Hindi)` move to `1080p Compact` before those profiles are deleted, and a temporary release profile named `Phase 0 bans (until profile pack)` is removed (the `Junk ·` formats replace it). Release profiles with other names are left alone.
5. Run `profiles migrate` without `--dry-run`, then `profiles check` (it should report no drift).
6. Delete Recyclarr's binary and config files when you no longer need them.

## Using Recyclarr instead

Set `MEDIA_PROFILES=off` (or untick **Manage release profiles** in the wizard) and the installer leaves profiles alone. Recyclarr syncs TRaSH formats by ID but cannot define custom formats, so the language formats above are not available that way; and never run the pack and Recyclarr against the same profiles, or each will undo the other.

## Why isn't it downloading?

Work down the list:

1. **Search interactively.** In Radarr/Sonarr, open the title → Search (the person icon). Every result shows its quality, score and the reason it was rejected. Nothing is grabbed until you click.
2. **"Not wanted in profile" / quality.** Remux, 2160p, 480p and HDTV-720p are outside the `HD` group by design, and `1080p Compact` takes no 720p at all.
3. **"Custom Formats ... score of X is below minimum".** A −10000 format matched; hover the score to see which, and check the title against the format list above. In `1080p Family` (minimum 1400) it also means the release name doesn't mention the second language.
4. **"Hardcode subs found".** A tag other than `ESub`/`MSub`/`EngSub` looks burned in. Add it to Whitelisted Hardcoded Subs only if it really means soft subtitles.
5. **"Original Language ... wanted".** The Radarr profile language must be `Any`; run `profiles check`.
6. **"Larger than maximum allowed" / "smaller than minimum".** See [size limits](#size-limits).
7. **Nothing found at all.** Indexers: Prowlarr → Indexers → Test All. Minimum seeders 4 hides releases with 0–3 seeders; rare titles may need an indexer on the `Live seeders` profile. If only 720p releases with the second language exist, `1080p Family` takes them.
8. **Grabbed but stuck at 0%.** A dead torrent. Remove it from the app's queue (Activity → Queue → remove, with **Blocklist** and **Search again** ticked), never directly in qBittorrent, so the app blocklists it and picks the next release.
9. **Profiles look wrong again.** Something else changed them: `profiles check` lists the differences; look for another sync tool on the server.

## Seeding and qBittorrent

On public trackers there is no ratio requirement, so seeding after a download has no direct reward. What it does give: healthier swarms for the older titles that die first, and a policy already in place if you ever join a private tracker. What it costs: nothing on disk while the film is in the library (hardlinks, [ADR-0001](adr/0001-single-mount-atomic-hardlinks.md)), a little RAM and CPU, and disk reads that compete with playback over the network.

| Setting | `MEDIA_SEEDING=while-it-helps` | `off` |
| :--- | :--- | :--- |
| Stop seeding at | ratio 1.0, or 24 hours, or 60 minutes without an upload, whichever first | right after downloading |

Always set:

| Setting | Value | Why |
| :--- | :--- | :--- |
| Evening upload limit | 18:00–24:00 daily: upload 1 MiB/s, download unlimited (qBittorrent's alternative speed scheduler) | Seeding reads never make TV playback stutter on a shared disk |
| Queue | downloads 8, torrents 20, active uploads 5; slow torrents (under 4 KiB/s for 300 s) don't count | Dead torrents can't block new ones |
| Public tracker list | Appended from ngosang's `trackers_best.txt` (qBittorrent 5) | Peers found when a torrent's own trackers are dead |
| Re-announce when the address changes | on | Helps after wake-up if the public IP changed |
| Excluded file names | executables, scripts and archives (`*.exe`, `*.msi`, `*.ps1`, `*.js`, `*.jar`, `*.apk`, `*.zipx`, ...) merged into your list | Malware-bait torrents end up empty and get replaced |

**Private trackers** forbid foreign trackers: set `MEDIA_PUBLIC_TRACKERS=off` and turn off "Automatically append trackers from URL" in qBittorrent before adding one. Also leave their seeding rules to the tracker (per-indexer seed goals in Prowlarr).

**Without a VPN**, uploading on public trackers makes your address more visible than downloading alone. That trade-off is yours; this project ships no indexer list.

## Related

* [Playing over SMB with Nova Video Player](SMB_PLAYBACK_WITH_NOVA.md): codecs, subtitles and NFO metadata on the TVs.
* [mediaserver module README](../apps/mediaserver/README.md)
* [Setup Wizard](../setup/README.md)
