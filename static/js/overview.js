function renderOverview(data) {
  // KPIs
  const k = data.kpis;
  const kmDelta = k.distance_km - k.prev_distance_km;
  const elevDelta = k.elevation_m - k.prev_elevation_m;
  const hoursDelta = k.hours - k.prev_hours;
  document.getElementById("kpi-row").innerHTML =
    kpiCard("Activities", k.activities.toLocaleString(), null, "") +
    kpiCard("Distance", `${k.distance_km.toLocaleString()} km`,
      `${kmDelta >= 0 ? "+" : ""}${kmDelta.toFixed(0)} km ${k.prev_label}`, kmDelta >= 0 ? "pos" : "neg") +
    kpiCard("Elevation", `${k.elevation_m.toLocaleString()} m`,
      `${elevDelta >= 0 ? "+" : ""}${elevDelta.toFixed(0)} m ${k.prev_label}`, elevDelta >= 0 ? "pos" : "neg") +
    kpiCard("Moving time", `${k.hours.toLocaleString()} h`,
      `${hoursDelta >= 0 ? "+" : ""}${hoursDelta.toFixed(0)} h ${k.prev_label}`, hoursDelta >= 0 ? "pos" : "neg");

  // Heatmap
  const hm = data.heatmap;
  Plotly.newPlot("chart-heatmap", [{
    type: "heatmap",
    z: hm.z, x: hm.x, y: hm.y,
    colorscale: "Greens",
    hovertemplate: "Year: %{x}<br>Week: %{y}<br>Distance: %{z:.1f} km<extra></extra>",
    showscale: true,
    colorbar: { title: "km", tickfont: { color: _themeVars().fontColor }, titlefont: { color: _themeVars().fontColor } },
  }], {
    ...PLOTLY_LAYOUT,
    height: 480,
    yaxis: { ...PLOTLY_LAYOUT.yaxis, autorange: "reversed" },
    xaxis: { ...PLOTLY_LAYOUT.xaxis, title: "Year" },
  }, PLOTLY_CONFIG);

  // Monthly bar + line
  const m = data.monthly;
  const tv = _themeVars();
  Plotly.newPlot("chart-monthly", [
    {
      type: "bar", x: m.months, y: m.distance,
      name: "Distance (km)",
      marker: {
        color: "#f97316",
        opacity: 0.85,
        line: { width: 0 },
      },
      yaxis: "y",
      hovertemplate: "<b>%{x}</b><br>Distance: %{y:.1f} km<extra></extra>",
    },
    {
      type: "scatter", mode: "lines+markers", x: m.months, y: m.elevation,
      name: "Elevation (m)",
      line: { color: "#38bdf8", width: 2.5, shape: "spline", smoothing: 0.6 },
      marker: { color: "#38bdf8", size: 6, symbol: "circle", line: { color: tv.bg, width: 1.5 } },
      yaxis: "y2",
      hovertemplate: "<b>%{x}</b><br>Elevation: %{y:.0f} m<extra></extra>",
    },
  ], {
    ...PLOTLY_LAYOUT,
    height: 340,
    yaxis: {
      ...PLOTLY_LAYOUT.yaxis,
      title: { text: "Distance (km)", standoff: 12 },
      gridcolor: tv.grid,
    },
    yaxis2: {
      title: { text: "Elevation (m)", standoff: 12 },
      overlaying: "y", side: "right",
      gridcolor: "transparent",
      color: "#38bdf8",
      tickfont: { color: "#38bdf8" },
      titlefont: { color: "#38bdf8" },
    },
    legend: {
      orientation: "h", y: 1.08, x: 0.5, xanchor: "center",
      bgcolor: "transparent",
      font: { size: 12 },
    },
    xaxis: { ...PLOTLY_LAYOUT.xaxis, tickangle: -40, tickfont: { size: 11 } },
    bargap: 0.25,
  }, PLOTLY_CONFIG);

  // Streaks
  const s = data.streaks;
  document.getElementById("streak-row").innerHTML =
    `<h3 style="grid-column:1/-1;margin-bottom:4px">Running streaks</h3>` +
    kpiCard("Current streak", `${s.current} days`, null, "") +
    kpiCard("Longest streak", `${s.longest} days`, null, "") +
    kpiCard(`Active days in ${s.year}`, s.days_active_this_year, null, "");

}
