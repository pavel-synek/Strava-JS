function renderFitness(data) {
  if (data.error) {
    document.getElementById("fitness-kpi-row").innerHTML = `<p class="caption">${data.error}</p>`;
    return;
  }

  const c = data.current;
  const tsbClass = c.tsb >= 5 ? "pos" : c.tsb <= -10 ? "neg" : "neu";

  let mornCard = "";
  if (data.morning_readiness) {
    const mr = data.morning_readiness;
    const mrScore = mr.score;
    const mrColor = mrScore >= 0 ? "#27ae60" : "#e74c3c";
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
    mornCard;

  const s = data.series;
  const acts = data.activities;

  const tsbColors = s.tsb.map(v => v >= 0 ? "rgba(39,174,96,0.55)" : "rgba(231,76,60,0.55)");

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
        color: "#1abc9c",
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
