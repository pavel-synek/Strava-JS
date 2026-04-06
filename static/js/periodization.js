function renderPeriodization(data) {
  // Weekly volume
  const wk = data.weekly;
  if (wk && wk.weeks.length > 0) {
    Plotly.newPlot("chart-weekly", [
      {
        type: "bar", x: wk.weeks, y: wk.distance,
        name: "Weekly km", marker: { color: "#4a90d9", opacity: 0.7 },
        hovertemplate: "Week: %{x}<br>%{y:.1f} km<extra></extra>",
      },
      {
        type: "scatter", x: wk.weeks, y: wk.rolling,
        mode: "lines", name: "4-week avg",
        line: { color: "#1abc9c", width: 2 },
        hovertemplate: "4w avg: %{y:.1f} km<extra></extra>",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: 300,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Distance (km)" },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  }

  // YoY
  const yoy = data.yoy;
  console.log("[YoY debug]", yoy?._debug);
  if (yoy && yoy.years) {
    const colors = ["#4a90d9", "#27ae60", "#f1c40f", "#e67e22", "#e74c3c", "#9b59b6", "#1abc9c"];
    const yearKeys = Object.keys(yoy.years).sort();
    const traces = yearKeys.map((yr, i) => ({
      type: "scatter",
      x: yoy.months, y: yoy.years[yr],
      mode: "lines+markers",
      name: yr,
      line: { color: colors[i % colors.length], width: 1.5 },
      marker: { size: 5 },
      hovertemplate: `${yr} %{x}: %{y:.1f} km<extra></extra>`,
    }));
    Plotly.newPlot("chart-yoy", traces, {
      ...PLOTLY_LAYOUT,
      height: 300,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Distance (km)" },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  }

  // Monotony
  const mn = data.monotony;
  if (mn && mn.dates && mn.dates.length > 0) {
    Plotly.newPlot("chart-monotony", [
      {
        type: "scatter", x: mn.dates, y: mn.monotony,
        mode: "lines",
        line: { color: "#4a90d9", width: 1.5 },
        name: "Monotony",
        hovertemplate: "Date: %{x}<br>Monotony: %{y:.2f}<extra></extra>",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: 280,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Monotony" },
      shapes: [
        { type: "line", x0: mn.dates[0], x1: mn.dates[mn.dates.length - 1], y0: 1.5, y1: 1.5, line: { color: "#f1c40f", dash: "dash", width: 1 } },
        { type: "line", x0: mn.dates[0], x1: mn.dates[mn.dates.length - 1], y0: 2.0, y1: 2.0, line: { color: "#e74c3c", dash: "dash", width: 1 } },
      ],
      annotations: [
        { x: mn.dates[mn.dates.length - 1], y: 1.5, text: "Caution", showarrow: false, xanchor: "right", font: { color: "#f1c40f", size: 11 }, yshift: 8 },
        { x: mn.dates[mn.dates.length - 1], y: 2.0, text: "Risk", showarrow: false, xanchor: "right", font: { color: "#e74c3c", size: 11 }, yshift: 8 },
      ],
    }, PLOTLY_CONFIG);
  } else {
    document.getElementById("chart-monotony").innerHTML = `<p class="caption" style="padding:20px">No TRIMP data available.</p>`;
  }

  // Intensity distribution
  const intn = data.intensity;
  if (intn && intn.months && intn.months.length > 0) {
    Plotly.newPlot("chart-intensity", [
      { type: "bar", x: intn.months, y: intn.easy, name: "Easy (Z1+Z2)", marker: { color: "#27ae60" }, hovertemplate: "Easy: %{y:.1f}%<extra></extra>" },
      { type: "bar", x: intn.months, y: intn.moderate, name: "Moderate (Z3)", marker: { color: "#f1c40f" }, hovertemplate: "Moderate: %{y:.1f}%<extra></extra>" },
      { type: "bar", x: intn.months, y: intn.hard, name: "Hard (Z4+Z5)", marker: { color: "#e74c3c" }, hovertemplate: "Hard: %{y:.1f}%<extra></extra>" },
    ], {
      ...PLOTLY_LAYOUT,
      height: 280,
      barmode: "stack",
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "% of training time", range: [0, 100] },
      xaxis: { ...PLOTLY_LAYOUT.xaxis, tickangle: -45 },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  } else {
    document.getElementById("chart-intensity").innerHTML = `<p class="caption" style="padding:20px">No stream HR data for intensity distribution.</p>`;
  }
}
