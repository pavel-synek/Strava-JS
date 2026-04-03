function renderHRZones(data) {
  // Zone definitions table
  const zoneColors = { Z1: "#4a90d9", Z2: "#27ae60", Z3: "#f1c40f", Z4: "#e67e22", Z5: "#e74c3c", Easy: "#27ae60", Moderate: "#f1c40f", Hard: "#e74c3c" };
  const rows = data.zone_defs.map(z => `
    <tr>
      <td><span class="zone-swatch" style="background:${zoneColors[z.name] || '#999'}"></span>${z.name}</td>
      <td>${z.min_bpm}</td>
      <td>${z.max_bpm}</td>
      <td>${z.pct}</td>
    </tr>`).join("");
  document.getElementById("zone-defs-table").innerHTML = `
    <table class="zone-table">
      <thead><tr><th>Zone</th><th>Min BPM</th><th>Max BPM</th><th>% Max HR</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;

  // Rolling time in zones
  const rz = data.rolling_zones;
  if (rz && rz.dates && rz.dates.length > 0) {
    const zoneNames = Object.keys(rz.zones);
    const traces = zoneNames.map(z => ({
      type: "scatter",
      x: rz.dates, y: rz.zones[z],
      name: z,
      stackgroup: "one",
      fillcolor: zoneColors[z] || "#999",
      line: { color: zoneColors[z] || "#999", width: 0.5 },
      hovertemplate: `${z}: %{y:.1f}%<extra></extra>`,
    }));
    Plotly.newPlot("chart-zones", traces, {
      ...PLOTLY_LAYOUT,
      height: 320,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "% of training time", range: [0, 100] },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  } else {
    document.getElementById("chart-zones").innerHTML = `<p class="caption" style="padding:20px">No HR stream data available.</p>`;
  }

  // Aerobic efficiency
  const ae = data.aerobic_efficiency;
  if (ae && ae.dates && ae.dates.length > 0) {
    Plotly.newPlot("chart-ae", [
      {
        type: "scatter", x: ae.dates, y: ae.ae,
        mode: "markers", name: "Weekly AE",
        marker: { color: "#4a90d9", size: 6, opacity: 0.5 },
        hovertemplate: "Week: %{x}<br>AE: %{y:.5f}<extra></extra>",
      },
      {
        type: "scatter", x: ae.dates, y: ae.ae_rolling,
        mode: "lines", name: "4-week avg",
        line: { color: "#1abc9c", width: 2 },
        hovertemplate: "4w avg: %{y:.5f}<extra></extra>",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: 320,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Speed / HR" },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  } else {
    document.getElementById("chart-ae").innerHTML = `<p class="caption" style="padding:20px">Not enough running data with HR.</p>`;
  }

  // HR drift
  const dr = data.hr_drift;
  if (dr && dr.early_hr && dr.early_hr.length > 0) {
    const allHr = [...dr.early_hr, ...dr.late_hr];
    const minHr = Math.min(...allHr) - 2;
    const maxHr = Math.max(...allHr) + 2;
    Plotly.newPlot("chart-drift", [
      {
        type: "scatter",
        x: dr.early_hr, y: dr.late_hr,
        mode: "markers",
        marker: {
          color: dr.pace, colorscale: "RdYlGn", reversescale: true,
          size: dr.distance_km.map(d => Math.min(Math.max(d / 3, 4), 18)),
          opacity: 0.7,
          colorbar: { title: "Pace<br>(min/km)", tickfont: { color: "#e0e0e0" }, titlefont: { color: "#e0e0e0" } },
        },
        text: dr.dates,
        hovertemplate: "Date: %{text}<br>Early HR: %{x:.1f}<br>Late HR: %{y:.1f}<extra></extra>",
      },
      {
        type: "scatter",
        x: [minHr, maxHr], y: [minHr, maxHr],
        mode: "lines",
        line: { color: "rgba(255,255,255,0.3)", dash: "dash", width: 1 },
        showlegend: false,
        hoverinfo: "skip",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: 380,
      xaxis: { ...PLOTLY_LAYOUT.xaxis, title: "Early HR (bpm)" },
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Late HR (bpm)" },
      showlegend: false,
    }, PLOTLY_CONFIG);
  } else {
    document.getElementById("chart-drift").innerHTML = `<p class="caption" style="padding:20px">No HR drift data available.</p>`;
  }
}
