# ADR-0004: Repo-Owned Release Profiles Replace Recyclarr

## Status
**Accepted** (2026-11-28)

## Context
Radarr and Sonarr choose between releases in a fixed order ([guide](../MEDIA_RELEASE_PROFILES.md#how-radarr-and-sonarr-rank-releases)): quality position in the profile first, then custom-format score, protocol, indexer priority and only then seeders, compared in powers of ten. Whatever sits highest in the quality list wins before anything else is looked at.

A live server running this blueprint showed what that means:
* The `1080p Compact` profile ranked `HDTV-1080p` highest. Radarr gives that label to any title that says "1080p" without naming a source, so old untagged uploads beat every BluRay and WEB release, and every one of 17 stuck downloads was such a grab.
* The ranking came from the module's Recyclarr example, which listed `HDTV-1080p` first. Recyclarr ran daily from a personal crontab with that file and silently undid every fix made in the apps' UI.
* Recyclarr syncs TRaSH Guides formats by ID but cannot define custom formats of its own, so the language formats a dual-audio household needs (Hindi + English here) needed a second owner of the same profile.
* It was not "few clicks": the README asked users to install a binary, copy YAML and paste API keys by hand, and the installer did not manage it.
* Its `Ozlem` block used `/api/v3/restriction`, which Radarr 7 and Sonarr 4 removed, so it was a silent no-op.

The blueprint targets small, low-memory hosts and one-command installs, so a fix must not add an always-on service, and its Python must stay standard-library only like the rest of the installer ([ADR-0002](0002-zero-dependency-setup-wizard.md)).

## Decision
The mediaserver module owns its release profiles as data, `apps/mediaserver/profiles/`, and applies them itself:

1. **Merged quality group plus scores.** Each profile allows one group, `HD` (Bluray, WEB-DL, WEBRip and HDTV at 1080p; `1080p Family` adds the 720p ones), so every acceptable quality ties at the first comparison. Preferences are custom-format scores: 1080p, the second audio language, HEVC, a compact size band, source. Junk, theatre recordings, banned uploaders, commentary editions and formats the players cannot decode score −10000, far below any minimum score.
2. **Two profiles.** `1080p Compact` (default: the best 1080p and 1080p only; dual audio preferred, English-only fine) and `1080p Family` (only with a second language, which it requires: 1080p dual audio, then 720p dual audio, then 1080p and 720p releases with only the second language; a minimum score of 1400 rejects releases without it). The small tie-breakers (HEVC, source, season pack, repack) add up to less than the 400 upgrade step, so none of them triggers an upgrade on its own; a bigger file never replaces a smaller one just for its codec.
3. **Any second language.** Language formats are generated from `languages.json` (app language name plus title tokens; short tokens only next to another language marker). The Radarr profile language is `Any`, so custom formats decide.
4. **One owner, by prefix.** `wire_arr.py profiles apply` creates or updates only custom formats whose names start with the pack's prefixes (`Lang ·`, `Res ·`, `Src ·`, `Eff ·`, `Size ·`, `Compat ·`, `Junk ·`, `Fix ·`, `TV ·`) and the two profiles it names. User-made formats and profiles are never touched, and a user's own format keeps its score inside the pack's profiles. Existing profiles are updated in place so Seerr's profile IDs stay valid.
5. **Drift, not overnight overwrite.** `profiles check --json` reports differences; nothing re-applies on a timer. The installer applies the pack once; the Control Hub will show drift and offer a re-apply (Phase 3 of the media pipeline plan).
6. **Vendored TRaSH formats.** Formats TRaSH Guides already maintains (x265 (HD), AV1, DV without HDR fallback, BR-DISK, 3D, Extras, Upscaled, Repack/Proper 1–3, Season Pack) are kept byte-for-byte under `profiles/trash/` with the upstream commit and MIT licence, renamed with a pack prefix. A weekly workflow (`.github/workflows/trash-sync.yml`) opens a pull request when upstream changes.
7. **Related settings travel with the pack**: soft-subtitle whitelist (`ESub`, `MSub`, `EngSub`), recycle bin, delay-profile bypass for near-perfect releases, Prowlarr Full Sync and minimum seeders, qBittorrent's "seed while it helps" limits, queue limits, evening upload limit, public tracker list and excluded file names.
8. **Choices in the Setup Wizard.** A "Release preferences" step asks for the second language, default profile, what the players decode, seeding and stuck-download handling, and writes them as `MEDIA_*` keys in `mediaserver.env`. `MEDIA_PROFILES=off` hands profiles back to the user or another tool. Existing installs get `off` on upgrade and opt in with `profiles migrate`, which removes the legacy formats and profiles after printing a plan (`--dry-run`).

The Recyclarr example and README section are removed; [the guide](../MEDIA_RELEASE_PROFILES.md#using-recyclarr-instead) keeps a short note for people who prefer it.

## Alternatives Considered
* **Keep Recyclarr and fix the example:**
  * *Rejected:* still cannot hold the language formats, still needs manual installation and API keys, and a daily re-application still makes the apps look broken whenever the file and the UI disagree.
* **Configarr (Recyclarr-compatible, with local custom formats):**
  * *Rejected:* adds a Node.js runtime or container and YAML containing API keys, and remains a second owner outside the installer.
* **Profilarr with the Dictionarry database:**
  * *Rejected:* an always-on container and database on a RAM-constrained host; its profiles penalise x265 at HD (wrong for players that decode HEVC and a nearly full disk) and have no Indian-language handling; database maintenance is unclear.
* **Document the settings and let users click them in:**
  * *Rejected:* not reproducible, not testable, and the opposite of a few-click installer.

## Consequences
### Positive
* Untagged "1080p" uploads no longer outrank tagged BluRay and WEB releases; language and efficiency can matter more than a quality label.
* One owner of profile state, applied by the installer with no extra steps and no new service.
* Every regex is tested in CI against a corpus of real release titles (`apps/mediaserver/tests/test_profile_pack.py`), including false-positive guards such as *The Thin Red Line* and *Ben-Hur*.
* Works for any household: the second language, codecs, seeding and the default profile are choices, not assumptions.

### Negative / Trade-offs
* TRaSH changes arrive by reviewed pull request, not overnight.
* Size limits are global in each app, so both profiles share them; per-profile size pressure comes only from custom formats, and Sonarr's size condition cannot judge a season pack per episode.
* Python's `re` cannot compile every .NET regex, so the corpus test rewrites the few variable-width look-behinds TRaSH uses into equivalents.
* People who want Recyclarr must switch the pack off (`MEDIA_PROFILES=off`), or the two will disagree.

## References
* [Release profiles and dual audio guide](../MEDIA_RELEASE_PROFILES.md)
* [Profile pack data](../../apps/mediaserver/profiles/README.md)
* [wire_arr.py](../../apps/mediaserver/scripts/wire_arr.py) -> `PackRunner`, and [profile_pack.py](../../apps/mediaserver/scripts/profile_pack.py)
* [Media Pipeline Reliability Plan](../../Media%20Pipeline%20Reliability%20Plan.md#59-replacing-recyclarr-with-a-repo-owned-profile-pack)
* [Radarr `DownloadDecisionComparer`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/DecisionEngine/DownloadDecisionComparer.cs)
* [TRaSH Guides: merge quality](https://trash-guides.info/Radarr/Tips/Merge-quality) and [language custom formats](https://trash-guides.info/Radarr/Tips/How-to-setup-language-custom-formats)
* [ADR-0002: Zero-Dependency Setup Wizard](0002-zero-dependency-setup-wizard.md)
