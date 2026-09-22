const manifest = { name: "WiFi BandLock" };
const internal = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internal) throw new Error("Decky Loader API was not initialized");

let api;
try {
  api = internal.connect(2, manifest.name);
} catch (_) {
  api = internal.connect(1, manifest.name);
}

const callable = api.callable;
const getWifiStatus = callable("get_wifi_status");
const scanNetworks = callable("scan_networks");
const lockToBssid = callable("lock_to_bssid");
const lockToBand = callable("lock_to_band");
const unlockConnection = callable("unlock_connection");
const toggleWifi = callable("toggle_wifi");
const startSpeedTest = callable("start_speed_test");
const getSpeedTestProgress = callable("get_speed_test_progress");

const { createElement: h, useState, useEffect, useCallback, useRef } = SP_REACT;

const THEME = {
  bg: "#0B0E14",
  surface: "#161B22",
  card: "#1E242F",
  cardActive: "#252E3D",
  primary: "#1A9FFF",
  primaryBg: "rgba(26, 159, 255, 0.15)",
  accent6G: "#A78BFA",
  accent6GBg: "rgba(167, 139, 250, 0.15)",
  accent5G: "#34D399",
  accent5GBg: "rgba(52, 211, 153, 0.15)",
  accent2G: "#FBBF24",
  accent2GBg: "rgba(251, 191, 36, 0.15)",
  danger: "#F87171",
  dangerBg: "rgba(248, 113, 113, 0.15)",
  text: "#F0F6FC",
  textMuted: "#8B949E",
  border: "#30363D",
  radius: "8px"
};

function getBandColor(band) {
  if (!band) return THEME.textMuted;
  if (band.includes("6")) return THEME.accent6G;
  if (band.includes("5")) return THEME.accent5G;
  if (band.includes("2.4")) return THEME.accent2G;
  return THEME.primary;
}

function getShortBand(band) {
  if (!band) return "";
  if (band.includes("6")) return "6 GHz";
  if (band.includes("5")) return "5 GHz";
  if (band.includes("2.4")) return "2.4 GHz";
  return band;
}

function cleanMac(mac) {
  if (!mac) return "";
  return mac.replace(/\\:/g, ":");
}

function SignalBar({ signal }) {
  const bars = Math.min(4, Math.max(1, Math.ceil(signal / 25)));
  const color = signal > 65 ? "#34D399" : signal > 40 ? "#FBBF24" : "#F87171";
  return h(
    "div",
    { style: { display: "inline-flex", alignItems: "flex-end", gap: "2px", height: "12px", marginRight: "5px" } },
    [1, 2, 3, 4].map(idx =>
      h("div", {
        key: idx,
        style: {
          width: "3px",
          height: `${idx * 25}%`,
          backgroundColor: idx <= bars ? color : "#484F58",
          borderRadius: "1px"
        }
      })
    )
  );
}

function WifiBandLockApp() {
  const [status, setStatus] = useState(null);
  const [networks, setNetworks] = useState([]);
  const [scanning, setScanning] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);
  const [expandedSsids, setExpandedSsids] = useState({});
  const [showAdvancedMesh, setShowAdvancedMesh] = useState({});
  const [msg, setMsg] = useState(null);
  const [speedState, setSpeedState] = useState(null);
  const [passwordTarget, setPasswordTarget] = useState(null);
  const [passwordInput, setPasswordInput] = useState("");
  const speedTimerRef = useRef(null);
  const hasAutoExpanded = useRef(false);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await getWifiStatus();
      if (res) {
        setStatus(res);
        if (res.ssid && !hasAutoExpanded.current) {
          hasAutoExpanded.current = true;
          setExpandedSsids(prev => ({ ...prev, [res.ssid]: true }));
        }
      }
    } catch (e) {
      console.error("Failed to fetch wifi status", e);
    }
  }, []);

  const triggerScan = useCallback(async (rescan = true) => {
    setScanning(true);
    try {
      const nets = await scanNetworks(rescan);
      if (Array.isArray(nets)) {
        setNetworks(nets);
      }
      await fetchStatus();
    } catch (e) {
      console.error("Scan error", e);
      setMsg({ type: "error", text: "Scan failed: " + e });
    } finally {
      setScanning(false);
    }
  }, [fetchStatus]);

  useEffect(() => {
    fetchStatus();
    triggerScan(true);
    const interval = setInterval(fetchStatus, 8000);
    return () => {
      clearInterval(interval);
      if (speedTimerRef.current) {
        clearInterval(speedTimerRef.current);
      }
    };
  }, []);

  const handleLockBssid = async (ssid, bssid, band, password) => {
    setActionLoading(bssid);
    const shortB = getShortBand(band);
    setMsg({ type: "info", text: `Locking to ${ssid} (${shortB})...` });
    try {
      const res = await lockToBssid(ssid, bssid, password || "");
      if (res && res.success) {
        setMsg({ type: "success", text: `Locked to ${ssid} on ${shortB}!` });
        setPasswordTarget(null);
        setPasswordInput("");
      } else {
        if (res && res.requires_password) {
          setPasswordTarget({ type: "bssid", ssid, bssid, band });
        }
        setMsg({ type: "error", text: res?.error || "Failed to switch AP" });
      }
    } catch (e) {
      setMsg({ type: "error", text: "Error: " + e });
    } finally {
      setActionLoading(null);
      await triggerScan(false);
    }
  };

  const handleLockBand = async (ssid, bandKey, bandLabel, password) => {
    setActionLoading(ssid + "_" + bandKey);
    setMsg({ type: "info", text: `Setting ${ssid} band preference to ${bandLabel}...` });
    try {
      const res = await lockToBand(ssid, bandKey, password || "");
      if (res && res.success) {
        setMsg({ type: "success", text: `Locked ${ssid} to ${bandLabel} band!` });
        setPasswordTarget(null);
        setPasswordInput("");
      } else {
        if (res && res.requires_password) {
          setPasswordTarget({ type: "band", ssid, bandKey, bandLabel });
        }
        setMsg({ type: "error", text: res?.error || "Failed to set band" });
      }
    } catch (e) {
      setMsg({ type: "error", text: "Error: " + e });
    } finally {
      setActionLoading(null);
      await triggerScan(false);
    }
  };

  const handleUnlock = async ssid => {
    setActionLoading("unlock");
    setMsg({ type: "info", text: "Restoring Auto-Band roaming..." });
    try {
      const res = await unlockConnection(ssid);
      if (res && res.success) {
        setMsg({ type: "success", text: "Restored Auto-Band roaming!" });
      } else {
        setMsg({ type: "error", text: res?.error || "Failed to unlock" });
      }
    } catch (e) {
      setMsg({ type: "error", text: "Error: " + e });
    } finally {
      setActionLoading(null);
      await triggerScan(false);
    }
  };

  const handleRunSpeedTest = async () => {
    if (speedTimerRef.current) {
      clearInterval(speedTimerRef.current);
    }
    try {
      const initial = await startSpeedTest();
      setSpeedState(initial);
      
      speedTimerRef.current = setInterval(async () => {
        try {
          const prog = await getSpeedTestProgress();
          if (prog) {
            setSpeedState(prog);
            if (!prog.running && (prog.phase === "done" || prog.phase === "error")) {
              clearInterval(speedTimerRef.current);
              speedTimerRef.current = null;
            }
          }
        } catch (e) {
          if (speedTimerRef.current) {
            clearInterval(speedTimerRef.current);
            speedTimerRef.current = null;
          }
        }
      }, 150);
    } catch (e) {
      console.error("Speed test launch error", e);
    }
  };

  const toggleMeshForSsid = ssid => {
    setShowAdvancedMesh(prev => ({ ...prev, [ssid]: !prev[ssid] }));
  };

  return h(
    "div",
    {
      style: {
        width: "100%",
        padding: "8px 6px",
        boxSizing: "border-box",
        backgroundColor: THEME.bg,
        color: THEME.text,
        fontFamily: "Inter, system-ui, -apple-system, sans-serif",
        fontSize: "12px",
        overflowX: "hidden"
      }
    },
    // Header Bar
    h(
      "div",
      {
        style: {
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "10px",
          paddingBottom: "8px",
          borderBottom: `1px solid ${THEME.border}`
        }
      },
      h(
        "div",
        { style: { display: "flex", alignItems: "center", gap: "6px" } },
        h("span", { style: { fontSize: "16px" } }, "📶"),
        h("span", { style: { fontWeight: 700, fontSize: "13px", color: "#FFF" } }, "WiFi BandLock")
      ),
      h(
        "button",
        {
          onClick: () => triggerScan(true),
          disabled: scanning,
          style: {
            backgroundColor: THEME.surface,
            color: scanning ? THEME.textMuted : THEME.primary,
            border: `1px solid ${THEME.border}`,
            padding: "4px 10px",
            borderRadius: "6px",
            fontSize: "11px",
            fontWeight: 600,
            cursor: "pointer",
            flexShrink: 0
          }
        },
        scanning ? "Scanning..." : "🔄 Rescan"
      )
    ),

    // Status Message Alert
    msg
      ? h(
          "div",
          {
            style: {
              padding: "6px 8px",
              borderRadius: "6px",
              marginBottom: "10px",
              fontSize: "11px",
              lineHeight: "1.3",
              backgroundColor: msg.type === "error" ? THEME.dangerBg : msg.type === "success" ? THEME.accent5GBg : THEME.primaryBg,
              color: msg.type === "error" ? THEME.danger : msg.type === "success" ? THEME.accent5G : THEME.primary,
              border: `1px solid ${msg.type === "error" ? THEME.danger : msg.type === "success" ? THEME.accent5G : THEME.primary}`
            }
          },
          msg.text
        )
      : null,

    // Active Connected Network Card
    status && status.connected
      ? h(
          "div",
          {
            style: {
              backgroundColor: THEME.surface,
              borderRadius: THEME.radius,
              padding: "10px",
              marginBottom: "12px",
              border: `1px solid ${status.is_locked ? THEME.accent5G : THEME.border}`,
              boxSizing: "border-box"
            }
          },
          // Header Row
          h(
            "div",
            { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" } },
            h(
              "div",
              { style: { minWidth: 0, flex: 1, marginRight: "6px" } },
              h("div", { style: { fontSize: "9px", fontWeight: 700, color: THEME.textMuted, letterSpacing: ".05em" } }, "CURRENT WI-FI NETWORK"),
              h(
                "div",
                {
                  style: {
                    fontSize: "15px",
                    fontWeight: 800,
                    color: "#FFF",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis"
                  }
                },
                status.ssid
              )
            ),
            h(
              "span",
              {
                style: {
                  backgroundColor: getBandColor(status.band),
                  color: "#000",
                  fontSize: "10px",
                  fontWeight: 800,
                  padding: "2px 7px",
                  borderRadius: "10px",
                  flexShrink: 0
                }
              },
              getShortBand(status.band) || "Connected"
            )
          ),

          // Details Row
          h(
            "div",
            { style: { display: "flex", flexWrap: "wrap", gap: "8px", fontSize: "11px", color: THEME.textMuted, marginBottom: "8px" } },
            h(
              "div",
              { style: { display: "flex", alignItems: "center" } },
              h(SignalBar, { signal: status.signal }),
              `${status.signal}%`
            ),
            h("div", null, `Ch ${status.channel} · ${status.freq}`)
          ),

          // Lock Status & Unlock Action Bar
          h(
            "div",
            {
              style: {
                display: "flex",
                flexDirection: "column",
                gap: "6px",
                backgroundColor: THEME.card,
                padding: "8px",
                borderRadius: "6px"
              }
            },
            h(
              "div",
              { style: { display: "flex", alignItems: "center", gap: "5px", fontSize: "11px" } },
              h("span", null, status.is_locked ? "🔒" : "🌐"),
              h(
                "span",
                { style: { color: status.is_locked ? THEME.accent5G : THEME.textMuted, fontWeight: 600 } },
                status.is_locked
                  ? status.locked_bssid
                    ? `Locked to AP (${cleanMac(status.locked_bssid)})`
                    : `Locked to ${status.locked_band} Band`
                  : "Auto-Roaming (All Bands Active)"
              )
            ),
            status.is_locked
              ? h(
                  "button",
                  {
                    onClick: () => handleUnlock(status.ssid),
                    disabled: actionLoading === "unlock",
                    style: {
                      width: "100%",
                      backgroundColor: THEME.dangerBg,
                      color: THEME.danger,
                      border: `1px solid ${THEME.danger}`,
                      padding: "6px 0",
                      borderRadius: "5px",
                      fontSize: "11px",
                      fontWeight: 700,
                      cursor: "pointer",
                      textAlign: "center"
                    }
                  },
                  actionLoading === "unlock" ? "Unlocking..." : "🔓 Unlock (Restore Auto-Roaming)"
                )
              : null
          ),

          // Speed Test Panel
          h(
            "div",
            {
              style: {
                marginTop: "8px",
                padding: "8px",
                backgroundColor: THEME.card,
                borderRadius: "6px",
                border: `1px solid ${THEME.border}`
              }
            },
            h(
              "div",
              {
                style: {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: speedState ? "6px" : "0px"
                }
              },
              h(
                "div",
                { style: { display: "flex", alignItems: "center", gap: "5px", fontWeight: 700, fontSize: "11px", color: THEME.primary } },
                h("span", null, "⚡"),
                h("span", null, "LIVE SPEED TEST")
              ),
              speedState && speedState.phase === "done"
                ? h("span", { style: { fontSize: "9px", color: THEME.textMuted } }, `Tested ${speedState.timestamp}`)
                : null
            ),

            // Live In-Progress State
            speedState && speedState.running
              ? h(
                  "div",
                  { style: { display: "flex", flexDirection: "column", gap: "6px", padding: "4px 0" } },
                  h(
                    "div",
                    { style: { display: "flex", justifyContent: "space-between", alignItems: "baseline" } },
                    h(
                      "div",
                      {
                        style: {
                          fontSize: "11px",
                          fontWeight: 700,
                          color:
                            speedState.phase === "ping"
                              ? THEME.accent2G
                              : speedState.phase === "download"
                              ? THEME.accent5G
                              : THEME.accent6G
                        }
                      },
                      speedState.phase === "ping"
                        ? "⚡ Measuring Latency..."
                        : speedState.phase === "download"
                        ? "↓ Testing Download..."
                        : "↑ Testing Upload..."
                    ),
                    h(
                      "div",
                      { style: { fontSize: "16px", fontWeight: 800, color: "#FFF" } },
                      speedState.phase === "ping"
                        ? `${speedState.ping_ms || 0} ms`
                        : `${speedState.current_speed || (speedState.phase === "download" ? speedState.download_mbps : speedState.upload_mbps)} Mbps`
                    )
                  ),
                  // Animated Progress Bar
                  h(
                    "div",
                    {
                      style: {
                        width: "100%",
                        height: "4px",
                        backgroundColor: THEME.surface,
                        borderRadius: "2px",
                        overflow: "hidden"
                      }
                    },
                    h("div", {
                      style: {
                        width: `${speedState.progress}%`,
                        height: "100%",
                        backgroundColor:
                          speedState.phase === "ping"
                            ? THEME.accent2G
                            : speedState.phase === "download"
                            ? THEME.accent5G
                            : THEME.accent6G,
                        transition: "width 0.15s ease"
                      }
                    })
                  )
                )
              : null,

            // Finished Test Results Grid
            speedState && speedState.phase === "done"
              ? h(
                  "div",
                  { style: { display: "flex", flexDirection: "column", gap: "6px" } },
                  h(
                    "div",
                    { style: { display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "4px", textAlign: "center" } },
                    // Download Box
                    h(
                      "div",
                      { style: { backgroundColor: THEME.surface, padding: "6px 2px", borderRadius: "5px", border: `1px solid ${THEME.border}` } },
                      h("div", { style: { fontSize: "8px", fontWeight: 700, color: THEME.accent5G, letterSpacing: ".05em" } }, "↓ DOWNLOAD"),
                      h("div", { style: { fontSize: "13px", fontWeight: 800, color: "#FFF", marginTop: "2px" } }, `${Math.round(speedState.download_mbps)}`),
                      h("div", { style: { fontSize: "8px", color: THEME.textMuted } }, "Mbps")
                    ),
                    // Upload Box
                    h(
                      "div",
                      { style: { backgroundColor: THEME.surface, padding: "6px 2px", borderRadius: "5px", border: `1px solid ${THEME.border}` } },
                      h("div", { style: { fontSize: "8px", fontWeight: 700, color: THEME.accent6G, letterSpacing: ".05em" } }, "↑ UPLOAD"),
                      h("div", { style: { fontSize: "13px", fontWeight: 800, color: "#FFF", marginTop: "2px" } }, `${Math.round(speedState.upload_mbps)}`),
                      h("div", { style: { fontSize: "8px", color: THEME.textMuted } }, "Mbps")
                    ),
                    // Ping Box
                    h(
                      "div",
                      { style: { backgroundColor: THEME.surface, padding: "6px 2px", borderRadius: "5px", border: `1px solid ${THEME.border}` } },
                      h("div", { style: { fontSize: "8px", fontWeight: 700, color: THEME.accent2G, letterSpacing: ".05em" } }, "⚡ PING"),
                      h("div", { style: { fontSize: "13px", fontWeight: 800, color: "#FFF", marginTop: "2px" } }, `${Math.round(speedState.ping_ms)}`),
                      h("div", { style: { fontSize: "8px", color: THEME.textMuted } }, `ms (±${speedState.jitter_ms})`)
                    )
                  ),
                  h(
                    "button",
                    {
                      onClick: handleRunSpeedTest,
                      style: {
                        width: "100%",
                        backgroundColor: THEME.surface,
                        color: THEME.primary,
                        border: `1px solid ${THEME.border}`,
                        padding: "5px 0",
                        borderRadius: "5px",
                        fontSize: "10px",
                        fontWeight: 700,
                        cursor: "pointer",
                        marginTop: "2px",
                        textAlign: "center"
                      }
                    },
                    "🔄 Retest Speed"
                  )
                )
              : null,

            // Initial Launch Button
            !speedState || (!speedState.running && speedState.phase !== "done")
              ? h(
                  "button",
                  {
                    onClick: handleRunSpeedTest,
                    style: {
                      width: "100%",
                      backgroundColor: THEME.primaryBg,
                      color: THEME.primary,
                      border: `1px solid ${THEME.primary}`,
                      padding: "6px 0",
                      borderRadius: "5px",
                      fontSize: "11px",
                      fontWeight: 700,
                      cursor: "pointer",
                      textAlign: "center",
                      marginTop: "2px"
                    }
                  },
                  "🚀 Run Live Speed Test"
                )
              : null,

            // Error notice
            speedState && speedState.phase === "error"
              ? h(
                  "div",
                  { style: { color: THEME.danger, fontSize: "10px", marginTop: "4px", textAlign: "center" } },
                  speedState.error || "Speed test failed. Check internet connection."
                )
              : null
          )
        )
      : null,

    // Networks Section Header
    h(
      "div",
      { style: { fontSize: "10px", fontWeight: 700, color: THEME.textMuted, letterSpacing: ".05em", margin: "10px 0 6px 2px" } },
      `AVAILABLE NETWORKS (${networks.length})`
    ),

    // Network groups list
    h(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: "8px" } },
      networks.map(net => {
        const isExpanded = Boolean(expandedSsids[net.ssid]);
        const bands = net.bands || [];
        const isMeshVisible = showAdvancedMesh[net.ssid] || false;
        return h(
          "div",
          {
            key: net.ssid,
            style: {
              backgroundColor: THEME.surface,
              borderRadius: THEME.radius,
              overflow: "hidden",
              border: `1px solid ${net.is_connected ? THEME.primary : THEME.border}`,
              boxSizing: "border-box"
            }
          },
          // Header of Network Group
          h(
            "div",
            {
              onClick: () => setExpandedSsids(prev => ({ ...prev, [net.ssid]: !prev[net.ssid] })),
              style: {
                padding: "9px 10px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                cursor: "pointer",
                backgroundColor: isExpanded ? THEME.card : "transparent"
              }
            },
            h(
              "div",
              { style: { display: "flex", alignItems: "center", gap: "6px", minWidth: 0, flex: 1, marginRight: "8px" } },
              h("span", { style: { fontSize: "13px" } }, "📶"),
              h(
                "span",
                {
                  style: {
                    fontWeight: 800,
                    fontSize: "13px",
                    color: "#FFF",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis"
                  }
                },
                net.ssid
              ),
              net.is_connected
                ? h(
                    "span",
                    {
                      style: {
                        fontSize: "9px",
                        fontWeight: 800,
                        backgroundColor: THEME.primary,
                        color: "#000",
                        padding: "1px 5px",
                        borderRadius: "6px",
                        flexShrink: 0
                      }
                    },
                    "CONNECTED"
                  )
                : null
            ),
            h(
              "div",
              { style: { display: "flex", alignItems: "center", gap: "4px", flexShrink: 0 } },
              h(
                "span",
                { style: { fontSize: "10px", color: THEME.textMuted, fontWeight: 600 } },
                `${bands.length} ${bands.length === 1 ? "Band" : "Bands"}`
              ),
              h("span", { style: { color: THEME.textMuted, fontSize: "10px", marginLeft: "2px" } }, isExpanded ? "▲" : "▼")
            )
          ),

          // Expanded Content: Clean Deduplicated Band Cards
          isExpanded
            ? h(
                "div",
                { style: { padding: "8px", borderTop: `1px solid ${THEME.border}`, display: "flex", flexDirection: "column", gap: "8px" } },
                // Quick Force Band Row (if multiple bands exist)
                bands.length > 1
                  ? h(
                      "div",
                      { style: { display: "flex", flexDirection: "column", gap: "4px", backgroundColor: "rgba(0,0,0,0.25)", padding: "6px 8px", borderRadius: "6px" } },
                      h("div", { style: { fontSize: "10px", color: THEME.textMuted, fontWeight: 600 } }, `Quick Band Restriction for ${net.ssid}:`),
                      h(
                        "div",
                        { style: { display: "flex", gap: "6px" } },
                        bands.map(b => {
                          const bandKey = b.band.includes("6") ? "6ghz" : b.band.includes("5") ? "5ghz" : b.band.includes("2.4") ? "2.4ghz" : null;
                          if (!bandKey) return null;
                          return h(
                            "button",
                            {
                              key: b.band,
                              onClick: () => handleLockBand(net.ssid, bandKey, b.band),
                              disabled: Boolean(actionLoading),
                              style: {
                                flex: 1,
                                backgroundColor: THEME.card,
                                color: getBandColor(b.band),
                                border: `1px solid ${getBandColor(b.band)}`,
                                padding: "5px 0",
                                borderRadius: "4px",
                                fontSize: "10px",
                                fontWeight: 700,
                                cursor: "pointer",
                                textAlign: "center"
                              }
                            },
                            `Force ${getShortBand(b.band)}`
                          );
                        })
                      )
                    )
                  : null,

                // Primary View: One Clean Card Per Distinct Band
                h(
                  "div",
                  { style: { display: "flex", flexDirection: "column", gap: "6px" } },
                  bands.map(b => {
                    const isBandLocked = net.locked_bssid && net.locked_bssid.toLowerCase() === b.best_bssid.toLowerCase();
                    const isCurrent = b.in_use;
                    const loadingThis = actionLoading === b.best_bssid;
                    const shortB = getShortBand(b.band);
                    return h(
                      "div",
                      {
                        key: b.band,
                        style: {
                          backgroundColor: THEME.card,
                          borderRadius: "6px",
                          padding: "8px 10px",
                          display: "flex",
                          flexDirection: "column",
                          gap: "6px",
                          border: isBandLocked ? `1px solid ${THEME.accent5G}` : isCurrent ? `1px solid ${THEME.primary}` : "1px solid rgba(255,255,255,0.06)",
                          boxSizing: "border-box"
                        }
                      },
                      // Band Card Top Row: Network Name + Band Badge + Signal
                      h(
                        "div",
                        { style: { display: "flex", justifyContent: "space-between", alignItems: "center" } },
                        h(
                          "div",
                          { style: { display: "flex", alignItems: "center", gap: "6px", minWidth: 0 } },
                          h(
                            "span",
                            {
                              style: {
                                fontWeight: 800,
                                fontSize: "12px",
                                color: "#FFF",
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis"
                              }
                            },
                            net.ssid
                          ),
                          h(
                            "span",
                            {
                              style: {
                                fontWeight: 800,
                                fontSize: "10px",
                                color: "#000",
                                backgroundColor: getBandColor(b.band),
                                padding: "1px 5px",
                                borderRadius: "4px",
                                flexShrink: 0
                              }
                            },
                            shortB
                          )
                        ),
                        h(
                          "div",
                          { style: { display: "flex", alignItems: "center", fontSize: "11px", color: THEME.textMuted, flexShrink: 0 } },
                          h(SignalBar, { signal: b.signal }),
                          `${b.signal}%`
                        )
                      ),

                      // Channel + Frequency + AP Count
                      h(
                        "div",
                        { style: { display: "flex", justifyContent: "space-between", fontSize: "10px", color: THEME.textMuted } },
                        h("span", null, `Ch ${b.channel} · ${b.freq_str}`),
                        b.aps && b.aps.length > 1
                          ? h("span", { style: { color: THEME.textMuted } }, `${b.aps.length} AP Nodes`)
                          : h("span", { style: { fontFamily: "monospace" } }, cleanMac(b.best_bssid))
                      ),

                      // Action Button or Inline Password Prompt
                      isBandLocked
                        ? h(
                            "button",
                            {
                              onClick: () => handleUnlock(net.ssid),
                              disabled: Boolean(actionLoading),
                              style: {
                                width: "100%",
                                backgroundColor: THEME.accent5GBg,
                                color: THEME.accent5G,
                                border: `1px solid ${THEME.accent5G}`,
                                padding: "6px 0",
                                borderRadius: "4px",
                                fontSize: "11px",
                                fontWeight: 700,
                                cursor: "pointer",
                                textAlign: "center"
                              }
                            },
                            `🔒 Locked to ${net.ssid} (${shortB}) · Tap to Unlock`
                          )
                        : passwordTarget && passwordTarget.ssid === net.ssid && (passwordTarget.bandKey === b.band_id || passwordTarget.bssid === b.best_bssid)
                        ? h(
                            "form",
                            {
                              onSubmit: e => {
                                e.preventDefault();
                                if (passwordTarget.type === "bssid") {
                                  handleLockBssid(net.ssid, passwordTarget.bssid, passwordTarget.band, passwordInput);
                                } else {
                                  handleLockBand(net.ssid, b.band_id, b.band, passwordInput);
                                }
                              },
                              style: {
                                display: "flex",
                                flexDirection: "column",
                                gap: "6px",
                                backgroundColor: "rgba(0,0,0,0.4)",
                                padding: "8px",
                                borderRadius: "6px",
                                border: `1px solid ${THEME.primary}`
                              }
                            },
                            h("div", { style: { fontSize: "11px", fontWeight: 700, color: THEME.primary } }, `🔑 Enter Password for ${net.ssid}:`),
                            h("input", {
                              type: "password",
                              value: passwordInput,
                              autoFocus: true,
                              enterKeyHint: "go",
                              onChange: e => setPasswordInput(e.target.value),
                              onKeyDown: e => {
                                if (e.key === "Enter" || e.keyCode === 13) {
                                  e.preventDefault();
                                  if (passwordTarget.type === "bssid") {
                                    handleLockBssid(net.ssid, passwordTarget.bssid, passwordTarget.band, passwordInput);
                                  } else {
                                    handleLockBand(net.ssid, b.band_id, b.band, passwordInput);
                                  }
                                }
                              },
                              placeholder: "Wi-Fi Password",
                              style: {
                                backgroundColor: THEME.bg,
                                color: THEME.text,
                                border: `1px solid ${THEME.border}`,
                                borderRadius: "4px",
                                padding: "6px 8px",
                                fontSize: "12px",
                                outline: "none"
                              }
                            }),
                            h(
                              "div",
                              { style: { display: "flex", gap: "6px" } },
                              h(
                                "button",
                                {
                                  type: "submit",
                                  disabled: Boolean(actionLoading),
                                  style: {
                                    flex: 1,
                                    backgroundColor: THEME.primary,
                                    color: "#000",
                                    border: "none",
                                    padding: "6px 0",
                                    borderRadius: "4px",
                                    fontSize: "11px",
                                    fontWeight: 700,
                                    cursor: "pointer"
                                  }
                                },
                                actionLoading ? "Connecting..." : "Connect & Pin"
                              ),
                              h(
                                "button",
                                {
                                  type: "button",
                                  onClick: () => {
                                    setPasswordTarget(null);
                                    setPasswordInput("");
                                  },
                                  style: {
                                    backgroundColor: THEME.surface,
                                    color: THEME.textMuted,
                                    border: `1px solid ${THEME.border}`,
                                    padding: "6px 12px",
                                    borderRadius: "4px",
                                    fontSize: "11px",
                                    cursor: "pointer"
                                  }
                                },
                                "Cancel"
                              )
                            ),
                            h(
                              "div",
                              { style: { fontSize: "10px", color: THEME.textMuted, fontStyle: "italic" } },
                              "Tip: You can also connect via Steam Settings > Internet once."
                            )
                          )
                        : h(
                            "button",
                            {
                              onClick: () => {
                                if (!net.has_saved_profile && net.security !== "Open") {
                                  setPasswordTarget({ type: "band", ssid: net.ssid, bandKey: b.band_id, bandLabel: b.band });
                                } else {
                                  handleLockBand(net.ssid, b.band_id, b.band);
                                }
                              },
                              disabled: Boolean(actionLoading),
                              style: {
                                width: "100%",
                                backgroundColor: isCurrent ? THEME.primaryBg : THEME.primary,
                                color: isCurrent ? THEME.primary : "#000",
                                border: isCurrent ? `1px solid ${THEME.primary}` : "none",
                                padding: "6px 0",
                                borderRadius: "4px",
                                fontSize: "11px",
                                fontWeight: 700,
                                cursor: "pointer",
                                textAlign: "center"
                              }
                            },
                            loadingThis
                              ? "Locking..."
                              : isCurrent
                              ? `📌 Pin & Lock to ${net.ssid} (${shortB})`
                              : !net.has_saved_profile && net.security !== "Open"
                              ? `🔑 Connect & Lock to ${net.ssid} (${shortB})`
                              : `🎯 Lock to ${net.ssid} (${shortB})`
                          )
                    );
                  })
                ),

                // Advanced Mesh Sub-View Toggle (if more than 1 AP per band)
                net.total_aps > bands.length
                  ? h(
                      "div",
                      { style: { marginTop: "4px" } },
                      h(
                        "button",
                        {
                          onClick: () => toggleMeshForSsid(net.ssid),
                          style: {
                            width: "100%",
                            backgroundColor: "transparent",
                            color: THEME.textMuted,
                            border: `1px dashed ${THEME.border}`,
                            padding: "5px 0",
                            borderRadius: "4px",
                            fontSize: "10px",
                            fontWeight: 600,
                            cursor: "pointer",
                            textAlign: "center"
                          }
                        },
                        isMeshVisible
                          ? `▲ Hide Detailed Mesh APs (${net.total_aps})`
                          : `▼ Show All Individual Mesh APs / MACs (${net.total_aps})`
                      ),
                      isMeshVisible
                        ? h(
                            "div",
                            { style: { display: "flex", flexDirection: "column", gap: "4px", marginTop: "6px" } },
                            net.aps.map(ap =>
                              h(
                                "div",
                                {
                                  key: ap.bssid,
                                  style: {
                                    backgroundColor: "rgba(0,0,0,0.3)",
                                    borderRadius: "4px",
                                    padding: "6px 8px",
                                    display: "flex",
                                    justifyContent: "space-between",
                                    alignItems: "center",
                                    fontSize: "10px"
                                  }
                                },
                                h(
                                  "div",
                                  { style: { display: "flex", alignItems: "center", gap: "4px" } },
                                  h("span", { style: { fontWeight: 700, color: getBandColor(ap.band) } }, getShortBand(ap.band)),
                                  h("span", { style: { fontFamily: "monospace", color: THEME.textMuted } }, cleanMac(ap.bssid))
                                ),
                                h(
                                  "div",
                                  { style: { display: "flex", alignItems: "center", gap: "6px" } },
                                  h("span", { style: { color: THEME.textMuted } }, `${ap.signal}%`),
                                  h(
                                    "button",
                                    {
                                      onClick: () => handleLockBssid(net.ssid, ap.bssid, ap.band),
                                      disabled: Boolean(actionLoading),
                                      style: {
                                        backgroundColor: THEME.surface,
                                        color: THEME.primary,
                                        border: `1px solid ${THEME.primary}`,
                                        padding: "2px 6px",
                                        borderRadius: "3px",
                                        fontSize: "9px",
                                        fontWeight: 700,
                                        cursor: "pointer"
                                      }
                                    },
                                    "Pin"
                                  )
                                )
                              )
                            )
                          )
                        : null
                    )
                  : null
              )
            : null
        );
      })
    )
  );
}

export default function() {
  return {
    name: manifest.name,
    title: h("div", { className: (typeof DFL !== "undefined" && DFL.staticClasses && DFL.staticClasses.Title) || "" }, "WiFi BandLock"),
    content: h(WifiBandLockApp, null),
    icon: h("span", null, "📶"),
    onDismount() {}
  };
}
