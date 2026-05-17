# clinicvoice — Schema ERD

Six tables, no PHI in any column, no `raw_text` anywhere. Implemented in
`src/db/models.py` with SQLAlchemy 2.0 declarative mappings; persisted
via async SQLite (`aiosqlite`) by default.

## Entity diagram

```
                  ┌─────────────────────────┐
                  │       recording         │
                  │─────────────────────────│
                  │ id          PK  TEXT    │
                  │ created_at      TEXT    │
                  │ file_hash       TEXT    │  ← SHA-256 of source bytes
                  │ duration_s      REAL    │
                  │ scenario        TEXT    │  ← hallway | consult
                  │ track_mode      TEXT    │  ← option_a_stems | option_b_single
                  │ si_sdr          REAL    │
                  │ speaker_count   INT     │
                  │ retention_ttl   INT     │  ← seconds; default 86400
                  │ purged_at       TEXT    │
                  └─────┬─────────┬─────┬───┘
                        │1        │1    │1
              ┌─────────┘         │     └────────────────┐
              │1..N               │1..N                  │1..N
              ▼                   ▼                      ▼
   ┌──────────────────┐  ┌────────────────────┐  ┌────────────────────┐
   │   audio_asset    │  │     segment        │  │    metrics_run     │
   │──────────────────│  │────────────────────│  │────────────────────│
   │ id        PK     │  │ id          PK     │  │ id           PK    │
   │ recording_id FK──┘  │ recording_id FK ───┘  │ recording_id FK ───┘
   │ file_path        │  │ speaker_id         │  │ wer                │
   │ asset_type       │  │ start_ts           │  │ medical_ter        │
   │ speaker_id       │  │ end_ts             │  │ der_proxy          │
   │ format           │  │ confidence         │  │ si_sdr             │
   │ sample_rate      │  │ language_tag       │  │ speaker_count      │
   │ channels         │  │ overlap_flag  INT  │  │ segment_count      │
   └──────────────────┘  │ stem_used     INT  │  │ track_mode         │
                         └────────┬───┬───────┘  │ run_at             │
                                  │1  │1..N      │ report_path        │
                                  │   ▼          └────────────────────┘
                                  │  ┌────────────────────────────────┐
                                  │  │       transcript_span          │
                                  │  │────────────────────────────────│
                                  │  │ id              PK             │
                                  │  │ segment_id      FK ───────┐    │
                                  │  │ -- NO raw_text column --  │    │
                                  │  │ redacted_text   TEXT      │    │
                                  │  │ redaction_map   TEXT JSON │    │
                                  │  │ word_count      INT       │    │
                                  │  │ char_count      INT       │    │
                                  │  └───────────────────────────┘    │
                                  │                                   │
                                  │1..N                               │
                                  ▼                                   │
                         ┌──────────────────────────┐                 │
                         │    escalation_event      │                 │
                         │──────────────────────────│                 │
                         │ id            PK         │                 │
                         │ recording_id  FK ────────┼─────────────────┘
                         │ segment_id    FK ────────┘
                         │ triggered_at  TEXT       │
                         │ event_type    TEXT       │  ← escalation_high | escalation_medium
                         │ watchlist_term TEXT      │    | memory_candidate | handoff_note
                         │ speaker_id    TEXT       │
                         │ confidence    TEXT       │  ← never fires on 'low'
                         │ resolved      INT        │
                         └──────────────────────────┘
```

## Cardinalities and lifecycle

| Relation                                           | Cardinality | Notes                                  |
| -------------------------------------------------- | ----------- | -------------------------------------- |
| `recording`            → `audio_asset`             | 1 : N       | source / normalized / stem(N)          |
| `recording`            → `segment`                 | 1 : N       | one segment per diarized + ASR'd turn  |
| `segment`              → `transcript_span`         | 1 : N       | normally 1; >1 if re-decoded           |
| `recording`            → `escalation_event`        | 1 : N       | zero on healthy recordings             |
| `segment`              → `escalation_event`        | 1 : N       | event always belongs to a segment      |
| `recording`            → `metrics_run`             | 1 : N       | one per benchmark or correction pass   |

## Invariants verified by tests

- `TranscriptSpan` carries `redacted_text` + `redaction_map`, never
  `raw_text` — `tests/test_segmentation_schema.py`.
- `RedactionSpan` carries `start`, `end`, `type`, `replacement`, never
  `original_value` — `tests/test_redaction.py`.
- `EscalationEvent.confidence` is never `'low'` (engine refuses to
  create those) — `tests/test_escalation.py`.
- `send_to_model(raw_text)` raises `RedactionBoundaryError` unless the
  caller used `mark_as_redacted(redacted_text)` —
  `tests/test_access_boundary.py`.

## Indexing

Foreign-key columns (`recording_id`, `segment_id`) are indexed on every
child table. `metrics_run.run_at` is the natural sort key for "latest
metrics" queries used by `GET /api/metrics/{id}`.

## Retention semantics

`recording.retention_ttl` (default 86400 s) drives the audio purge task
in `src/db/retention.py`. The task deletes the `audio_asset` files from
disk, stamps `recording.purged_at`, and leaves transcript and metrics
rows in place — the redacted transcript is the durable artifact.
