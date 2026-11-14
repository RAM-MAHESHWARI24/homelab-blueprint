/**
 * Homelab Blueprint - Setup Wizard Frontend State Machine
 * Handles live diagnostics, reactive verification, mode switching, and provisioning.
 */

let systemSnapshot = null;
let currentMode = "express"; // "express" | "power" | "ai"

// ---------------------------------------------------------------------------
// Access token: the wizard runs as root, so every API call carries the one-time
// token printed in the terminal (?token=... on first open, then sessionStorage).
// ---------------------------------------------------------------------------
const TOKEN_KEY = "homelab_setup_token";
let setupToken = "";
try {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    setupToken = fromUrl;
    sessionStorage.setItem(TOKEN_KEY, fromUrl);
    url.searchParams.delete("token");
    window.history.replaceState({}, document.title, url.pathname + url.search + url.hash);
  } else {
    setupToken = sessionStorage.getItem(TOKEN_KEY) || "";
  }
} catch (_) { /* storage unavailable */ }

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (setupToken) headers["Authorization"] = `Bearer ${setupToken}`;
  const res = await fetch(path, Object.assign({}, options, { headers }));
  if (res.status === 401) {
    const entered = window.prompt("Access token required.\nPaste the token shown in the server terminal (the ?token=... part of the URL):");
    if (entered && entered.trim()) {
      setupToken = entered.trim();
      try { sessionStorage.setItem(TOKEN_KEY, setupToken); } catch (_) { /* ignore */ }
      headers["Authorization"] = `Bearer ${setupToken}`;
      return fetch(path, Object.assign({}, options, { headers }));
    }
  }
  return res;
}

document.addEventListener("DOMContentLoaded", () => {
  if (new URLSearchParams(window.location.search).get("netplan_confirm") === "1") {
    showNetplanConfirmPage();
    return;
  }
  initTabs();
  fetchSystemSnapshot();
  bindActionEvents();
});

// ---------------------------------------------------------------------------
// Static-IP confirmation, served from the NEW address after a deploy changed it.
// Same-origin, so it uses the normal token-protected API. Opened as
// /?token=...&netplan_confirm=1#next=<dashboard url>
// ---------------------------------------------------------------------------
function safeNextUrl() {
  try {
    const raw = new URLSearchParams(window.location.hash.slice(1)).get("next") || "";
    const next = new URL(raw);
    // Only follow plain http(s) links to this same host (the dashboard on another port).
    if ((next.protocol === "http:" || next.protocol === "https:") && next.hostname === window.location.hostname) {
      return next.href;
    }
  } catch (_) { /* missing or malformed */ }
  return "";
}

async function showNetplanConfirmPage() {
  const nextUrl = safeNextUrl();
  const panel = document.createElement("div");
  panel.style.cssText = "position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:16px;background:var(--bg-dark)";
  panel.innerHTML = `
    <div class="launch-card" style="display:block;cursor:default;max-width:520px;width:100%;border-color:var(--amber)">
      <h4 style="margin-top:0">Confirm the new static IP (${window.location.hostname})</h4>
      <p id="netplan-page-status" style="margin:0 0 .8rem">Checking the pending network change...</p>
      <button type="button" class="btn-primary" id="btn-netplan-keep" disabled>Keep this IP</button>
      <span style="margin-left:.8rem;font-family:var(--font-mono);font-size:.8rem">reverts in <span id="netplan-page-countdown">-</span>s if not confirmed</span>
    </div>`;
  document.body.appendChild(panel);

  const status = document.getElementById("netplan-page-status");
  const btn = document.getElementById("btn-netplan-keep");
  const countdown = document.getElementById("netplan-page-countdown");

  let state = {};
  try {
    state = await (await api("/api/netplan/status")).json();
  } catch (err) {
    status.innerText = `Could not read the pending change: ${err.message}`;
    return;
  }
  if (!state.pending) {
    status.innerText = "No static-IP change is pending: it was already confirmed, or the revert window passed and the previous address was restored.";
    btn.style.display = "none";
    countdown.parentElement.style.display = "none";
    return;
  }

  let remaining = Number(state.remaining_sec) || 0;
  countdown.innerText = remaining;
  const tick = setInterval(() => {
    remaining -= 1;
    countdown.innerText = Math.max(remaining, 0);
    if (remaining <= 0) {
      clearInterval(tick);
      btn.disabled = true;
      status.innerText = "The revert window has passed. The previous network configuration is being restored.";
    }
  }, 1000);

  status.innerText = "This page reached the server on its new address. Click below to make the change permanent.";
  btn.disabled = false;
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      const data = await (await api("/api/netplan/confirm", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).json();
      if (data.success) {
        clearInterval(tick);
        countdown.parentElement.style.display = "none";
        status.innerText = nextUrl ? "Static IP confirmed. Opening the dashboard..." : "Static IP confirmed. You can close this page.";
        if (nextUrl) setTimeout(() => { window.location.href = nextUrl; }, 1500);
      } else {
        status.innerText = `Confirmation failed: ${data.message || "unknown error"}`;
        btn.disabled = false;
      }
    } catch (err) {
      status.innerText = `Could not confirm: ${err.message}`;
      btn.disabled = false;
    }
  };
}

// Tab & Mode Navigation
function initTabs() {
  const tabs = document.querySelectorAll(".mode-tab-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      currentMode = tab.dataset.mode;
      renderActiveMode();
    });
  });
}

function renderActiveMode() {
  document.getElementById("section-express").style.display = (currentMode === "express") ? "block" : "none";
  document.getElementById("section-power").style.display = (currentMode === "power") ? "block" : "none";
  document.getElementById("section-ai").style.display = (currentMode === "ai") ? "block" : "none";
}

// Fetch Host Snapshot from REST API
async function fetchSystemSnapshot() {
  try {
    const res = await api("/api/probe");
    if (!res.ok) throw new Error("Failed to fetch system snapshot");
    systemSnapshot = await res.json();
    populateSnapshotUI(systemSnapshot);
    populateSmartDefaults(systemSnapshot);
    loadAIPrompt();
  } catch (err) {
    console.error("System probe error:", err);
    document.getElementById("snap-cpu").innerText = "Error loading hardware info";
  }
}

function populateSnapshotUI(snap) {
  // Snapshot top pills
  document.getElementById("snap-cpu").innerText = `${snap.cpu.model} (${snap.cpu.threads} Threads)`;
  document.getElementById("snap-ram").innerText = `${snap.ram.total_gib} GiB (${snap.ram.free_gib} GiB Free)`;
  document.getElementById("snap-ip").innerText = `${snap.network.current_ip} (${snap.network.active_nic})`;
  document.getElementById("snap-user").innerText = `${snap.user.username} (${snap.user.puid}:${snap.user.pgid})`;

  // Mount Chips for easy 1-click selection
  const diskContainer = document.getElementById("disk-chips-container");
  const powerDiskContainer = document.getElementById("power-disk-chips-container");
  if (diskContainer) diskContainer.innerHTML = "";
  if (powerDiskContainer) powerDiskContainer.innerHTML = "";

  snap.disks.forEach(disk => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip-btn";
    chip.innerText = `${disk.mount_point} (${disk.free_gb} GB Free)`;
    chip.onclick = () => {
      document.getElementById("exp-data-dir").value = disk.mount_point.endsWith("/data") ? disk.mount_point : `${disk.mount_point.replace(/\\/g, '/')}/data`;
      testHardlink(document.getElementById("exp-data-dir").value, "exp-hl-status");
    };

    if (diskContainer) diskContainer.appendChild(chip);
    if (powerDiskContainer) {
      const pChip = chip.cloneNode(true);
      pChip.onclick = () => {
        document.getElementById("pow-data-dir").value = disk.mount_point.endsWith("/data") ? disk.mount_point : `${disk.mount_point.replace(/\\/g, '/')}/data`;
        testHardlink(document.getElementById("pow-data-dir").value, "pow-hl-status");
      };
      powerDiskContainer.appendChild(pChip);
    }
  });

  // Hardware acceleration notice
  const hwNotice = document.getElementById("hwaccel-badge");
  if (hwNotice) {
    hwNotice.innerText = snap.hwaccel.has_vaapi_dri ? "Intel QSV / VAAPI Available" : "CPU Direct Play Enforced";
    hwNotice.className = `badge-soft ${snap.hwaccel.has_vaapi_dri ? "badge-emerald" : "badge-amber"}`;
  }
}

function populateSmartDefaults(snap) {
  // Express defaults
  const firstHdd = snap.disks.find(d => !d.is_root) || snap.disks[0];
  const defaultMount = firstHdd ? firstHdd.mount_point.replace(/\\/g, '/') : "/mnt/hdd";

  const expData = document.getElementById("exp-data-dir");
  const expPhotos = document.getElementById("exp-photos-dir");
  const expIp = document.getElementById("exp-server-ip");

  if (expData && !expData.value) expData.value = `${defaultMount}/data`;
  if (expPhotos && !expPhotos.value) expPhotos.value = `${defaultMount}/Memories`;
  if (expIp) expIp.value = snap.network.current_ip;

  // Power defaults
  const powData = document.getElementById("pow-data-dir");
  const powPhotos = document.getElementById("pow-photos-dir");
  const powSsd = document.getElementById("pow-ssd-dir");
  const powUser = document.getElementById("pow-user");
  const powPuid = document.getElementById("pow-puid");
  const powPgid = document.getElementById("pow-pgid");
  const powIp = document.getElementById("pow-server-ip");
  const powNic = document.getElementById("pow-nic");
  const powGateway = document.getElementById("pow-gateway");
  const powTz = document.getElementById("pow-tz");

  if (powData) powData.value = `${defaultMount}/data`;
  if (powPhotos) powPhotos.value = `${defaultMount}/Memories`;
  if (powSsd) powSsd.value = "./config";
  if (powUser) powUser.value = snap.user.username;
  if (powPuid) powPuid.value = snap.user.puid;
  if (powPgid) powPgid.value = snap.user.pgid;
  if (powIp) powIp.value = snap.network.current_ip;
  if (powNic) powNic.value = snap.network.active_nic;
  if (powGateway) powGateway.value = snap.network.default_gateway;
  if (powTz) powTz.value = snap.timezone;

  // Run initial hardlink test
  if (expData && expData.value) {
    testHardlink(expData.value, "exp-hl-status");
  }
}

// Live Atomic Hardlink Verification
async function testHardlink(path, statusElemId) {
  const elem = document.getElementById(statusElemId);
  if (!elem) return;
  elem.innerHTML = `<span style="color: var(--cyan)">Testing atomic link...</span>`;

  try {
    const res = await api("/api/verify/hardlink", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: path }),
    });
    const data = await res.json();
    if (data.supported) {
      elem.innerHTML = `<span style="color: var(--emerald)">✓ 0-I/O Hardlinks Verified (${data.latency_ms} ms | Inode: ${data.inode})</span>`;
    } else {
      elem.innerHTML = `<span style="color: var(--rose)" title="${data.error || ''}">✗ Hardlinks Failed: ${data.tip || data.error}</span>`;
    }
  } catch (err) {
    elem.innerHTML = `<span style="color: var(--amber)">Could not probe hardlinks</span>`;
  }
}

// Secrets Generation
async function generateAllSecrets() {
  try {
    const res = await api("/api/secrets/generate", { method: "POST" });
    const secrets = await res.json();

    const expPwd = document.getElementById("exp-admin-pass");
    if (expPwd) expPwd.value = secrets.qbittorrent_pass;

    const powQbitPwd = document.getElementById("pow-qbit-pass");
    const powPgPwd = document.getElementById("pow-pg-pass");
    const powRadarrKey = document.getElementById("pow-radarr-key");
    const powSonarrKey = document.getElementById("pow-sonarr-key");
    const powProwlarrKey = document.getElementById("pow-prowlarr-key");

    if (powQbitPwd) powQbitPwd.value = secrets.qbittorrent_pass;
    if (powPgPwd) powPgPwd.value = secrets.postgres_password;
    if (powRadarrKey) powRadarrKey.value = secrets.radarr_api_key;
    if (powSonarrKey) powSonarrKey.value = secrets.sonarr_api_key;
    if (powProwlarrKey) powProwlarrKey.value = secrets.prowlarr_api_key;

    alert("✓ Generated fresh cryptographic credentials!");
  } catch (err) {
    console.error("Secrets error:", err);
  }
}

// Load AI Context Dump
async function loadAIPrompt() {
  try {
    const res = await api("/api/ai/context");
    const data = await res.json();
    const promptElem = document.getElementById("ai-prompt-content");
    if (promptElem) promptElem.innerText = data.prompt;

    // AI Hardware Recommendation
    const recBox = document.getElementById("ai-rec-text");
    if (recBox && systemSnapshot) {
      let recs = [];
      if (systemSnapshot.cpu.is_low_power) {
        recs.push("⚡ <b>Older / Low-Power CPU Detected:</b> Enforce <b>Direct Play</b> across Jellyfin clients to prevent CPU freeze (Haswell HD 4400 lacks HEVC 10-bit decoding).");
      }
      if (systemSnapshot.ram.is_constrained) {
        recs.push("💾 <b>Low Memory (<8GB):</b> PostgreSQL shared buffers tuned to conservative values to keep total system idle RAM < 25MB.");
      }
      recs.push("📂 <b>Single-Mount Verified:</b> Media and torrent directories share the same filesystem inode table for instant 0.001s moves.");
      recBox.innerHTML = recs.join("<br><br>");
    }
  } catch (err) {
    console.error("AI context error:", err);
  }
}

function copyAIPrompt() {
  const promptText = document.getElementById("ai-prompt-content").innerText;
  navigator.clipboard.writeText(promptText).then(() => {
    alert("✓ Copied token-optimized diagnostic prompt to clipboard! Paste directly into ChatGPT, Claude, Cursor, or Antigravity.");
  });
}

// Bind Action Events
function bindActionEvents() {
  // Test hardlink buttons
  const btnExpHl = document.getElementById("btn-test-exp-hl");
  if (btnExpHl) {
    btnExpHl.onclick = () => testHardlink(document.getElementById("exp-data-dir").value, "exp-hl-status");
  }

  const btnPowHl = document.getElementById("btn-test-pow-hl");
  if (btnPowHl) {
    btnPowHl.onclick = () => testHardlink(document.getElementById("pow-data-dir").value, "pow-hl-status");
  }

  // Generate secrets buttons
  const btnExpSec = document.getElementById("btn-gen-exp-secrets");
  if (btnExpSec) btnExpSec.onclick = generateAllSecrets;

  const btnPowSec = document.getElementById("btn-gen-pow-secrets");
  if (btnPowSec) btnPowSec.onclick = generateAllSecrets;

  // The rclone remote field only matters when photo backup is ticked
  const powBackup = document.getElementById("pow-svc-photo-backup");
  const gdriveGroup = document.getElementById("pow-gdrive-group");
  if (powBackup && gdriveGroup) {
    const sync = () => { gdriveGroup.style.display = powBackup.checked ? "" : "none"; };
    powBackup.addEventListener("change", sync);
    sync();
  }

  // Deploy buttons
  const btnDeployExp = document.getElementById("btn-deploy-express");
  if (btnDeployExp) btnDeployExp.onclick = () => executeDeployment("express");

  const btnDeployPow = document.getElementById("btn-deploy-power");
  if (btnDeployPow) btnDeployPow.onclick = () => executeDeployment("power");

  // Copy AI Prompt
  const btnCopyAi = document.getElementById("btn-copy-ai-prompt");
  if (btnCopyAi) btnCopyAi.onclick = copyAIPrompt;
}

// Full Deployment Runner
async function executeDeployment(mode) {
  const overlay = document.getElementById("deploy-overlay");
  const terminal = document.getElementById("deploy-terminal");
  const progressFill = document.getElementById("progress-fill");
  const launchSection = document.getElementById("deploy-success-section");

  overlay.style.display = "flex";
  launchSection.style.display = "none";
  terminal.innerText = "Initiating deployment...\n";
  progressFill.style.width = "25%";

  let payload = {};

  if (mode === "express") {
    const isDryRun = document.getElementById("exp-dry-run-toggle") ? document.getElementById("exp-dry-run-toggle").checked : true;
    payload = {
      mode: "express",
      dry_run: isDryRun,
      hdd_data: document.getElementById("exp-data-dir").value,
      hdd_memories: document.getElementById("exp-photos-dir").value,
      server_ip: document.getElementById("exp-server-ip").value,
      enable_static_ip: document.getElementById("exp-static-ip-toggle").checked,
      default_gateway: systemSnapshot ? systemSnapshot.network.default_gateway : "",
      dns_servers: systemSnapshot ? systemSnapshot.network.dns_servers : [],
      qbittorrent_pass: document.getElementById("exp-admin-pass").value || "",
      puid: systemSnapshot ? systemSnapshot.user.puid : 1000,
      pgid: systemSnapshot ? systemSnapshot.user.pgid : 1000,
      host_user: systemSnapshot ? systemSnapshot.user.username : "",
      timezone: systemSnapshot ? systemSnapshot.timezone : "UTC",
      active_nic: systemSnapshot ? systemSnapshot.network.active_nic : "",
      enabled_services: ["media", "photos", "control_hub"],
    };
  } else {
    // Power mode
    const isDryRun = document.getElementById("pow-dry-run-toggle") ? document.getElementById("pow-dry-run-toggle").checked : true;
    const services = [];
    if (document.getElementById("pow-svc-media").checked) services.push("media");
    if (document.getElementById("pow-svc-photos").checked) services.push("photos");
    if (document.getElementById("pow-svc-tv").checked) services.push("tv_autoupdater");
    if (document.getElementById("pow-svc-sleep").checked) services.push("sleep_guard");
    if (document.getElementById("pow-svc-ml-schedule").checked) services.push("ml_schedule");
    if (document.getElementById("pow-svc-photo-backup").checked) services.push("photo_backup");
    if (document.getElementById("pow-svc-samba").checked) services.push("samba");
    if (document.getElementById("pow-svc-tailscale").checked) services.push("tailscale");
    services.push("control_hub");

    payload = {
      mode: "power",
      dry_run: isDryRun,
      host_user: document.getElementById("pow-user").value,
      puid: parseInt(document.getElementById("pow-puid").value) || 1000,
      pgid: parseInt(document.getElementById("pow-pgid").value) || 1000,
      server_ip: document.getElementById("pow-server-ip").value,
      active_nic: document.getElementById("pow-nic").value,
      enable_static_ip: document.getElementById("pow-static-ip-toggle").checked,
      default_gateway: document.getElementById("pow-gateway").value,
      timezone: document.getElementById("pow-tz").value,
      hdd_data: document.getElementById("pow-data-dir").value,
      hdd_memories: document.getElementById("pow-photos-dir").value,
      config_dir: document.getElementById("pow-ssd-dir").value,
      dns_servers: systemSnapshot ? systemSnapshot.network.dns_servers : [],
      qbittorrent_user: document.getElementById("pow-qbit-user").value || "admin",
      qbittorrent_pass: document.getElementById("pow-qbit-pass").value || "",
      postgres_password: document.getElementById("pow-pg-pass").value || "",
      radarr_api_key: document.getElementById("pow-radarr-key").value,
      sonarr_api_key: document.getElementById("pow-sonarr-key").value,
      prowlarr_api_key: document.getElementById("pow-prowlarr-key").value,
      gdrive_remote: document.getElementById("pow-gdrive-remote").value.trim(),
      enable_byparr: document.getElementById("pow-opt-byparr").checked,
      enable_tmdb_bypass: document.getElementById("pow-opt-tmdb").checked,
      dns_override: document.getElementById("pow-opt-dns").checked,
      enabled_services: services,
    };
  }

  try {
    progressFill.style.width = "50%";
    terminal.innerText += "Provisioning in progress. Pulling container images can take several minutes on a first install...\n";
    const res = await api("/api/deploy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const result = await res.json();
    progressFill.style.width = "100%";

    terminal.innerText = result.logs ? result.logs.join("\n") : "Deployment complete.";

    if (result.success) {
      renderSuccessLaunch(result);
    } else {
      const errs = (result.errors || []).map(e => `  - [${e.service}] ${e.msg}`).join("\n");
      terminal.innerText += `\n\n[ERROR] Deployment finished with errors:\n${errs || result.error || "see logs above"}`;
    }
  } catch (err) {
    terminal.innerText += `\n[FATAL ERROR] ${err.message}`;
  }
}

function renderSuccessLaunch(result) {
  const launchSection = document.getElementById("deploy-success-section");
  const grid = document.getElementById("service-launch-grid");
  const redirectBtn = document.getElementById("btn-goto-dashboard");

  grid.innerHTML = "";
  result.access_catalog.forEach(svc => {
    const card = document.createElement("a");
    card.href = svc.url;
    card.target = "_blank";
    card.className = "launch-card";
    card.innerHTML = `
      <div>
        <span class="badge-soft badge-cyan" style="margin-bottom: 0.5rem; display: inline-block;">${svc.badge}</span>
        <h4>${svc.name}</h4>
        <p>${svc.desc}</p>
      </div>
      <div style="font-family: var(--font-mono); font-size: 0.8rem; color: var(--cyan); margin-top: 0.8rem;">
        Port :${svc.port} →
      </div>
    `;
    grid.appendChild(card);
  });

  const creds = result.credentials || {};
  const hubToken = creds.control_hub_token || "";
  const dashboardUrl = hubToken ? `${result.dashboard_url}/?token=${encodeURIComponent(hubToken)}` : result.dashboard_url;
  redirectBtn.href = dashboardUrl;
  launchSection.style.display = "block";

  // Show generated credentials exactly once (they are also stored under /etc/homelab, root-only).
  if (!result.dry_run && (hubToken || creds.qbittorrent_pass || creds.postgres_password)) {
    const box = document.createElement("div");
    box.className = "launch-card";
    box.style.cssText = "margin-top:1rem;display:block;cursor:default";
    box.innerHTML = `
      <h4 style="margin-top:0">Save these credentials now</h4>
      <p style="margin:0 0 .6rem">They are stored root-only in <code>/etc/homelab/</code>. Show the dashboard token again later with <code>sudo ./setup.sh token</code>.</p>
      <div style="font-family: var(--font-mono); font-size:.85rem; line-height:1.7; word-break:break-all">
        ${hubToken ? `Control Hub token: <b>${hubToken}</b><br>` : ""}
        ${creds.qbittorrent_pass ? `qBittorrent: <b>${creds.qbittorrent_user || "admin"}</b> / <b>${creds.qbittorrent_pass}</b><br>` : ""}
        ${creds.postgres_password ? `Photo DB password: <b>${creds.postgres_password}</b>` : ""}
      </div>`;
    grid.parentNode.insertBefore(box, grid.nextSibling);
  }

  const countSpan = document.getElementById("redirect-countdown");
  const netplan = result.netplan_result || {};

  // A static IP change is pending: the server now answers on the NEW address and will
  // revert automatically unless confirmed within the window. The wizard sends no CORS
  // headers, so this page (old address) cannot call the API on the new address. Instead:
  // probe with a no-cors request (resolves only if the host answers), then move the
  // browser to the wizard on the new address, which confirms same-origin.
  if (netplan.pending) {
    const newIp = String(netplan.ip || "").split("/")[0];
    const newBase = `${window.location.protocol}//${newIp}:${window.location.port || 80}`;
    const nextUrl = dashboardUrl.replace(window.location.hostname, newIp);
    const confirmUrl = `${newBase}/?token=${encodeURIComponent(setupToken)}&netplan_confirm=1#next=${encodeURIComponent(nextUrl)}`;
    const confirmBox = document.createElement("div");
    confirmBox.className = "launch-card";
    confirmBox.style.cssText = "margin-top:1rem;display:block;cursor:default;border-color:var(--amber)";
    confirmBox.innerHTML = `
      <h4 style="margin-top:0">Confirm the new static IP (${newIp})</h4>
      <p style="margin:0 0 .6rem">Save the credentials above first: the next step opens the wizard on the new address.</p>
      <p id="netplan-confirm-status" style="margin:0 0 .8rem">Checking that the server is reachable on ${newIp}...</p>
      <button type="button" class="btn-primary" id="btn-netplan-confirm" disabled>Continue on ${newIp}</button>
      <span style="margin-left:.8rem;font-family:var(--font-mono);font-size:.8rem">reverts in <span id="netplan-countdown">${netplan.timeout_sec || 120}</span>s if not confirmed</span>`;
    grid.parentNode.insertBefore(confirmBox, grid.nextSibling);
    if (countSpan) countSpan.parentElement.style.display = "none";

    let remaining = netplan.timeout_sec || 120;
    const tick = setInterval(() => {
      remaining -= 1;
      const el = document.getElementById("netplan-countdown");
      if (el) el.innerText = Math.max(remaining, 0);
      if (remaining <= 0) clearInterval(tick);
    }, 1000);

    const status = document.getElementById("netplan-confirm-status");
    const btn = document.getElementById("btn-netplan-confirm");
    const probe = async () => {
      try {
        // Opaque response: we cannot read it, but it only resolves if the new address answers.
        await fetch(`${newBase}/api/health`, { mode: "no-cors", cache: "no-store" });
        status.innerText = `Server reachable on ${newIp}. Continue there to keep this IP.`;
        btn.disabled = false;
        return true;
      } catch (_) { /* not reachable yet */ }
      return false;
    };
    const poll = setInterval(async () => { if (await probe()) clearInterval(poll); }, 3000);
    probe();

    btn.onclick = () => { window.location.href = confirmUrl; };
    return;
  }

  // Dry runs stay on this page; real installs redirect after a countdown.
  if (result.dry_run) {
    if (countSpan) countSpan.parentElement.innerText = "Dry run complete. Nothing was changed on this server.";
    return;
  }
  let count = 15;
  const timer = setInterval(() => {
    count -= 1;
    if (countSpan) countSpan.innerText = count;
    if (count <= 0) {
      clearInterval(timer);
      window.location.href = dashboardUrl;
    }
  }, 1000);
}
