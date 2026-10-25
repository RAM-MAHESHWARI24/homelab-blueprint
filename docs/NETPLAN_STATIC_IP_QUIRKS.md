# Netplan Static IP Configuration & SSH Safety Quirks 🌐

## 1. The SSH Lockout Danger
When applying network changes to a headless Ubuntu Server over SSH, any typographical error (e.g. invalid subnet CIDR, wrong gateway, YAML indentation) drops the network interface and permanently terminates the SSH session.

## 2. Safe Netplan Workflow
Never run `sudo netplan apply` directly over an SSH connection. Always follow this 3-step safe workflow:

### Step 1: Pre-Validate Syntax
```bash
sudo netplan generate
```
Validates YAML indentation, schema version, and interface names without applying changes. If an error is returned, stop immediately.

### Step 2: Test with Automated Rollback
```bash
sudo netplan try --timeout 45
```
Applies the configuration and prompts for confirmation. If the SSH session drops or the operator does not press ENTER within 45 seconds, **Netplan automatically reverts back to the previous working configuration**!

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
