/* ──────────────────────────────────────────────────────────────────────────
   Arabic OSINT Intelligence Dashboard — Main JS
   ────────────────────────────────────────────────────────────────────────── */

"use strict";

// ── State ───────────────────────────────────────────────────────────────────
let REPORT = null;
let activeGroup = "all";
let activeTheme = "all";
let activeConf = new Set(["high", "medium"]);
let chartView = "score";

// Chart instances
let timelineChart = null;
let radarChart = null;
let compareChart = null;
let doughnutChart = null;
let deltaChart = null;

const GROUP_COLORS = {
  hezbollah: "#FFD700",
  irgc_iran:  "#f87171",
  houthis:    "#4ade80",
  hamas_pij:  "#94a3b8",
};
const GROUP_COLORS_ALPHA = (g, a) => {
  const hex = GROUP_COLORS[g] || "#3b82f6";
  const r = parseInt(hex.slice(1,3),16);
  const g2 = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g2},${b},${a})`;
};

const THEME_LABELS = {
  military_morale:       "Military Morale",
  civilian_support:      "Civilian Support",
  economic_hardship:     "Economic Pressure",
  military_operations:   "Operations",
  leadership_trust:      "Leadership Trust",
  international_relations: "Int'l Relations",
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
    console.error("Failed to load report:", e);
    document.querySelector(".alert-banner").textContent =
      "⚠ Failed to load intelligence_report.json. Run the Python pipeline first.";
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
  renderHeatmap();
  renderAssessments();
  bindFilters();
}

// ── META ────────────────────────────────────────────────────────────────────
function updateMeta() {
  const ts = new Date(REPORT.meta.generated_at);
  document.getElementById("report-ts").textContent =
    `Generated: ${ts.toISOString().slice(0,16).replace("T"," ")} UTC`;

  const groups = REPORT.summary.groups;
  const total = Object.values(groups).reduce((s, g) => s + g.post_count, 0);
  document.getElementById("stat-total").textContent = total.toLocaleString();
  document.getElementById("stat-telegram").textContent =
    (REPORT.summary.platforms?.telegram ?? "—").toLocaleString();
  document.getElementById("stat-twitter").textContent =
    (REPORT.summary.platforms?.twitter ?? "—").toLocaleString();
  document.getElementById("stat-assessments").textContent =
    REPORT.assessments.length;
}

// ── KPI CARDS ───────────────────────────────────────────────────────────────
function renderKPIs() {
  const grid = document.getElementById("kpi-grid");
  grid.innerHTML = "";
  const groups = REPORT.summary.groups;
  const assessments = REPORT.assessments;

  Object.entries(groups).forEach(([gid, g]) => {
    // find overall assessment delta
    const oa = assessments.find(a => a.group_id === gid && a.theme === "overall");
    const delta = oa ? oa.delta_pct : null;
    const score = g.avg_sentiment_score;
    const scoreClass = score > 0.05 ? "pos" : score < -0.05 ? "neg" : "neu";
    const deltaClass = delta === null ? "flat" : delta < 0 ? "down" : delta > 0 ? "up" : "flat";
    const deltaArrow = delta === null ? "—" : delta < 0 ? "▼" : "▲";

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
        <span>▲ ${g.positive_pct}%</span>
        <span>▼ ${g.negative_pct}%</span>
        <span>◆ ${g.neutral_pct}%</span>
      </div>
      <div class="kpi-posts">${g.post_count.toLocaleString()} posts analyzed</div>
    `;
    card.addEventListener("click", () => {
      document.querySelectorAll(".group-btn").forEach(b => b.classList.remove("active"));
      const btn = document.querySelector(`.group-btn[data-group="${gid}"]`);
      if (btn) btn.classList.add("active");
      activeGroup = gid;
      applyFilters();
    });
    grid.appendChild(card);
  });
}

// ── ALERT BANNER ────────────────────────────────────────────────────────────
function renderAlertBanner() {
  const top = REPORT.summary.top_assessments?.[0];
  if (!top) return;
  document.getElementById("alert-text").textContent =
    `TOP FINDING: ${top.group} — ${top.theme_label ?? top.theme}: ${top.narrative.slice(0, 200)}…`;
}

// ── TIMELINE CHART ──────────────────────────────────────────────────────────
function renderTimeline(view = "score") {
  const ctx = document.getElementById("timelineChart").getContext("2d");
  const timeline = REPORT.timeline;
  const groups = REPORT.summary.groups;

  // Gather all months (union across groups)
  const allMonths = new Set();
  Object.values(timeline).forEach(arr => arr.forEach(d => allMonths.add(d.month)));
  const months = [...allMonths].sort();

  const datasets = Object.entries(timeline)
    .filter(([gid]) => activeGroup === "all" || gid === activeGroup)
    .map(([gid, data]) => {
      const monthMap = Object.fromEntries(data.map(d => [d.month, d]));
      const values = months.map(m => {
        const d = monthMap[m];
        if (!d) return null;
        if (view === "score") return d.avg_sentiment;
        if (view === "negative") return d.negative_pct;
        if (view === "positive") return d.positive_pct;
        return d.avg_sentiment;
      });
      const color = GROUP_COLORS[gid] || "#3b82f6";
      return {
        label: groups[gid]?.display_name ?? gid,
        data: values,
        borderColor: color,
        backgroundColor: GROUP_COLORS_ALPHA(gid, 0.08),
        pointBackgroundColor: color,
        pointRadius: 3,
        pointHoverRadius: 5,
        borderWidth: 2,
        fill: true,
        tension: 0.3,
        spanGaps: true,
      };
    });

  if (timelineChart) timelineChart.destroy();
  timelineChart = new Chart(ctx, {
    type: "line",
    data: { labels: months, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, padding: 12, font: { size: 10 } } },
        tooltip: {
          callbacks: {
            label: ctx => {
              const v = ctx.parsed.y;
              return v === null ? "" :
                `${ctx.dataset.label}: ${view === "score" ? (v >= 0 ? "+" : "") + v.toFixed(3) : v.toFixed(1) + "%"}`;
            },
          },
        },
        annotation: {
          annotations: {
            periodLine: {
              type: "line",
              xMin: "2025-01", xMax: "2025-01",
              borderColor: "rgba(59,130,246,0.5)",
              borderWidth: 1,
              borderDash: [4, 4],
              label: {
                display: true, content: "2025 →",
                color: "#3b82f6", font: { size: 9 },
                position: "start",
              },
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { maxTicksLimit: 10, font: { size: 9 }, color: "#4a5a78" },
          grid: { color: "rgba(31,45,71,0.6)" },
        },
        y: {
          ticks: {
            font: { size: 9 }, color: "#4a5a78",
            callback: v => view === "score" ? (v >= 0 ? "+" : "") + v.toFixed(2) : v.toFixed(0) + "%",
          },
          grid: { color: "rgba(31,45,71,0.6)" },
        },
      },
    },
  });
}

// ── RADAR CHART ─────────────────────────────────────────────────────────────
function renderRadar() {
  const ctx = document.getElementById("radarChart").getContext("2d");
  const matrix = REPORT.theme_matrix;
  const themeIds = Object.keys(THEME_LABELS);
  const labels = themeIds.map(t => THEME_LABELS[t]);
  const groups = REPORT.summary.groups;

  const datasets = Object.entries(matrix)
    .filter(([gid]) => activeGroup === "all" || gid === activeGroup)
    .map(([gid, themes]) => {
      const color = GROUP_COLORS[gid] || "#3b82f6";
      return {
        label: groups[gid]?.display_name ?? gid,
        data: themeIds.map(t => {
          const v = themes[t]?.avg_sentiment ?? 0;
          return Math.round((v + 1) * 50); // map -1..+1 → 0..100
        }),
        borderColor: color,
        backgroundColor: GROUP_COLORS_ALPHA(gid, 0.12),
        pointBackgroundColor: color,
        borderWidth: 1.5,
        pointRadius: 3,
      };
    });

  if (radarChart) radarChart.destroy();
  radarChart = new Chart(ctx, {
    type: "radar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { boxWidth: 8, padding: 8, font: { size: 9 } } } },
      scales: {
        r: {
          min: 0, max: 100,
          ticks: { stepSize: 25, font: { size: 8 }, color: "#4a5a78", backdropColor: "transparent",
            callback: v => v === 50 ? "neutral" : v === 0 ? "−1" : v === 100 ? "+1" : "" },
          grid: { color: "rgba(31,45,71,0.8)" },
          pointLabels: { font: { size: 9 }, color: "#8899b5" },
          angleLines: { color: "rgba(31,45,71,0.8)" },
        },
      },
    },
  });
}

// ── COMPARE CHART ───────────────────────────────────────────────────────────
function renderCompare() {
  const ctx = document.getElementById("compareChart").getContext("2d");
  const assessments = REPORT.assessments.filter(a => a.theme === "overall");
  const groups = Object.entries(REPORT.summary.groups)
    .filter(([gid]) => activeGroup === "all" || gid === activeGroup);

  const labels = groups.map(([, g]) => g.display_name);
  const baselineData = groups.map(([gid]) => {
    const a = assessments.find(a => a.group_id === gid);
    return a ? a.baseline_score : 0;
  });
  const currentData = groups.map(([gid]) => {
    const a = assessments.find(a => a.group_id === gid);
    return a ? a.current_score : 0;
  });

  if (compareChart) compareChart.destroy();
  compareChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "2024 Baseline",
          data: baselineData,
          backgroundColor: "rgba(99,102,241,0.6)",
          borderColor: "rgba(99,102,241,1)",
          borderWidth: 1,
        },
        {
          label: "Current (2025–2026)",
          data: currentData,
          backgroundColor: groups.map(([gid]) => GROUP_COLORS_ALPHA(gid, 0.6)),
          borderColor: groups.map(([gid]) => GROUP_COLORS[gid] || "#3b82f6"),
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { boxWidth: 10, padding: 10, font: { size: 10 } } } },
      scales: {
        x: { grid: { color: "rgba(31,45,71,0.6)" }, ticks: { font: { size: 10 }, color: "#8899b5" } },
        y: {
          grid: { color: "rgba(31,45,71,0.6)" },
          ticks: { font: { size: 9 }, color: "#4a5a78", callback: v => (v >= 0 ? "+" : "") + v.toFixed(2) },
        },
      },
    },
  });
}

// ── DOUGHNUT CHART ──────────────────────────────────────────────────────────
function renderDoughnut() {
  const ctx = document.getElementById("doughnutChart").getContext("2d");
  const groups = Object.entries(REPORT.summary.groups)
    .filter(([gid]) => activeGroup === "all" || gid === activeGroup);

  let pos = 0, neg = 0, neu = 0, total = 0;
  groups.forEach(([, g]) => {
    pos += g.positive_pct * g.post_count;
    neg += g.negative_pct * g.post_count;
    neu += g.neutral_pct * g.post_count;
    total += g.post_count;
  });
  const t = Math.max(total, 1);

  if (doughnutChart) doughnutChart.destroy();
  doughnutChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: ["Positive", "Negative", "Neutral"],
      datasets: [{
        data: [(pos / t).toFixed(1), (neg / t).toFixed(1), (neu / t).toFixed(1)],
        backgroundColor: ["rgba(34,197,94,0.75)", "rgba(239,68,68,0.75)", "rgba(245,158,11,0.5)"],
        borderColor: ["#22c55e", "#ef4444", "#f59e0b"],
        borderWidth: 1,
        hoverOffset: 6,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      cutout: "62%",
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 10, padding: 10, font: { size: 10 } } },
        tooltip: { callbacks: { label: ctx => `${ctx.label}: ${ctx.parsed}%` } },
      },
    },
  });
}

// ── DELTA CHART ─────────────────────────────────────────────────────────────
function renderDelta() {
  const ctx = document.getElementById("deltaChart").getContext("2d");
  const assessments = REPORT.assessments
    .filter(a => activeGroup === "all" || a.group_id === activeGroup)
    .filter(a => activeConf.has(a.confidence))
    .slice(0, 8);

  const labels = assessments.map(a => `${a.group_display_name} · ${a.theme_label}`);
  const values = assessments.map(a => a.delta_pct);
  const colors = values.map(v => v < 0 ? "rgba(239,68,68,0.75)" : "rgba(34,197,94,0.75)");
  const borderColors = values.map(v => v < 0 ? "#ef4444" : "#22c55e");

  if (deltaChart) deltaChart.destroy();
  deltaChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Delta (pp) vs 2024",
        data: values,
        backgroundColor: colors,
        borderColor: borderColors,
        borderWidth: 1,
      }],
    },
    options: {
      indexAxis: "y",
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `Δ ${ctx.parsed.x >= 0 ? "+" : ""}${ctx.parsed.x.toFixed(1)} pp` } },
      },
      scales: {
        x: {
          grid: { color: "rgba(31,45,71,0.6)" },
          ticks: { font: { size: 9 }, color: "#4a5a78", callback: v => (v >= 0 ? "+" : "") + v.toFixed(0) + " pp" },
        },
        y: { ticks: { font: { size: 9 }, color: "#8899b5" }, grid: { display: false } },
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
      const r = val < 0 ? 239 : 34;
      const g = val < 0 ? 68 : 197;
      const b = val < 0 ? 68 : 94;
      const alpha = Math.min(Math.abs(val) * 0.7 + 0.1, 0.9);
      const textColor = val < 0 ? "#fca5a5" : "#86efac";
      html += `<td style="background:rgba(${r},${g},${b},${alpha});color:${textColor}"
                   title="${THEME_LABELS[tid]} | ${REPORT.summary.groups[gid]?.display_name} | n=${count}">
                 ${val >= 0 ? "+" : ""}${val.toFixed(2)}
               </td>`;
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

  if (filtered.length === 0) {
    list.innerHTML = `<div style="color:var(--text-muted);padding:24px;text-align:center">
      No assessments match the current filters.</div>`;
    return;
  }

  list.innerHTML = filtered.map((a, i) => {
    const dirIcon = a.direction === "decrease" ? "▼" : a.direction === "increase" ? "▲" : "➡";
    const scoreClass = s => s >= 0 ? "pos" : "neg";
    const evidenceHTML = (a.evidence || []).slice(0, 3).map(e => `
      <div class="evidence-post">
        <span class="evidence-platform ${e.platform}">${e.platform}</span>
        <span class="evidence-source">${e.source}</span>
        <span class="evidence-sentiment ${e.sentiment}">${e.sentiment}</span>
        <div class="evidence-text">${escHtml(e.text)}</div>
        <span class="evidence-ts">${e.timestamp?.slice(0, 10) ?? ""}</span>
      </div>
    `).join("");

    return `
      <div class="assessment-card ${a.confidence}">
        <div class="assessment-header" onclick="toggleAssessment(${i})">
          <span class="asmnt-group-badge" style="color:${GROUP_COLORS[a.group_id] || '#3b82f6'}">${a.group_display_name}</span>
          <span class="asmnt-theme-badge">${a.theme_label}</span>
          <span class="asmnt-direction ${a.direction}">${dirIcon} ${a.magnitude} ${a.direction}</span>
          <span class="asmnt-delta" style="color:${a.delta_pct < 0 ? 'var(--negative)' : 'var(--positive)'}">
            ${a.delta_pct >= 0 ? "+" : ""}${a.delta_pct.toFixed(1)} pp
          </span>
          <span class="asmnt-conf ${a.confidence}">${a.confidence}</span>
          <span class="asmnt-toggle" id="toggle-${i}">▼</span>
        </div>
        <div class="assessment-body" id="body-${i}">
          <div class="asmnt-narrative">${a.narrative}</div>
          <div class="score-comparison">
            <div class="score-box">
              <div class="score-box-label">2024 Baseline</div>
              <div class="score-box-val ${scoreClass(a.baseline_score)}">${a.baseline_score >= 0 ? "+" : ""}${a.baseline_score.toFixed(3)}</div>
            </div>
            <div class="score-arrow">→</div>
            <div class="score-box">
              <div class="score-box-label">Current</div>
              <div class="score-box-val ${scoreClass(a.current_score)}">${a.current_score >= 0 ? "+" : ""}${a.current_score.toFixed(3)}</div>
            </div>
            <div class="score-box">
              <div class="score-box-label">Change</div>
              <div class="score-box-val ${a.delta_pct < 0 ? "neg" : "pos"}">${a.delta_pct >= 0 ? "+" : ""}${a.delta_pct.toFixed(1)} pp</div>
            </div>
          </div>
          ${evidenceHTML ? `
            <div class="evidence-section">
              <div class="evidence-label">Supporting Evidence</div>
              <div class="evidence-list">${evidenceHTML}</div>
            </div>
          ` : ""}
        </div>
      </div>
    `;
  }).join("");

  // Auto-open first high-confidence assessment
  const firstHigh = filtered.findIndex(a => a.confidence === "high");
  if (firstHigh >= 0) toggleAssessment(firstHigh);
}

window.toggleAssessment = function(i) {
  const body = document.getElementById(`body-${i}`);
  const toggle = document.getElementById(`toggle-${i}`);
  if (!body) return;
  const open = body.classList.toggle("open");
  toggle.classList.toggle("open", open);
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
      renderAssessments();
      renderDelta();
    });
  });

  document.querySelectorAll(".conf-filter").forEach(cb => {
    cb.addEventListener("change", () => {
      activeConf = new Set(
        [...document.querySelectorAll(".conf-filter:checked")].map(c => c.value)
      );
      renderAssessments();
      renderDelta();
    });
  });

  document.querySelectorAll(".ctrl-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".ctrl-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      chartView = btn.dataset.chartView;
      renderTimeline(chartView);
    });
  });
}

function applyFilters() {
  renderTimeline(chartView);
  renderRadar();
  renderCompare();
  renderDoughnut();
  renderDelta();
  renderHeatmap();
  renderAssessments();
}

// ── UTILITIES ────────────────────────────────────────────────────────────────
function escHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
