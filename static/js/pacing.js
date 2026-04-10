function renderPacing(data) {
  // Splits
  const sp = data.splits;
  if (sp && sp.dates && sp.dates.length > 0) {
    const colors = sp.split_diff.map(v => (v < 0 ? "rgba(251,191,36,0.75)" : "rgba(239,68,68,0.7)"));
    Plotly.newPlot("chart-splits", [
      {
        type: "scatter", x: sp.dates, y: sp.split_diff,
        mode: "markers",
        marker: { color: colors, size: 6 },
        name: "Split diff",
        hovertemplate: "Date: %{x}<br>%{y:+.0f} s/km<extra></extra>",
      },
      {
        type: "scatter", x: sp.dates, y: sp.rolling,
        mode: "lines",
        line: { color: "#f1c40f", width: 2 },
        name: "20-run avg",
        hovertemplate: "Avg: %{y:+.0f} s/km<extra></extra>",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: 300,
      shapes: [{ type: "line", x0: sp.dates[0], x1: sp.dates[sp.dates.length - 1], y0: 0, y1: 0, line: { color: "rgba(255,255,255,0.25)", dash: "dot", width: 1 } }],
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "2nd half − 1st half (s/km)" },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  } else {
    document.getElementById("chart-splits").innerHTML = `<p class="caption" style="padding:20px">No split data available.</p>`;
  }

  // Consistency
  const cs = data.consistency;
  if (cs && cs.dates && cs.dates.length > 0) {
    Plotly.newPlot("chart-consistency", [
      {
        type: "scatter", x: cs.dates, y: cs.pace_std,
        mode: "markers",
        marker: { color: "#4a90d9", size: 5, opacity: 0.5 },
        name: "Pace std",
        hovertemplate: "Date: %{x}<br>Std: %{y:.1f} s/km<extra></extra>",
      },
      {
        type: "scatter", x: cs.dates, y: cs.rolling,
        mode: "lines",
        line: { color: "#f97316", width: 2 },
        name: "20-run avg",
        hovertemplate: "Avg: %{y:.1f} s/km<extra></extra>",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: 300,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Std dev of km paces (s/km)" },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  } else {
    document.getElementById("chart-consistency").innerHTML = `<p class="caption" style="padding:20px">No consistency data.</p>`;
  }

  // Best efforts
  const be = data.best_efforts;
  if (be && Object.keys(be).length > 0) {
    const colors = ["#4a90d9", "#fbbf24", "#f97316", "#ea580c", "#ef4444"];
    const traces = [];
    Object.entries(be).forEach(([label, d], i) => {
      traces.push({
        type: "scatter", x: d.months, y: d.pace,
        mode: "markers",
        marker: { color: colors[i % colors.length], size: 5, opacity: 0.4 },
        name: label,
        legendgroup: label,
        hovertemplate: `${label}: %{y:.2f} min/km<extra></extra>`,
      });
      traces.push({
        type: "scatter", x: d.months, y: d.pb,
        mode: "lines",
        line: { color: colors[i % colors.length], width: 2 },
        name: `${label} PB`,
        legendgroup: label,
        showlegend: false,
        hovertemplate: `${label} PB: %{y:.2f} min/km<extra></extra>`,
      });
    });
    Plotly.newPlot("chart-best", traces, {
      ...PLOTLY_LAYOUT,
      height: 360,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Pace (min/km)", autorange: "reversed" },
      legend: { orientation: "h", y: 1.1, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  } else {
    document.getElementById("chart-best").innerHTML = `<p class="caption" style="padding:20px">Not enough data for best efforts.</p>`;
  }

  // Race history
  const rh = data.race_history;
  const raceHistEl = document.getElementById("chart-race-history");
  if (rh && Object.keys(rh).length > 0) {
    const rhColors = { "5 km": "#fbbf24", "10 km": "#4a90d9", "Half marathon": "#f97316", "Marathon": "#ef4444" };
    const rhTraces = Object.entries(rh).map(([label, d]) => ({
      type: "scatter",
      x: d.dates, y: d.pace,
      mode: "markers",
      name: label,
      marker: { color: rhColors[label] || "#f97316", size: 8, opacity: 0.85 },
      text: d.distance_km ? d.distance_km.map(dist => `${dist} km`) : [],
      hovertemplate: `<b>${label}</b><br>%{x}<br>%{y:.2f} min/km<br>%{text}<extra></extra>`,
    }));
    Plotly.newPlot("chart-race-history", rhTraces, {
      ...PLOTLY_LAYOUT,
      height: 320,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Pace (min/km)", autorange: "reversed" },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  } else if (raceHistEl) {
    raceHistEl.innerHTML = `<p class="caption" style="padding:20px">No race data. Log activities as "Race" in Strava.</p>`;
  }

  // Race predictor table
  const predEl = document.getElementById("race-predictor-block");
  if (predEl) {
    const pred = data.predictions;
    if (pred && Object.keys(pred).length > 0) {
      function fmtPace(paceMinPerKm) {
        const totalSec = Math.round(paceMinPerKm * 60);
        const mm = Math.floor(totalSec / 60);
        const ss = String(totalSec % 60).padStart(2, "0");
        return `${mm}:${ss}/km`;
      }
      function paceToFinish(paceMinPerKm, distKm) {
        const totalMin = paceMinPerKm * distKm;
        const h = Math.floor(totalMin / 60);
        const m = Math.floor(totalMin % 60);
        const s = Math.round((totalMin * 60) % 60);
        return h > 0 ? `${h}h ${String(m).padStart(2,"0")}m ${String(s).padStart(2,"0")}s`
                     : `${m}m ${String(s).padStart(2,"0")}s`;
      }
      const distKm = { "Half marathon": 21.0975, "Marathon": 42.195 };
      const rows = Object.entries(pred).map(([label, pace]) =>
        `<tr><td>${label}</td><td>${fmtPace(pace)}</td><td>${paceToFinish(pace, distKm[label] || 0)}</td></tr>`
      ).join("");
      predEl.innerHTML = `<table style="width:100%;border-collapse:collapse;color:#e0e0e0;font-size:0.95em">
        <thead><tr style="border-bottom:1px solid #2d3447">
          <th style="text-align:left;padding:8px 12px">Distance</th>
          <th style="text-align:left;padding:8px 12px">Predicted pace</th>
          <th style="text-align:left;padding:8px 12px">Finish time</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    } else {
      predEl.innerHTML = `<p class="caption" style="padding:20px">Need 5 km or 10 km training data for predictions.</p>`;
    }
  }
}
