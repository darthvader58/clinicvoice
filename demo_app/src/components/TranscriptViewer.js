// TranscriptViewer.js — renders redacted transcript segments.
//
// Public API:
//   const tv = createTranscriptViewer({ onSelectSegment(id), onCorrection({recordingId, segmentId, text}) })
//   tv.mount(container)
//   tv.setData({ recording_id, segments })
//   tv.highlight(segmentId)
//   tv.destroy()

import { api } from '../api.js'

const SPEAKER_CLASS = {
  S1: 'speaker-s1',
  S2: 'speaker-s2',
  S3: 'speaker-s3',
  S4: 'speaker-s4',
}

function speakerClass(id) {
  return SPEAKER_CLASS[id] || 'speaker-unknown'
}

function fmtTs(t) {
  if (t == null || Number.isNaN(t)) return '?'
  const m = Math.floor(t / 60)
  const s = (t - m * 60).toFixed(1)
  return `${m}:${String(s).padStart(4, '0')}`
}

function escapeHtml(str) {
  return String(str ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

// Render redacted text with [REDACTED] spans visually distinct + tooltip.
function renderRedactedText(text) {
  const escaped = escapeHtml(text)
  // Common redaction patterns from Presidio: [REDACTED], <PHONE>, <PERSON>, etc.
  return escaped.replace(
    /(\[(?:REDACTED|PHI)[^\]]*\]|&lt;[A-Z_]+&gt;)/g,
    '<span class="redacted" title="PHI redacted before storage">$1</span>',
  )
}

export function createTranscriptViewer({ onSelectSegment, onCorrection } = {}) {
  let root
  let listEl
  let data = { recording_id: null, segments: [] }

  function render(container) {
    root = document.createElement('section')
    root.className = 'card transcript-viewer'
    root.innerHTML = `
      <header class="card-header">
        <h2>Transcript</h2>
        <span class="badge badge-muted mono" data-role="count">0 segments</span>
      </header>
      <div class="transcript-list" data-role="list" role="list"></div>
    `
    container.appendChild(root)
    listEl = root.querySelector('[data-role="list"]')
    paintEmpty()
  }

  function paintEmpty() {
    listEl.innerHTML = `
      <div class="empty-state">
        <p>No transcript yet. Record or upload audio to see redacted segments.</p>
      </div>
    `
    root.querySelector('[data-role="count"]').textContent = '0 segments'
  }

  function setData(payload) {
    data = {
      recording_id: payload?.recording_id || payload?.id || null,
      segments: payload?.segments || [],
    }
    paint()
  }

  function paint() {
    if (!data.segments?.length) return paintEmpty()
    root.querySelector('[data-role="count"]').textContent = `${data.segments.length} segment${data.segments.length === 1 ? '' : 's'}`
    listEl.innerHTML = data.segments.map(renderSegment).join('')
    bindSegmentEvents()
  }

  function renderSegment(seg) {
    const sid = escapeHtml(seg.id || seg.segment_id || '')
    const spk = escapeHtml(seg.speaker_id || '?')
    const conf = (seg.confidence || 'med').toLowerCase()
    const lang = escapeHtml(seg.language_tag || 'unknown')
    const start = fmtTs(seg.start_ts ?? seg.start)
    const end = fmtTs(seg.end_ts ?? seg.end)
    // Prefer the romanized version for display when present (non-English).
    // The canonical seg.redacted_text remains in the original script in the
    // DB and the API response for downstream consumers.
    const text = seg.redacted_text_roman || seg.redacted_text || seg.text || ''
    const stemBadge = seg.stem_used
      ? '<span class="badge badge-stem mono" title="Decoded from Option A stem">&#x26A1; Stem</span>'
      : ''
    const overlapBadge = seg.overlap_flag
      ? '<span class="badge badge-overlap mono" title="Overlapping speech detected">&#x21C6; Overlap</span>'
      : ''

    return `
      <article class="segment ${speakerClass(spk)}" role="listitem" data-segment-id="${sid}">
        <div class="segment-meta">
          <span class="badge speaker-badge mono">${spk}</span>
          <span class="badge confidence-${conf} mono" title="Confidence">${conf}</span>
          <span class="badge badge-lang mono">${lang}</span>
          ${stemBadge}
          ${overlapBadge}
          <span class="ts mono" aria-label="timestamp">${start} &rarr; ${end}</span>
        </div>
        <div class="segment-text mono" data-role="text" tabindex="0" title="Double-click to correct">${renderRedactedText(text)}</div>
        <div class="segment-edit" hidden data-role="edit">
          <textarea class="edit-input mono" data-role="edit-input" rows="2"></textarea>
          <div class="edit-actions">
            <button type="button" class="btn-secondary" data-role="cancel">Cancel</button>
            <button type="button" class="btn-primary" data-role="save">Save correction</button>
          </div>
        </div>
      </article>
    `
  }

  function bindSegmentEvents() {
    listEl.querySelectorAll('.segment').forEach((node) => {
      const segmentId = node.dataset.segmentId
      const textEl = node.querySelector('[data-role="text"]')
      const editEl = node.querySelector('[data-role="edit"]')
      const input = node.querySelector('[data-role="edit-input"]')
      const cancelBtn = node.querySelector('[data-role="cancel"]')
      const saveBtn = node.querySelector('[data-role="save"]')

      node.addEventListener('click', (e) => {
        if (e.target.closest('[data-role="edit"]')) return
        if (onSelectSegment) onSelectSegment(segmentId)
        listEl.querySelectorAll('.segment').forEach((n) => n.classList.remove('is-selected'))
        node.classList.add('is-selected')
      })

      textEl.addEventListener('dblclick', () => {
        input.value = textEl.textContent.trim()
        textEl.hidden = true
        editEl.hidden = false
        input.focus()
      })

      cancelBtn.addEventListener('click', () => {
        editEl.hidden = true
        textEl.hidden = false
      })

      saveBtn.addEventListener('click', async () => {
        const corrected = input.value.trim()
        if (!corrected) return
        saveBtn.disabled = true
        saveBtn.textContent = 'Saving…'
        try {
          let result = null
          if (data.recording_id) {
            result = await api.correction(data.recording_id, segmentId, corrected)
          }
          textEl.innerHTML = renderRedactedText(corrected)
          editEl.hidden = true
          textEl.hidden = false
          if (onCorrection) {
            onCorrection({
              recordingId: data.recording_id,
              segmentId,
              text: corrected,
              result,
            })
          }
        } catch (err) {
          console.error('[transcript] correction failed', err)
          saveBtn.textContent = 'Save correction'
          alertInline(node, `Correction failed: ${err.message}`)
        } finally {
          saveBtn.disabled = false
          saveBtn.textContent = 'Save correction'
        }
      })
    })
  }

  function alertInline(node, msg) {
    let bar = node.querySelector('.inline-error')
    if (!bar) {
      bar = document.createElement('div')
      bar.className = 'inline-error mono'
      node.appendChild(bar)
    }
    bar.textContent = msg
    setTimeout(() => bar.remove(), 5000)
  }

  function highlight(segmentId) {
    const node = listEl.querySelector(`[data-segment-id="${segmentId}"]`)
    if (!node) return
    listEl.querySelectorAll('.segment').forEach((n) => n.classList.remove('is-selected'))
    node.classList.add('is-selected')
    node.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  return {
    mount(container) {
      render(container)
    },
    setData,
    highlight,
    destroy() {
      root?.remove()
    },
  }
}
