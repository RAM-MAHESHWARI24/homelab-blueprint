# Port Bindings, Network Mapping & Conflict Resolution 🔌

## 1. Master Homelab Blueprint Port Map

| Port | Service | Subsystem | Protocol | Default URL |
| :--- | :--- | :--- | :--- | :--- |
| **7575** | **Control Hub Dashboard** | Core UI | TCP | `http://<server-ip>:7575` |
| **8000** | **Setup Wizard** | Installer | TCP | `http://<server-ip>:8000` |
| **8096** | **Jellyfin Streaming** | Media | TCP | `http://<server-ip>:8096` |
| **8920** | Jellyfin HTTPS | Media | TCP | `https://<server-ip>:8920` |
| **5055** | **Seerr (Jellyseerr)** | Media | TCP | `http://<server-ip>:5055` |
| **8080** | **qBittorrent WebUI** | Ingest | TCP | `http://<server-ip>:8080` |
| **6881** | qBittorrent Listening | Ingest | TCP/UDP | Peer-to-Peer |
| **7878** | **Radarr (Movies)** | Ingest | TCP | `http://<server-ip>:7878` |
| **8989** | **Sonarr (TV)** | Ingest | TCP | `http://<server-ip>:8989` |
| **9696** | **Prowlarr (Indexers)**| Ingest | TCP | `http://<server-ip>:9696` |
| **6767** | **Bazarr (Subtitles)** | Ingest | TCP | `http://<server-ip>:6767` |
| **8191** | **Byparr** | Solver | TCP | `http://<server-ip>:8191` |
| **2283** | **Noodle Gallery** | Photos | TCP | `http://<server-ip>:2283` |

## 2. Common Port Collisions & Diagnosis

### Port 8080 Collision:
Port 8080 is often used by proxy daemons, Apache, Tomcat, or dev servers.
Diagnose what process owns port 8080:
```bash
sudo lsof -i :8080 || sudo ss -tulpn | grep 8080
```
Resolution: Remap in `apps/control-hub/.env` and `apps/mediaserver/docker-compose.yml`:
```yaml
ports:
  - "8085:8080" # Maps host 8085 to container 8080
```

### Port 2283 Collision:
If a previous Immich instance is running:
```bash
sudo lsof -i :2283
```
Remap `GALLERY_PORT=2284` in `apps/noodle-gallery/.env`.
