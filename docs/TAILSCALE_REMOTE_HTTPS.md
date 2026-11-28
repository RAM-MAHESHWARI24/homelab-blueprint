# Tailscale Remote HTTPS Access & Phone Tailnet Setup

Access Control Hub, Jellyfin, Immich, and Seerr securely from anywhere over encrypted HTTPS without opening router ports or forwarding traffic to the public internet.

> [!TIP]
> You do not need to manage TLS keys manually inside Control Hub. `tailscale serve` terminates HTTPS with automatically rotated Tailscale MagicDNS certificates and proxies traffic cleanly to `http://127.0.0.1:7575` with `X-Forwarded-Proto: https`.

---

## Prerequisites

1. **Tailscale installed on your server** (enabled during the Setup Wizard or verified in **System -> Network Ports, Tailscale & Port Map**).
2. **MagicDNS & HTTPS Certificates enabled** in the [Tailscale Admin Console -> DNS](https://login.tailscale.com/admin/dns):
   * Turn on **MagicDNS**.
   * Click **Enable HTTPS** under **HTTPS Certificates**.

---

## Option A: One-Command HTTPS Proxy (`tailscale serve`, Recommended)

Run one command over SSH on your server (replace `7575` only if you customized `PORT`):

```bash
sudo tailscale serve --bg 7575
```

What this does:
* Exposes `https://<node>.<tailnet>.ts.net` **only inside your private tailnet**.
* Requests and renews a valid Let's Encrypt TLS certificate automatically.
* Sends `X-Forwarded-Proto: https`, so Control Hub automatically marks browser session cookies `Secure` when reached over your tailnet URL while still working over plain `http://<server-lan-ip>:7575` on your home LAN.

Verify live status anytime:

```bash
tailscale serve status
```

To turn off remote HTTPS serving later:

```bash
sudo tailscale serve off
```

---

## Option B: Export Standalone TLS Certificates (`tailscale cert`)

If you terminate TLS with a custom reverse proxy (Caddy or Nginx) instead of `tailscale serve`, inspect your host's MagicDNS name in Control Hub (**System -> Network -> Tailscale Mesh**) and run:

```bash
sudo tailscale cert <node>.<tailnet>.ts.net
```

---

## Phone Onboarding (iOS & Android)

1. Install **Tailscale** from the App Store or Google Play Store on your phone.
2. Sign in with the same tailnet account (or share the node to a family member's Tailscale account with ACL access to your server).
3. Keep Tailscale connected on mobile data or away-from-home Wi-Fi.
4. Open **`https://<node>.<tailnet>.ts.net`** in Safari or Chrome — no certificate warning, and you can bookmark it or use Family View (`role=family`) if enabled in **Account -> Family View**.

---

## Troubleshooting

| Symptom | Fix |
| :--- | :--- |
| `tailscale serve` says HTTPS is not enabled | Open Tailscale Admin Console -> **DNS** and enable both **MagicDNS** and **HTTPS Certificates**. |
| Control Hub loads over HTTPS, but redirects fail or login doesn't stick | Ensure you run recent Control Hub (`X-Forwarded-Proto` aware cookies) and access via exact `https://<node>.<tailnet>.ts.net`. |
| Phone reaches Control Hub, but cannot reach other LAN ports | Check **Subnet Router** & **IPv4 Forwarding** in **System -> Network Ports, Tailscale & Port Map** (`net.ipv4.ip_forward=1`). |

---

## Related Documentation

* **[Networking: Tailscale & Samba](NETWORKING_TAILSCALE_SAMBA.md)** — Base mesh & subnet router setup
* **[Control Hub Configuration Center & AI Copilot](CONTROL_HUB_CONFIGURATION_CENTER.md)** — Dashboard configuration & diagnostics
* **[Documentation Hub](README.md)** — Full blueprint index
