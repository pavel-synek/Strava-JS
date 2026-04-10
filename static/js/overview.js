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
  const sportColors = { Run: "#f97316", TrailRun: "#8b5cf6", Ride: "#2980b9", Walk: "#94a3b8", Hike: "#ea580c" };
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
      name: "Distance (km)", marker: { color: "#f97316" }, yaxis: "y",
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

  // Gear mileage
  const gearEl = document.getElementById("chart-gear");
  if (data.gear_mileage && data.gear_mileage.length > 0) {
    const gearNames = data.gear_mileage.map(g => g.gear_name);
    const gearDist = data.gear_mileage.map(g => g.distance_km);
    const WARNING_KM = 700;
    Plotly.newPlot("chart-gear", [
      {
        type: "bar",
        orientation: "h",
        x: gearDist,
        y: gearNames,
        marker: { color: gearDist.map(d => d >= WARNING_KM ? "#ef4444" : "#f97316") },
        hovertemplate: "<b>%{y}</b><br>%{x:.0f} km<extra></extra>",
        name: "Mileage",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: Math.max(160, gearNames.length * 48 + 60),
      margin: { l: 180, r: 60, t: 20, b: 40 },
      xaxis: { ...PLOTLY_LAYOUT.xaxis, title: "Total km" },
      yaxis: { ...PLOTLY_LAYOUT.yaxis, autorange: "reversed" },
      shapes: [{
        type: "line",
        x0: WARNING_KM, x1: WARNING_KM, y0: -0.5, y1: gearNames.length - 0.5,
        line: { color: "#e74c3c", dash: "dot", width: 1.5 },
      }],
      annotations: [{
        x: WARNING_KM, y: 0, text: "700 km", showarrow: false,
        xanchor: "left", font: { color: "#e74c3c", size: 11 }, xshift: 4,
      }],
    }, PLOTLY_CONFIG);
  } else if (gearEl) {
    gearEl.innerHTML = `<p class="caption" style="padding:20px">No shoe data available.</p>`;
  }
}
