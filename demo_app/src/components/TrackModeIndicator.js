// TrackModeIndicator.js — status pill in the app header showing
// Option A (source-separated) vs Option B (single channel) and SI-SDR.

function sisdrClass(v) {
  if (v == null || Number.isNaN(v)) return 'sisdr-muted'
  if (v >= 8) return 'sisdr-good'
  if (v >= 5) return 'sisdr-warn'
  return 'sisdr-bad'
}

export function createTrackModeIndicator() {
  let root
  let mode = null
  let siSdr = null
  let threshold = 5.0
  let reason = null

  function render(container) {
    root = document.createElement('div')
    root.className = 'track-mode-pill mode-idle'
    root.innerHTML = `
      <span class="tm-icon" aria-hidden="true">&#9675;</span>
      <span class="tm-label">Awaiting recording</span>
      <span class="tm-sisdr mono" data-role="sisdr" hidden></span>
    `
    container.appendChild(root)
  }

  function paint() {
    if (!root) return
    const sisdrEl = root.querySelector('[data-role="sisdr"]')
    root.classList.remove('mode-idle', 'mode-a', 'mode-b')
    root.classList.remove('has-tooltip')

    if (!mode) {
      root.classList.add('mode-idle')
      root.querySelector('.tm-icon').innerHTML = '&#9675;'
      root.querySelector('.tm-label').textContent = 'Awaiting recording'
      sisdrEl.hidden = true
      root.removeAttribute('title')
      return
    }

    if (mode === 'option_a_stems') {
      root.classList.add('mode-a')
      root.querySelector('.tm-icon').innerHTML = '&#x26A1;'
      root.querySelector('.tm-label').textContent = 'Source Separated (Option A)'
    } else {
      root.classList.add('mode-b')
      root.querySelector('.tm-icon').innerHTML = '&#9675;'
      root.querySelector('.tm-label').textContent = 'Single Channel (Option B)'
    }

    if (siSdr != null && !Number.isNaN(siSdr)) {
      sisdrEl.hidden = false
      sisdrEl.className = `tm-sisdr mono ${sisdrClass(siSdr)}`
      sisdrEl.textContent = `SI-SDR ${Number(siSdr).toFixed(1)} dB`
    } else {
      sisdrEl.hidden = true
    }

    if (reason) {
      root.classList.add('has-tooltip')
      root.title = reason
    } else if (mode === 'option_b_single' && siSdr != null) {
      root.title = `SI-SDR below threshold (${Number(siSdr).toFixed(1)} dB < ${threshold.toFixed(1)} dB threshold)`
    } else {
      root.removeAttribute('title')
    }
  }

  return {
    mount(container) {
      render(container)
      paint()
    },
    set({ track_mode, si_sdr, threshold: thr, reason: r } = {}) {
      mode = track_mode ?? mode
      siSdr = si_sdr ?? siSdr
      if (thr != null) threshold = thr
      reason = r ?? reason
      paint()
    },
    reset() {
      mode = null
      siSdr = null
      reason = null
      paint()
    },
    destroy() {
      root?.remove()
    },
  }
}
