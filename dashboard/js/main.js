/* ──────────────────────────────────────────────────────────────────────────
   Arabic OSINT Intelligence Dashboard — Main JS
   Handles: KPIs, timeline, radar, compare, doughnut, delta,
            source-type analysis, divergence alerts, platform breakdown,
            heatmap, assessment cards, all filters.
   ────────────────────────────────────────────────────────────────────────── */
"use strict";

// ── State ───────────────────────────────────────────────────────────────────
let REPORT = null;
let activeGroup = "all";
let activeTheme = "all";
let activeConf = new Set(["high", "medium"]);
let chartView = "score";
let srcView = "bar";

// Chart instances (destroy before re-render)
const CHARTS = {};

const GROUP_COLORS = {
  hezbollah: "#FFD700",
  irgc_iran:  "#f87171",
  houthis:    "#4ade80",
  hamas_pij:  "#94a3b8",
};
const rgba = (hex, a) => {
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${a})`;
};
const groupRgba = (gid, a) => rgba(GROUP_COLORS[gid] || "#3b82f6", a);

const SOURCE_TYPE_ORDER = [
  "official_media","official_telegram","rss_feed","web_official",
  "twitter_official","affiliated_telegram","twitter_affiliated","civilian_telegram",
];
const SOURCE_LABELS = {
  official_media:      "Official Media",
  official_telegram:   "Official Telegram",
  affiliated_telegram: "Affiliated Telegram",
  civilian_telegram:   "Civilian Telegram",
  twitter_official:    "Official Twitter",
  twitter_affiliated:  "Affiliated Twitter",
  rss_feed:            "RSS / News",
  web_official:        "Official Websites",
};
const SOURCE_COLORS = {
  official_media:      "#ef4444",
  official_telegram:   "#f97316",
  affiliated_telegram: "#eab308",
  civilian_telegram:   "#22c55e",
  twitter_official:    "#818cf8",
  twitter_affiliated:  "#a78bfa",
  rss_feed:            "#06b6d4",
  web_official:        "#64748b",
};

const THEME_LABELS = {
  military_morale:         "Military Morale",
  civilian_support:        "Civilian Support",
  economic_hardship:       "Economic Pressure",
  military_operations:     "Operations",
  leadership_trust:        "Leadership Trust",
  international_relations: "Int'l Relations",
  propaganda_intensity:    "Propaganda",
  humanitarian:            "Humanitarian",
};

Chart.defaults.color = "#8899b5";
Chart.defaults.borderColor = "#1f2d47";
Chart.defaults.font.family = "'Inter', sans-serif";

// ── Bootstrap ───────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  try {
    const res = await fetch("data/intelligence_report.json");
    REPORT = await res.json();
    init();
  } catch (e) {
    console.error(e);
    document.querySelector(".alert-banner").textContent =
      "⚠ Failed to load intelligence_report.json. Run: python main.py --mode demo";
  }
});

function init() {
  updateMeta();
  renderKPIs();
  renderAlertBanner();
  renderTimeline();
  renderRadar();
  renderCompare();
  renderDoughnut();
  renderDelta();
  renderSourceTypeSection();
  renderHeatmap();
  renderPlatformChart();
  renderAssessments();
  bindFilters();
}

function destroyChart(id) {
  if (CHARTS[id]) { CHARTS[id].destroy(); delete CHARTS[id]; }
}

// ── META ────────────────────────────────────────────────────────────────────
function updateMeta() {
  const ts = new Date(REPORT.meta.generated_at);
  document.getElementById("report-ts").textContent =
    `Generated: ${ts.toISOString().slice(0,16).replace("T"," ")} UTC`;
  const stats = REPORT.meta.collection_stats || {};
  document.getElementById("stat-total").textContent =
    (stats.total_posts || REPORT.meta.total_posts_analyzed || 0).toLocaleString();
  const plat = REPORT.summary.platforms || {};
  document.getElementById("stat-telegram").textContent = (plat.telegram||0).toLocaleString();
  document.getElementById("stat-twitter").textContent  = (plat.twitter||0).toLocaleString();
  document.getElementById("stat-assessments").textContent = REPORT.assessments.length;
}

// ── KPI CARDS ───────────────────────────────────────────────────────────────
function renderKPIs() {
  const grid = document.getElementById("kpi-grid");
  grid.innerHTML = "";
  Object.entries(REPORT.summary.groups).forEach(([gid, g]) => {
    const oa = REPORT.assessments.find(a => a.group_id === gid && a.theme === "overall");
    const delta = oa ? oa.delta_pct : null;
    const score = g.avg_sentiment_score;
    const scoreClass = score > 0.05 ? "pos" : score < -0.05 ? "neg" : "neu";
    const deltaClass = delta === null ? "flat" : delta < 0 ? "down" : "up";
    const deltaArrow = delta === null ? "—" : delta < 0 ? "▼" : "▲";

    // Divergence score from source analysis
    const srcData = (REPORT.source_analysis || {})[gid] || {};
    const divScore = srcData.narrative_divergence_score || 0;
    const divColor = divScore > 0.6 ? "#ef4444" : divScore > 0.3 ? "#f59e0b" : "#22c55e";

    const card = document.createElement("div");
    card.className = "kpi-card";
    card.style.setProperty("--g-color", g.color);
    card.dataset.group = gid;
    card.innerHTML = `
      <div class="kpi-group-name">${g.display_name}</div>
      <div class="kpi-score ${scoreClass}">${score >= 0 ? "+" : ""}${score.toFixed(3)}</div>
      ${delta !== null
        ? `<div class="kpi-delta ${deltaClass}">${deltaArrow} ${Math.abs(delta).toFixed(1)} pp vs 2024</div>`
        : `<div class="kpi-delta flat">—</div>`}
      <div class="kpi-bars">
        <div class="kpi-bar-pos" style="flex:${g.positive_pct}"></div>
        <div class="kpi-bar-neg" style="flex:${g.negative_pct}"></div>
        <div class="kpi-bar-neu" style="flex:${g.neutral_pct}"></div>
      </div>
      <div class="kpi-row">
        <span style="color:var(--positive)">▲ ${g.positive_pct}%</span>
        <span style="color:var(--negative)">▼ ${g.negative_pct}%</span>
        <span style="color:var(--neutral)">◆ ${g.neutral_pct}%</span>
      </div>
      <div class="kpi-posts" style="display:flex;justify-content:space-between;margin-top:8px">
        <span>${g.post_count.toLocaleString()} posts</span>
        <span style="color:${divColor};font-weight:600;font-size:10px">⊗ DIV ${divScore.toFixed(2)}</span>
      </div>`;
    card.addEventListener("click", () => {
      document.querySelectorAll(".group-btn").forEach(b => b.classList.remove("active"));
      document.querySelector(`.group-btn[data-group="${gid}"]`)?.classList.add("active");
      activeGroup = gid;
      applyFilters();
    });
    grid.appendChild(card);
  });
}

// ── ALERT BANNER ────────────────────────────────────────────────────────────
function renderAlertBanner() {
  // Find highest-severity divergence alert
  let worst = null;
  for (const [gid, src] of Object.entries(REPORT.source_analysis || {})) {
    for (const alert of src.divergence_alerts || []) {
      if (!worst || alert.severity === "critical") worst = { gid, alert, name: src.group_display_name };
    }
  }
  if (worst) {
    document.getElementById("alert-text").textContent =
      `CRITICAL DIVERGENCE — ${worst.name}: Official channels ${worst.alert.propaganda_score >= 0 ? "+" : ""}${worst.alert.propaganda_score.toFixed(2)} vs Civilian channels ${worst.alert.grassroots_score.toFixed(2)} (Δ ${worst.alert.delta.toFixed(2)}) — ${worst.alert.interpretation.slice(0, 180)}…`;
  } else {
    const top = REPORT.summary.top_assessments?.[0];
    if (top) document.getElementById("alert-text").textContent =
      `TOP FINDING: ${top.group} — ${top.theme_label}: ${top.narrative.slice(0, 200)}…`;
  }
}

// ── TIMELINE CHART ──────────────────────────────────────────────────────────
function renderTimeline(view = chartView) {
  destroyChart("timeline");
  const ctx = document.getElementById("timelineChart").getContext("2d");
  const timeline = REPORT.timeline;
  const groups = REPORT.summary.groups;
  const allMonths = new Set();
  Object.values(timeline).forEach(arr => arr.forEach(d => allMonths.add(d.month)));
  const months = [...allMonths].sort();

  const datasets = Object.entries(timeline)
    .filter(([gid]) => activeGroup === "all" || gid === activeGroup)
    .map(([gid, data]) => {
      const mm = Object.fromEntries(data.map(d => [d.month, d]));
      const values = months.map(m => {
        const d = mm[m];
        if (!d) return null;
        return view === "score" ? d.avg_sentiment : view === "negative" ? d.negative_pct : d.positive_pct;
      });
      return {
        label: groups[gid]?.display_name ?? gid,
        data: values,
        borderColor: GROUP_COLORS[gid] || "#3b82f6",
        backgroundColor: groupRgba(gid, 0.07),
        pointBackgroundColor: GROUP_COLORS[gid],
        pointRadius: 2, pointHoverRadius: 5,
        borderWidth: 2, fill: true, tension: 0.35, spanGaps: true,
      };
    });

  CHARTS.timeline = new Chart(ctx, {
    type: "line",
    data: { labels: months, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, padding: 12, font: { size: 10 } } },
        tooltip: { callbacks: { label: c => {
          const v = c.parsed.y;
          return v === null ? "" : `${c.dataset.label}: ${view === "score" ? (v >= 0 ? "+" : "") + v.toFixed(3) : v.toFixed(1) + "%"}`;
        }}},
        annotation: { annotations: { periodLine: {
          type: "line", xMin: "2025-01", xMax: "2025-01",
          borderColor: "rgba(59,130,246,0.5)", borderWidth: 1, borderDash: [4, 4],
          label: { display: true, content: "2025 →", color: "#3b82f6", font: { size: 9 }, position: "start" },
        }}},
      },
      scales: {
        x: { ticks: { maxTicksLimit: 10, font: { size: 9 }, color: "#4a5a78" }, grid: { color: "rgba(31,45,71,0.6)" } },
        y: { ticks: { font: { size: 9 }, color: "#4a5a78", callback: v => view === "score" ? (v >= 0 ? "+" : "") + v.toFixed(2) : v.toFixed(0) + "%" }, grid: { color: "rgba(31,45,71,0.6)" } },
      },
    },
  });
}

// ── RADAR ───────────────────────────────────────────────────────────────────
function renderRadar() {
  destroyChart("radar");
  const ctx = document.getElementById("radarChart").getContext("2d");
  const matrix = REPORT.theme_matrix;
  const groups = REPORT.summary.groups;
  const themeIds = Object.keys(THEME_LABELS);
  const labels = themeIds.map(t => THEME_LABELS[t]);

  const datasets = Object.entries(matrix)
    .filter(([gid]) => activeGroup === "all" || gid === activeGroup)
    .map(([gid, themes]) => ({
      label: groups[gid]?.display_name ?? gid,
      data: themeIds.map(t => Math.round(((themes[t]?.avg_sentiment ?? 0) + 1) * 50)),
      borderColor: GROUP_COLORS[gid] || "#3b82f6",
      backgroundColor: groupRgba(gid, 0.12),
      pointBackgroundColor: GROUP_COLORS[gid],
      borderWidth: 1.5, pointRadius: 3,
    }));

  CHARTS.radar = new Chart(ctx, {
    type: "radar",
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { boxWidth: 8, padding: 8, font: { size: 9 } } } },
      scales: { r: {
        min: 0, max: 100,
        ticks: { stepSize: 25, font: { size: 8 }, color: "#4a5a78", backdropColor: "transparent",
          callback: v => v === 50 ? "neutral" : v === 0 ? "−1" : v === 100 ? "+1" : "" },
        grid: { color: "rgba(31,45,71,0.8)" },
        pointLabels: { font: { size: 9 }, color: "#8899b5" },
        angleLines: { color: "rgba(31,45,71,0.8)" },
      }},
    },
  });
}

// ── COMPARE ─────────────────────────────────────────────────────────────────
function renderCompare() {
  destroyChart("compare");
  const ctx = document.getElementById("compareChart").getContext("2d");
  const assessments = REPORT.assessments.filter(a => a.theme === "overall");
  const groups = Object.entries(REPORT.summary.groups)
    .filter(([gid]) => activeGroup === "all" || gid === activeGroup);

  CHARTS.compare = new Chart(ctx, {
    type: "bar",
    data: {
      labels: groups.map(([, g]) => g.display_name),
      datasets: [
        { label: "2024 Baseline", data: groups.map(([gid]) => assessments.find(a => a.group_id === gid)?.baseline_score ?? 0), backgroundColor: "rgba(99,102,241,0.6)", borderColor: "rgba(99,102,241,1)", borderWidth: 1 },
        { label: "Current", data: groups.map(([gid]) => assessments.find(a => a.group_id === gid)?.current_score ?? 0), backgroundColor: groups.map(([gid]) => groupRgba(gid, 0.6)), borderColor: groups.map(([gid]) => GROUP_COLORS[gid] || "#3b82f6"), borderWidth: 1 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { boxWidth: 10, padding: 10, font: { size: 10 } } } },
      scales: {
        x: { grid: { color: "rgba(31,45,71,0.6)" }, ticks: { font: { size: 10 }, color: "#8899b5" } },
        y: { grid: { color: "rgba(31,45,71,0.6)" }, ticks: { font: { size: 9 }, color: "#4a5a78", callback: v => (v >= 0 ? "+" : "") + v.toFixed(2) } },
      },
    },
  });
}

// ── DOUGHNUT ─────────────────────────────────────────────────────────────────
function renderDoughnut() {
  destroyChart("doughnut");
  const ctx = document.getElementById("doughnutChart").getContext("2d");
  const groups = Object.entries(REPORT.summary.groups).filter(([gid]) => activeGroup === "all" || gid === activeGroup);
  let pos = 0, neg = 0, neu = 0, total = 0;
  groups.forEach(([, g]) => { pos += g.positive_pct * g.post_count; neg += g.negative_pct * g.post_count; neu += g.neutral_pct * g.post_count; total += g.post_count; });
  const t = Math.max(total, 1);
  CHARTS.doughnut = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: ["Positive", "Negative", "Neutral"],
      datasets: [{ data: [(pos/t).toFixed(1),(neg/t).toFixed(1),(neu/t).toFixed(1)], backgroundColor: ["rgba(34,197,94,0.75)","rgba(239,68,68,0.75)","rgba(245,158,11,0.5)"], borderColor: ["#22c55e","#ef4444","#f59e0b"], borderWidth: 1, hoverOffset: 6 }],
    },
    options: { responsive: true, maintainAspectRatio: false, cutout: "62%", plugins: { legend: { position: "bottom", labels: { boxWidth: 10, padding: 10, font: { size: 10 } } }, tooltip: { callbacks: { label: c => `${c.label}: ${c.parsed}%` } } } },
  });
}

// ── DELTA ───────────────────────────────────────────────────────────────────
function renderDelta() {
  destroyChart("delta");
  const ctx = document.getElementById("deltaChart").getContext("2d");
  const assessments = REPORT.assessments
    .filter(a => (activeGroup === "all" || a.group_id === activeGroup) && activeConf.has(a.confidence))
    .slice(0, 10);
  CHARTS.delta = new Chart(ctx, {
    type: "bar",
    data: {
      labels: assessments.map(a => `${a.group_display_name} · ${a.theme_label}`),
      datasets: [{ label: "Δ pp vs 2024", data: assessments.map(a => a.delta_pct), backgroundColor: assessments.map(a => a.delta_pct < 0 ? "rgba(239,68,68,0.75)" : "rgba(34,197,94,0.75)"), borderColor: assessments.map(a => a.delta_pct < 0 ? "#ef4444" : "#22c55e"), borderWidth: 1 }],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `Δ ${c.parsed.x >= 0 ? "+" : ""}${c.parsed.x.toFixed(1)} pp` } } },
      scales: {
        x: { grid: { color: "rgba(31,45,71,0.6)" }, ticks: { font: { size: 9 }, color: "#4a5a78", callback: v => (v >= 0 ? "+" : "") + v.toFixed(0) + " pp" } },
        y: { ticks: { font: { size: 9 }, color: "#8899b5" }, grid: { display: false } },
      },
    },
  });
}

// ── SOURCE TYPE ANALYSIS ─────────────────────────────────────────────────────
function renderSourceTypeSection() {
  renderDivergenceAlerts();
  renderSourceTypeChart();
  renderSourcePieChart();
  renderSourceProfileCards();
}

function renderDivergenceAlerts() {
  const container = document.getElementById("divergence-alerts");
  container.innerHTML = "";
  const srcAnalysis = REPORT.source_analysis || {};

  Object.entries(srcAnalysis)
    .filter(([gid]) => activeGroup === "all" || gid === activeGroup)
    .forEach(([gid, data]) => {
      (data.divergence_alerts || []).forEach(alert => {
        const div = document.createElement("div");
        div.className = `divergence-alert ${alert.severity}`;
        const propColor = alert.propaganda_score >= 0 ? "pos" : "neg";
        const grassColor = alert.grassroots_score >= 0 ? "pos" : "neg";
        div.innerHTML = `
          <div>
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
              <span class="div-severity ${alert.severity}">${alert.severity.toUpperCase()}</span>
              <span class="div-group" style="color:${GROUP_COLORS[gid]||'#fff'}">${data.group_display_name}</span>
            </div>
            <div class="div-text">${alert.interpretation.slice(0, 300)}${alert.interpretation.length > 300 ? "…" : ""}</div>
          </div>
          <div class="div-scores">
            <div class="div-score-box">
              <div class="div-score-label">Official</div>
              <div class="div-score-val ${propColor}">${alert.propaganda_score >= 0 ? "+" : ""}${alert.propaganda_score.toFixed(2)}</div>
            </div>
            <div class="div-score-box">
              <div class="div-score-label">Civilian</div>
              <div class="div-score-val ${grassColor}">${alert.grassroots_score.toFixed(2)}</div>
            </div>
            <div class="div-score-box">
              <div class="div-score-label">Gap</div>
              <div class="div-score-val neg">${alert.delta.toFixed(2)}</div>
            </div>
          </div>`;
        container.appendChild(div);
      });
    });
}

function renderSourceTypeChart() {
  destroyChart("sourceType");
  const ctx = document.getElementById("sourceTypeChart").getContext("2d");
  const srcAnalysis = REPORT.source_analysis || {};
  const filtered = Object.entries(srcAnalysis)
    .filter(([gid]) => activeGroup === "all" || gid === activeGroup);

  if (!filtered.length) return;

  // Build dataset per source type across groups
  const stypes = SOURCE_TYPE_ORDER.filter(st =>
    filtered.some(([, d]) => d.profiles?.[st])
  );
  const groupLabels = filtered.map(([, d]) => d.group_display_name);

  const datasets = stypes.map(st => ({
    label: SOURCE_LABELS[st] || st,
    data: filtered.map(([, d]) => d.profiles?.[st]?.avg_sentiment ?? null),
    backgroundColor: rgba(SOURCE_COLORS[st] || "#888", 0.7),
    borderColor: SOURCE_COLORS[st] || "#888",
    borderWidth: 1,
    borderRadius: 3,
  }));

  CHARTS.sourceType = new Chart(ctx, {
    type: "bar",
    data: { labels: groupLabels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, padding: 8, font: { size: 9 } } },
        tooltip: { callbacks: { label: c => c.parsed.y === null ? "" : `${c.dataset.label}: ${c.parsed.y >= 0 ? "+" : ""}${c.parsed.y.toFixed(3)}` } },
      },
      scales: {
        x: { grid: { color: "rgba(31,45,71,0.6)" }, ticks: { font: { size: 10 }, color: "#8899b5" } },
        y: { grid: { color: "rgba(31,45,71,0.6)" }, ticks: { font: { size: 9 }, color: "#4a5a78", callback: v => (v >= 0 ? "+" : "") + v.toFixed(2) } },
      },
    },
  });
}

function renderSourcePieChart() {
  destroyChart("sourcePie");
  const ctx = document.getElementById("sourcePieChart").getContext("2d");
  // Show post count distribution by source type for current active group
  const gid = activeGroup === "all" ? "hezbollah" : activeGroup;
  const srcData = (REPORT.source_analysis || {})[gid];
  if (!srcData) return;

  const profiles = srcData.profiles || {};
  const labels = Object.keys(profiles).map(st => SOURCE_LABELS[st] || st);
  const counts = Object.values(profiles).map(p => p.post_count);
  const colors = Object.keys(profiles).map(st => SOURCE_COLORS[st] || "#888");

  CHARTS.sourcePie = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{ data: counts, backgroundColor: colors.map(c => rgba(c, 0.75)), borderColor: colors, borderWidth: 1, hoverOffset: 6 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: "55%",
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 8, padding: 8, font: { size: 9 } } },
        tooltip: { callbacks: { label: c => `${c.label}: ${c.parsed.toLocaleString()} posts` } },
      },
    },
  });
}

function renderSourceProfileCards() {
  const container = document.getElementById("source-profiles-grid");
  container.innerHTML = "";
  const gid = activeGroup === "all" ? null : activeGroup;
  const targets = gid
    ? [[gid, (REPORT.source_analysis || {})[gid]]]
    : Object.entries(REPORT.source_analysis || {}).slice(0, 1);

  // Show profiles for first group (or selected group)
  const [, srcData] = targets[0] || [];
  if (!srcData) return;

  SOURCE_TYPE_ORDER.forEach(st => {
    const p = srcData.profiles?.[st];
    if (!p) return;
    const scoreClass = p.avg_sentiment > 0.05 ? "pos" : p.avg_sentiment < -0.05 ? "neg" : "neu";
    const color = SOURCE_COLORS[st] || "#888";
    const card = document.createElement("div");
    card.className = "source-profile-card";
    card.style.setProperty("--st-color", color);
    card.innerHTML = `
      <div class="sp-type-label">${SOURCE_LABELS[st] || st}</div>
      <div class="sp-score ${scoreClass}">${p.avg_sentiment >= 0 ? "+" : ""}${p.avg_sentiment.toFixed(3)}</div>
      <div class="sp-count">${p.post_count.toLocaleString()} posts</div>
      <div class="sp-bar">
        <div style="flex:${p.positive_pct};background:var(--positive)"></div>
        <div style="flex:${p.negative_pct};background:var(--negative)"></div>
        <div style="flex:${p.neutral_pct};background:var(--neutral);opacity:0.5"></div>
      </div>
      <div class="sp-sources">
        ${(p.top_sources || []).slice(0, 3).map(s => `<span>· ${s}</span>`).join("")}
      </div>`;
    container.appendChild(card);
  });
}

// ── PLATFORM CHART ───────────────────────────────────────────────────────────
function renderPlatformChart() {
  destroyChart("platform");
  const ctx = document.getElementById("platformChart").getContext("2d");
  const pd = REPORT.platform_breakdown || {};
  const platforms = ["telegram", "twitter", "rss", "web"];
  const platformLabels = { telegram: "Telegram", twitter: "Twitter/X", rss: "RSS/News", web: "Web" };

  const groups = Object.entries(REPORT.summary.groups)
    .filter(([gid]) => activeGroup === "all" || gid === activeGroup);

  const datasets = groups.map(([gid, g]) => ({
    label: g.display_name,
    data: platforms.map(p => pd[gid]?.[p]?.avg_sentiment ?? null),
    backgroundColor: groupRgba(gid, 0.65),
    borderColor: GROUP_COLORS[gid] || "#3b82f6",
    borderWidth: 1, borderRadius: 3,
  }));

  CHARTS.platform = new Chart(ctx, {
    type: "bar",
    data: { labels: platforms.map(p => platformLabels[p] || p), datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "bottom", labels: { boxWidth: 10, padding: 10, font: { size: 10 } } } },
      scales: {
        x: { grid: { color: "rgba(31,45,71,0.6)" }, ticks: { font: { size: 10 }, color: "#8899b5" } },
        y: { grid: { color: "rgba(31,45,71,0.6)" }, ticks: { font: { size: 9 }, color: "#4a5a78", callback: v => (v >= 0 ? "+" : "") + v.toFixed(2) } },
      },
    },
  });
}

// ── HEATMAP ─────────────────────────────────────────────────────────────────
function renderHeatmap() {
  const container = document.getElementById("heatmap-container");
  const matrix = REPORT.theme_matrix;
  const groups = Object.entries(REPORT.summary.groups)
    .filter(([gid]) => activeGroup === "all" || gid === activeGroup);
  const themeIds = Object.keys(THEME_LABELS);

  let html = `<table class="heatmap-table"><thead><tr>
    <th class="row-header">Theme</th>
    ${groups.map(([, g]) => `<th style="color:${g.color}">${g.display_name}</th>`).join("")}
  </tr></thead><tbody>`;
  themeIds.forEach(tid => {
    html += `<tr><td>${THEME_LABELS[tid]}</td>`;
    groups.forEach(([gid]) => {
      const val = matrix[gid]?.[tid]?.avg_sentiment ?? null;
      const count = matrix[gid]?.[tid]?.count ?? 0;
      if (val === null) { html += `<td style="color:#4a5a78">—</td>`; return; }
      const r = val < 0 ? 239 : 34, g = val < 0 ? 68 : 197, b = val < 0 ? 68 : 94;
      const alpha = Math.min(Math.abs(val) * 0.7 + 0.1, 0.9);
      const textColor = val < 0 ? "#fca5a5" : "#86efac";
      html += `<td style="background:rgba(${r},${g},${b},${alpha});color:${textColor}" title="${THEME_LABELS[tid]} | n=${count.toLocaleString()}">${val >= 0 ? "+" : ""}${val.toFixed(2)}</td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody></table>`;
  container.innerHTML = html;
}

// ── ASSESSMENTS ─────────────────────────────────────────────────────────────
function renderAssessments() {
  const list = document.getElementById("assessments-list");
  const filtered = REPORT.assessments.filter(a => {
    if (activeGroup !== "all" && a.group_id !== activeGroup) return false;
    if (activeTheme !== "all" && a.theme !== activeTheme) return false;
    if (!activeConf.has(a.confidence)) return false;
    return true;
  });
  if (!filtered.length) {
    list.innerHTML = `<div style="color:var(--text-muted);padding:24px;text-align:center">No assessments match current filters.</div>`;
    return;
  }
  list.innerHTML = filtered.map((a, i) => {
    const dirIcon = a.direction === "decrease" ? "▼" : a.direction === "increase" ? "▲" : "➡";
    const evidenceHTML = (a.evidence || []).slice(0, 3).map(e => `
      <div class="evidence-post">
        <span class="evidence-platform ${e.platform}">${e.platform}</span>
        <span class="evidence-source">${e.source}</span>
        ${e.source_type ? `<span style="font-size:9px;color:${SOURCE_COLORS[e.source_type]||'#888'};padding:2px 6px;background:var(--bg-4);border-radius:3px">${SOURCE_LABELS[e.source_type]||e.source_type}</span>` : ""}
        <span class="evidence-sentiment ${e.sentiment}">${e.sentiment}</span>
        <div class="evidence-text">${escHtml(e.text)}</div>
        <span class="evidence-ts">${e.timestamp?.slice(0,10) ?? ""}</span>
      </div>`).join("");

    return `
      <div class="assessment-card ${a.confidence}">
        <div class="assessment-header" onclick="toggleAssessment(${i})">
          <span class="asmnt-group-badge" style="color:${GROUP_COLORS[a.group_id]||'#3b82f6'}">${a.group_display_name}</span>
          <span class="asmnt-theme-badge">${a.theme_label}</span>
          <span class="asmnt-direction ${a.direction}">${dirIcon} ${a.magnitude} ${a.direction}</span>
          <span class="asmnt-delta" style="color:${a.delta_pct < 0 ? "var(--negative)" : "var(--positive)"}">${a.delta_pct >= 0 ? "+" : ""}${a.delta_pct.toFixed(1)} pp</span>
          <span class="asmnt-conf ${a.confidence}">${a.confidence}</span>
          <span class="asmnt-toggle" id="toggle-${i}">▼</span>
        </div>
        <div class="assessment-body" id="body-${i}">
          <div class="asmnt-narrative">${a.narrative}</div>
          <div class="score-comparison">
            <div class="score-box"><div class="score-box-label">2024 Baseline</div><div class="score-box-val ${a.baseline_score >= 0 ? "pos" : "neg"}">${a.baseline_score >= 0 ? "+" : ""}${a.baseline_score.toFixed(3)}</div></div>
            <div class="score-arrow">→</div>
            <div class="score-box"><div class="score-box-label">Current</div><div class="score-box-val ${a.current_score >= 0 ? "pos" : "neg"}">${a.current_score >= 0 ? "+" : ""}${a.current_score.toFixed(3)}</div></div>
            <div class="score-box"><div class="score-box-label">Change</div><div class="score-box-val ${a.delta_pct < 0 ? "neg" : "pos"}">${a.delta_pct >= 0 ? "+" : ""}${a.delta_pct.toFixed(1)} pp</div></div>
          </div>
          ${evidenceHTML ? `<div class="evidence-section"><div class="evidence-label">Supporting Evidence</div><div class="evidence-list">${evidenceHTML}</div></div>` : ""}
        </div>
      </div>`;
  }).join("");
  const firstHigh = filtered.findIndex(a => a.confidence === "high");
  if (firstHigh >= 0) toggleAssessment(firstHigh);
}

window.toggleAssessment = (i) => {
  const body = document.getElementById(`body-${i}`);
  const toggle = document.getElementById(`toggle-${i}`);
  if (!body) return;
  body.classList.toggle("open");
  toggle.classList.toggle("open", body.classList.contains("open"));
};

// ── FILTERS ─────────────────────────────────────────────────────────────────
function bindFilters() {
  document.querySelectorAll(".group-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".group-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeGroup = btn.dataset.group;
      applyFilters();
    });
  });
  document.querySelectorAll(".theme-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".theme-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeTheme = btn.dataset.theme;
      renderAssessments(); renderDelta();
    });
  });
  document.querySelectorAll(".conf-filter").forEach(cb => {
    cb.addEventListener("change", () => {
      activeConf = new Set([...document.querySelectorAll(".conf-filter:checked")].map(c => c.value));
      renderAssessments(); renderDelta();
    });
  });
  document.querySelectorAll(".ctrl-btn[data-chart-view]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".ctrl-btn[data-chart-view]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      chartView = btn.dataset.chartView;
      renderTimeline(chartView);
    });
  });
  document.querySelectorAll(".ctrl-btn[data-src-view]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".ctrl-btn[data-src-view]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      srcView = btn.dataset.srcView;
      renderSourceTypeChart();
    });
  });
}

function applyFilters() {
  renderKPIs();
  renderAlertBanner();
  renderTimeline(chartView);
  renderRadar();
  renderCompare();
  renderDoughnut();
  renderDelta();
  renderSourceTypeSection();
  renderHeatmap();
  renderPlatformChart();
  renderAssessments();
}

// ── Utils ────────────────────────────────────────────────────────────────────
const escHtml = s => s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
