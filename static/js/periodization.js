function renderPeriodization(data) {
  // Weekly volume (with long-run highlighting)
  const wk = data.weekly;
  if (wk && wk.weeks.length > 0) {
    const longRunFlags = (data.long_runs && data.long_runs.is_long_run) ? data.long_runs.is_long_run : [];
    const barColors = wk.weeks.map((_, i) => longRunFlags[i] ? "#8e44ad" : "#4a90d9");
    const barOpacity = wk.weeks.map((_, i) => longRunFlags[i] ? 0.9 : 0.7);
    Plotly.newPlot("chart-weekly", [
      {
        type: "bar", x: wk.weeks, y: wk.distance,
        name: "Weekly km",
        marker: { color: barColors, opacity: barOpacity },
        hovertemplate: "Week: %{x}<br>%{y:.1f} km<extra></extra>",
      },
      {
        type: "scatter", x: wk.weeks, y: wk.rolling,
        mode: "lines", name: "4-week avg",
        line: { color: "#f97316", width: 2 },
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
  const colors = ["#4a90d9", "#fbbf24", "#f97316", "#ea580c", "#ef4444", "#8b5cf6", "#fb923c"];
  const yoy = data.yoy;
  if (yoy && yoy.years) {
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
      xaxis: { ...PLOTLY_LAYOUT.xaxis, type: "category" },
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Distance (km)" },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  }

  // YoY — Aerobic Efficiency
  const yoyAe = data.yoy_ae;
  if (yoyAe && yoyAe.years) {
    const aeYearKeys = Object.keys(yoyAe.years).sort();
    const aeTraces = aeYearKeys.map((yr, i) => ({
      type: "scatter",
      x: yoyAe.months, y: yoyAe.years[yr],
      mode: "lines+markers",
      name: yr,
      connectgaps: false,
      line: { color: colors[i % colors.length], width: 1.5 },
      marker: { size: 5 },
      hovertemplate: `${yr} %{x}: %{y:.5f}<extra></extra>`,
    }));
    Plotly.newPlot("chart-yoy-ae", aeTraces, {
      ...PLOTLY_LAYOUT,
      height: 300,
      xaxis: { ...PLOTLY_LAYOUT.xaxis, type: "category" },
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Adj. Speed / HR" },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  } else {
    document.getElementById("chart-yoy-ae").innerHTML = `<p class="caption" style="padding:20px">No HR data available.</p>`;
  }

  // YoY — GAP Pace
  const yoyGap = data.yoy_gap;
  if (yoyGap && yoyGap.years) {
    const gapYearKeys = Object.keys(yoyGap.years).sort();
    const gapTraces = gapYearKeys.map((yr, i) => ({
      type: "scatter",
      x: yoyGap.months, y: yoyGap.years[yr],
      mode: "lines+markers",
      name: yr,
      connectgaps: false,
      line: { color: colors[i % colors.length], width: 1.5 },
      marker: { size: 5 },
      hovertemplate: `${yr} %{x}: %{y:.2f} min/km<extra></extra>`,
    }));
    Plotly.newPlot("chart-yoy-gap", gapTraces, {
      ...PLOTLY_LAYOUT,
      height: 300,
      xaxis: { ...PLOTLY_LAYOUT.xaxis, type: "category" },
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "GAP (min/km)", autorange: "reversed" },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
    }, PLOTLY_CONFIG);
  } else {
    document.getElementById("chart-yoy-gap").innerHTML = `<p class="caption" style="padding:20px">No pace data available.</p>`;
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
      { type: "bar", x: intn.months, y: intn.easy, name: "Easy (Z1+Z2)", marker: { color: "#fbbf24" }, hovertemplate: "Easy: %{y:.1f}%<extra></extra>" },
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

  // Ramp rate chart
  const rampEl = document.getElementById("chart-ramp-rate");
  const rr = data.ramp_rate;
  if (rr && rr.weeks && rr.weeks.length > 0) {
    const validRamp = rr.ramp_rate.map(v => v == null ? 0 : v);
    Plotly.newPlot("chart-ramp-rate", [
      {
        type: "bar",
        x: rr.weeks,
        y: validRamp,
        name: "Ramp rate",
        marker: { color: validRamp.map(v => Math.abs(v) > 10 ? "#ef4444" : "#f97316"), opacity: 0.8 },
        hovertemplate: "Week: %{x}<br>Ramp: %{y:+.1f}%<extra></extra>",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: 280,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "% week-over-week change", zeroline: true, zerolinecolor: _themeVars().zeroLine },
      shapes: [
        { type: "line", x0: rr.weeks[0], x1: rr.weeks[rr.weeks.length - 1], y0: 10, y1: 10, line: { color: "#e74c3c", dash: "dot", width: 1 } },
        { type: "line", x0: rr.weeks[0], x1: rr.weeks[rr.weeks.length - 1], y0: -10, y1: -10, line: { color: "#e74c3c", dash: "dot", width: 1 } },
      ],
      annotations: [
        { x: rr.weeks[rr.weeks.length - 1], y: 10, text: "+10%", showarrow: false, xanchor: "right", font: { color: "#e74c3c", size: 10 }, yshift: 8 },
      ],
    }, PLOTLY_CONFIG);
  } else if (rampEl) {
    rampEl.innerHTML = `<p class="caption" style="padding:20px">No ramp rate data available.</p>`;
  }
}
