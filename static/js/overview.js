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
    colorbar: { title: "km", tickfont: { color: "#e0e0e0" }, titlefont: { color: "#e0e0e0" } },
  }], {
    ...PLOTLY_LAYOUT,
    height: 480,
    yaxis: { ...PLOTLY_LAYOUT.yaxis, autorange: "reversed" },
    xaxis: { ...PLOTLY_LAYOUT.xaxis, title: "Year" },
  }, PLOTLY_CONFIG);

  // Sport pie
  const sp = data.sports;
  const sportColors = { Run: "#1abc9c", TrailRun: "#8e44ad", Ride: "#2980b9", Walk: "#95a5a6", Hike: "#d35400" };
  Plotly.newPlot("chart-sports", [{
    type: "pie",
    labels: sp.labels,
    values: sp.counts,
    hole: 0.4,
    marker: { colors: sp.labels.map(l => sportColors[l] || "#bdc3c7") },
    hovertemplate: "<b>%{label}</b><br>%{value} activities<extra></extra>",
    textinfo: "label+percent",
    textfont: { color: "#e0e0e0" },
  }], {
    ...PLOTLY_LAYOUT,
    height: 300,
    margin: { l: 10, r: 10, t: 20, b: 10 },
    showlegend: false,
  }, PLOTLY_CONFIG);

  // Monthly bar
  const m = data.monthly;
  Plotly.newPlot("chart-monthly", [
    {
      type: "bar", x: m.months, y: m.distance,
      name: "Distance (km)", marker: { color: "#1abc9c" }, yaxis: "y",
      hovertemplate: "%{x}<br>%{y:.1f} km<extra></extra>",
    },
    {
      type: "bar", x: m.months, y: m.elevation,
      name: "Elevation (m)", marker: { color: "#e67e22", opacity: 0.7 }, yaxis: "y2",
      hovertemplate: "%{x}<br>%{y:.0f} m<extra></extra>",
    },
  ], {
    ...PLOTLY_LAYOUT,
    height: 320,
    barmode: "overlay",
    yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Distance (km)" },
    yaxis2: { title: "Elevation (m)", overlaying: "y", side: "right", gridcolor: "transparent", color: "#e0e0e0" },
    legend: { orientation: "h", y: 1.1, bgcolor: "transparent" },
    xaxis: { ...PLOTLY_LAYOUT.xaxis, tickangle: -45 },
  }, PLOTLY_CONFIG);

  // Streaks
  const s = data.streaks;
  document.getElementById("streak-row").innerHTML =
    `<h3 style="grid-column:1/-1;margin-bottom:4px">Running streaks</h3>` +
    kpiCard("Current streak", `${s.current} days`, null, "") +
    kpiCard("Longest streak", `${s.longest} days`, null, "") +
    kpiCard(`Active days in ${s.year}`, s.days_active_this_year, null, "");
}
