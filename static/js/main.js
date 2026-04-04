// ── Globals ───────────────────────────────────────────────────────────────────
const PLOTLY_LAYOUT = {
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
  font: { color: "#e0e0e0", family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", size: 12 },
  margin: { l: 50, r: 30, t: 30, b: 50 },
  xaxis: { gridcolor: "#2e3347", zerolinecolor: "#2e3347" },
  yaxis: { gridcolor: "#2e3347", zerolinecolor: "#2e3347" },
  legend: { bgcolor: "transparent", borderwidth: 0 },
  colorway: ["#4a90d9", "#27ae60", "#f1c40f", "#e67e22", "#e74c3c", "#9b59b6", "#1abc9c"],
};
const PLOTLY_CONFIG = { responsive: true, displayModeBar: false };
const ZONE_COLORS = { Z1: "#4a90d9", Z2: "#27ae60", Z3: "#f1c40f", Z4: "#e67e22", Z5: "#e74c3c", Easy: "#27ae60", Moderate: "#f1c40f", Hard: "#e74c3c" };

// Track which tabs have been loaded
const tabLoaded = {};
let currentParams = {};

// ── Params ────────────────────────────────────────────────────────────────────
function getParams() {
  const sports = Array.from(document.getElementById("sports-select").selectedOptions).map(o => o.value);
  return {
    max_hr: document.getElementById("max-hr").value,
    resting_hr: document.getElementById("resting-hr").value,
    zone_model: document.getElementById("zone-model").value,
    date_start: document.getElementById("date-start").value,
    date_end: document.getElementById("date-end").value,
    sports,
    window_days: document.getElementById("zone-window")?.value || 90,
  };
}

function buildQuery(params) {
  const p = new URLSearchParams();
  p.set("max_hr", params.max_hr);
  p.set("resting_hr", params.resting_hr);
  p.set("zone_model", params.zone_model);
  if (params.date_start) p.set("date_start", params.date_start);
  if (params.date_end) p.set("date_end", params.date_end);
  if (params.window_days) p.set("window_days", params.window_days);
  (params.sports || []).forEach(s => p.append("sports", s));
  return p.toString();
}

async function fetchAPI(endpoint, params) {
  const res = await fetch(`/api/${endpoint}?${buildQuery(params)}`);
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = body.traceback || body.error || "";
    } catch (_) {}
    throw new Error(`API /${endpoint} returned ${res.status}${detail ? ":\n" + detail : ""}`);
  }
  return res.json();
}

// ── Loading overlay ───────────────────────────────────────────────────────────
function showLoading(msg = "Loading…") {
  document.getElementById("loading-msg").textContent = msg;
  document.getElementById("loading-overlay").classList.remove("hidden");
}
function hideLoading() {
  document.getElementById("loading-overlay").classList.add("hidden");
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function activateTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === tabName));
  document.querySelectorAll(".tab-content").forEach(s => s.classList.toggle("active", s.id === `tab-${tabName}`));
  if (!tabLoaded[tabName]) loadTab(tabName);
}

async function loadTab(tabName) {
  const params = getParams();
  try {
    if (tabName === "overview") {
      showLoading("Loading overview…");
      const data = await fetchAPI("overview", params);
      renderOverview(data);
    } else if (tabName === "hr-zones") {
      showLoading("Loading HR zones (stream data may take ~10s on first load)…");
      const data = await fetchAPI("hr-zones", params);
      renderHRZones(data);
    } else if (tabName === "fitness") {
      showLoading("Loading fitness tracker…");
      const data = await fetchAPI("fitness", params);
      renderFitness(data);
    } else if (tabName === "pacing") {
      showLoading("Loading pacing data…");
      const data = await fetchAPI("pacing", params);
      renderPacing(data);
    } else if (tabName === "periodization") {
      showLoading("Loading periodization…");
      const data = await fetchAPI("periodization", params);
      renderPeriodization(data);
    }
    tabLoaded[tabName] = true;
  } catch (err) {
    console.error(err);
    showError(tabName, err.message);
  } finally {
    hideLoading();
  }
}

function showError(tabName, message) {
  const section = document.getElementById(`tab-${tabName}`);
  if (!section) return;
  let box = section.querySelector(".error-box");
  if (!box) {
    box = document.createElement("div");
    box.className = "error-box";
    section.prepend(box);
  }
  box.innerHTML = `<strong>Failed to load data</strong><pre>${escapeHtml(message)}</pre>` +
    `<a href="/api/debug" target="_blank" class="debug-link">Open /api/debug for diagnostics</a>`;
}

function escapeHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function reloadAllLoaded() {
  Object.keys(tabLoaded).forEach(tab => { tabLoaded[tab] = false; });
  const activeTab = document.querySelector(".tab-btn.active")?.dataset.tab || "overview";
  loadTab(activeTab);
}

// ── KPI card helper ───────────────────────────────────────────────────────────
function kpiCard(label, value, delta, deltaClass) {
  return `<div class="kpi-card">
    <div class="kpi-label">${label}</div>
    <div class="kpi-value">${value}</div>
    ${delta ? `<div class="kpi-delta ${deltaClass}">${delta}</div>` : ""}
  </div>`;
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  showLoading("Initialising…");
  try {
    const cfg = await fetchAPI("config", {});
    document.getElementById("max-hr").value = cfg.max_hr;
    document.getElementById("date-start").value = cfg.date_min;
    document.getElementById("date-end").value = cfg.date_max;
    document.getElementById("header-meta").textContent =
      `${cfg.total_activities.toLocaleString()} activities · ${cfg.date_min} → ${cfg.date_max}`;

    const sel = document.getElementById("sports-select");
    cfg.sports.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      opt.selected = ["Run", "TrailRun"].includes(s);
      sel.appendChild(opt);
    });
    // Expand multi-select to show all options
    sel.size = Math.min(cfg.sports.length, 5);
  } catch (e) {
    console.error("Config load failed", e);
    document.getElementById("header-meta").innerHTML =
      `<span class="error-inline">Config failed: ${escapeHtml(e.message)} — ` +
      `<a href="/api/debug" target="_blank">open /api/debug</a></span>`;
    hideLoading();
    return;
  }

  // Tab buttons
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
  });

  // Apply button
  document.getElementById("apply-btn").addEventListener("click", reloadAllLoaded);

  // Zone window change triggers HR zone reload
  document.getElementById("zone-window")?.addEventListener("change", () => {
    tabLoaded["hr-zones"] = false;
    if (document.querySelector(".tab-btn.active")?.dataset.tab === "hr-zones") loadTab("hr-zones");
  });

  // Load first tab
  await loadTab("overview");
  hideLoading();

  // Keboola status (non-blocking)
  loadKeboolaStatus();
}

// ── Keboola sync ─────────────────────────────────────────────────────────────
async function loadKeboolaStatus() {
  try {
    const res = await fetch("/api/keboola-status");
    if (!res.ok) return;
    const data = await res.json();
    const el = document.getElementById("last-update-value");
    if (!el) return;
    if (data.last_run) {
      const d = new Date(data.last_run);
      el.textContent = d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
    } else {
      el.textContent = "—";
    }
  } catch (_) {}
}

async function triggerKeboolaRun() {
  const btn = document.getElementById("keboola-run-btn");
  btn.disabled = true;
  btn.textContent = "Running…";
  try {
    const res = await fetch("/api/keboola-run", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || JSON.stringify(data));
    btn.textContent = "✓ Started";
    setTimeout(() => { btn.textContent = "▶ Sync"; btn.disabled = false; }, 3000);
  } catch (e) {
    console.error("Keboola run error:", e.message);
    btn.textContent = "✗ Error";
    btn.title = e.message;
    // Show inline error below button
    let errEl = document.getElementById("keboola-run-error");
    if (!errEl) {
      errEl = document.createElement("span");
      errEl.id = "keboola-run-error";
      errEl.style.cssText = "color:#e74c3c;font-size:11px;max-width:300px;word-break:break-all;";
      document.getElementById("keboola-bar").appendChild(errEl);
    }
    errEl.textContent = e.message;
    setTimeout(() => {
      btn.textContent = "▶ Sync";
      btn.disabled = false;
      btn.title = "Run Keboola sync job";
      if (errEl) errEl.textContent = "";
    }, 8000);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("keboola-run-btn")?.addEventListener("click", triggerKeboolaRun);
});

document.addEventListener("DOMContentLoaded", init);
