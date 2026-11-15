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

## 2. Samba Shares (`system/networking/homelab-shares.conf.example`)
Samba is an opt-in module of the Setup Wizard. The installer renders the template to `/etc/samba/homelab-shares.conf`, adds one `include =` line to `smb.conf`, validates with `testparm` and sets the host user's Samba password. `teardown.sh` removes both again.

* **`[Media]` (`DATA_DIR`, default `/mnt/hdd/data`):**
  - Browseable share for adding torrents, managing movies and playing media.
  - File permissions: `create mask = 0775`, `directory mask = 0775`.
* **`[Photos]` (`MEMORIES_DIR`):**
  - The photo library, with `vfs_fruit` extras for macOS clients.

No share exposes the root filesystem. Access is limited to the host user (`valid users = {{HOST_USER}}`).
