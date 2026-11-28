# Release profile pack

The release profiles this module installs in Radarr and Sonarr, kept as data. `scripts/wire_arr.py profiles apply` turns these files into custom formats, two quality profiles, size limits and a few related settings; `profiles check` shows where the apps have drifted from them. JSON only, so the standard library reads it.

How the ranking works, what the two profiles do and how to change the language: [release profiles guide](https://github.com/RAM-MAHESHWARI24/homelab-blueprint/blob/main/docs/MEDIA_RELEASE_PROFILES.md). Why the pack replaced Recyclarr: [ADR-0004](https://github.com/RAM-MAHESHWARI24/homelab-blueprint/blob/main/docs/adr/0004-repo-owned-release-profiles.md).

## Layout

```text
profiles/
├── pack.json                 # pack version, owned name prefixes and profiles, legacy names
│                             # that `migrate` removes, vendored TRaSH files and upstream commit
├── languages.json            # second languages: app language name + title tokens
├── settings.json             # app settings the pack owns (subtitle whitelist, recycle bin,
│                             # delay profile, Prowlarr, qBittorrent seeding/queue/trackers)
├── custom_formats/*.json     # the pack's own formats; {LANG} and {LANG_RX} are filled in
│                             # from languages.json when the pack is applied
├── trash/                    # TRaSH Guides formats, byte-for-byte (MIT, see trash/LICENSE)
│   ├── radarr/*.json
│   └── sonarr/*.json
├── profiles/                 # one file per app and profile; qualities listed highest first
│   ├── radarr-1080p-compact.json
│   ├── radarr-1080p-family.json
│   ├── sonarr-1080p-compact.json
│   └── sonarr-1080p-family.json
└── quality_definitions/      # size limits in MB per minute (global in each app)
    ├── radarr.json
    └── sonarr.json
```

## Rules the tests enforce

`tests/test_profile_pack.py` checks, among other things:

* every file parses, and every quality name exists in the app;
* qualities are listed highest first, and an unknown-source quality (`HDTV-1080p`, what the apps call an untagged "1080p") never sits above BluRay or WEB on its own;
* every format the pack creates carries an owned prefix and is scored in every profile;
* the minimum score and the upgrade-until score are reachable, `1080p Compact` holds only 1080p qualities, and `1080p Family` ranks dual audio over a single second language and rejects releases without it (an untagged release of a title in that language counts as having it);
* the small tie-breakers (HEVC, source, season pack, repack) add up to less than the 400 upgrade step in every profile, so none of them triggers an upgrade on its own;
* every regex matches a corpus of real release titles as expected, including guards like *The Thin Red Line* (not "line audio") and *Ben-Hur* (not Bengali).

## Changing the pack

* **Scores or limits:** edit the profile or `quality_definitions` file, run the tests, then `profiles apply`.
* **A banned uploader:** add the name to the alternation in `custom_formats/junk-banned-uploaders.json`.
* **A language:** add an entry to `languages.json` with its name as the apps spell it and safe title tokens. A token that is also an ordinary word goes in `adjacent_tokens`; add guard titles to the tests.
* **Vendored TRaSH formats:** do not edit them by hand. `scripts/trash_sync.py --check` compares them with upstream and `--write` updates them; the blueprint runs it weekly and opens a pull request.

Objects without one of the pack's prefixes, and profiles other than `1080p Compact` and `1080p Family`, are never changed. To manage profiles another way (for example with Recyclarr), set `MEDIA_PROFILES=off`.
