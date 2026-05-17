// MetricsDashboard.js — 4 metric gauges + before/after benchmark bar chart.
//
// Public API:
//   const md = createMetricsDashboard()
//   md.mount(container)
//   md.setMetrics(metricsRun)                  // updates 4 gauges
//   md.setBenchmark(benchmarkPayload)          // updates bar chart
//   md.setBenchmarkError(message)
//   md.destroy()

function fmtPct(v) {
  if (v == null || Number.isNaN(v)) return 'N/A'
  return `${(v * 100).toFixed(1)}%`
}

function fmtDb(v) {
  if (v == null || Number.isNaN(v)) return 'N/A'
  return `${Number(v).toFixed(1)} dB`
}

function gaugeClass(metric, value) {
  if (value == null || Number.isNaN(value)) return 'gauge-muted'
  if (metric === 'wer' || metric === 'mter' || metric === 'der') {
    if (value < 0.1) return 'gauge-good'
    if (value < 0.25) return 'gauge-warn'
    return 'gauge-bad'
  }
  if (metric === 'sisdr') {
    if (value >= 8) return 'gauge-good'
    if (value >= 5) return 'gauge-warn'
    return 'gauge-bad'
  }
  return 'gauge-muted'
}

export function createMetricsDashboard() {
  let root
  let gaugesEl
  let chartEl
  let trackEl
  let metrics = null
  let benchmark = null
  let benchmarkError = null

  function render(container) {
    root = document.createElement('section')
    root.className = 'card metrics-dashboard'
    root.innerHTML = `
      <header class="card-header">
        <h2>Metrics</h2>
        <span class="badge badge-muted mono" data-role="track"></span>
      </header>

      <div class="gauges" data-role="gauges"></div>

      <div class="chart-section">
        <h3 class="section-title">Before / After Tuning</h3>
        <div class="chart" data-role="chart"></div>
        <div class="legend mono">
          <span class="legend-key"><i class="swatch swatch-wer"></i> WER</span>
          <span class="legend-key"><i class="swatch swatch-mter"></i> MTER (medical terms)</span>
        </div>
      </div>
    `
    container.appendChild(root)
    gaugesEl = root.querySelector('[data-role="gauges"]')
    chartEl = root.querySelector('[data-role="chart"]')
    trackEl = root.querySelector('[data-role="track"]')
    paintGauges()
    paintChart()
  }

  function setMetrics(m) {
    metrics = m || null
    paintGauges()
  }

  function setBenchmark(b) {
    benchmark = b || null
    benchmarkError = null
    paintChart()
  }

  function setBenchmarkError(msg) {
    benchmarkError = msg
    benchmark = null
    paintChart()
  }

  function paintGauges() {
    const m = metrics || {}
    const wer = m.wer
    const mter = m.medical_ter ?? m.mter
    const der = m.der_proxy ?? m.der
    const sisdr = m.si_sdr ?? m.sisdr
    const mode = m.track_mode
    trackEl.textContent = mode ? `Track: ${mode}` : ''

    gaugesEl.innerHTML = [
      renderGauge('WER', fmtPct(wer), gaugeClass('wer', wer), 'Word Error Rate (lower is better)'),
      renderGauge('MTER', fmtPct(mter), gaugeClass('mter', mter), 'Medical-Term Error Rate'),
      renderGauge('DER', fmtPct(der), gaugeClass('der', der), 'Diarization Error Rate (proxy)'),
      renderGauge(
        'SI-SDR',
        mode === 'option_b_single' && sisdr == null ? 'N/A (Option B)' : fmtDb(sisdr),
        gaugeClass('sisdr', sisdr),
        'Separation quality (higher is better)',
      ),
    ].join('')
  }

  function renderGauge(label, valueText, cls, tip) {
    return `
      <div class="gauge ${cls}" title="${tip}">
        <div class="gauge-label">${label}</div>
        <div class="gauge-value mono">${valueText}</div>
      </div>
    `
  }

  function paintChart() {
    if (benchmarkError) {
      chartEl.innerHTML = `
        <div class="empty-state">
          <p>${benchmarkError}</p>
          <p class="mono hint">Run <code>python scripts/benchmark.py</code> first.</p>
        </div>
      `
      return
    }

    if (!benchmark || !benchmark.passes) {
      chartEl.innerHTML = `
        <div class="empty-state">
          <p>No benchmark results yet.</p>
          <p class="mono hint">Run <code>python scripts/benchmark.py</code> first.</p>
        </div>
      `
      return
    }

    const passes = benchmark.passes
    // Normalize so the tallest bar = 100% of chart height
    const allValues = passes.flatMap((p) => [p.wer ?? 0, p.mter ?? p.medical_ter ?? 0])
    const maxV = Math.max(0.01, ...allValues)

    const groups = passes
      .map((p, idx) => {
        const wer = p.wer ?? 0
        const mter = p.mter ?? p.medical_ter ?? 0
        const prev = passes[idx - 1]
        const dMter =
          prev != null
            ? mter - (prev.mter ?? prev.medical_ter ?? 0)
            : null
        const dLabel = dMter == null
          ? ''
          : `<span class="delta ${dMter < 0 ? 'delta-good' : 'delta-bad'} mono">${dMter < 0 ? '▼' : '▲'} ${fmtPct(Math.abs(dMter))}</span>`
        return `
          <div class="bar-group">
            <div class="bars">
              <div class="bar bar-wer" style="height:${(wer / maxV) * 100}%">
                <span class="bar-value mono">${fmtPct(wer)}</span>
              </div>
              <div class="bar bar-mter" style="height:${(mter / maxV) * 100}%">
                <span class="bar-value mono">${fmtPct(mter)}</span>
              </div>
            </div>
            <div class="bar-label">${p.label || `Pass ${idx + 1}`}</div>
            ${dLabel ? `<div class="bar-delta">${dLabel}</div>` : ''}
          </div>
        `
      })
      .join('')

    chartEl.innerHTML = `<div class="bar-chart">${groups}</div>`
  }

  return {
    mount(container) {
      render(container)
    },
    setMetrics,
    setBenchmark,
    setBenchmarkError,
    destroy() {
      root?.remove()
    },
  }
}
