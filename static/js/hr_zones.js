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
        line: { color: "#f97316", width: 2 },
        hovertemplate: "4w avg: %{y:.5f}<extra></extra>",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: 320,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Elev-adjusted Speed / HR" },
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
          colorbar: { title: "Pace<br>(min/km)", tickfont: { color: _themeVars().fontColor }, titlefont: { color: _themeVars().fontColor } },
        },
        text: dr.dates,
        hovertemplate: "Date: %{text}<br>Early HR: %{x:.1f}<br>Late HR: %{y:.1f}<extra></extra>",
      },
      {
        type: "scatter",
        x: [minHr, maxHr], y: [minHr, maxHr],
        mode: "lines",
        line: { color: _themeVars().dimLine, dash: "dash", width: 1 },
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

  // Cadence trend
  const cadEl = document.getElementById("chart-cadence");
  const cad = data.cadence_weekly;
  if (cad && cad.dates && cad.dates.length > 0) {
    Plotly.newPlot("chart-cadence", [
      {
        type: "scatter", x: cad.dates, y: cad.avg_cadence,
        mode: "markers", name: "Weekly avg",
        marker: { color: "#4a90d9", size: 6, opacity: 0.6 },
        hovertemplate: "Week: %{x}<br>Cadence: %{y:.0f} spm<extra></extra>",
      },
      {
        type: "scatter", x: cad.dates, y: cad.cadence_rolling,
        mode: "lines", name: "4-week avg",
        line: { color: "#f97316", width: 2 },
        hovertemplate: "4w avg: %{y:.0f} spm<extra></extra>",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: 300,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Steps/min (spm)" },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
      shapes: [
        { type: "rect", x0: cad.dates[0], x1: cad.dates[cad.dates.length - 1], y0: 170, y1: 180, fillcolor: "rgba(251,191,36,0.08)", line: { width: 0 } },
        { type: "line", x0: cad.dates[0], x1: cad.dates[cad.dates.length - 1], y0: 170, y1: 170, line: { color: "#fbbf24", dash: "dot", width: 1 } },
        { type: "line", x0: cad.dates[0], x1: cad.dates[cad.dates.length - 1], y0: 180, y1: 180, line: { color: "#fbbf24", dash: "dot", width: 1 } },
      ],
      annotations: [
        { x: cad.dates[cad.dates.length - 1], y: 175, text: "Optimal 170–180", showarrow: false, xanchor: "right", font: { color: "#fbbf24", size: 10 } },
      ],
    }, PLOTLY_CONFIG);
  } else if (cadEl) {
    cadEl.innerHTML = `<p class="caption" style="padding:20px">No cadence data available. Ensure Garmin/Strava records average cadence.</p>`;
  }

  // Decoupling factor
  const decEl = document.getElementById("chart-decoupling");
  const dec = data.decoupling_factor;
  if (dec && dec.dates && dec.dates.length > 0) {
    const decColors = dec.decoupling_pct.map(v => v != null && v >= 5 ? "#ef4444" : "#fbbf24");
    Plotly.newPlot("chart-decoupling", [
      {
        type: "scatter", x: dec.dates, y: dec.decoupling_pct,
        mode: "markers", name: "Cardiac drift %",
        marker: { color: decColors, size: 6, opacity: 0.7 },
        hovertemplate: "Date: %{x}<br>Drift: %{y:+.1f}%<extra></extra>",
      },
      {
        type: "scatter", x: dec.dates, y: dec.rolling_20,
        mode: "lines", name: "20-run avg",
        line: { color: "#f1c40f", width: 2 },
        hovertemplate: "20-run avg: %{y:+.1f}%<extra></extra>",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: 300,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Cardiac drift (%)", zeroline: true, zerolinecolor: _themeVars().zeroLine },
      legend: { orientation: "h", y: 1.12, bgcolor: "transparent" },
      shapes: [
        { type: "line", x0: dec.dates[0], x1: dec.dates[dec.dates.length - 1], y0: 5, y1: 5, line: { color: "#e74c3c", dash: "dash", width: 1.5 } },
      ],
      annotations: [
        { x: dec.dates[dec.dates.length - 1], y: 5, text: "Aerobic threshold 5%", showarrow: false, xanchor: "right", font: { color: "#e74c3c", size: 10 }, yshift: 8 },
      ],
    }, PLOTLY_CONFIG);
  } else if (decEl) {
    decEl.innerHTML = `<p class="caption" style="padding:20px">No decoupling data available (needs HR drift data).</p>`;
  }

  if (data.hr_recovery && data.hr_recovery.length > 0) {
    const recDates = data.hr_recovery.map(d => d.date);
    const rec1 = data.hr_recovery.map(d => d.recovery_1min);
    const rec2 = data.hr_recovery.map(d => d.recovery_2min);
    const distKm = data.hr_recovery.map(d => d.distance_km);
    const pace = data.hr_recovery.map(d => d.pace_min_per_km);

    // 20-point rolling average helper
    function rollingMean(arr, window) {
      return arr.map((_, i) => {
        const slice = arr.slice(Math.max(0, i - window + 1), i + 1).filter(v => v !== null && !isNaN(v));
        return slice.length > 0 ? slice.reduce((a, b) => a + b, 0) / slice.length : null;
      });
    }

    const trace1 = {
      x: recDates, y: rec1,
      mode: 'markers', name: '1 min recovery',
      marker: { color: '#fb923c', size: 5, opacity: 0.7 },
      text: distKm.map((d, i) => `${d} km, ${pace[i]} min/km`),
      hovertemplate: '%{y:.1f} bpm<br>%{text}<extra>1 min</extra>',
      type: 'scatter',
    };
    const trace2 = {
      x: recDates, y: rec2,
      mode: 'markers', name: '2 min recovery',
      marker: { color: '#fbbf24', size: 5, opacity: 0.7 },
      text: distKm.map((d, i) => `${d} km, ${pace[i]} min/km`),
      hovertemplate: '%{y:.1f} bpm<br>%{text}<extra>2 min</extra>',
      type: 'scatter',
    };
    const roll1 = rollingMean(rec1, 20);
    const roll2 = rollingMean(rec2, 20);
    const traceRoll1 = {
      x: recDates, y: roll1,
      mode: 'lines', name: '1 min (20-run avg)',
      line: { color: '#ea580c', width: 2 },
      type: 'scatter',
    };
    const traceRoll2 = {
      x: recDates, y: roll2,
      mode: 'lines', name: '2 min (20-run avg)',
      line: { color: '#f97316', width: 2, dash: 'dot' },
      type: 'scatter',
    };
    // Reference line at y=12 (good recovery threshold)
    const traceRef = {
      x: [recDates[0], recDates[recDates.length - 1]],
      y: [12, 12],
      mode: 'lines', name: 'Dobrá kondice (12 bpm)',
      line: { color: '#f39c12', width: 1, dash: 'dash' },
      type: 'scatter',
    };

    const layoutRec = {
      ...PLOTLY_LAYOUT,
      title: { text: 'HR Recovery po aktivitě', font: { color: _themeVars().fontColor } },
      xaxis: { ...PLOTLY_LAYOUT.xaxis, type: 'date' },
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: 'BPM pokles' },
      legend: { orientation: 'h', y: -0.25 },
      margin: { t: 40, b: 80, l: 50, r: 20 },
      height: 280,
    };
    Plotly.newPlot('hrRecoveryChart', [trace1, trace2, traceRoll1, traceRoll2, traceRef], layoutRec, { responsive: true, displayModeBar: false });
  } else {
    document.getElementById('hrRecoveryChart').innerHTML = '';
  }
}
