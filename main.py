import asyncio
import subprocess
import re
import json
import logging
import os
import time
import urllib.request
import statistics
import ssl
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WiFi-BandLock")

MAC_REGEX = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
ALLOWED_BANDS = {"2.4ghz", "2.4g", "2.4", "5ghz", "5g", "5", "6ghz", "6g", "6"}

TRI_BAND_FREQS = [
    # 2.4 GHz
    "2412", "2417", "2422", "2427", "2432", "2437", "2442", "2447", "2452", "2457", "2462",
    # 5 GHz
    "5180", "5200", "5220", "5240", "5260", "5280", "5300", "5320",
    "5500", "5520", "5540", "5560", "5580", "5600", "5620", "5640", "5660", "5680", "5700", "5720",
    "5745", "5765", "5785", "5805", "5825",
    # 6 GHz (Wi-Fi 6E/7 PSC Preferred Scanning Channels)
    "5955", "5975", "6035", "6095", "6155", "6215", "6275", "6295", "6335", "6395", "6455",
    "6515", "6575", "6635", "6695", "6755", "6815", "6875", "6935", "6995", "7055", "7115"
]

def run_cmd(cmd, timeout=10):
    """Executes a command using explicit argument arrays without shell expansion."""
    exec_cmd = cmd if os.geteuid() == 0 else (["sudo", "-n"] + cmd if cmd[0] != "sudo" else cmd)
    try:
        res = subprocess.run(exec_cmd, capture_output=True, text=True, timeout=timeout)
        if res.returncode != 0 and os.geteuid() != 0:
            fallback = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if fallback.returncode == 0:
                return fallback
        return res
    except Exception as e:
        logger.error(f"Command error: {cmd} - {e}")
        raise

def run_nmcli(args, timeout=10):
    """Executes nmcli directly using explicit argument arrays."""
    return run_cmd(["nmcli"] + args, timeout=timeout)

def get_wifi_interface():
    """Dynamically detects the primary Wi-Fi interface name (e.g. wlan0, wlp1s0)."""
    try:
        res = run_nmcli(["-t", "-f", "DEVICE,TYPE,STATE", "device"], timeout=4)
        for line in res.stdout.strip().splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] == "wifi":
                return parts[0]
    except Exception:
        pass
    return "wlan0"

def get_channel_from_freq(freq_mhz):
    """Calculates official Wi-Fi channel number from frequency in MHz."""
    if 2412 <= freq_mhz <= 2484:
        if freq_mhz == 2484:
            return "14"
        return str(int((freq_mhz - 2407) / 5))
    elif 5150 <= freq_mhz <= 5895:
        return str(int((freq_mhz - 5000) / 5))
    elif 5925 <= freq_mhz <= 7125:
        return str(int((freq_mhz - 5950) / 5)) if freq_mhz >= 5950 else "1"
    return "0"

def clean_ssid(raw_ssid):
    """Decodes hex escapes in SSIDs and filters out null/hidden network names."""
    if not raw_ssid:
        return ""
    try:
        def unescape_match(m):
            b = bytes.fromhex(m.group(1))
            return b.decode("utf-8", errors="ignore")
        s = re.sub(r"\\x([0-9a-fA-F]{2})", unescape_match, raw_ssid)
    except Exception:
        s = raw_ssid
    s = s.strip()
    if not s or s.replace("\x00", "") == "":
        return ""
    return s

IWD_CONFIG_PATH = "/etc/iwd/main.conf"

def get_iwd_locked_band():
    """Reads /etc/iwd/main.conf to see if a band rank modifier is currently active."""
    try:
        if not os.path.exists(IWD_CONFIG_PATH):
            return ""
        with open(IWD_CONFIG_PATH, "r") as f:
            content = f.read()
        m6 = re.search(r"BandModifier6GHz\s*=\s*([0-9.]+)", content)
        m5 = re.search(r"BandModifier5GHz\s*=\s*([0-9.]+)", content)
        m2 = re.search(r"BandModifier2_4GHz\s*=\s*([0-9.]+)", content)
        v6 = float(m6.group(1)) if m6 else 1.0
        v5 = float(m5.group(1)) if m5 else 1.0
        v2 = float(m2.group(1)) if m2 else 1.0
        if v6 > v5 and v6 > v2 and v6 >= 2.0:
            return "6 GHz"
        if v5 > v6 and v5 > v2 and v5 >= 2.0:
            return "5 GHz"
        if v2 > v6 and v2 > v5 and v2 >= 2.0:
            return "2.4 GHz"
        return ""
    except Exception as e:
        logger.debug(f"Error reading iwd config: {e}")
        return ""

def set_iwd_band_lock(band):
    """
    Sets IWD [Rank] BandModifiers in /etc/iwd/main.conf to force connection to 6GHz, 5GHz, or 2.4GHz.
    Pass band=None or empty string to remove the configuration and restore auto-roaming.
    """
    try:
        if not band:
            if os.path.exists(IWD_CONFIG_PATH):
                try:
                    os.remove(IWD_CONFIG_PATH)
                except Exception:
                    run_cmd(["rm", "-f", IWD_CONFIG_PATH], timeout=5)
            run_cmd(["systemctl", "restart", "iwd"], timeout=10)
            return True

        b = band.lower().strip()
        if "6" in b:
            config_text = "[Rank]\nBandModifier6GHz=9.0\nBandModifier5GHz=0.01\nBandModifier2_4GHz=0.01\n"
        elif "5" in b:
            config_text = "[Rank]\nBandModifier5GHz=9.0\nBandModifier6GHz=0.01\nBandModifier2_4GHz=0.01\n"
        elif "2.4" in b or "2" in b:
            config_text = "[Rank]\nBandModifier2_4GHz=9.0\nBandModifier5GHz=0.01\nBandModifier6GHz=0.01\n"
        else:
            return False

        if os.geteuid() == 0:
            os.makedirs(os.path.dirname(IWD_CONFIG_PATH), exist_ok=True)
            with open(IWD_CONFIG_PATH, "w") as f:
                f.write(config_text)
        else:
            tmp_path = "/tmp/iwd_main.conf"
            with open(tmp_path, "w") as f:
                f.write(config_text)
            run_cmd(["mkdir", "-p", os.path.dirname(IWD_CONFIG_PATH)], timeout=5)
            run_cmd(["cp", tmp_path, IWD_CONFIG_PATH], timeout=5)
            run_cmd(["chmod", "644", IWD_CONFIG_PATH], timeout=5)
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        run_cmd(["systemctl", "restart", "iwd"], timeout=10)
        return True
    except Exception as e:
        logger.error(f"Error setting IWD band lock: {e}")
        return False

class SpeedTestWorker:
    """Live background worker providing streaming speed test metrics."""
    def __init__(self):
        self.state = {
            "running": False,
            "phase": "idle", # idle, ping, download, upload, done, error
            "progress": 0,
            "current_speed": 0.0,
            "ping_ms": 0.0,
            "jitter_ms": 0.0,
            "download_mbps": 0.0,
            "upload_mbps": 0.0,
            "error": None,
            "timestamp": ""
        }
        self._thread = None
        self._lock = threading.Lock()

    def get_state(self):
        with self._lock:
            return dict(self.state)

    def start(self):
        with self._lock:
            if self.state["running"]:
                return self.get_state()
            self.state = {
                "running": True,
                "phase": "ping",
                "progress": 5,
                "current_speed": 0.0,
                "ping_ms": 0.0,
                "jitter_ms": 0.0,
                "download_mbps": 0.0,
                "upload_mbps": 0.0,
                "error": None,
                "timestamp": ""
            }
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self.get_state()

    def _run(self):
        try:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            # 1. Ping Phase (~1.5s)
            with self._lock:
                self.state["phase"] = "ping"
                self.state["progress"] = 15
            
            ping_res = subprocess.run(["ping", "-c", "5", "-W", "2", "1.1.1.1"], capture_output=True, text=True, timeout=6)
            times = []
            if ping_res.returncode == 0:
                for line in ping_res.stdout.splitlines():
                    if "time=" in line:
                        try:
                            times.append(float(line.split("time=")[1].split()[0]))
                        except Exception:
                            pass
            if times:
                with self._lock:
                    self.state["ping_ms"] = round(statistics.mean(times), 1)
                    self.state["jitter_ms"] = round(statistics.stdev(times), 1) if len(times) > 1 else 0.0
            
            # 2. Download Phase (~4-5s, 60MB continuous stream)
            with self._lock:
                self.state["phase"] = "download"
                self.state["progress"] = 25
            
            total_bytes = 0
            t_start = time.time()
            for url in ["https://speed.cloudflare.com/__down?bytes=60000000", "http://speed.cloudflare.com/__down?bytes=60000000"]:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Decky-WiFi-BandLock)"})
                    t_start = time.time()
                    total_bytes = 0
                    with urllib.request.urlopen(req, timeout=15, context=ssl_ctx if url.startswith("https") else None) as resp:
                        while True:
                            chunk = resp.read(131072) # 128KB
                            if not chunk:
                                break
                            total_bytes += len(chunk)
                            elapsed = max(0.001, time.time() - t_start)
                            cur_mbps = round((total_bytes * 8) / (elapsed * 1_000_000), 1)
                            with self._lock:
                                self.state["current_speed"] = cur_mbps
                                self.state["download_mbps"] = cur_mbps
                                self.state["progress"] = min(65, int(25 + 40 * (total_bytes / 60000000)))
                    if total_bytes > 0:
                        break
                except Exception as e:
                    logger.warning(f"Download speedtest notice: {e}")
            
            # 3. Upload Phase (~3-4s, 15MB burst)
            with self._lock:
                self.state["phase"] = "upload"
                self.state["progress"] = 65
                self.state["current_speed"] = 0.0
            
            ul_data = b"0" * (5 * 1024 * 1024) # 5MB per burst
            total_ul_bytes = 0
            t_ul_start = time.time()
            for i in range(3): # 15MB total upload
                for url in ["https://speed.cloudflare.com/__up", "http://speed.cloudflare.com/__up"]:
                    try:
                        req = urllib.request.Request(url, data=ul_data, method="POST", headers={"User-Agent": "Mozilla/5.0 (Decky-WiFi-BandLock)"})
                        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx if url.startswith("https") else None) as resp:
                            _ = resp.read()
                        total_ul_bytes += len(ul_data)
                        elapsed = max(0.001, time.time() - t_ul_start)
                        cur_ul_mbps = round((total_ul_bytes * 8) / (elapsed * 1_000_000), 1)
                        with self._lock:
                            self.state["current_speed"] = cur_ul_mbps
                            self.state["upload_mbps"] = cur_ul_mbps
                            self.state["progress"] = min(95, int(65 + 30 * ((i + 1) / 3)))
                        break
                    except Exception as e:
                        logger.warning(f"Upload speedtest notice: {e}")

            # Done
            with self._lock:
                self.state["running"] = False
                self.state["phase"] = "done"
                self.state["progress"] = 100
                self.state["timestamp"] = time.strftime("%H:%M:%S")

        except Exception as e:
            with self._lock:
                self.state["running"] = False
                self.state["phase"] = "error"
                self.state["error"] = str(e)

_speed_worker = SpeedTestWorker()

class Plugin:
    async def get_wifi_status(self):
        """Returns current Wi-Fi interface status, active connection, and lock state."""
        try:
            iface = get_wifi_interface()
            radio_res = run_nmcli(["radio", "wifi"], timeout=5)
            wifi_enabled = radio_res.stdout.strip().lower() == "enabled"

            if not wifi_enabled:
                return {
                    "enabled": False,
                    "connected": False,
                    "interface": iface,
                    "ssid": "",
                    "bssid": "",
                    "band": "",
                    "channel": "",
                    "freq": "",
                    "signal": 0,
                    "rate": "",
                    "is_locked": False,
                    "locked_bssid": "",
                    "locked_band": "",
                    "connection_name": "",
                    "connection_uuid": ""
                }

            conn_res = run_nmcli(
                ["-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show", "--active"],
                timeout=5
            )
            
            active_conn = None
            for line in conn_res.stdout.strip().splitlines():
                if not line:
                    continue
                parts = line.split(":")
                if len(parts) >= 4 and parts[2] == "802-11-wireless":
                    active_conn = {
                        "name": parts[0],
                        "uuid": parts[1],
                        "device": parts[3]
                    }
                    break

            if not active_conn:
                return {
                    "enabled": True,
                    "connected": False,
                    "interface": iface,
                    "ssid": "",
                    "bssid": "",
                    "band": "",
                    "channel": "",
                    "freq": "",
                    "signal": 0,
                    "rate": "",
                    "is_locked": False,
                    "locked_bssid": "",
                    "locked_band": "",
                    "connection_name": "",
                    "connection_uuid": ""
                }

            bssid_q = run_nmcli(
                ["-g", "802-11-wireless.bssid", "connection", "show", active_conn["uuid"]],
                timeout=4
            )
            band_q = run_nmcli(
                ["-g", "802-11-wireless.band", "connection", "show", active_conn["uuid"]],
                timeout=4
            )
            
            locked_bssid = bssid_q.stdout.strip().replace(r"\:", ":")
            if locked_bssid == "--":
                locked_bssid = ""
            
            locked_band = band_q.stdout.strip()
            if locked_band == "--":
                locked_band = ""

            iw_link = run_cmd(["iw", "dev", active_conn["device"], "link"], timeout=5)
            curr_bssid = ""
            curr_ssid = active_conn["name"]
            curr_freq = ""
            curr_signal_dbm = -100
            curr_bitrate = ""
            
            for line in iw_link.stdout.strip().splitlines():
                l = line.strip()
                if l.startswith("Connected to"):
                    match = re.search(r"Connected to ([0-9a-fA-F:]{17})", l)
                    if match:
                        curr_bssid = match.group(1).upper()
                elif l.startswith("SSID:"):
                    curr_ssid = clean_ssid(l[5:].strip()) or active_conn["name"]
                elif l.startswith("freq:"):
                    curr_freq = l.split()[1]
                elif l.startswith("signal:"):
                    try:
                        curr_signal_dbm = float(l.split()[1].replace("dBm", ""))
                    except Exception:
                        pass
                elif l.startswith("tx bitrate:"):
                    curr_bitrate = l.split("tx bitrate:")[1].strip()

            freq_num = 0
            try:
                freq_num = int(float(curr_freq))
            except Exception:
                pass

            if freq_num > 0:
                if freq_num < 3000:
                    band = "2.4 GHz"
                elif freq_num < 5900:
                    band = "5 GHz"
                else:
                    band = "6 GHz"
                channel = get_channel_from_freq(freq_num)
            else:
                band = "Unknown"
                channel = "0"

            signal_pct = max(0, min(100, int(2 * (curr_signal_dbm + 100))))
            locked_band_iwd = get_iwd_locked_band()
            locked_band = locked_band_iwd or locked_band
            is_locked = bool(locked_bssid or locked_band)

            return {
                "enabled": True,
                "connected": True,
                "interface": active_conn["device"],
                "connection_name": active_conn["name"],
                "connection_uuid": active_conn["uuid"],
                "ssid": curr_ssid,
                "bssid": curr_bssid,
                "band": band,
                "channel": channel,
                "freq": f"{freq_num} MHz" if freq_num else "",
                "signal": signal_pct,
                "rate": curr_bitrate,
                "security": "WPA2/WPA3",
                "is_locked": is_locked,
                "locked_bssid": locked_bssid,
                "locked_band": locked_band
            }
        except Exception as e:
            logger.error(f"Error getting wifi status: {e}")
            return {"error": str(e), "enabled": False, "connected": False}

    def __init__(self):
        self._cached_aps = {}  # (ssid, bssid) -> dict with seen timestamp

    async def scan_networks(self, rescan=True):
        """Scans for all available Wi-Fi networks across 2.4 GHz, 5 GHz, and 6 GHz."""
        try:
            iface = get_wifi_interface()
            if rescan:
                try:
                    run_cmd(["iw", "dev", iface, "scan"], timeout=8)
                except Exception as e:
                    logger.debug(f"Active scan notice: {e}")
            
            res = run_cmd(["iw", "dev", iface, "scan", "dump"], timeout=8)
            
            # If 6 GHz is not present in dump, do quick targeted PSC scan
            if not re.search(r"freq:\s*6\d{3}", res.stdout):
                try:
                    scan_cmd = ["iw", "dev", iface, "scan", "freqs"] + TRI_BAND_FREQS[27:]
                    run_cmd(scan_cmd, timeout=8)
                    res = run_cmd(["iw", "dev", iface, "scan", "dump"], timeout=8)
                except Exception as e:
                    logger.debug(f"6GHz PSC scan notice: {e}")

            conn_res = run_nmcli(["-t", "-f", "NAME,UUID,TYPE", "connection", "show"], timeout=5)
            iwd_band = get_iwd_locked_band()
            saved_conns = {}
            for line in conn_res.stdout.strip().splitlines():
                if not line:
                    continue
                parts = line.split(":")
                if len(parts) >= 3 and parts[2] == "802-11-wireless":
                    name = parts[0]
                    uuid = parts[1]
                    bssid_q = run_nmcli(["-g", "802-11-wireless.bssid", "connection", "show", uuid], timeout=3)
                    band_q = run_nmcli(["-g", "802-11-wireless.band", "connection", "show", uuid], timeout=3)
                    lb = bssid_q.stdout.strip().replace(r"\:", ":")
                    lband = band_q.stdout.strip()
                    saved_conns[name] = {
                        "uuid": uuid,
                        "locked_bssid": lb if lb != "--" else "",
                        "locked_band": iwd_band or (lband if lband != "--" else "")
                    }

            now = time.time()

            # 1. Parse raw iw scan dump (accurate 6 GHz, dBm, capabilities)
            bss_blocks = res.stdout.split("BSS ")
            for b in bss_blocks[1:]:
                lines = b.splitlines()
                bssid_match = re.match(r"^([0-9a-fA-F:]{17})", lines[0])
                if not bssid_match:
                    continue
                bssid = bssid_match.group(1).upper()
                associated = "-- associated" in lines[0]

                raw_ssid = ""
                freq_mhz = 0
                signal_dbm = -100
                security = "Open"

                for line in lines[1:]:
                    l = line.strip()
                    if l.startswith("freq:"):
                        try:
                            freq_mhz = int(float(l.split()[1]))
                        except Exception:
                            pass
                    elif l.startswith("SSID:"):
                        raw_ssid = l[5:].strip()
                    elif l.startswith("signal:"):
                        try:
                            signal_dbm = float(l.split()[1].replace("dBm", ""))
                        except Exception:
                            pass
                    elif "RSN:" in l or "WPA:" in l or "WPA2" in l:
                        security = "WPA2"
                    elif "SAE" in l or "WPA3" in l:
                        security = "WPA3"

                ssid = clean_ssid(raw_ssid)
                if not ssid:
                    continue

                signal_pct = max(0, min(100, int(2 * (signal_dbm + 100))))

                if freq_mhz < 3000:
                    band = "2.4 GHz"
                    band_id = "2.4ghz"
                elif freq_mhz < 5900:
                    band = "5 GHz"
                    band_id = "5ghz"
                else:
                    band = "6 GHz"
                    band_id = "6ghz"

                channel = get_channel_from_freq(freq_mhz)
                key = (ssid, bssid)
                self._cached_aps[key] = {
                    "ssid": ssid,
                    "bssid": bssid,
                    "freq_mhz": freq_mhz,
                    "freq_str": f"{freq_mhz} MHz",
                    "band": band,
                    "band_id": band_id,
                    "channel": channel,
                    "signal": signal_pct,
                    "security": security,
                    "in_use": associated,
                    "last_seen": now
                }

            # 2. Parse NetworkManager's persistent Wi-Fi cache (preserves 2.4/5 GHz when connected on 6 GHz)
            nm_wifi_res = run_nmcli(["-t", "-f", "SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY", "dev", "wifi", "list"], timeout=5)
            for line in nm_wifi_res.stdout.strip().splitlines():
                if not line:
                    continue
                clean_line = line.replace(r"\:", "__COLON__")
                parts = [p.replace("__COLON__", ":") for p in clean_line.split(":")]
                if len(parts) >= 6:
                    nm_ssid = clean_ssid(parts[0])
                    nm_bssid = parts[1].upper()
                    if not nm_ssid or not MAC_REGEX.match(nm_bssid):
                        continue
                    nm_chan = parts[2]
                    nm_freq_str = parts[3]
                    nm_signal_pct = 0
                    try:
                        nm_signal_pct = int(parts[4])
                    except Exception:
                        pass
                    nm_sec = "WPA3" if "SAE" in parts[5] or "WPA3" in parts[5] else "WPA2" if "WPA" in parts[5] else "Open"
                    
                    nm_freq_mhz = 0
                    if "MHz" in nm_freq_str:
                        try:
                            nm_freq_mhz = int(nm_freq_str.replace("MHz", "").strip())
                        except Exception:
                            pass
                    
                    if nm_freq_mhz < 3000:
                        nm_band = "2.4 GHz"
                        nm_band_id = "2.4ghz"
                    elif nm_freq_mhz < 5900:
                        nm_band = "5 GHz"
                        nm_band_id = "5ghz"
                    else:
                        nm_band = "6 GHz"
                        nm_band_id = "6ghz"

                    key = (nm_ssid, nm_bssid)
                    if key not in self._cached_aps or (now - self._cached_aps[key].get("last_seen", 0) > 10):
                        self._cached_aps[key] = {
                            "ssid": nm_ssid,
                            "bssid": nm_bssid,
                            "freq_mhz": nm_freq_mhz,
                            "freq_str": nm_freq_str or f"{nm_freq_mhz} MHz",
                            "band": nm_band,
                            "band_id": nm_band_id,
                            "channel": nm_chan or get_channel_from_freq(nm_freq_mhz),
                            "signal": nm_signal_pct,
                            "security": nm_sec,
                            "in_use": False,
                            "last_seen": now
                        }

            # 3. Clean up cache and group APs by SSID
            grouped = {}
            expired_keys = []
            for (s, b), ap_data in self._cached_aps.items():
                # Keep active/saved networks permanently, others for 5 minutes
                if (now - ap_data.get("last_seen", 0) > 300) and (s not in saved_conns):
                    expired_keys.append((s, b))
                    continue

                if s not in grouped:
                    conn_info = saved_conns.get(s, {})
                    grouped[s] = {
                        "ssid": s,
                        "security": ap_data["security"],
                        "is_connected": False,
                        "has_saved_profile": s in saved_conns,
                        "connection_uuid": conn_info.get("uuid", ""),
                        "locked_bssid": conn_info.get("locked_bssid", ""),
                        "locked_band": conn_info.get("locked_band", ""),
                        "aps": []
                    }

                is_locked = bool(grouped[s]["locked_bssid"] and grouped[s]["locked_bssid"].lower() == b.lower())
                if ap_data["in_use"]:
                    grouped[s]["is_connected"] = True

                grouped[s]["aps"].append({
                    "bssid": b,
                    "freq_mhz": ap_data["freq_mhz"],
                    "freq_str": ap_data["freq_str"],
                    "band": ap_data["band"],
                    "band_id": ap_data["band_id"],
                    "channel": ap_data["channel"],
                    "rate": "",
                    "signal": ap_data["signal"],
                    "security": ap_data["security"],
                    "in_use": ap_data["in_use"],
                    "is_locked": is_locked
                })

            for k in expired_keys:
                self._cached_aps.pop(k, None)

            result = []
            for ssid, net in grouped.items():
                bands_dict = {}
                for ap in net["aps"]:
                    b_name = ap["band"]
                    if b_name not in bands_dict:
                        bands_dict[b_name] = {
                            "band": b_name,
                            "band_id": ap["band_id"],
                            "channel": ap["channel"],
                            "freq_str": ap["freq_str"],
                            "signal": ap["signal"],
                            "best_bssid": ap["bssid"],
                            "in_use": ap["in_use"],
                            "is_locked": ap["is_locked"],
                            "aps": []
                        }
                    bands_dict[b_name]["aps"].append(ap)

                for b_name, b_info in bands_dict.items():
                    b_info["aps"].sort(key=lambda x: (not x["in_use"], -x["signal"]))
                    strongest = b_info["aps"][0]
                    b_info["signal"] = strongest["signal"]
                    b_info["channel"] = strongest["channel"]
                    b_info["freq_str"] = strongest["freq_str"]
                    b_info["best_bssid"] = strongest["bssid"]
                    b_info["in_use"] = any(a["in_use"] for a in b_info["aps"])
                    b_info["is_locked"] = any(a["is_locked"] for a in b_info["aps"])

                def band_rank(b):
                    if "6" in b: return 0
                    if "5" in b: return 1
                    return 2

                band_list = list(bands_dict.values())
                band_list.sort(key=lambda x: (not x["in_use"], not x["is_locked"], band_rank(x["band"]), -x["signal"]))

                net["bands"] = band_list
                net["distinct_bands"] = [b["band"] for b in band_list]
                net["total_aps"] = len(net["aps"])
                result.append(net)

            result.sort(key=lambda x: (not x["is_connected"], -(max([b["signal"] for b in x["bands"]]) if x["bands"] else 0)))
            return result
        except Exception as e:
            logger.error(f"Error scanning networks: {e}")
            return {"error": str(e)}

    async def lock_to_bssid(self, ssid, bssid, password=None, auto_rollback=True):
        """Forces connection to a specific Access Point BSSID."""
        try:
            if not bssid or not MAC_REGEX.match(bssid):
                return {"success": False, "error": f"Invalid BSSID format: '{bssid}'"}

            logger.info(f"Locking connection for SSID '{ssid}' to BSSID '{bssid}'")
            iface = get_wifi_interface()
            
            # Detect band of this BSSID from cached APs or scan
            target_band = None
            for (s, b), ap_data in self._cached_aps.items():
                if b.lower() == bssid.lower():
                    target_band = ap_data.get("band_id")
                    break

            if target_band:
                set_iwd_band_lock(target_band)

            # Check if connection exists in NetworkManager
            conn_res = run_nmcli(["-t", "-f", "NAME,UUID,TYPE", "connection", "show"], timeout=5)
            uuid = None
            for line in conn_res.stdout.strip().splitlines():
                if not line:
                    continue
                parts = line.split(":")
                if len(parts) >= 3 and parts[0] == ssid and parts[2] == "802-11-wireless":
                    uuid = parts[1]
                    break

            if uuid:
                # Try setting BSSID in NetworkManager profile
                run_nmcli(
                    ["connection", "modify", uuid, "802-11-wireless.bssid", bssid, "802-11-wireless.band", ""],
                    timeout=5
                )
                up_res = run_nmcli(["connection", "up", uuid], timeout=12)
                if up_res.returncode != 0:
                    # If NM rejects explicit BSSID (common on multi-AP mesh under IWD), clear BSSID constraint
                    logger.info(f"NM explicit BSSID pin notice: {up_res.stderr.strip()}. Retrying with band lock...")
                    run_nmcli(["connection", "modify", uuid, "802-11-wireless.bssid", ""], timeout=5)
                    up_res = run_nmcli(["connection", "up", uuid], timeout=10)

                if up_res.returncode == 0:
                    return {"success": True, "output": up_res.stdout}
                return {"success": False, "error": f"Failed connecting to {bssid}: {up_res.stderr.strip()}"}
            else:
                if not password:
                    return {
                        "success": False,
                        "requires_password": True,
                        "error": f"'{ssid}' is not saved. Please enter the Wi-Fi password or connect in Steam Settings first."
                    }
                
                cmd = ["dev", "wifi", "connect", ssid, "password", str(password)]
                if iface:
                    cmd.extend(["ifname", iface])
                connect_res = run_nmcli(cmd, timeout=25)
                if connect_res.returncode != 0:
                    return {"success": False, "error": f"Failed to connect to '{ssid}'. Please check the password."}
                return {"success": True, "output": connect_res.stdout}
        except Exception as e:
            logger.error(f"Error locking to BSSID: {e}")
            return {"success": False, "error": str(e)}

    async def lock_to_band(self, ssid, band, password=None):
        """Locks connection to the requested frequency band (6 GHz, 5 GHz, or 2.4 GHz) using IWD ranking."""
        try:
            band_clean = band.lower().strip() if band else ""
            if band_clean not in ALLOWED_BANDS:
                return {"success": False, "error": f"Invalid band parameter: '{band}'"}

            target_band_label = "6 GHz" if "6" in band_clean else "5 GHz" if "5" in band_clean else "2.4 GHz"
            logger.info(f"Locking connection for SSID '{ssid}' to band '{target_band_label}' (key: {band_clean})")

            # Check if saved connection exists in NetworkManager
            conn_res = run_nmcli(["-t", "-f", "NAME,UUID,TYPE", "connection", "show"], timeout=5)
            uuid = None
            for line in conn_res.stdout.strip().splitlines():
                if not line:
                    continue
                parts = line.split(":")
                if len(parts) >= 3 and parts[0] == ssid and parts[2] == "802-11-wireless":
                    uuid = parts[1]
                    break

            if not uuid:
                if not password:
                    return {
                        "success": False,
                        "requires_password": True,
                        "error": f"'{ssid}' is not saved. Please enter the Wi-Fi password to connect."
                    }
                iface = get_wifi_interface()
                cmd = ["dev", "wifi", "connect", ssid, "password", str(password)]
                if iface:
                    cmd.extend(["ifname", iface])
                c_res = run_nmcli(cmd, timeout=25)
                if c_res.returncode != 0:
                    return {"success": False, "error": f"Failed connecting to '{ssid}': {c_res.stderr.strip()}"}

                conn_res2 = run_nmcli(["-t", "-f", "NAME,UUID,TYPE", "connection", "show"], timeout=5)
                for line in conn_res2.stdout.strip().splitlines():
                    parts = line.split(":")
                    if len(parts) >= 3 and parts[0] == ssid and parts[2] == "802-11-wireless":
                        uuid = parts[1]
                        break

            # Clear any conflicting BSSID constraint on NetworkManager profile
            if uuid:
                run_nmcli(["connection", "modify", uuid, "802-11-wireless.bssid", "", "802-11-wireless.band", ""], timeout=5)

            # Apply IWD rank modifier and restart iwd
            ok = set_iwd_band_lock(band_clean)
            if not ok:
                return {"success": False, "error": "Failed to update IWD band configuration."}

            # Wait for connection to re-establish on target band
            for attempt in range(8):
                await asyncio.sleep(0.7)
                st = await self.get_wifi_status()
                if st.get("connected") and st.get("ssid") == ssid:
                    cur_b = st.get("band", "")
                    if ("6" in band_clean and "6" in cur_b) or \
                       ("5" in band_clean and "5" in cur_b) or \
                       ("2.4" in band_clean and "2.4" in cur_b):
                        logger.info(f"Successfully locked to {cur_b} on SSID '{ssid}'")
                        return {"success": True, "band": cur_b}

            # If not yet connected, trigger profile activation
            if uuid:
                run_nmcli(["connection", "up", uuid], timeout=10)
                await asyncio.sleep(1.5)
                st = await self.get_wifi_status()
                if st.get("connected") and st.get("ssid") == ssid:
                    return {"success": True, "band": st.get("band", target_band_label)}

            # Rollback if target band is unreachable
            logger.warning(f"Target band {target_band_label} unreachable for '{ssid}'. Restoring auto-roam...")
            set_iwd_band_lock(None)
            if uuid:
                run_nmcli(["connection", "up", uuid], timeout=10)
            return {
                "success": False,
                "error": f"{target_band_label} is out of range or unreachable for '{ssid}'. Restored auto-roaming."
            }
        except Exception as e:
            logger.error(f"Error locking to band: {e}")
            return {"success": False, "error": str(e)}

    async def unlock_connection(self, ssid):
        """Clears any BSSID or Band lock on the connection profile to restore auto-roaming."""
        try:
            logger.info(f"Unlocking connection for SSID '{ssid}'")
            set_iwd_band_lock(None)

            conn_res = run_nmcli(["-t", "-f", "NAME,UUID,TYPE", "connection", "show"], timeout=5)
            uuid = None
            for line in conn_res.stdout.strip().splitlines():
                if not line:
                    continue
                parts = line.split(":")
                if len(parts) >= 3 and (parts[0] == ssid or not ssid) and parts[2] == "802-11-wireless":
                    uuid = parts[1]
                    break

            if uuid:
                run_nmcli(
                    ["connection", "modify", uuid, "802-11-wireless.bssid", "", "802-11-wireless.band", ""],
                    timeout=5
                )
                run_nmcli(["connection", "up", uuid], timeout=10)

            return {"success": True, "output": "Auto-roaming enabled."}
        except Exception as e:
            logger.error(f"Error unlocking connection: {e}")
            return {"success": False, "error": str(e)}

    async def toggle_wifi(self, enabled):
        """Enables or disables Wi-Fi radio."""
        try:
            state = "on" if enabled else "off"
            res = run_nmcli(["radio", "wifi", state], timeout=5)
            return {"success": res.returncode == 0}
        except Exception as e:
            logger.error(f"Error toggling wifi: {e}")
            return {"success": False, "error": str(e)}

    async def start_speed_test(self):
        """Starts live network speed test in a background thread."""
        return _speed_worker.start()

    async def get_speed_test_progress(self):
        """Gets real-time speed test progress and throughput measurements."""
        return _speed_worker.get_state()

    async def run_speed_test(self):
        """Runs speed test and waits for completion."""
        _speed_worker.start()
        while True:
            await asyncio.sleep(0.3)
            st = _speed_worker.get_state()
            if not st["running"]:
                return st

    async def _main(self):
        logger.info("WiFi-BandLock backend initialized.")

    async def _unload(self):
        logger.info("WiFi-BandLock backend unloaded.")
