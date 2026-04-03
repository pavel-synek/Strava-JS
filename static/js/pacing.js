function renderPacing(data) {
  // Splits
  const sp = data.splits;
  if (sp && sp.dates && sp.dates.length > 0) {
    const colors = sp.split_diff.map(v => (v < 0 ? "rgba(39,174,96,0.7)" : "rgba(231,76,60,0.7)"));
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
        line: { color: "#1abc9c", width: 2 },
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
    const colors = ["#4a90d9", "#27ae60", "#f1c40f", "#e67e22", "#e74c3c"];
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
}
