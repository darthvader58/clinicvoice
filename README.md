# clinicvoice

Local-first medical voice intake with PHI redaction, speaker diarization, and Nightingale-ready transcript provenance.

## What it does

clinicvoice ingests phone-quality audio from a clinic — either a single-mic
hallway capture or a multi-speaker consult — and produces a redacted,
structured transcript with per-segment speaker, language, and confidence
attribution. PHI never leaves the device by default: Whisper, pyannote 3.1,
and the asteroid ConvTasNet separator all run locally, and every transcript
passes through a Presidio-backed redaction boundary before any DB write,
log line, or API response. The output is purpose-built for downstream
summarization systems like Nightingale: structured segments, stable speaker
IDs, escalation events, and a verifiable redaction map.

## Setup

1. Install Python 3.11 or newer.
2. Install ffmpeg (required by `librosa` / `pydub`).
   - macOS: `brew install ffmpeg`
   - Debian/Ubuntu: `sudo apt install ffmpeg`
3. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m spacy download en_core_web_sm
```

4. (Optional) export `PYANNOTE_HF_TOKEN` to enable real pyannote diarization
   instead of the energy-based fallback.
5. (Optional) create a `.env` from the defaults in `src/config.py` if you
   want to override any settings (DB path, retention TTL, lexicon paths, etc.).

## Running the server

```bash
uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload
```

The API is bound to `localhost` only. CORS is open to the local Vite dev
server so the demo app at `http://localhost:5173` can talk to it.

## Running tests

```bash
# all tests
pytest tests/ -v

# the 4 required tests
pytest tests/test_redaction.py tests/test_segmentation_schema.py \
       tests/test_metrics_report.py tests/test_access_boundary.py -v

# bonus + additional
pytest tests/test_corrections_improve.py tests/test_escalation.py \
       tests/test_source_separation.py -v

# with coverage
pytest tests/ --cov=src --cov-report=term-missing
```

## Where redaction happens

- **File:** `src/redact/engine.py`
- **Function:** `redact(text: str, language: str) -> RedactionResult`
- **Contract:** the input string is the only place raw PHI exists; the
  function returns `RedactionResult(redacted_text, redaction_map, ...)`. The
  raw string is never persisted, never logged, and never accepted by
  `src.redact.boundary.send_to_model()`.
- **Coverage:**
  - English: Presidio NER (`en_core_web_sm`) + all custom patterns
    (phone, MRN, NRIC, MY-IC, IN-Phone, PK-CNIC, Aadhaar, NIK, DOB).
  - Hindi / Urdu / Tamil / Indonesian / Malay: pattern-only recognizers
    (phone, ID, DOB). Non-English NER for names is a documented limitation.

## What data leaves the device

Nothing, by default. Whisper, pyannote, ConvTasNet, noisereduce, Silero
VAD, and Presidio all run locally. Cloud ASR is gated behind two
explicit flags in `src/config.py`:

```python
USE_CLOUD_ASR = True          # opt-in
CLOUD_REDACT_FIRST = True     # redact before any network call
```

When `USE_CLOUD_ASR=True`, the cloud transport is only reachable through
`src.redact.boundary.send_to_model(...)`, which rejects any input that has
not been marked redacted.

## Retention policy

| Data                       | TTL                         | Notes                                  |
| -------------------------- | --------------------------- | -------------------------------------- |
| Raw audio file (uploaded)  | 24 h, configurable to 0     | Purged by background TTL task          |
| Raw transcript text        | Process memory only         | Never written to disk or DB            |
| Redacted transcript        | Indefinite                  | `transcript_span.redacted_text`        |
| Redaction map              | Indefinite                  | `transcript_span.redaction_map` (JSON) |
| Metrics report             | Indefinite                  | `data/reports/*.json`                  |
| Application logs           | PHI-free forever            | Method, path, status, duration, req-id |

## Track separation (Option A / Option B)

clinicvoice always attempts **Option A** first: asteroid ConvTasNet
(`JorisCos/ConvTasNet_Libri2Mix_sepclean_16k`) splits the mixed audio into
per-speaker stems. The mean SI-SDR of those stems is compared to
`SEPARATION_SI_SDR_THRESHOLD` (default 5 dB):

- **SI-SDR ≥ 5 dB → `option_a_stems`**: each stem is decoded individually
  by Whisper, aligned to pyannote turns by RMS energy dominance. Higher
  fidelity in overlapping speech.
- **SI-SDR < 5 dB → `option_b_single`**: the separator's output is rejected
  and Whisper transcribes the original mixed audio. Diarization still
  partitions speakers.

The chosen mode and the SI-SDR value are stored on `recording.track_mode`
and `recording.si_sdr`. No config flag selects between them — the gate is
data-driven.

## Running the demo app

```bash
cd demo_app
npm install
npm run dev
```

The Vite app starts on `http://localhost:5173` and talks to
`http://localhost:8000`. It includes a MediaRecorder capture surface, a
transcript viewer with speaker colors and confidence badges, a before/after
metrics chart for the corrections loop, an escalation panel, a speaker
timeline, and an Option A/B track-mode indicator.

## Running the benchmark

```bash
python scripts/benchmark.py
```

The benchmark runs a 3-pass measurement (Option A only, Option B only,
hybrid with the SI-SDR gate) over the synthetic fixtures in `tests/data/`
and writes `data/reports/benchmark_results.json`. The latest report is also
exposed at `GET /api/benchmark`.

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full pipeline
diagram, schema ERD, language coverage matrix, and Nightingale alignment
notes. See [`docs/schema_erd.md`](docs/schema_erd.md) for the table-level
ERD and [`docs/nightingale_alignment.md`](docs/nightingale_alignment.md)
for the 10 integration points that earn the bonus.

## Demo scenarios

- **A — Hallway capture.** Single-mic, ambient hallway noise, one provider
  dictating a brief patient note. Exercises the noisereduce path
  (`scenario="hallway"`), VAD trimming, and the `handoff_note` escalation
  branch. Synthetic source: `tests/data/synthetic_hallway.wav`.
- **B — Medical stress test.** Two-speaker consult, dense medical
  terminology, dosages, and a mid-conversation language switch (EN → HI).
  Exercises lexicon-biased decoding, the 4-stage text normalization, and
  per-segment language detection. Synthetic source:
  `tests/data/synthetic_consult.wav`.
- **C — Four-speaker overlap.** Provider, patient, family member, and a
  background voice with two overlap regions. Exercises Option A
  separation, the SI-SDR gate, and the overlap-driven confidence
  degradation (`overlap_flag=1` → `confidence` capped at `med`).
