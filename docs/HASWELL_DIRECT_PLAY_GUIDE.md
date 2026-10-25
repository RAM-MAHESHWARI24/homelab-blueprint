# Low-Power CPU & Direct Play Optimization Guide ⚡

## 1. The Challenge: Transcoding on Low-Power Hardware
Older low-power CPUs (such as Intel Haswell Core i3-4005U with dual cores @ 1.70GHz and HD Graphics 4400) do not possess hardware HEVC 10-bit decoding blocks (QuickSync HEVC arrived in Skylake 6th Gen+).

If a client requests a transcode of a 1080p or 4K HEVC stream:
* CPU locks at **100% across all 4 threads**.
* Buffer pauses every 3 seconds.
* Background services (downloaders, database backups) crawl to a halt.

## 2. The Solution: Direct Play Enforcement
When **Direct Play** is active:
* The server acts purely as a high-speed file streamer.
* CPU usage drops to **< 1.5%**.
* Memory consumption is minimal (< 100 MB).

## 3. Client Configuration Blueprint
To ensure 100% Direct Play across all household devices:
1. **Android TV & Google TV:**
   - Install official **Jellyfin Android TV app**.
   - Under Settings -> Playback: Set Video Quality to **Maximum** / **Direct Stream Only**.
   - Enable **ExoPlayer** as playback engine.
2. **Windows / Mac Laptops:**
   - Use **Jellyfin Media Player (JMP)** desktop application instead of web browsers. Web browsers (Chrome, Edge, Firefox) often lack native MKV container support or HEVC decoders, forcing the server to transcode. JMP includes built-in MPV decoders that Direct Play every codec natively.
3. **Mobile (iOS & Android):**
   - Ensure the mobile app has **Native Player** or **VLC/MPV engine** enabled.
