# Hardware Acceleration (VAAPI / QSV / NVIDIA) & Multi-Hardware Modes 🎬

## 1. Automated Render Node Probing
The system prober (`setup/config_core/system_prober.py`) automatically inspects the host hardware environment at boot and on-demand:
1. **Intel QuickSync / VAAPI:** Checks for the presence of Linux Direct Rendering Infrastructure (DRI) nodes:
   - `/dev/dri/renderD128` (Primary GPU compute & render node)
   - `/dev/dri/card0` (Direct Rendering Manager)
2. **NVIDIA GPUs:** Checks whether `nvidia-smi` is installed and reports active CUDA driver state.
3. **CPU Fallback:** If no dedicated render node or supported discrete GPU is detected, sets mode to `direct_play`.

Probed hardware acceleration status is exposed via `GET /api/probe` and displayed dynamically in both the Setup Wizard and Control Hub's **🤖 AI Copilot** drawer (`ai-hw-pill`).

---

## 2. Enabling Hardware Acceleration in Docker Compose

On modern systems (Intel Skylake 6th Gen+, Alder Lake-N N100/N200/N305, or discrete GPUs), enable hardware acceleration by passing the render node into Jellyfin in `apps/mediaserver/docker-compose.yml`:

```yaml
  jellyfin:
    container_name: jellyfin
    image: lscr.io/linuxserver/jellyfin:latest
    devices:
      - /dev/dri:/dev/dri # Enables Intel QuickSync & VAAPI inside the container
    environment:
      - PUID=${PUID:-1000}
      - PGID=${PGID:-1000}
      - TZ=${TZ:-Asia/Kolkata}
```

For NVIDIA GPUs, add the NVIDIA container toolkit runtime:
```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

---

## 3. Host Linux Permissions (`render` & `video` Groups)

Docker containers running under non-root users (`PUID=1000`) need read/write permissions to `/dev/dri/renderD128`:

```bash
# Add host user to render and video groups
sudo usermod -aG render,video $USER

# Inspect group permissions
ls -l /dev/dri/renderD128
# Expected: crw-rw---- 1 root render 226, 128 /dev/dri/renderD128
```

---

## 4. Hardware Profiles & Playback Strategy

* **Modern Intel (6th Gen+ / N100 / N200 / Core Ultra):**
  Configure Jellyfin under **Admin Dashboard -> Playback -> Transcoding**:
  - Hardware Acceleration: **Intel QuickSync (QSV)**
  - Enable Hardware Decoding for: H.264, HEVC, VP9, AV1 (on 11th Gen+ / N100).
  - VPP Tone Mapping: Enabled.
* **AMD Radeon / APUs:**
  - Hardware Acceleration: **VAAPI** (Device: `/dev/dri/renderD128`).
* **Legacy Low-Power CPUs (Haswell 4th Gen, Celeron, Atom):**
  - Keep hardware transcoding disabled.
  - Enforce **Direct Play** across all clients (<1.5% CPU utilization vs 100% transcode lock).
  - See [`HASWELL_DIRECT_PLAY_GUIDE.md`](HASWELL_DIRECT_PLAY_GUIDE.md).
