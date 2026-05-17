// EscalationPanel.js — escalation events, memory candidates, handoff notes.
//
// Public API:
//   const ep = createEscalationPanel({ onSendToNightingale(candidate) })
//   ep.mount(container)
//   ep.setData(escalationPayload)
//   ep.destroy()

function escapeHtml(str) {
  return String(str ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function fmtTs(t) {
  if (t == null) return ''
  if (typeof t === 'number') {
    const m = Math.floor(t / 60)
    const s = (t - m * 60).toFixed(1)
    return `${m}:${String(s).padStart(4, '0')}`
  }
  return String(t)
}

function severityClass(type) {
  if (!type) return 'sev-medium'
  if (type.includes('high')) return 'sev-high'
  if (type.includes('medium')) return 'sev-medium'
  return 'sev-info'
}

export function createEscalationPanel({ onSendToNightingale } = {}) {
  let root
  let data = { events: [], memory_candidates: [], handoff_notes: [] }

  function render(container) {
    root = document.createElement('section')
    root.className = 'card escalation-panel'
    root.innerHTML = `
      <header class="card-header">
        <h2>Escalation</h2>
        <span class="badge badge-muted mono" data-role="count">0 signals</span>
      </header>
      <div class="escalation-body" data-role="body"></div>
    `
    container.appendChild(root)
    paint()
  }

  function setData(payload) {
    data = {
      events: payload?.events || payload?.escalation_events || [],
      memory_candidates: payload?.memory_candidates || [],
      handoff_notes: payload?.handoff_notes || [],
    }
    paint()
  }

  function paint() {
    const total = data.events.length + data.memory_candidates.length + data.handoff_notes.length
    root.querySelector('[data-role="count"]').textContent = `${total} signal${total === 1 ? '' : 's'}`
    const body = root.querySelector('[data-role="body"]')

    if (total === 0) {
      body.innerHTML = `
        <div class="empty-state ok">
          <div class="check-icon" aria-hidden="true">&#x2713;</div>
          <p>No escalation events detected.</p>
        </div>
      `
      return
    }

    body.innerHTML = [renderEvents(), renderMemory(), renderHandoff()].join('')
    bindEvents()
  }

  function renderEvents() {
    if (!data.events.length) return ''
    return `
      <section class="esc-section">
        <h3 class="section-title">&#x1F6A8; Escalation Events</h3>
        <div class="card-list">
          ${data.events.map(renderEventCard).join('')}
        </div>
      </section>
    `
  }

  function renderEventCard(ev, idx) {
    const sev = severityClass(ev.event_type || ev.severity)
    const term = escapeHtml(ev.watchlist_term || ev.term || '?')
    const spk = escapeHtml(ev.speaker_id || '?')
    const ts = escapeHtml(ev.triggered_at || ev.timestamp || '')
    const conf = escapeHtml(ev.confidence || 'med')
    const resolved = !!ev.resolved
    return `
      <article class="esc-card ${sev} ${resolved ? 'is-resolved' : ''}" data-role="event" data-index="${idx}">
        <div class="esc-card-head">
          <span class="badge sev-badge mono">${escapeHtml(ev.event_type || 'event')}</span>
          <span class="badge badge-muted mono">${spk}</span>
          <span class="badge confidence-${conf} mono">${conf}</span>
        </div>
        <div class="esc-card-body mono">
          <strong>${term}</strong>
          <span class="ts">${ts}</span>
        </div>
        <div class="esc-card-actions">
          <button type="button" class="btn-secondary" data-role="resolve" ${resolved ? 'disabled' : ''}>
            ${resolved ? 'Resolved' : 'Mark Resolved'}
          </button>
        </div>
      </article>
    `
  }

  function renderMemory() {
    if (!data.memory_candidates.length) return ''
    return `
      <section class="esc-section">
        <h3 class="section-title">&#x1F9E0; Memory Candidates</h3>
        <div class="card-list">
          ${data.memory_candidates.map(renderMemoryCard).join('')}
        </div>
      </section>
    `
  }

  function renderMemoryCard(mc, idx) {
    const text = escapeHtml(mc.redacted_text || mc.text || '')
    const spk = escapeHtml(mc.speaker_id || '?')
    const cat = escapeHtml(mc.category || 'instruction')
    const conf = escapeHtml(mc.confidence || 'med')
    return `
      <article class="esc-card memory-card" data-role="memory" data-index="${idx}">
        <div class="esc-card-head">
          <span class="badge badge-category mono">${cat}</span>
          <span class="badge badge-muted mono">${spk}</span>
          <span class="badge confidence-${conf} mono">${conf}</span>
        </div>
        <div class="esc-card-body mono">${text}</div>
        <div class="esc-card-actions">
          <button type="button" class="btn-primary" data-role="send">Send to Nightingale &rarr;</button>
        </div>
      </article>
    `
  }

  function renderHandoff() {
    if (!data.handoff_notes.length) return ''
    return `
      <section class="esc-section">
        <h3 class="section-title">&#x1F4CB; Handoff Notes</h3>
        <div class="card-list">
          ${data.handoff_notes.map(renderHandoffCard).join('')}
        </div>
      </section>
    `
  }

  function renderHandoffCard(hn) {
    const from = escapeHtml(hn.from_speaker || hn.speaker_id || '?')
    const text = escapeHtml(hn.redacted_instruction || hn.text || '')
    const ts = escapeHtml(fmtTs(hn.timestamp ?? hn.start_ts ?? ''))
    return `
      <article class="esc-card handoff-card">
        <div class="esc-card-head">
          <span class="badge badge-handoff mono">handoff</span>
          <span class="badge badge-muted mono">from ${from}</span>
          <span class="ts mono">${ts}</span>
        </div>
        <div class="esc-card-body mono">${text}</div>
      </article>
    `
  }

  function bindEvents() {
    root.querySelectorAll('[data-role="event"]').forEach((node) => {
      const idx = Number(node.dataset.index)
      node.querySelector('[data-role="resolve"]').addEventListener('click', () => {
        data.events[idx].resolved = true
        paint()
      })
    })
    root.querySelectorAll('[data-role="memory"]').forEach((node) => {
      const idx = Number(node.dataset.index)
      node.querySelector('[data-role="send"]').addEventListener('click', () => {
        const candidate = data.memory_candidates[idx]
        console.info('[nightingale] memory candidate ->', candidate)
        if (onSendToNightingale) onSendToNightingale(candidate)
        const btn = node.querySelector('[data-role="send"]')
        btn.textContent = 'Sent'
        btn.disabled = true
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
