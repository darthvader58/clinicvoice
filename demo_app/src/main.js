// main.js — clinicvoice demo app bootstrap.
// Builds the layout, wires components, runs the upload → poll → fetch flow.

import { api, pollStatus, ApiError } from './api.js'
import { createRecorder } from './components/Recorder.js'
import { createTranscriptViewer } from './components/TranscriptViewer.js'
import { createMetricsDashboard } from './components/MetricsDashboard.js'
import { createEscalationPanel } from './components/EscalationPanel.js'
import { createSpeakerTimeline } from './components/SpeakerTimeline.js'
import { createTrackModeIndicator } from './components/TrackModeIndicator.js'

const TABS = [
  { id: 'transcript', label: 'Transcript' },
  { id: 'metrics', label: 'Metrics' },
  { id: 'escalation', label: 'Escalation' },
  { id: 'timeline', label: 'Timeline' },
]

const state = {
  recordingId: null,
  activeTab: 'transcript',
  transcriptData: null,
  liveSegments: [],
  liveCursorTs: 0,
}

function $(sel, root = document) {
  return root.querySelector(sel)
}

function setText(sel, text) {
  const el = $(sel)
  if (el) el.textContent = text
}

function buildLayout() {
  const app = document.getElementById('app')
  app.innerHTML = `
    <header class="app-header">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true"></span>
        <div class="brand-text">
          <span class="brand-name">clinicvoice</span>
          <span class="brand-tag mono">privacy-first clinical voice pipeline</span>
        </div>
      </div>
      <div class="header-right">
        <div class="track-mode-slot" data-role="track-slot"></div>
        <div class="health-pill" data-role="health">
          <span class="health-dot" data-role="health-dot"></span>
          <span class="health-text mono">checking…</span>
        </div>
      </div>
    </header>

    <main class="app-main">
      <aside class="left-panel" data-role="left"></aside>

      <section class="right-panel">
        <nav class="tabs" role="tablist" data-role="tabs">
          ${TABS.map(
            (t, i) =>
              `<button type="button" class="tab ${i === 0 ? 'is-active' : ''}" role="tab" aria-selected="${i === 0}" data-tab="${t.id}">${t.label}</button>`,
          ).join('')}
        </nav>
        <div class="tab-panels">
          ${TABS.map(
            (t, i) =>
              `<div class="tab-panel ${i === 0 ? 'is-active' : ''}" role="tabpanel" data-panel="${t.id}"></div>`,
          ).join('')}
        </div>

        <div class="status-banner" data-role="banner" hidden></div>
      </section>
    </main>

    <footer class="app-footer mono">
      <span>clinicvoice demo · all audio processed locally · redaction enforced before storage</span>
      <span data-role="recording-id"></span>
    </footer>
  `
}

function bindTabs(panels) {
  document.querySelectorAll('[data-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.tab
      state.activeTab = id
      document.querySelectorAll('[data-tab]').forEach((b) => {
        const active = b.dataset.tab === id
        b.classList.toggle('is-active', active)
        b.setAttribute('aria-selected', String(active))
      })
      document.querySelectorAll('[data-panel]').forEach((p) => {
        p.classList.toggle('is-active', p.dataset.panel === id)
      })
    })
  })
}

function showBanner(message, kind = 'info', autoHideMs = 0) {
  const banner = document.querySelector('[data-role="banner"]')
  if (!banner) return
  banner.hidden = false
  banner.dataset.kind = kind
  banner.textContent = message
  if (autoHideMs > 0) {
    setTimeout(() => {
      banner.hidden = true
    }, autoHideMs)
  }
}

function hideBanner() {
  const banner = document.querySelector('[data-role="banner"]')
  if (banner) banner.hidden = true
}

async function refreshHealth(trackIndicator) {
  const dot = document.querySelector('[data-role="health-dot"]')
  const text = document.querySelector('[data-role="health"] .health-text')
  try {
    const h = await api.health()
    const ok = h.status === 'ok' || h.status === 'healthy' || h.status === 'ready'
    dot.dataset.state = ok ? 'ok' : 'degraded'
    const parts = []
    if (h.whisper_loaded) parts.push('whisper')
    if (h.pyannote_loaded) parts.push('pyannote')
    if (h.asteroid_loaded) parts.push('asteroid')
    text.textContent = parts.length ? `backend · ${parts.join(' · ')}` : `backend · ${h.status || 'ok'}`
  } catch (err) {
    dot.dataset.state = 'down'
    text.textContent = 'backend offline'
    if (err instanceof ApiError) console.warn('[health]', err.status, err.message)
  }
}

async function loadBenchmark(dashboard) {
  try {
    const b = await api.benchmark()
    dashboard.setBenchmark(b)
  } catch (err) {
    const msg =
      err instanceof ApiError && err.status === 404
        ? 'No benchmark results yet.'
        : `Could not load benchmark: ${err.message}`
    dashboard.setBenchmarkError(msg)
  }
}

async function handleUpload({ result }, components) {
  if (!result?.recording_id) {
    showBanner('Upload did not return a recording_id.', 'error', 6000)
    return
  }
  state.recordingId = result.recording_id
  setText('[data-role="recording-id"]', `recording_id: ${state.recordingId}`)
  if (result.track_mode) {
    components.trackIndicator.set({ track_mode: result.track_mode })
  }
  showBanner('Pipeline running — waiting for completion…', 'info')
  try {
    const final = await pollStatus(state.recordingId, {
      onTick(s) {
        if (s.track_mode || s.si_sdr != null) {
          components.trackIndicator.set({ track_mode: s.track_mode, si_sdr: s.si_sdr })
        }
        const pct = s.progress != null ? ` ${(s.progress * 100).toFixed(0)}%` : ''
        showBanner(`status: ${s.status}${pct}`, 'info')
      },
    })
    components.trackIndicator.set({ track_mode: final.track_mode, si_sdr: final.si_sdr })
    await loadAllForRecording(state.recordingId, components)
    showBanner('Pipeline complete.', 'success', 3000)
  } catch (err) {
    console.error('[pipeline]', err)
    showBanner(`Pipeline failed: ${err.message}`, 'error', 8000)
  }
}

function renderLiveTranscript(components) {
  const payload = {
    recording_id: state.recordingId,
    track_mode: 'live',
    si_sdr: null,
    segments: state.liveSegments,
  }
  state.transcriptData = payload
  components.transcriptViewer.setData(payload)
  components.speakerTimeline.setData({
    segments: state.liveSegments,
    track_mode: 'live',
  })
}

function handleLiveStart({ recording_id, language }, components) {
  state.recordingId = recording_id
  state.liveSegments = []
  state.liveCursorTs = 0
  setText('[data-role="recording-id"]', `recording_id: ${recording_id}`)
  components.trackIndicator.set({ track_mode: 'live', si_sdr: null })
  renderLiveTranscript(components)
  showBanner(`Live session started (${language}). Speak into the mic.`, 'info', 4000)
}

function handleLiveChunk(chunk, components) {
  if (!chunk || chunk.recording_id !== state.recordingId) return
  const start = state.liveCursorTs
  const end = start + (chunk.duration_s || 0)
  state.liveCursorTs = end
  state.liveSegments = [
    ...state.liveSegments,
    {
      segment_id: `live-${chunk.seq}`,
      speaker_id: 'LIVE',
      start_ts: start,
      end_ts: end,
      confidence: 'med',
      language_tag: chunk.language_tag || 'unknown',
      overlap_flag: false,
      stem_used: false,
      redacted_text: chunk.redacted_text || '',
      redaction_map: [],
    },
  ]
  renderLiveTranscript(components)
}

async function handleLiveStop({ recording_id, chunks }, components) {
  showBanner(
    `Consolidating ${chunks} chunks into final transcript…`,
    'info',
  )
  try {
    await pollStatus(recording_id, {
      intervalMs: 1500,
      timeoutMs: 600000,
      onTick(s) {
        if (s.track_mode || s.si_sdr != null) {
          components.trackIndicator.set({
            track_mode: s.track_mode,
            si_sdr: s.si_sdr,
          })
        }
        const pct = s.progress != null ? ` ${(s.progress * 100).toFixed(0)}%` : ''
        showBanner(`consolidation: ${s.status}${pct}`, 'info')
      },
    })
    await loadAllForRecording(recording_id, components)
    showBanner('Final transcript ready.', 'success', 3000)
  } catch (err) {
    console.warn('[live-consolidate]', err)
    showBanner(`Consolidation failed: ${err.message}`, 'error', 6000)
  }
}

async function loadAllForRecording(recordingId, components) {
  const [transcript, metrics, escalation] = await Promise.allSettled([
    api.transcript(recordingId),
    api.metrics(recordingId),
    api.escalation(recordingId),
  ])

  if (transcript.status === 'fulfilled') {
    state.transcriptData = transcript.value
    components.transcriptViewer.setData(transcript.value)
    components.speakerTimeline.setData({
      segments: transcript.value.segments || [],
      track_mode: transcript.value.track_mode,
    })
  } else {
    console.warn('[transcript]', transcript.reason)
  }

  if (metrics.status === 'fulfilled') {
    components.metricsDashboard.setMetrics(metrics.value)
  } else {
    console.warn('[metrics]', metrics.reason)
  }

  if (escalation.status === 'fulfilled') {
    components.escalationPanel.setData(escalation.value)
  } else {
    console.warn('[escalation]', escalation.reason)
  }
}

function bootstrap() {
  buildLayout()

  const trackIndicator = createTrackModeIndicator()
  trackIndicator.mount(document.querySelector('[data-role="track-slot"]'))

  const transcriptViewer = createTranscriptViewer({
    onSelectSegment(id) {
      // jump tab to timeline highlight could go here; keep transcript-driven for now
      if (id) state.activeTab = state.activeTab
    },
    onCorrection({ result }) {
      if (result?.new_mter != null) {
        showBanner(`New MTER after correction: ${(result.new_mter * 100).toFixed(1)}%`, 'success', 4000)
      }
    },
  })
  const metricsDashboard = createMetricsDashboard()
  const escalationPanel = createEscalationPanel({
    onSendToNightingale(candidate) {
      showBanner(`Memory candidate logged to console: ${candidate?.category || 'instruction'}`, 'info', 3000)
    },
  })
  const speakerTimeline = createSpeakerTimeline({
    onSelectSegment(segmentId) {
      // switch to transcript and highlight
      const tabBtn = document.querySelector('[data-tab="transcript"]')
      if (tabBtn) tabBtn.click()
      transcriptViewer.highlight(segmentId)
    },
  })

  const components = {
    trackIndicator,
    transcriptViewer,
    metricsDashboard,
    escalationPanel,
    speakerTimeline,
  }

  // mount panels
  transcriptViewer.mount(document.querySelector('[data-panel="transcript"]'))
  metricsDashboard.mount(document.querySelector('[data-panel="metrics"]'))
  escalationPanel.mount(document.querySelector('[data-panel="escalation"]'))
  speakerTimeline.mount(document.querySelector('[data-panel="timeline"]'))

  // mount recorder in left panel
  const recorder = createRecorder({
    onUpload(payload) {
      handleUpload(payload, components)
    },
    onLiveStart(payload) {
      handleLiveStart(payload, components)
    },
    onLiveChunk(payload) {
      handleLiveChunk(payload, components)
    },
    onLiveStop(payload) {
      handleLiveStop(payload, components)
    },
    onError(err) {
      console.warn('[recorder]', err)
      showBanner(`Recorder: ${err.message || err}`, 'error', 5000)
    },
  })
  recorder.mount(document.querySelector('[data-role="left"]'))

  bindTabs()

  // initial fetches
  refreshHealth(trackIndicator)
  setInterval(() => refreshHealth(trackIndicator), 15000)
  loadBenchmark(metricsDashboard)
}

document.addEventListener('DOMContentLoaded', bootstrap)
