// SpeakerTimeline.js — horizontal speaker lanes with turn rectangles.
//
// Public API:
//   const st = createSpeakerTimeline({ onSelectSegment(id) })
//   st.mount(container)
//   st.setData({ segments, track_mode })
//   st.destroy()

const SPEAKER_COLORS = {
  S1: '#00e5ff',
  S2: '#ffb703',
  S3: '#06d6a0',
  S4: '#b388ff',
}
const UNKNOWN_COLOR = '#5a7fa8'

function colorFor(speaker) {
  return SPEAKER_COLORS[speaker] || UNKNOWN_COLOR
}

function confidenceOpacity(conf) {
  switch ((conf || 'med').toLowerCase()) {
    case 'high':
      return 1.0
    case 'low':
      return 0.35
    default:
      return 0.65
  }
}

function clip(text, n = 60) {
  if (!text) return ''
  return text.length > n ? text.slice(0, n - 1) + '…' : text
}

function escapeAttr(str) {
  return String(str ?? '').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

export function createSpeakerTimeline({ onSelectSegment } = {}) {
  let root
  let svgEl
  let legendEl
  let trackBadgeEl
  let tooltipEl
  let segments = []
  let trackMode = null

  function render(container) {
    root = document.createElement('section')
    root.className = 'card speaker-timeline'
    root.innerHTML = `
      <header class="card-header">
        <h2>Speaker Timeline</h2>
        <span class="badge badge-muted mono" data-role="track"></span>
      </header>
      <div class="timeline-body">
        <svg class="timeline-svg" data-role="svg" preserveAspectRatio="none"></svg>
        <div class="timeline-tooltip mono" data-role="tooltip" hidden></div>
      </div>
      <div class="timeline-legend mono" data-role="legend"></div>
    `
    container.appendChild(root)
    svgEl = root.querySelector('[data-role="svg"]')
    legendEl = root.querySelector('[data-role="legend"]')
    tooltipEl = root.querySelector('[data-role="tooltip"]')
    trackBadgeEl = root.querySelector('[data-role="track"]')
    paint()
  }

  function setData({ segments: segs, track_mode } = {}) {
    segments = segs || []
    trackMode = track_mode || null
    paint()
  }

  function paint() {
    if (!segments.length) {
      svgEl.innerHTML = ''
      svgEl.removeAttribute('viewBox')
      legendEl.innerHTML = '<span class="hint">No timeline data.</span>'
      trackBadgeEl.textContent = ''
      return
    }

    const speakers = Array.from(new Set(segments.map((s) => s.speaker_id || '?'))).sort()
    const tMax = Math.max(...segments.map((s) => s.end_ts ?? s.end ?? 0))
    const tMin = Math.min(...segments.map((s) => s.start_ts ?? s.start ?? 0))
    const duration = Math.max(0.5, tMax - tMin)

    const W = 900
    const laneH = 36
    const headerH = 24
    const H = headerH + speakers.length * laneH + 12

    svgEl.setAttribute('viewBox', `0 0 ${W} ${H}`)
    svgEl.setAttribute('width', '100%')
    svgEl.setAttribute('height', String(H))

    const defs = `
      <defs>
        <pattern id="overlap-stripes" patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(45)">
          <rect width="8" height="8" fill="rgba(239,71,111,0.35)"/>
          <line x1="0" y1="0" x2="0" y2="8" stroke="#ef476f" stroke-width="2"/>
        </pattern>
      </defs>
    `

    const axisTicks = renderAxis(W, headerH, tMin, tMax)
    const lanes = speakers
      .map((spk, i) => {
        const y = headerH + i * laneH
        const bg = `<rect x="0" y="${y}" width="${W}" height="${laneH}" class="lane-bg" />`
        const label = `<text x="6" y="${y + laneH / 2 + 4}" class="lane-label">${escapeAttr(spk)}</text>`
        const turns = segments
          .filter((s) => (s.speaker_id || '?') === spk)
          .map((s) => renderTurn(s, y, laneH, W, tMin, duration))
          .join('')
        return bg + label + turns
      })
      .join('')

    svgEl.innerHTML = defs + axisTicks + lanes
    bindTurnEvents()
    paintLegend(speakers)
    trackBadgeEl.textContent = trackMode ? trackMode : ''
  }

  function renderAxis(W, headerH, tMin, tMax) {
    const ticks = 6
    let out = `<line x1="0" y1="${headerH - 1}" x2="${W}" y2="${headerH - 1}" class="axis-line"/>`
    for (let i = 0; i <= ticks; i++) {
      const x = (i / ticks) * W
      const t = tMin + (i / ticks) * (tMax - tMin)
      out += `<line x1="${x}" y1="${headerH - 6}" x2="${x}" y2="${headerH - 1}" class="axis-tick"/>`
      out += `<text x="${x + 2}" y="${headerH - 8}" class="axis-text mono">${t.toFixed(1)}s</text>`
    }
    return out
  }

  function renderTurn(seg, y, laneH, W, tMin, duration) {
    const x = ((((seg.start_ts ?? seg.start ?? 0) - tMin) / duration) * W) | 0
    const x2 = ((((seg.end_ts ?? seg.end ?? 0) - tMin) / duration) * W) | 0
    const w = Math.max(2, x2 - x)
    const opacity = confidenceOpacity(seg.confidence)
    const fill = colorFor(seg.speaker_id)
    const overlap = seg.overlap_flag
      ? `<rect x="${x}" y="${y + 4}" width="${w}" height="${laneH - 8}" fill="url(#overlap-stripes)" />`
      : ''
    const tip = JSON.stringify({
      id: seg.id || seg.segment_id || '',
      text: clip(seg.redacted_text || seg.text || ''),
      confidence: seg.confidence || 'med',
      language: seg.language_tag || 'unknown',
      stem: !!seg.stem_used,
    })
    return `
      <g class="turn" data-tip='${escapeAttr(tip)}' data-segment-id="${escapeAttr(seg.id || seg.segment_id || '')}">
        <rect x="${x}" y="${y + 4}" width="${w}" height="${laneH - 8}" rx="3" fill="${fill}" fill-opacity="${opacity}" />
        ${overlap}
      </g>
    `
  }

  function paintLegend(speakers) {
    const swatches = speakers
      .map(
        (s) =>
          `<span class="legend-key"><i class="swatch" style="background:${colorFor(s)}"></i>${escapeAttr(s)}</span>`,
      )
      .join('')
    const trackIcon = trackMode === 'option_a_stems' ? '⚡ Option A' : trackMode === 'option_b_single' ? '〇 Option B' : ''
    legendEl.innerHTML = `
      ${swatches}
      <span class="legend-key"><i class="swatch overlap-swatch"></i>overlap</span>
      <span class="legend-key"><i class="swatch conf-low"></i>low conf</span>
      ${trackIcon ? `<span class="legend-key track-mode">${trackIcon}</span>` : ''}
    `
  }

  function bindTurnEvents() {
    svgEl.querySelectorAll('.turn').forEach((g) => {
      g.addEventListener('click', () => {
        const segmentId = g.dataset.segmentId
        if (segmentId && onSelectSegment) onSelectSegment(segmentId)
      })
      g.addEventListener('mousemove', (e) => {
        try {
          const tip = JSON.parse(g.dataset.tip)
          tooltipEl.hidden = false
          tooltipEl.innerHTML = `
            <div><strong>${tip.text || '(no text)'}</strong></div>
            <div>conf: ${tip.confidence} · lang: ${tip.language}${tip.stem ? ' · stem' : ''}</div>
          `
          const r = svgEl.getBoundingClientRect()
          tooltipEl.style.left = `${e.clientX - r.left + 12}px`
          tooltipEl.style.top = `${e.clientY - r.top + 12}px`
        } catch {
          /* ignore */
        }
      })
      g.addEventListener('mouseleave', () => {
        tooltipEl.hidden = true
      })
    })
  }

  return {
    mount(container) {
      render(container)
    },
    setData,
    destroy() {
      root?.remove()
    },
  }
}
