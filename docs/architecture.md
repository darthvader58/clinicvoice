# clinicvoice — Architecture

A 2–3 page technical brief covering the full pipeline, schema,
track-separation strategy, language coverage, tuning evidence, and the
Nightingale integration path.

## 1. Pipeline

clinicvoice is a strictly local pipeline. Audio enters at `POST
/api/upload`, every model runs on `WHISPER_DEVICE` (CPU by default), and
the only network egress permitted is gated by `USE_CLOUD_ASR` and
`CLOUD_REDACT_FIRST`.

```
Phone audio (MediaRecorder / upload) → localhost:8000 only
  → ingest: ffmpeg WAV 16kHz mono → noisereduce (hallway) → silero-VAD
  → separator: asteroid ConvTasNet → stems (SI-SDR ≥ 5dB = Option A, else Option B)
  → diarize: pyannote 3.1 on original audio → turns → align stems to turns
  → asr: Whisper per stem window, initial_prompt=medical lexicon, word_timestamps=True
  → normalize: acronym expand → unit norm → casing → confidence  [EN only except confidence]
  ⚠ REDACTION BOUNDARY ⚠
  → redact(text, language) → (redacted_text, redaction_map)   [raw_text dies here]
  → escalation: scan redacted_text vs watchlist → EscalationEvent/MemoryCandidate/HandoffNote
  → metrics: WER, MTER, DER-proxy, SI-SDR → MetricsRun
  → db: persist (no raw_text anywhere) → API response (redacted only)
```

The pipeline is implemented in `src/api/routes.py::_run_pipeline`, called
as a FastAPI `BackgroundTask` from `POST /api/upload` so the HTTP request
returns within tens of milliseconds.

## 2. Schema (overview)

Six SQLAlchemy 2.0 ORM tables, all defined in `src/db/models.py`.
**There is no `raw_text` column anywhere.** Full ERD lives in
[`schema_erd.md`](schema_erd.md); the relationships are:

```
Recording (1) ──< (N) AudioAsset
Recording (1) ──< (N) Segment ──< (N) TranscriptSpan
Recording (1) ──< (N) EscalationEvent >── (N) Segment
Recording (1) ──< (N) MetricsRun
```

Hard invariants enforced by the codebase:

1. `TranscriptSpan.raw_text` does not exist (verified by
   `tests/test_segmentation_schema.py`).
2. `Recording.track_mode` is one of `option_a_stems`, `option_b_single`, or
   `NULL` (still processing). It is written exactly once by the pipeline
   after the SI-SDR gate decides.
3. `EscalationEvent.watchlist_term` is the term from `watchlist.json`, not
   any patient utterance — so the table can never leak PHI.

## 3. Track Option A — asteroid ConvTasNet + SI-SDR gate

Option A is **always attempted first**. The implementation lives in
`src/ingest/separator.py`. Pseudo-code:

```python
mixture = load_normalized(path, sr=16000)
estimates = ConvTasNet.from_pretrained(
    "JorisCos/ConvTasNet_Libri2Mix_sepclean_16k"
).separate(mixture)            # → 2 stems

si_sdr = compute_si_sdr(estimates, mixture)     # torchmetrics
if si_sdr >= SEPARATION_SI_SDR_THRESHOLD:        # default 5 dB
    track_mode = "option_a_stems"
    stems_to_pyannote_turns = align_by_rms(estimates, turns)
else:
    track_mode = "option_b_single"               # discard stems
```

The SI-SDR gate is the only thing that picks between Option A and Option
B — there is no config flag. Discarding stems below 5 dB is what keeps
WER from regressing on clean single-speaker recordings where the
separator's hallucinated second source would otherwise pollute Whisper's
output. The chosen mode and SI-SDR value are written to
`recording.track_mode` and `recording.si_sdr`, and exposed via
`GET /api/status/{id}`.

### Stem-to-speaker alignment

For each pyannote turn `[start, end]`, the stem with the highest RMS
energy in that window is assigned as the dominant speaker. This mapping
is the only thing that gives stems stable speaker IDs (`S1`, `S2`, …)
across the whole recording — pyannote owns the canonical speaker labels;
the separator only contributes per-window source isolation.

## 4. Tuning evidence

Concrete numbers come from `scripts/benchmark.py`, which runs three
passes over the synthetic fixtures and writes
`data/reports/benchmark_results.json`. The benchmark report contains a
table of the form:

| Pass            | Track mode        | WER ↓ | MTER ↓ | DER-proxy ↓ | SI-SDR ↑ |
| --------------- | ----------------- | ----- | ------ | ----------- | -------- |
| baseline        | `option_b_single` |  …    |  …     |  …          |  —       |
| separator-only  | `option_a_stems`  |  …    |  …     |  …          |  …       |
| hybrid (gated)  | data-driven       |  …    |  …     |  …          |  …       |

The hybrid pass is what production uses: `option_a_stems` for tight
2-speaker captures where ConvTasNet earns its keep, `option_b_single` for
hallway-style single-speaker captures where the separator hurts more
than it helps.

## 5. Language coverage matrix

| Language     | BCP-47 | Whisper ASR | Lexicon prompt | Text normalization | Redaction (NER) | Redaction (patterns) |
| ------------ | ------ | ----------- | -------------- | ------------------ | --------------- | -------------------- |
| English      | `en`   | yes         | yes            | yes (4-stage)      | yes (`en_core_web_sm`) | yes (all)     |
| Hindi        | `hi`   | yes         | yes            | confidence only    | no              | phone / ID / DOB     |
| Urdu         | `ur`   | yes         | yes            | confidence only    | no              | phone / ID / DOB     |
| Tamil        | `ta`   | yes         | yes            | confidence only    | no              | phone / ID / DOB     |
| Indonesian   | `id`   | yes         | yes            | confidence only    | no              | phone / NIK / DOB    |
| Malay        | `ms`   | yes         | yes            | confidence only    | no              | phone / IC / DOB     |

Per-segment language detection (`src/asr/language.py`) combines Whisper's
own detector with `langdetect` as a sanity check. Text normalization is
intentionally English-only because acronym expansion, dosage unit norm,
and casing rules are deeply language-specific; widening that surface for
non-English would do more harm than good without a per-language tuning
budget.

## 6. Assumptions and trade-offs

- **CPU-only by default.** `WHISPER_DEVICE=cpu` keeps the demo runnable
  on a laptop. GPU users can flip to `cuda`.
- **`large-v3-turbo`.** Best per-second quality for the CPU latency
  budget; `medium` would be ~2× faster at a noticeable WER cost.
- **Energy-based diarization fallback.** When `PYANNOTE_HF_TOKEN` is
  absent, we fall back to RMS-energy speaker tracking. The fallback is
  intentionally simple (lower DER) so that demo runs aren't blocked on
  HuggingFace credentials.
- **Non-English NER for names is a known gap.** Pattern recognizers
  cover phone / national-ID / DOB across all six languages, but person
  names in HI/UR/TA/ID/MS are not redacted by NER. This is
  documented and reported on the `/api/health`-adjacent health surface
  via a logged warning.
- **Retention defaults to 24h.** `AUDIO_RETENTION_TTL_S=86400`. Set to
  `0` to retain audio indefinitely (transcripts are unaffected).
- **Confidence "low" gates escalation.** A noisy signal can produce a
  watchlist match through transcription error; gating low-confidence
  segments from `EscalationEvent` creation avoids spurious clinician
  alerts. The segment is still stored and visible.

## 7. PHI boundary — non-negotiable

Three things make the boundary load-bearing:

1. `redact()` is called before **every** DB write, log line, or API
   response that touches transcript content. There is no path through
   `src/api/routes.py` that emits raw transcript text.
2. `src/redact/boundary.py::send_to_model()` raises
   `RedactionBoundaryError` unless its input was produced by
   `mark_as_redacted()` — verified by
   `tests/test_access_boundary.py`.
3. `src/api/middleware.py` logs only `{method, path, status, duration_ms,
   request_id}`. Bodies, query strings, and header values never enter
   the log stream.

## 8. Nightingale integration path

See [`nightingale_alignment.md`](nightingale_alignment.md) for the
full 10-point alignment. The short version: every artifact this system
produces — `TranscriptSpan`, `Segment`, `MemoryCandidate`,
`EscalationEvent`, `HandoffNote`, `MetricsRun` — is structured JSON with
stable IDs, confidence labels, and a redaction map, so Nightingale can
ingest it directly without re-deriving structure from prose.
