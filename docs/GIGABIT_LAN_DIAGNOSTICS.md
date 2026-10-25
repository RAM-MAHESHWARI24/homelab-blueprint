# Gigabit LAN Diagnostics & Ethernet Link Negotiation 🔌

## 1. Overview
Many compact homelab servers rely on USB-to-Gigabit adapters (e.g. Realtek RTL8153) or integrated onboard NICs. Under certain conditions (cable degradation, dirty RJ45 pins, power saving), the physical link auto-negotiation downshifts from **1000 Mbps (Gigabit)** to **100 Mbps (Fast Ethernet)**.

## 2. Diagnosing Link Speed in Linux
Check current negotiated speed and duplex mode:
```bash
sudo ethtool <interface-name> | grep -E "(Speed|Duplex|Auto-negotiation)"
```
Example Output:
```
Speed: 1000Mb/s
Duplex: Full
Auto-negotiation: on
```
If `Speed: 100Mb/s` is shown:
* Check all 8 pins of the RJ45 cable (Fast Ethernet uses 4 pins; Gigabit requires all 8 pins connected).
* Test forcing 1000Mb/s auto-negotiation:
  ```bash
  sudo ethtool -s <interface-name> speed 1000 duplex full autoneg on
  ```

## 3. Real-Time Telemetry in Control Hub
Control Hub tracks the physical link speed and compares live bandwidth consumption against maximum interface capacity. If the adapter downshifts to 100Mbps, Control Hub displays an amber indicator alerting the operator to check the cable connection.
