# Playing over SMB with Nova Video Player

How to watch the media library on Android TVs by opening the server's Samba share in [Nova Video Player](https://github.com/nova-video-player/aos-AVP), and what that means for codecs, subtitles, audio language and library metadata. The share itself comes from the Samba module ([Networking: Tailscale & Samba](NETWORKING_TAILSCALE_SAMBA.md)).

With this setup the TV decodes everything and **the server never transcodes**, so the server's CPU no longer limits which files you can keep. Jellyfin can stay installed as Seerr's backend without being used for playback.

## 1. Add the share in Nova

1. Install Nova Video Player on the TV (Play Store, or an APK from its GitHub releases).
2. In Nova, open **Network** (network shares), add an SMB share with the server's LAN address (`<server-lan-ip>`) and the user and password the installer gave the Samba share (the master password unless you changed it).
3. Pick the `Media` share, then index `movies/` and `tv/` (under `media/`) as content folders. Nova scans them and builds its library from them.

Nova's own settings change between versions; the names below describe what to look for rather than exact labels.

## 2. Library metadata: NFO files

Nova reads `.nfo` files and artwork next to each video, and it can also write its own. Let **Radarr and Sonarr own those files**:

| Where | Setting |
| :--- | :--- |
| Sonarr → Settings → Metadata → Kodi (XBMC) / Emby | Enabled (series and episode metadata and images) |
| Radarr → Settings → Metadata → Kodi (XBMC) / Emby | Enable it (movie metadata and images). Off by default |
| Nova → settings for scraping / NFO | Prefer local NFO data; **turn off NFO export**, or limit it to the TV's own storage, so Nova never overwrites the apps' files |
| Jellyfin → each library → "Save artwork and metadata into media folders" (`SaveLocalMetadata`) | Keep **off**, so a third writer never competes |

The apps' NFO files carry the TMDb and TVDb IDs the stack uses and are rewritten on every upgrade, so titles and posters in Nova stay right even for Hindi and other non-English titles whose file names are hard to match. Radarr's "Movie metadata" writes `<file name>.nfo` unless **Use Movie Nfo** is ticked (`movie.nfo`); check which one your Nova build picks up.

## 3. Audio language and subtitles

* **Preferred audio language:** set it in Nova's settings on each TV (Hindi on one, English on another). A dual-audio file then opens in that TV's language. Older Nova builds applied it unreliably; keep Nova updated.
* **Preferred subtitle language:** same place.
* **Subtitle files:** Nova reads SRT, ASS and SUB files next to the video, and PGS from 6.4.1. Bazarr writes `.srt` files beside each video (its "subfolder" setting `current`), and Radarr/Sonarr carry `srt, ass, ssa, vtt` along on import.

## 4. Codecs your TVs can play

The [release profiles](MEDIA_RELEASE_PROFILES.md) follow what you told the Setup Wizard your players decode (`MEDIA_CODECS`):

| Codec | Default | Why |
| :--- | :--- | :--- |
| H.264 | Allowed | Plays everywhere |
| HEVC (x265, 10-bit) | **Preferred** | 30–50% smaller at the same quality; Android TVs from about 2016 decode it in hardware |
| AV1 | Blocked | Many TV chips lack hardware AV1, and software decoding can stutter at 1080p. Add `av1` to `MEDIA_CODECS` for newer TVs |
| Dolby Vision without HDR10 fallback | Blocked | Wrong (purple and green) colours on screens without Dolby Vision. Add `dv` if every TV supports it |
| HDR10 at 1080p | Neutral | Falls back cleanly |
| AC3, EAC3, DTS audio | Allowed | Nova decodes or passes them through |

To check a TV: play a sample of the codec from the share and watch for stutter or wrong colours; Nova's playback info shows whether decoding runs in hardware.

## 5. Resume files

Nova writes `<name>.archos.resume.xml` beside a file you stopped watching. After an upgrade replaces the video, the old resume file stays behind; it is harmless and small, and can be deleted.

## 6. Naming and browsing

With NFO files, Nova doesn't depend on file names, but short names are still easier to browse over SMB. The defaults keep `Title (Year)` folders. If you also want the audio languages in movie file names, Radarr's naming token `{MediaInfo AudioLanguages}` adds them with its own brackets (for example `[HI+EN]`); it leaves out a track list that is English only, while `{MediaInfo AudioLanguagesAll}` always shows it.

## 7. Server sleep

Every TV or PC with the share open holds an SMB session, and the Sleep Guard currently treats any session as activity, so an idle TV left on the share can keep the server awake at night ([Power management](POWER_MANAGEMENT_RTCWAKE.md)). Close Nova or let the TV sleep; a later release checks for open media files instead of sessions.

## Related

* [Release profiles and dual audio](MEDIA_RELEASE_PROFILES.md)
* [Low-power direct play](HASWELL_DIRECT_PLAY_GUIDE.md)
* [mediaserver module README](../apps/mediaserver/README.md)
