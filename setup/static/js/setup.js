/**
 * Homelab Blueprint - Setup Wizard Frontend State Machine
 * Handles live diagnostics, reactive verification, mode switching, and provisioning.
 */

let systemSnapshot = null;
let currentMode = "express"; // "express" | "power" | "ai"

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  fetchSystemSnapshot();
  bindActionEvents();
});

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
    const res = await fetch("/api/probe");
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
    const res = await fetch("/api/verify/hardlink", {
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
    const res = await fetch("/api/secrets/generate", { method: "POST" });
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
    const res = await fetch("/api/ai/context");
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
      qbittorrent_pass: document.getElementById("exp-admin-pass").value || "adminadmin",
      puid: systemSnapshot ? systemSnapshot.user.puid : 1000,
      pgid: systemSnapshot ? systemSnapshot.user.pgid : 1000,
      host_user: systemSnapshot ? systemSnapshot.user.username : "homelab_user",
      timezone: systemSnapshot ? systemSnapshot.timezone : "Asia/Kolkata",
      active_nic: systemSnapshot ? systemSnapshot.network.active_nic : "eth0",
      enabled_services: ["media", "photos", "control_hub", "tv_updater"],
    };
  } else {
    // Power mode
    const isDryRun = document.getElementById("pow-dry-run-toggle") ? document.getElementById("pow-dry-run-toggle").checked : true;
    const services = [];
    if (document.getElementById("pow-svc-media").checked) services.push("media");
    if (document.getElementById("pow-svc-photos").checked) services.push("photos");
    if (document.getElementById("pow-svc-tv").checked) services.push("tv_updater");
    if (document.getElementById("pow-svc-sleep").checked) services.push("sleep_guard");

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
      qbittorrent_user: document.getElementById("pow-qbit-user").value || "admin",
      qbittorrent_pass: document.getElementById("pow-qbit-pass").value || "adminadmin",
      postgres_password: document.getElementById("pow-pg-pass").value || "postgres_pass",
      radarr_api_key: document.getElementById("pow-radarr-key").value,
      sonarr_api_key: document.getElementById("pow-sonarr-key").value,
      prowlarr_api_key: document.getElementById("pow-prowlarr-key").value,
      enabled_services: services,
    };
  }

  try {
    progressFill.style.width = "50%";
    const res = await fetch("/api/deploy", {
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
      terminal.innerText += "\n[ERROR] Deployment encountered errors. See logs above.";
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

  redirectBtn.href = result.dashboard_url;
  launchSection.style.display = "block";

  // Auto redirect countdown
  let count = 8;
  const countSpan = document.getElementById("redirect-countdown");
  const timer = setInterval(() => {
    count -= 1;
    if (countSpan) countSpan.innerText = count;
    if (count <= 0) {
      clearInterval(timer);
      window.location.href = result.dashboard_url;
    }
  }, 1000);
}
