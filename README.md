# WiFi BandLock - Decky Loader Plugin

A Decky Loader plugin for SteamOS / ROG Ally / Steam Deck that exposes all broadcasting frequency bands (2.4 GHz, 5 GHz, 6 GHz Wi-Fi 6E/7) under shared Wi-Fi SSID network names, with one-click band forcing and AP (BSSID) pinning.

---

## 🎯 Features

- **Live Band & Link Telemetry**:
  - Displays your current active Wi-Fi connection, current frequency band (**2.4 GHz**, **5 GHz**, or **6 GHz**), Channel, Frequency (MHz), Signal %, and Link Speed (Mbps).
  - Shows current lock status (`🔒 Locked to AP/Band` vs `🌐 Auto-Roaming`).
- **Multi-Band Network Breakdown**:
  - Groups broadcasting Access Points under their common SSID network name.
  - Color-coded badges for **6 GHz** (Purple/Cyan), **5 GHz** (Emerald), and **2.4 GHz** (Amber).
  - Displays signal strength meter and channel for every AP.
- **One-Click Band & AP Forcing**:
  - **Pin / Lock to AP**: Forces NetworkManager to stay connected to a specific BSSID MAC address.
  - **Force Band**: Forces connection strictly to 5 GHz or 2.4 GHz.
  - **Unlock / Auto-Band**: Instantly restores default dynamic roaming across all bands.
- **On-Demand Rescan**:
  - Real-time Wi-Fi rescan button to refresh signal strengths and nearby APs.

---

## 📦 Installation

To install or update the plugin:

```bash
chmod +x /home/deck/Decky-WiFi-BandLock/install.sh
/home/deck/Decky-WiFi-BandLock/install.sh
```

The plugin will appear in the Decky Loader sidebar menu under **WiFi BandLock** 📶.
