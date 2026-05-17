# clinicvoice — Build Log

Started: 2026-05-17

## Parallel Orchestration

This build is executed by 8 agents working in parallel. Each agent owns a disjoint slice of the codebase and commits independently. ETA is the documentation subagent and only writes to this file.

| Agent | Owns | Key deliverable |
|-------|------|----------------|
| **ALPHA** | `src/config.py`, `src/db/`, `src/main.py`, `pyproject.toml` | ORM (5 tables), FastAPI skeleton, retention task |
| **BETA** | `src/ingest/`, `src/diarize/` | normalizer+noisereduce, separator (Option A+SI-SDR), pyannote, overlap |
| **GAMMA** | `src/asr/`, `src/normalize/` | Whisper stem-aligned decode, lexicon biasing, language detection, 4-stage norm |
| **DELTA** | `src/redact/`, `src/escalation/` | Presidio+patterns, boundary enforcement, EscalationEngine, watchlist |
| **EPSILON** | `src/metrics/`, `tests/`, `scripts/` | WER/MTER/DER/SI-SDR, all 7 tests, 3-pass benchmark with real numbers |
| **ZETA** | `src/api/`, `README.md`, `ATTRIBUTION.txt`, `docs/` | All 8 routes, PHI-free middleware, technical brief |
| **THETA** | `demo_app/` | Vite+vanilla JS: recorder, transcript viewer, before/after chart, escalation panel, speaker timeline |
| **ETA** | `BUILD_LOG.md` | Creates from scratch, appends live — decisions, test outputs, errors, benchmarks |

Subsequent entries will be added by post-build integration since the parallel agents cannot be observed in real time from this process.

---

## [2026-05-17T00:00:00Z] INIT | ETA | BUILD_LOG.md — log initialized

**Agent:** ETA
**File:** `@clinicvoice/BUILD_LOG.md`

Created the build log at the start of the parallel 8-agent orchestration. This file is the single source of truth for decisions, errors, test outputs, and benchmark numbers across the build. ETA holds exclusive write access; no other agent touches this file.

Alternatives considered: a per-agent log directory (rejected — fragments narrative and complicates review) and inline commit-message-only history (rejected — too sparse for design decisions and benchmark tables).

---
