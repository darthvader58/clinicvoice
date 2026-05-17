# clinicvoice — Nightingale Alignment

Ten integration points where clinicvoice's structured output drops
cleanly into a Nightingale-style summarization + memory + alerting
system. Each point references the exact ORM model and module that
makes the alignment work.

## 1. Structured ground truth, not prose

**Artifact:** `TranscriptSpan[]` joined to `Segment[]` (see
`src/db/models.py`).

The transcript surface is already JSON — every segment has stable IDs,
speaker label, time bounds, language, confidence, and a redacted text
payload. Nightingale's summarization layer can ingest the JSON directly
without re-parsing prose; there is no "raw transcript blob" anywhere in
the data model.

## 2. Memory writes are pre-classified

**Artifact:** `EscalationEvent(event_type="memory_candidate")` produced
by `src/escalation/engine.py`.

Whenever a provider utters an instruction-class phrase ("follow up in
two weeks", "schedule a CBC", "remind me to…") at non-low confidence,
the engine emits a `memory_candidate`. Nightingale's memory writer
consumes these rows directly — no second classifier required.

## 3. Real-time alerting hook

**Artifact:** `EscalationEvent(event_type="escalation_high")`.

High-acuity watchlist terms (chest pain, anaphylaxis, suicidal ideation,
…) at high/med confidence trigger an `escalation_high` event. The event
fires the moment the segment is persisted, which makes it suitable for
a Nightingale push-alert pipeline driven by DB triggers or a CDC stream.

## 4. Shift-transition log from hallway captures

**Artifact:** `EscalationEvent(event_type="handoff_note")`.

When `scenario="hallway"` and the segment contains handoff terms ("the
patient in room 12", "give report to", "I'm handing off"), the engine
emits a `handoff_note`. Nightingale uses these to auto-populate the
shift-change log so providers don't have to re-type what they just said.

## 5. Low-confidence gating protects memory quality

**Artifact:** `segment.confidence == "low"` (CLAUDE.md hard rule).

Escalation engine refuses to create any event on a low-confidence
segment, full stop. Those segments are still surfaced (with the badge)
for clinician review, so Nightingale never writes a memory or fires an
alert based on a noisy transcription error.

## 6. Stable per-recording speaker attribution

**Artifact:** `segment.speaker_id` (`S1`, `S2`, …) — consistent across
all turns within a recording.

pyannote produces canonical labels; the separator's stem alignment
preserves them. Nightingale can attribute "the provider said X" vs
"the patient said Y" without speaker re-identification on its side.

## 7. Auditable redaction proof

**Artifact:** `transcript_span.redaction_map` — JSON of
`RedactionSpan[]` with type / offset / replacement.

The redaction map proves which entities were redacted, where, and with
what marker — without ever storing the original value. Nightingale (and
its auditors) can verify that the LLM only ever saw redacted input.

## 8. Correction loop improves downstream input

**Artifact:** `POST /api/corrections/{recording_id}` →
`MedicalLexicon` update → MTER recompute.

Providers can correct misheard terms in the demo UI; the lexicon update
biases the Whisper `initial_prompt` and the recomputed MTER drops
measurably (verified by `tests/test_corrections_improve.py`).
Nightingale benefits from monotonically improving medical-term accuracy
at zero LLM-side cost.

## 9. Per-recording quality signal

**Artifact:** `MetricsRun` (`wer`, `medical_ter`, `der_proxy`, `si_sdr`).

Each recording carries a structured quality scorecard. Nightingale can
gate memory writes on WER / MTER thresholds — e.g., "don't write to
patient memory if MTER > 0.2" — which is cheap to implement on top of
the existing schema.

## 10. End-to-end provenance

**Artifact:** the FK chain `metrics_run.recording_id` →
`recording.id` → `segment.recording_id` → `segment.start_ts` /
`segment.end_ts`.

Any summary sentence Nightingale produces can be traced back to a
specific `recording_id`, then to the originating `segment_id`, and from
there to the exact audio window via `start_ts` / `end_ts`. Combined
with the redaction map, this means every assertion in a Nightingale
summary has a verifiable, PHI-stripped audit trail.
