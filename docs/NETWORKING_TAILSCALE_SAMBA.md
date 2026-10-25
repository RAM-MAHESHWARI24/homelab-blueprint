# Networking Blueprint: Tailscale Subnet Routing & Samba Shares 🌐

## 1. Tailscale Subnet Routing (Zero Router Port Forwarding)
To securely access home server services (Jellyfin, Immich, Control Hub) from outside the house without exposing open ports to the public internet:

### Configuration
1. Enable IP forwarding in `/etc/sysctl.d/99-tailscale.conf`:
   ```ini
   net.ipv4.ip_forward = 1
   net.ipv6.conf.all.forwarding = 1
   ```
2. Apply changes: `sudo sysctl -p /etc/sysctl.d/99-tailscale.conf`
3. Advertise your local home LAN subnet:
   ```bash
   sudo tailscale up --advertise-routes=192.168.1.0/24
   ```
4. In the Tailscale Admin Console, approve the subnet route under your server device settings.

All Tailscale-connected phones and laptops can now access `http://<your-server-ip>:7575` directly from cellular or external Wi-Fi networks.

---

## 2. Samba Dual-Share Setup (`smb.conf`)
Samba provides network access from Windows and Mac computers.

* **Share 1: `[MediaDrive]` (`/mnt/hdd/data`):**
  - Browseable network folder for adding torrents, managing movies, and playing media.
  - File permissions: `create mask = 0775`, `directory mask = 0775`.
* **Share 2: `[RootFS]` (`/`):**
  - Hidden administrative share (`browseable = no`).
  - Useful for direct file editing from VS Code or developer tools over LAN.
