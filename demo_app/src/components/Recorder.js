// Recorder.js — MediaRecorder-based audio capture with live waveform.
//
// Public API:
//   const rec = createRecorder({
//     onUpload({ file, scenario, language, result }) {...},
//     onLiveStart({ recording_id, language }) {...},
//     onLiveChunk({ recording_id, seq, redacted_text, language_tag, duration_s }) {...},
//     onLiveStop({ recording_id, chunks }) {...},
//     onError(err),
//   })
//   rec.mount(container)
//   rec.destroy()

import { api } from '../api.js'

const LIVE_CHUNK_MS = 10000  // rotate MediaRecorder every 10s for live mode

const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/ogg',
  'audio/mp4',
]

function pickMimeType() {
  if (typeof MediaRecorder === 'undefined') return null
  for (const mt of PREFERRED_MIME_TYPES) {
    if (MediaRecorder.isTypeSupported(mt)) return mt
  }
  return ''
}

function formatDuration(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${String(r).padStart(2, '0')}`
}

export function createRecorder({
  onUpload,
  onLiveStart,
  onLiveChunk,
  onLiveStop,
  onError,
} = {}) {
  const state = {
    recording: false,
    uploading: false,
    stream: null,
    mediaRecorder: null,
    chunks: [],
    audioCtx: null,
    analyser: null,
    rafId: null,
    startedAt: 0,
    durationTimer: null,
    scenario: 'unknown',
    language: 'auto',
    mode: 'live',
    liveRecordingId: null,
    liveSeq: 0,
    liveRotateTimer: null,
    liveMime: '',
  }

  let root
  let canvas
  let canvasCtx
  let recordBtn
  let pulseRing
  let durationEl
  let statusEl
  let fileInput
  let dropZone
  let scenarioSel
  let languageSel
  let modeSel

  function render(container) {
    root = document.createElement('section')
    root.className = 'card recorder'
    root.innerHTML = `
      <header class="card-header">
        <h2>Capture</h2>
        <span class="privacy-label" title="No audio leaves your machine unless USE_CLOUD_ASR is set.">
          <span class="lock-icon" aria-hidden="true">&#x1F512;</span>
          Audio processed locally only. Nothing sent to cloud.
        </span>
      </header>

      <div class="recorder-body">
        <div class="waveform-wrap">
          <canvas class="waveform" width="640" height="120" aria-label="live audio waveform"></canvas>
          <div class="duration mono" data-role="duration">0:00</div>
        </div>

        <div class="record-controls">
          <button type="button" class="record-btn" data-role="record" aria-pressed="false">
            <span class="pulse-ring" data-role="pulse" aria-hidden="true"></span>
            <span class="record-dot" aria-hidden="true"></span>
            <span class="record-label">Start recording</span>
          </button>

          <label class="field">
            <span class="field-label">Mode</span>
            <select data-role="mode" class="select">
              <option value="live" selected>Live (rolling chunks)</option>
              <option value="batch">Batch (upload at end)</option>
            </select>
          </label>

          <label class="field">
            <span class="field-label">Scenario</span>
            <select data-role="scenario" class="select">
              <option value="unknown" selected>Unknown</option>
              <option value="consult">Consult</option>
              <option value="hallway">Hallway</option>
            </select>
          </label>

          <label class="field">
            <span class="field-label">Language</span>
            <select data-role="language" class="select">
              <option value="auto" selected>Auto-detect</option>
              <option value="en">English</option>
              <option value="hi">Hindi</option>
              <option value="ur">Urdu</option>
              <option value="ta">Tamil</option>
              <option value="id">Indonesian (Bahasa)</option>
              <option value="ms">Malay (Bahasa)</option>
            </select>
          </label>
        </div>

        <div class="status-line mono" data-role="status" role="status" aria-live="polite">Ready.</div>

        <div class="upload-zone" data-role="drop">
          <p class="upload-title">Or drop an audio file here</p>
          <p class="upload-hint mono">wav · webm · ogg · m4a · mp3 · flac</p>
          <input type="file" accept="audio/*" data-role="file" hidden />
          <button type="button" class="btn-secondary" data-role="browse">Browse files…</button>
        </div>
      </div>
    `

    container.appendChild(root)

    canvas = root.querySelector('.waveform')
    canvasCtx = canvas.getContext('2d')
    recordBtn = root.querySelector('[data-role="record"]')
    pulseRing = root.querySelector('[data-role="pulse"]')
    durationEl = root.querySelector('[data-role="duration"]')
    statusEl = root.querySelector('[data-role="status"]')
    fileInput = root.querySelector('[data-role="file"]')
    dropZone = root.querySelector('[data-role="drop"]')
    scenarioSel = root.querySelector('[data-role="scenario"]')
    languageSel = root.querySelector('[data-role="language"]')
    modeSel = root.querySelector('[data-role="mode"]')

    bindEvents()
    drawIdleWaveform()
  }

  function bindEvents() {
    recordBtn.addEventListener('click', toggleRecording)
    scenarioSel.addEventListener('change', () => {
      state.scenario = scenarioSel.value
    })
    languageSel.addEventListener('change', () => {
      state.language = languageSel.value
    })
    modeSel.addEventListener('change', () => {
      state.mode = modeSel.value
    })

    root.querySelector('[data-role="browse"]').addEventListener('click', () => {
      fileInput.click()
    })
    fileInput.addEventListener('change', (e) => {
      const f = e.target.files?.[0]
      if (f) submitFile(f)
      fileInput.value = ''
    })

    ;['dragenter', 'dragover'].forEach((evt) =>
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault()
        dropZone.classList.add('drag-over')
      }),
    )
    ;['dragleave', 'drop'].forEach((evt) =>
      dropZone.addEventListener(evt, (e) => {
        e.preventDefault()
        dropZone.classList.remove('drag-over')
      }),
    )
    dropZone.addEventListener('drop', (e) => {
      const f = e.dataTransfer?.files?.[0]
      if (f) submitFile(f)
    })
  }

  async function toggleRecording() {
    if (state.uploading) return
    if (state.recording) {
      if (state.mode === 'live') await stopLiveRecording()
      else stopRecording()
    } else {
      if (state.mode === 'live') await startLiveRecording()
      else await startRecording()
    }
  }

  async function startLiveRecording() {
    if (!navigator.mediaDevices?.getUserMedia) {
      return setStatus('Browser does not support microphone access.', 'error')
    }
    const mime = pickMimeType()
    if (mime === null) {
      return setStatus('MediaRecorder is not available in this browser.', 'error')
    }
    state.liveMime = mime || 'audio/webm'

    try {
      state.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (err) {
      reportError(err)
      return setStatus('Microphone permission denied.', 'error')
    }

    try {
      const startResp = await api.streamStart(state.scenario, state.language)
      state.liveRecordingId = startResp.recording_id
      state.liveSeq = 0
      if (onLiveStart)
        onLiveStart({ recording_id: state.liveRecordingId, language: state.language })
    } catch (err) {
      reportError(err)
      stopMediaTracks()
      return setStatus(`Could not start live session: ${err.message}`, 'error')
    }

    setupAnalyser(state.stream)
    state.recording = true
    state.startedAt = performance.now()
    setRecordingUi(true)
    setStatus(`Live — chunk every ${LIVE_CHUNK_MS / 1000}s`, 'recording')
    tickDuration()
    drawLiveWaveform()

    rotateLiveChunk()  // kick off the first chunk recorder immediately
    state.liveRotateTimer = setInterval(rotateLiveChunk, LIVE_CHUNK_MS)
  }

  function rotateLiveChunk() {
    // Stop the current recorder (its onstop will upload), then immediately
    // start a fresh recorder on the same MediaStream so we never miss audio.
    const previous = state.mediaRecorder
    if (previous && previous.state !== 'inactive') {
      try {
        previous.stop()
      } catch (err) {
        reportError(err)
      }
    }
    if (!state.recording || !state.stream) return

    let recorder
    try {
      recorder = new MediaRecorder(
        state.stream,
        state.liveMime ? { mimeType: state.liveMime } : undefined,
      )
    } catch (err) {
      reportError(err)
      return
    }
    const chunkBuf = []
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunkBuf.push(e.data)
    }
    recorder.onstop = async () => {
      if (chunkBuf.length === 0) return
      const blob = new Blob(chunkBuf, { type: state.liveMime })
      const ext = (state.liveMime.split('/')[1] || 'webm').split(';')[0]
      const filename = `chunk-${Date.now()}.${ext}`
      try {
        const resp = await api.streamChunk(state.liveRecordingId, blob, filename)
        state.liveSeq = (resp.seq ?? state.liveSeq) + 1
        if (onLiveChunk) onLiveChunk(resp)
      } catch (err) {
        reportError(err)
      }
    }
    recorder.onerror = (e) => reportError(e.error || new Error('MediaRecorder error'))
    state.mediaRecorder = recorder
    recorder.start()
  }

  async function stopLiveRecording() {
    if (state.liveRotateTimer) {
      clearInterval(state.liveRotateTimer)
      state.liveRotateTimer = null
    }
    // Flush the final chunk: stop the active recorder so its onstop fires
    // and uploads the tail. Wait briefly to give the upload a chance.
    if (state.mediaRecorder && state.mediaRecorder.state !== 'inactive') {
      try {
        state.mediaRecorder.stop()
      } catch (err) {
        reportError(err)
      }
    }
    state.recording = false
    setRecordingUi(false)
    cancelAnimationFrame(state.rafId)
    stopMediaTracks()
    setStatus('Stopping — consolidating final transcript…', 'uploading')
    try {
      const resp = await api.streamStop(state.liveRecordingId)
      setStatus(
        `Live session ended. Consolidating ${resp.chunks} chunks into final transcript…`,
        'success',
      )
      if (onLiveStop) onLiveStop(resp)
    } catch (err) {
      reportError(err)
      setStatus(`Could not stop live session: ${err.message}`, 'error')
    }
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia) {
      return setStatus('Browser does not support microphone access.', 'error')
    }
    const mime = pickMimeType()
    if (mime === null) {
      return setStatus('MediaRecorder is not available in this browser.', 'error')
    }

    try {
      state.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (err) {
      reportError(err)
      return setStatus('Microphone permission denied.', 'error')
    }

    try {
      state.mediaRecorder = new MediaRecorder(state.stream, mime ? { mimeType: mime } : undefined)
    } catch (err) {
      reportError(err)
      stopMediaTracks()
      return setStatus('Could not start MediaRecorder.', 'error')
    }

    state.chunks = []
    state.mediaRecorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) state.chunks.push(e.data)
    }
    state.mediaRecorder.onstop = handleRecordingStop
    state.mediaRecorder.onerror = (e) => reportError(e.error || new Error('MediaRecorder error'))

    setupAnalyser(state.stream)
    state.mediaRecorder.start(250)
    state.recording = true
    state.startedAt = performance.now()
    setRecordingUi(true)
    setStatus('Recording…', 'recording')
    tickDuration()
    drawLiveWaveform()
  }

  function stopRecording() {
    if (state.mediaRecorder && state.mediaRecorder.state !== 'inactive') {
      try {
        state.mediaRecorder.stop()
      } catch (err) {
        reportError(err)
      }
    }
    state.recording = false
    setRecordingUi(false)
    cancelAnimationFrame(state.rafId)
    state.rafId = null
    clearInterval(state.durationTimer)
    state.durationTimer = null
  }

  async function handleRecordingStop() {
    stopMediaTracks()
    const mime = state.mediaRecorder?.mimeType || 'audio/webm'
    const blob = new Blob(state.chunks, { type: mime })
    state.chunks = []
    if (blob.size === 0) {
      return setStatus('Empty recording — nothing to upload.', 'error')
    }
    const ext = (mime.split('/')[1] || 'webm').split(';')[0]
    const file = new File([blob], `recording-${Date.now()}.${ext}`, { type: mime })
    await submitFile(file)
  }

  async function submitFile(file) {
    state.uploading = true
    recordBtn.disabled = true
    setStatus(`Uploading ${file.name} (${(file.size / 1024).toFixed(1)} KB)…`, 'uploading')
    try {
      const result = await api.upload(file, state.scenario, state.language)
      setStatus(`Uploaded. recording_id=${result.recording_id}`, 'success')
      if (onUpload)
        onUpload({ file, scenario: state.scenario, language: state.language, result })
    } catch (err) {
      reportError(err)
      setStatus(`Upload failed: ${err.message}`, 'error')
    } finally {
      state.uploading = false
      recordBtn.disabled = false
    }
  }

  function setupAnalyser(stream) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext
      state.audioCtx = new Ctx()
      const source = state.audioCtx.createMediaStreamSource(stream)
      state.analyser = state.audioCtx.createAnalyser()
      state.analyser.fftSize = 2048
      source.connect(state.analyser)
    } catch (err) {
      reportError(err)
    }
  }

  function drawLiveWaveform() {
    if (!state.analyser) return
    const buf = new Uint8Array(state.analyser.fftSize)
    const draw = () => {
      state.rafId = requestAnimationFrame(draw)
      state.analyser.getByteTimeDomainData(buf)
      paintWaveform(buf)
    }
    draw()
  }

  function paintWaveform(buf) {
    const { width, height } = canvas
    canvasCtx.clearRect(0, 0, width, height)
    canvasCtx.fillStyle = '#0a1422'
    canvasCtx.fillRect(0, 0, width, height)

    // grid line
    canvasCtx.strokeStyle = 'rgba(0, 229, 255, 0.12)'
    canvasCtx.lineWidth = 1
    canvasCtx.beginPath()
    canvasCtx.moveTo(0, height / 2)
    canvasCtx.lineTo(width, height / 2)
    canvasCtx.stroke()

    canvasCtx.lineWidth = 2
    canvasCtx.strokeStyle = state.recording ? '#00e5ff' : '#5a7fa8'
    canvasCtx.beginPath()
    const slice = width / buf.length
    let x = 0
    for (let i = 0; i < buf.length; i++) {
      const v = buf[i] / 128.0
      const y = (v * height) / 2
      if (i === 0) canvasCtx.moveTo(x, y)
      else canvasCtx.lineTo(x, y)
      x += slice
    }
    canvasCtx.stroke()
  }

  function drawIdleWaveform() {
    const buf = new Uint8Array(256).fill(128)
    paintWaveform(buf)
  }

  function tickDuration() {
    const update = () => {
      const sec = (performance.now() - state.startedAt) / 1000
      durationEl.textContent = formatDuration(sec)
    }
    update()
    state.durationTimer = setInterval(update, 200)
  }

  function setRecordingUi(active) {
    recordBtn.setAttribute('aria-pressed', String(active))
    recordBtn.classList.toggle('is-recording', active)
    pulseRing.classList.toggle('is-active', active)
    recordBtn.querySelector('.record-label').textContent = active ? 'Stop recording' : 'Start recording'
    if (!active) drawIdleWaveform()
  }

  function setStatus(msg, kind = 'idle') {
    statusEl.textContent = msg
    statusEl.dataset.kind = kind
  }

  function stopMediaTracks() {
    if (state.stream) {
      state.stream.getTracks().forEach((t) => t.stop())
      state.stream = null
    }
    if (state.audioCtx && state.audioCtx.state !== 'closed') {
      state.audioCtx.close().catch(() => {})
    }
    state.audioCtx = null
    state.analyser = null
  }

  function reportError(err) {
    console.error('[recorder]', err)
    if (onError) onError(err)
  }

  return {
    mount(container) {
      render(container)
    },
    destroy() {
      if (state.recording) stopRecording()
      stopMediaTracks()
      clearInterval(state.durationTimer)
      cancelAnimationFrame(state.rafId)
      root?.remove()
    },
  }
}
