# Hardware Acceleration (VAAPI / QSV) & Low-Power Quirks 🎬

## 1. Hardware Render Nodes (`/dev/dri`)
On modern Intel CPUs (Skylake 6th Gen+ / Jasper Lake N5105 / Alder Lake-N N100):
Intel QuickSync provides zero-overhead GPU transcoding.

Verify the host DRI render node exists:
```bash
ls -l /dev/dri/renderD128
```
Example Output:
```
crw-rw---- 1 root render 226, 128 /dev/dri/renderD128
```

## 2. Linux Group Permissions
Docker containers running as `PUID=1000` must have permission to access `/dev/dri/renderD128`.
Add your host user to the `render` and `video` groups:
```bash
sudo usermod -aG render,video $USER
```
Check the group ID of `render`:
```bash
getent group render | cut -d: -f3 # Typically 107 or 992
```

## 3. Haswell 4th Gen Limitation Quirk
* **Intel Haswell (Core i3-4005U / HD Graphics 4400):**
  Haswell lacks fixed-function HEVC (H.265) 10-bit decoding hardware.
* Attempting to transcode a 4K HEVC stream locks CPU threads at 100%, causing playback to stutter every 3 seconds.
* **Resolution:** Enforce **Direct Play** across all clients (Jellyfin Media Player desktop app, ExoPlayer on Android TV). Direct Play streams the native file directly with <1.5% CPU utilization.
See [`HASWELL_DIRECT_PLAY_GUIDE.md`](file:///z:/opt/homelab-blueprint/docs/HASWELL_DIRECT_PLAY_GUIDE.md).
