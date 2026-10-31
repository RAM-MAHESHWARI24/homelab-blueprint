# Low-Power CPU & Direct Play Optimization Guide (Haswell, Celeron, Atom, & Low-TDP Processors) ⚡

## 1. The Challenge: Transcoding on Low-Power Hardware
Older low-power processors and energy-efficient architectures (such as 4th/5th Gen Intel Haswell/Broadwell like Core i3-4005U with HD Graphics 4400, Intel Celeron J1900/N5105, Intel Atom, older AMD APUs, or ARM SBCs) do not possess fixed-function hardware 10-bit HEVC (H.265) decoding blocks. Fixed-function QuickSync HEVC hardware decode was only introduced in Skylake (6th Gen+).

If a streaming client requests a software transcode of a 1080p or 4K HEVC / AV1 stream on these chips:
* CPU locks at **100% across all cores/threads**.
* Playback buffers and stutters every 3 to 5 seconds.
* Background services (torrent downloaders, database syncs, TV updates) starve for CPU cycles and crawl to a halt.

## 2. Automated Low-Power Detection
The blueprint's hardware probing engine (`setup/config_core/system_prober.py`) automatically detects low-power CPU models by inspecting `/proc/cpuinfo`:
* Matches keywords: `i3-4`, `i5-4`, `haswell`, `broadwell`, `celeron`, `atom`, `j1900`, `n5105`, `n100`.
* Sets `"is_low_power": true` in the system snapshot.
* Displays the active **"Low-Power Direct Play Profile"** in Control Hub's AI Copilot and Settings drawer.

## 3. The Solution: Direct Play Enforcement
When **Direct Play** is active:
* The server acts purely as a high-speed, zero-transcode file streamer.
* CPU usage drops to **< 1.5%**, leaving all cores cool and responsive.
* Memory consumption is minimal (< 100 MB).

## 4. Client Configuration Blueprint
To ensure 100% Direct Play across all household devices without server transcoding:
1. **Android TV & Google TV:**
   - Install the official **Jellyfin Android TV app**.
   - Under Settings -> Playback: Set Video Quality to **Maximum** / **Direct Stream Only**.
   - Select **ExoPlayer** or **LibVLC** as playback engine.
2. **Windows / Mac / Linux Laptops & Desktops:**
   - Use the **Jellyfin Media Player (JMP)** desktop application instead of standard web browsers. Web browsers (Chrome, Edge, Firefox, Safari) often lack native MKV container support or HEVC decoders, forcing the server into software transcode mode. JMP bundles built-in MPV decoders that Direct Play every codec natively.
3. **Mobile (iOS & Android):**
   - Ensure the mobile Jellyfin app has **Native Player** or **VLC/MPV engine** enabled in Client Settings.
