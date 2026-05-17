// clinicvoice API client.
// All requests go through the Vite dev proxy at /api/* → 127.0.0.1:8000.
// Every response from the backend is already redacted — this module
// does not handle any PHI on the client side.

const BASE = '/api'

async function asJson(res) {
  const text = await res.text()
  let data
  try {
    data = text ? JSON.parse(text) : {}
  } catch {
    throw new ApiError(res.status, `non-JSON response: ${text.slice(0, 200)}`)
  }
  if (!res.ok) {
    const detail = data?.detail || data?.message || res.statusText
    throw new ApiError(res.status, detail, data)
  }
  return data
}

export class ApiError extends Error {
  constructor(status, message, body) {
    super(`[${status}] ${message}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

export const api = {
  /**
   * Upload a recording for processing.
   * @param {Blob|File} file - audio blob (webm/ogg/wav/mp4)
   * @param {string} scenario - 'hallway' | 'consult' | 'unknown'
   * @returns {Promise<{recording_id: string, track_mode?: string}>}
   */
  upload(file, scenario = 'unknown', language = 'auto') {
    const fd = new FormData()
    const filename = file.name || `recording.${guessExt(file.type)}`
    fd.append('file', file, filename)
    fd.append('scenario', scenario)
    fd.append('language', language)
    return fetch(`${BASE}/upload`, { method: 'POST', body: fd }).then(asJson)
  },

  /**
   * Poll pipeline status.
   * @returns {Promise<{status: string, progress?: number, track_mode?: string, si_sdr?: number}>}
   */
  status(id) {
    return fetch(`${BASE}/status/${encodeURIComponent(id)}`).then(asJson)
  },

  /**
   * Fetch redacted transcript segments.
   */
  transcript(id) {
    return fetch(`${BASE}/transcript/${encodeURIComponent(id)}`).then(asJson)
  },

  /**
   * Fetch metrics run for a recording.
   */
  metrics(id) {
    return fetch(`${BASE}/metrics/${encodeURIComponent(id)}`).then(asJson)
  },

  /**
   * Fetch escalation events, memory candidates, and handoff notes.
   */
  escalation(id) {
    return fetch(`${BASE}/escalation/${encodeURIComponent(id)}`).then(asJson)
  },

  /**
   * Fetch pre-computed benchmark report (3-pass: baseline / biasing / corrections).
   */
  benchmark() {
    return fetch(`${BASE}/benchmark`).then(asJson)
  },

  /**
   * Backend health probe.
   * @returns {Promise<{status: string, whisper_loaded?: boolean, pyannote_loaded?: boolean, asteroid_loaded?: boolean}>}
   */
  health() {
    return fetch(`${BASE}/health`).then(asJson)
  },

  /**
   * Submit a transcript correction; backend updates lexicon and returns new MTER.
   */
  correction(id, segmentId, correctedText) {
    return fetch(`${BASE}/corrections/${encodeURIComponent(id)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        segment_id: segmentId,
        corrected_text: correctedText,
      }),
    }).then(asJson)
  },
}

function guessExt(mime) {
  if (!mime) return 'webm'
  if (mime.includes('webm')) return 'webm'
  if (mime.includes('ogg')) return 'ogg'
  if (mime.includes('mp4') || mime.includes('m4a')) return 'm4a'
  if (mime.includes('wav')) return 'wav'
  return 'webm'
}

/**
 * Poll a status endpoint until status === 'complete' or 'error'.
 * Resolves with the final status payload. Rejects on timeout or error.
 */
export function pollStatus(recordingId, { intervalMs = 1000, timeoutMs = 300000, onTick } = {}) {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const s = await api.status(recordingId)
        if (onTick) onTick(s)
        if (s.status === 'complete' || s.status === 'done' || s.status === 'finished') {
          return resolve(s)
        }
        if (s.status === 'error' || s.status === 'failed') {
          return reject(new ApiError(500, s.error || 'pipeline failed', s))
        }
        if (Date.now() - started > timeoutMs) {
          return reject(new ApiError(504, 'polling timed out'))
        }
        setTimeout(tick, intervalMs)
      } catch (err) {
        reject(err)
      }
    }
    tick()
  })
}
