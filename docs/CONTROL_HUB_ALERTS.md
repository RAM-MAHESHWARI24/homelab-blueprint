# Control Hub Alerts: Channels and Setup

The Control Hub can send you a message when something on the server needs attention:
a failed photo backup, a full disk, an app that stopped. This guide explains what
triggers an alert, how each delivery channel is set up, and how to fix the common
errors.

Everything here is configured in the dashboard: open the menu and choose **Alerts**.
No file editing or SSH is needed.

* [How alerts behave](#how-alerts-behave)
* [What triggers an alert](#what-triggers-an-alert)
* [Choosing a channel](#choosing-a-channel)
* [ntfy](#ntfy)
* [Telegram](#telegram)
* [Discord](#discord)
* [Email (SMTP)](#email-smtp)
* [Quiet hours and the daily summary](#quiet-hours-and-the-daily-summary)
* [Where settings are stored](#where-settings-are-stored)
* [Using the API](#using-the-api)
* [Troubleshooting](#troubleshooting)

---

## How alerts behave

* Rules are checked **once a minute** by a background thread inside the Control Hub.
* An alert is sent **once**, when it starts. Some rules wait first (an app must be
  down for 5 minutes, the CPU hot for 2 minutes), so short blips do not wake you up.
* While the problem lasts, the alert is **repeated every 24 hours**.
* When the problem clears you get a **"Resolved: ..."** message.
* Alerts go to **every channel that is switched on**. You can use several at once.
* If no channel is switched on, alerts are still listed under Alerts in the
  dashboard. The ones that are still open are sent as soon as you turn a channel on.
* The server cannot send anything while it is asleep (the nightly suspend) or off.

## What triggers an alert

| Rule | Severity | Default | Notes |
| --- | --- | --- | --- |
| Photo backup failed or was interrupted | Critical | on | From the backup's `status.json`. "Interrupted" means the run stopped without finishing (restart, power loss). |
| Backup remote not reachable | Critical | on | The backup pre-flight could not reach the rclone remote: usually an expired Google Drive login or a renamed remote. Sent instead of "backup failed". |
| No good photo backup for more than 26 hours | Warning | on | A nightly run was missed. The hour limit is `BACKUP_STALE_HOURS`. |
| Disk almost full | Critical | 95% | Checks `/`, the media folder and the photo folder. A disk shared by several folders is reported once. |
| Disk filling up | Warning | 85% | Same disks. Only one of the two disk alerts is open per disk. |
| App stopped or unhealthy | Warning | 5 minutes | Containers of the installed apps (Jellyfin, Sonarr, Radarr, Prowlarr, qBittorrent, Seerr, Bazarr, the photo server and the optional ones that exist). Add containers you stop on purpose to **Ignore these containers**. |
| CPU temperature high | Warning | 80 °C for 2 minutes | From the kernel's thermal zone. Not every machine reports one. |
| TV app update failed | Warning | on | New `[ERROR]` lines in the TV auto-updater log. Sent once per batch of errors; there is no "resolved" message. |
| Too many failed dashboard sign-ins | Warning | on | An address hit the sign-in lockout (10 wrong passwords in 5 minutes). |

Every rule can be switched off, and the numbers (percent, minutes, °C) can be changed
in the Alerts dialog. Press **Save** afterwards.

## Choosing a channel

| Channel | You need | Works away from home | Who can read the alerts | Effort |
| --- | --- | --- | --- | --- |
| **ntfy** on ntfy.sh | The ntfy app | Yes | Anyone who knows the topic name | 2 minutes |
| **ntfy** on ntfy.sh with an account | ntfy.sh account (reserving topics needs a paid plan) | Yes | Only your account | 5 minutes |
| **ntfy** on your own server | Docker, and Tailscale or a VPN for use away from home | With a VPN | Only users you create | 20 minutes |
| **Telegram** | A Telegram account | Yes | Only your chat with your own bot | 5 minutes |
| **Discord** | A Discord server you manage | Yes | Members of that channel | 2 minutes |
| **Email** | An SMTP account (for Gmail, an app password) | Yes | Whoever reads the mailbox | 5 minutes |

The alerts contain no passwords or keys: they say things like "/mnt/hdd/data is 88.5%
full" or "Radarr is exited". They do reveal your server's folder names and which apps
you run.

---

## ntfy

[ntfy](https://ntfy.sh) is a free, open-source push service. You subscribe to a
**topic** in the ntfy app; the Control Hub posts to that topic. There are apps for
Android (Google Play, F-Droid) and iPhone, and a web app at <https://ntfy.sh/app>.

Priorities used by the Control Hub:

| Alert | ntfy priority | Tag |
| --- | --- | --- |
| Critical | 5 (max: overrides Do Not Disturb if you allow it in the app) | 🚨 |
| Warning | 4 (high) | ⚠️ |
| Info, daily summary | 3 (default) | ℹ️ |
| Resolved | 2 (low) | ✅ |

### Option A: public ntfy.sh with a private topic (quickest)

On ntfy.sh, topics are not password protected: anyone who knows a topic's name can
read and post to it. A long random name is the protection, the same as a secret link.

1. In the dashboard, open **Alerts**. Under **ntfy**, leave **Server** as `https://ntfy.sh`.
2. Press **New topic**. It fills in a random name such as `homelab-k3x9q2m7v1p8w4z6`.
   Do not choose a short or guessable name (the dashboard refuses names under 12 characters).
3. Tick **Send alerts here** and press **Save**.
4. On your phone, open the ntfy app, tap **+**, and enter the same topic name
   (server `ntfy.sh`).
5. Back in the dashboard, press **Send test**. The test should appear on your phone
   within a few seconds.

Keep the topic out of screenshots and chat messages. If it leaks, press **New topic**,
**Save**, and subscribe to the new name.

### Option B: ntfy.sh with your own account and a reserved topic

With an ntfy.sh account you can reserve a topic so that only your account can use it.
Reserving topics is part of ntfy.sh's paid plans; see <https://ntfy.sh/#pricing>.

1. Sign up at <https://ntfy.sh/signup> and choose a plan that includes reserved topics.
2. In the web app, open **Account**, reserve a topic (for example
   `homelab-alerts-<something>`) and set access for everyone else to **deny**.
3. Under **Account → Access tokens**, create a token (it starts with `tk_`).
4. In the dashboard's ntfy section: server `https://ntfy.sh`, your reserved topic, and
   the token in **Access token**. Tick **Send alerts here**, **Save**, **Send test**.
5. In the phone app, sign in to the same account (**Settings → Manage users** on
   Android, or the account screen on iPhone) and subscribe to the topic.

### Option C: your own ntfy server with a password

Run ntfy on the home server (or any machine you control) and require a login for
everything. This is the only option where the messages never pass through a third
party.

**1. Run the server.** A minimal Docker Compose file (put it in its own folder, for
example `/srv/ntfy`):

```yaml
services:
  ntfy:
    image: binwiederhier/ntfy        # pin a version you have checked, e.g. binwiederhier/ntfy:v2.x.y
    container_name: ntfy
    command: serve
    restart: unless-stopped
    ports:
      - "2586:80"                    # pick any free port; check docs/PORT_BINDINGS_AND_CONFLICTS.md
    volumes:
      - ./etc:/etc/ntfy
      - ./cache:/var/cache/ntfy
      - ./lib:/var/lib/ntfy
    environment:
      TZ: Asia/Kolkata               # your time zone
```

and `./etc/server.yml`:

```yaml
base-url: "http://192.168.1.31:2586"          # how phones reach it (LAN IP or Tailscale name)
cache-file: "/var/cache/ntfy/cache.db"
auth-file: "/var/lib/ntfy/user.db"
auth-default-access: "deny-all"               # nothing is readable or writable without a login
behind-proxy: false
# iPhone only: instant notifications for a self-hosted server go through ntfy.sh's
# push relay, which only sees a message ID, not the content.
upstream-base-url: "https://ntfy.sh"
```

Start it with `docker compose up -d`.

**2. Create users and a token.** One user for your phone (read only) and one for the
Control Hub (write only):

```bash
docker exec -it ntfy ntfy user add phone           # asks for a password
docker exec -it ntfy ntfy access phone homelab-alerts read-only
docker exec -it ntfy ntfy user add hub
docker exec -it ntfy ntfy access hub homelab-alerts write-only
docker exec -it ntfy ntfy token add hub             # prints tk_...
```

**3. Point the Control Hub at it.** In the ntfy section: **Server**
`http://192.168.1.31:2586`, **Topic** `homelab-alerts`, **Access token** the `tk_...`
value. Tick **Send alerts here**, **Save**, **Send test**. Use the host address and
published port: the Control Hub runs on the host, not in the ntfy container's Docker
network, so `http://ntfy` does not resolve.

**4. Subscribe on the phone.** In the ntfy app, add your server
(`http://192.168.1.31:2586`) with the user `phone` and its password, then subscribe to
`homelab-alerts`.

Things to know:

* **Away from home** the phone can only reach the server through a VPN such as
  Tailscale (see [Networking: Tailscale and Samba](NETWORKING_TAILSCALE_SAMBA.md)). Do
  not forward the port on your router unless you put HTTPS in front of it.
* The ntfy container uses a little memory (tens of MB) and is off while the server sleeps,
  which does not matter: the server cannot send alerts while asleep either.
* The topic name no longer needs to be secret, because the server requires a login.
  The dashboard still asks for at least 12 characters.

---

## Telegram

Alerts arrive as messages from a bot you create. Only chats you add the bot to can
receive them.

1. In Telegram, open a chat with **@BotFather**, send `/newbot`, and follow the prompts
   (a display name, then a user name ending in `bot`). BotFather replies with a
   **token** like `123456789:AAH...`. Treat it as a password.
2. Open a chat with your new bot and send it any message (for example `/start`). A bot
   cannot write to you before you have written to it.
3. Find your **chat ID**: open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser (replace `<TOKEN>`).
   In the reply, look for `"chat":{"id":123456789,...}`. That number is the chat ID.
   * For a **group**, add the bot to the group, send a message in the group, and use
     the group's ID from the same page; group IDs are negative (for example
     `-1001234567890`).
4. In the dashboard's Telegram section, paste the **Bot token** and **Chat ID**, tick
   **Send alerts here**, **Save**, then **Send test**.

Messages are plain text: the alert title on the first line, the details below.

---

## Discord

Alerts are posted to a channel through a webhook.

1. In Discord, open **Server Settings → Integrations → Webhooks → New Webhook**
   (you need the *Manage Webhooks* permission).
2. Give it a name (for example "Home server"), choose the channel, and press
   **Copy Webhook URL**. The URL is the only credential: anyone who has it can post to
   the channel, so treat it as a password.
3. In the dashboard's Discord section, paste it into **Webhook URL**, tick **Send
   alerts here**, **Save**, then **Send test**.

Each alert is one message with the title in bold. Everyone who can see the channel
can read the alerts, so use a private channel.

---

## Email (SMTP)

The Control Hub signs in to an SMTP server and sends one email per alert. The subject
is the alert title.

| Field | What to enter |
| --- | --- |
| SMTP server | For example `smtp.gmail.com` |
| Port | `587` |
| Use STARTTLS | On. Turn off only for a local relay on port 25 that has no TLS. |
| User name | Usually your full email address |
| Password | The account's SMTP password or app password |
| From address | The sender. Empty uses the user name. Many providers require it to match the account. |
| Send to | Where alerts go. One address. |

Only STARTTLS on port 587 (or plain SMTP to a local relay) is supported. Port 465
("SMTPS", TLS from the first byte) is not; use 587 with the same provider instead.

### Gmail

Google does not accept your normal password for SMTP. You need an **app password**:

1. Turn on **2-Step Verification** for the Google account.
2. Open <https://myaccount.google.com/apppasswords>, create an app password (name it
   "Home server") and copy the 16 characters.
3. In the dashboard: server `smtp.gmail.com`, port `587`, STARTTLS on, user name your
   Gmail address, password the app password (spaces do not matter), From address your
   Gmail address, Send to the address that should receive alerts.
4. **Save**, then **Send test**.

Google Workspace accounts work the same way if the administrator allows app passwords.

### Other providers

Any provider that lets you send with a user name and password (or app password) over
STARTTLS on port 587 works: Fastmail, Zoho, Proton Mail Bridge, a transactional service
such as Brevo or Mailgun (their SMTP credentials), or your own mail server. Providers
that only allow OAuth sign-in for SMTP are not supported.

---

## Quiet hours and the daily summary

**Quiet hours** (default on, 23:00 to 07:00): only **critical** alerts are sent during
these hours. Warnings and "resolved" messages wait and arrive as one message,
"Overnight: N alert(s)", when quiet hours end. The times use the server's time zone.

**Daily summary** (default off): at the time you choose, one message lists every alert
that is still open, or says "Nothing needs attention".

## Where settings are stored

| File | Contents | Permissions |
| --- | --- | --- |
| `/var/lib/homelab/control-hub/alerts.json` | Channels, rules, quiet hours. Holds the bot token, webhook URL, ntfy token and SMTP password. | `0600`, owned by the `homelab` service account |
| `/var/lib/homelab/control-hub/alerts_state.json` | Open alerts, the overnight queue, recent history, last delivery result per channel | `0600` |

Both paths can be changed with `ALERTS_CONFIG_FILE` and `ALERTS_STATE_FILE` in
`/etc/homelab/control-hub.env` (standalone installs: the Control Hub's `.env`).

The dashboard never shows a stored secret: it shows `********`. Leaving `********` in
a field keeps the stored value; typing something else replaces it; clearing the field
removes it.

Back up `alerts.json` if you do not want to set the channels up again after a reinstall.

## Using the API

The same settings are available to scripts with the Control Hub's API token
(`/etc/homelab/control-hub.token`). Full details: `/api/docs` on your Control Hub.

```bash
TOKEN=$(sudo cat /etc/homelab/control-hub.token)
HUB=http://127.0.0.1:7575

# Current settings (secrets masked), open alerts and recent history
curl -s -H "Authorization: Bearer $TOKEN" $HUB/api/alerts

# Turn on ntfy with a topic
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"channels":{"ntfy":{"enabled":true,"server":"https://ntfy.sh","topic":"homelab-k3x9q2m7v1p8w4z6"}}}' \
  $HUB/api/alerts/config

# Send a test to one channel
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"channel":"ntfy"}' $HUB/api/alerts/test

# Check every rule now instead of waiting for the next minute
curl -s -X POST -H "Authorization: Bearer $TOKEN" $HUB/api/alerts/check
```

## Troubleshooting

Each channel shows its last result under its **Send test** button ("Last sent ..." or
"Last send failed: ..."). The message is the channel's own error.

| Message | Channel | Cause and fix |
| --- | --- | --- |
| `not configured` | any | A required field is empty: ntfy server and topic; Telegram token and chat ID; Discord URL; email server, port and recipient. |
| `HTTP 401` or `HTTP 403` | ntfy | The server requires a login: the access token is missing, wrong, or the token's user has no write access to the topic (`ntfy access`). |
| `HTTP 429` | ntfy | Rate limited. ntfy.sh limits anonymous publishing per IP; this only happens if something else on your network also posts a lot. |
| `HTTP 401` | Telegram | The bot token is wrong or was revoked in BotFather. |
| `HTTP 400: ... chat not found` | Telegram | Wrong chat ID, or you have not sent the bot a message yet. For groups, the bot must be a member. |
| `HTTP 403: ... bot was blocked by the user` | Telegram | Unblock the bot in Telegram and send it a message. |
| `HTTP 404` / `Unknown Webhook` | Discord | The webhook was deleted. Create a new one and paste its URL. |
| `(535, ... Username and Password not accepted)` | Email | Wrong password. For Gmail, use an app password, not the account password. |
| `Connection unexpectedly closed` or a timeout | Email | Wrong port or TLS mode. Use 587 with STARTTLS. Port 465 is not supported. |
| `Name or service not known`, `Connection refused`, timeouts | any | The server cannot reach the service: check its internet access, DNS and any outbound firewall. A self-hosted ntfy must be reachable at the address in **Server** from the host itself. |

**The test arrives but real alerts do not.** Check that the rule is switched on, that
the channel's **Send alerts here** box is ticked and saved, and whether you are inside
quiet hours (warnings wait until the morning). **Check now** in the Alerts dialog runs
every rule immediately and lists what it sent.

**An alert arrived once and never again.** That is by design: it repeats only every 24
hours while the problem lasts, and a "Resolved" message follows when it clears.

**No alerts at all from the server for hours.** The server may be asleep (see
[Power Management](POWER_MANAGEMENT_RTCWAKE.md)) or the Control Hub stopped. Alerts
come from the server itself, so they cannot report that the whole server is down. For
that, use an outside uptime monitor that pings the Control Hub's `/api/health`.
