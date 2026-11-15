# Netplan Static IP Configuration & SSH Safety Quirks 🌐

## 1. The SSH Lockout Danger
When applying network changes to a headless Ubuntu Server over SSH, any typographical error (e.g. invalid subnet CIDR, wrong gateway, YAML indentation) drops the network interface and permanently terminates the SSH session.

## 2. Safe Netplan Workflow

### How the blueprint applies a static IP (wizard and Control Hub)
`netplan try` only reverts when the *same process* that started it is still alive to time out, which is useless from a web request that may itself lose the network. The blueprint uses a revert timer instead (`config_core/netplan_manager.py`, run through the privileged `netplan_cli.py` helper):

1. Back up `/etc/netplan/*.yaml`.
2. Write the new file and run `netplan generate`. A syntax or schema error stops here; nothing changed.
3. Arm a transient systemd timer, `homelab-netplan-revert` (default 120 s), that restores the backup and re-applies it.
4. `netplan apply`.
5. The operator confirms **from the new address**: the Setup Wizard sends the browser to `http://<new-ip>:8000/?token=…&netplan_confirm=1`, the Control Hub exposes `POST /api/config/netplan-confirm`. Confirming cancels the timer and deletes the backup. The wizard stays up until the revert window has passed.

If the new address is unreachable, nobody confirms, and the old configuration is back within the timeout. `GET /api/config/netplan-status` reports whether a change is pending and how long is left.

### Doing it by hand over SSH
Never run `sudo netplan apply` directly over an SSH connection. Validate first:
```bash
sudo netplan generate
```
Then apply with Netplan's own interactive rollback:
```bash
sudo netplan try --timeout 45
```
If the SSH session drops or you do not press ENTER within 45 seconds, Netplan reverts to the previous configuration.

## 3. Netplan v2 Format Quirks (Ubuntu 22.04 / 24.04 / 26.04)

### Deprecated Syntax (Do NOT Use):
```yaml
# ❌ DEPRECATED (Will cause netplan warnings):
gateway4: 192.168.1.1
```

### Modern Netplan v2 Format (Correct):
```yaml
# ✅ MODERN STANDARD:
network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: false
      addresses:
        - 192.168.1.100/24
      routes:
        - to: default
          via: 192.168.1.1
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
```

## 4. Cloud-Init Interference
If Ubuntu Server was installed using cloud-init, `/etc/netplan/50-cloud-init.yaml` may regenerate on reboot.
To disable cloud-init network auto-generation:
```bash
echo "network: {config: disabled}" | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
```
Place homelab custom static configuration in `/etc/netplan/99-homelab-blueprint.yaml` (highest numerical priority).
