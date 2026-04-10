function renderFitness(data) {
  if (data.error) {
    document.getElementById("fitness-kpi-row").innerHTML = `<p class="caption">${data.error}</p>`;
    return;
  }

  const c = data.current;
  const tsbClass = c.tsb >= 5 ? "pos" : c.tsb <= -10 ? "neg" : "neu";

  // ACWR KPI card
  let acwrCard = "";
  if (data.acwr && data.acwr.current_value != null) {
    const av = data.acwr.current_value;
    const acwrColor = av >= 1.5 ? "#ef4444" : av >= 1.3 ? "#f97316" : "#fbbf24";
    const acwrZone = av >= 1.5 ? "Injury risk" : av >= 1.3 ? "Caution" : "Safe";
    acwrCard = kpiCard("ACWR", `<span style="color:${acwrColor}">${av.toFixed(2)}</span>`,
      acwrZone, av >= 1.5 ? "neg" : av >= 1.3 ? "neu" : "pos");
  } else {
    acwrCard = kpiCard("ACWR", "—", "No data", "neu");
  }

  let mornCard = "";
  if (data.morning_readiness) {
    const mr = data.morning_readiness;
    const mrScore = mr.score;
    const mrColor = mrScore >= 0 ? "#fbbf24" : "#ef4444";
    const mrSign = mrScore >= 0 ? "+" : "";
    const mrValue = `<span style="color:${mrColor}">${mrSign}${mrScore.toFixed(1)} %</span>`;
    mornCard = kpiCard("Ranní připravenost", mrValue,
      `${mr.morning_hr} bpm vs ${mr.baseline_hr} bpm baseline`, mrScore >= 0 ? "pos" : "neg");
  } else {
    mornCard = kpiCard("Ranní připravenost", "—", "", "neu");
  }

  document.getElementById("fitness-kpi-row").innerHTML =
    kpiCard("Fitness (CTL)", c.ctl,
      `${c.ctl_delta >= 0 ? "+" : ""}${c.ctl_delta} vs 7 days ago`, c.ctl_delta >= 0 ? "pos" : "neg") +
    kpiCard("Fatigue (ATL)", c.atl,
      `${c.atl_delta >= 0 ? "+" : ""}${c.atl_delta} vs 7 days ago`, c.atl_delta >= 0 ? "neg" : "pos") +
    kpiCard("Form (TSB)", c.tsb,
      `${c.tsb_delta >= 0 ? "+" : ""}${c.tsb_delta} vs 7 days ago · ${c.tsb >= 5 ? "Fresh" : c.tsb <= -10 ? "Fatigued" : "Neutral"}`,
      tsbClass) +
    acwrCard +
    mornCard;

  const s = data.series;
  const acts = data.activities;

  const tsbColors = s.tsb.map(v => v >= 0 ? "rgba(249,115,22,0.45)" : "rgba(239,68,68,0.55)");

  const traces = [
    {
      type: "scatter", x: s.dates, y: s.ctl,
      mode: "lines", name: "Fitness (CTL)",
      line: { color: "#4a90d9", width: 2 },
      hovertemplate: "CTL: %{y:.1f}<extra></extra>",
    },
    {
      type: "scatter", x: s.dates, y: s.atl,
      mode: "lines", name: "Fatigue (ATL)",
      line: { color: "#e67e22", width: 2, dash: "dash" },
      hovertemplate: "ATL: %{y:.1f}<extra></extra>",
    },
    {
      type: "bar", x: s.dates, y: s.tsb,
      name: "Form (TSB)", yaxis: "y2",
      marker: { color: tsbColors },
      hovertemplate: "TSB: %{y:.1f}<extra></extra>",
      opacity: 0.8,
    },
    {
      type: "scatter",
      x: acts.dates,
      y: acts.ctl,
      mode: "markers",
      name: "Activity",
      yaxis: "y",
      marker: {
        size: acts.distance_km.map(d => Math.min(Math.max(d / 3, 4), 18)),
        color: "#f97316",
        opacity: 0.6,
      },
      text: acts.names,
      hovertemplate: "<b>%{text}</b><br>%{x}<extra></extra>",
    },
  ];

  Plotly.newPlot("chart-fitness", traces, {
    ...PLOTLY_LAYOUT,
    height: 440,
    barmode: "overlay",
    yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "Load (TRIMP)" },
    yaxis2: { title: "Form (TSB)", overlaying: "y", side: "right", gridcolor: "transparent", color: "#e0e0e0", zeroline: true, zerolinecolor: "#555" },
    legend: { orientation: "h", y: 1.08, bgcolor: "transparent" },
    shapes: [{ type: "line", x0: s.dates[0], x1: s.dates[s.dates.length - 1], y0: 0, y1: 0, yref: "y2", line: { color: "rgba(255,255,255,0.2)", dash: "dot", width: 1 } }],
  }, PLOTLY_CONFIG);

  // ACWR chart
  const acwrEl = document.getElementById("chart-acwr");
  if (data.acwr && data.acwr.series && data.acwr.series.dates && data.acwr.series.dates.length > 0) {
    const ad = data.acwr.series.dates;
    const av = data.acwr.series.values;
    const xStart = ad[0], xEnd = ad[ad.length - 1];
    Plotly.newPlot("chart-acwr", [
      {
        type: "scatter", x: ad, y: av,
        mode: "lines", name: "ACWR",
        line: { color: "#f1c40f", width: 2 },
        hovertemplate: "ACWR: %{y:.2f}<extra></extra>",
      },
    ], {
      ...PLOTLY_LAYOUT,
      height: 260,
      yaxis: { ...PLOTLY_LAYOUT.yaxis, title: "ACWR", range: [0, Math.max(2.0, Math.max(...av) + 0.1)] },
      shapes: [
        { type: "rect", x0: xStart, x1: xEnd, y0: 0, y1: 1.3, fillcolor: "rgba(251,191,36,0.06)", line: { width: 0 } },
        { type: "rect", x0: xStart, x1: xEnd, y0: 1.3, y1: 1.5, fillcolor: "rgba(230,126,34,0.12)", line: { width: 0 } },
        { type: "rect", x0: xStart, x1: xEnd, y0: 1.5, y1: 2.5, fillcolor: "rgba(231,76,60,0.1)", line: { width: 0 } },
        { type: "line", x0: xStart, x1: xEnd, y0: 1.3, y1: 1.3, line: { color: "#e67e22", dash: "dot", width: 1 } },
        { type: "line", x0: xStart, x1: xEnd, y0: 1.5, y1: 1.5, line: { color: "#e74c3c", dash: "dot", width: 1 } },
      ],
      annotations: [
        { x: xEnd, y: 1.3, text: "Caution 1.3", showarrow: false, xanchor: "right", font: { color: "#e67e22", size: 10 }, yshift: 8 },
        { x: xEnd, y: 1.5, text: "Risk 1.5", showarrow: false, xanchor: "right", font: { color: "#e74c3c", size: 10 }, yshift: 8 },
      ],
    }, PLOTLY_CONFIG);
  } else if (acwrEl) {
    acwrEl.innerHTML = `<p class="caption" style="padding:20px">No ACWR data available.</p>`;
  }

  if (data.resting_hr_series && data.resting_hr_series.length > 0) {
    const rhrDates = data.resting_hr_series.map(d => d.date);
    const rhrValues = data.resting_hr_series.map(d => d.resting_hr);
    const rolling7d = data.resting_hr_series.map(d => d.rolling_7d);

    const traceDaily = {
      x: rhrDates,
      y: rhrValues,
      mode: 'markers',
      name: 'Denní klidová TF',
      marker: { color: '#e74c3c', size: 4, opacity: 0.6 },
      type: 'scatter',
      connectgaps: false,
    };
    const traceRolling = {
      x: rhrDates,
      y: rolling7d,
      mode: 'lines',
      name: '7-denní průměr',
      line: { color: '#c0392b', width: 2 },
      type: 'scatter',
      connectgaps: true,
    };
    const layoutRhr = {
      title: 'Klidová TF',
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
      font: { color: '#e0e0e0' },
      xaxis: { gridcolor: '#333', type: 'date' },
      yaxis: { gridcolor: '#333', title: 'bpm' },
      legend: { orientation: 'h', y: -0.2 },
      margin: { t: 40, b: 60, l: 50, r: 20 },
      height: 220,
    };
    Plotly.newPlot('restingHrChart', [traceDaily, traceRolling], layoutRhr, { responsive: true, displayModeBar: false });
  } else {
    document.getElementById('restingHrChart').innerHTML = '';
  }
}
