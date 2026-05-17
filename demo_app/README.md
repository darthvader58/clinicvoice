# clinicvoice Demo App

Standalone visualization web-app for the clinicvoice pipeline.
Vanilla JavaScript (no framework) + Vite. Connects to the clinicvoice
FastAPI server at `http://127.0.0.1:8000`.

## Prerequisites

- clinicvoice pipeline running:
  ```
  uvicorn src.main:app --host 127.0.0.1 --port 8000
  ```
- Node.js 18+

## Run

```
cd demo_app
npm install
npm run dev
```

Then open http://localhost:5173.

## Build for deployment

```
npm run build
```

Outputs to `demo_app/dist/` — deployable to Netlify, Vercel, or any
static host. In production, update `vite.config.js` proxy target or
serve the static files behind a reverse proxy that forwards `/api/*`
to the clinicvoice backend.

## Layout

- Header: clinicvoice logo, track-mode pill, backend health dot.
- Left panel (35%): Recorder (MediaRecorder + live waveform) and
  file upload drop zone.
- Right panel (65%): tabbed view —
  - Transcript (segments with speaker/confidence/language badges)
  - Metrics (4 gauges + before/after benchmark bar chart)
  - Escalation (events, memory candidates, handoff notes)
  - Timeline (horizontal speaker lanes with turn rectangles)

## Notes

- All audio is processed by your local clinicvoice server. The dev
  proxy in `vite.config.js` routes `/api` to `127.0.0.1:8000`.
- Nothing in the demo writes to disk on the client. Recordings are
  POSTed to the backend and discarded from browser memory.
- The privacy boundary lives in the backend: every API response is
  already redacted before it reaches the browser.
