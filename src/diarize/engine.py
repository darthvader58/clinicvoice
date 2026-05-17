from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, List, Optional

from src.diarize.overlap import detect_overlaps
from src.diarize.schemas import DiarizationResult, SpeakerTurn
from src.ingest.schemas import SeparationResult
from src.ingest.separator import align_stems_to_speakers

logger = logging.getLogger("clinicvoice.diarize.engine")


class DiarizationEngine:
    """Singleton-style pyannote 3.1 wrapper with an HF-token-free fallback.

    Always diarizes on the original/normalized audio (not stems) so the
    resulting turn timestamps remain accurate. After diarization, if
    Option A separation succeeded, stems are aligned to turns by RMS energy.
    """

    _instance: Optional["DiarizationEngine"] = None

    def __init__(self) -> None:
        self._pipeline: Any = None
        self._pipeline_loaded: bool = False
        self._load_attempted: bool = False

    @classmethod
    def instance(cls) -> "DiarizationEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Pipeline lifecycle
    # ------------------------------------------------------------------
    def _load_pipeline(self, settings: Any) -> None:
        if self._load_attempted:
            return
        self._load_attempted = True

        hf_token = getattr(settings, "PYANNOTE_HF_TOKEN", None)
        model_name = getattr(
            settings, "PYANNOTE_MODEL", "pyannote/speaker-diarization-3.1"
        )

        if not hf_token:
            logger.warning(
                "pyannote_token_missing_using_fallback",
                extra={"model": model_name},
            )
            self._pipeline = None
            return

        try:
            from pyannote.audio import Pipeline

            self._pipeline = Pipeline.from_pretrained(
                model_name,
                use_auth_token=hf_token,
            )
            self._pipeline_loaded = True
            logger.info("pyannote_loaded", extra={"model": model_name})
        except Exception as exc:
            logger.warning(
                "pyannote_load_failed_using_fallback",
                extra={"error_type": type(exc).__name__},
            )
            self._pipeline = None

    # ------------------------------------------------------------------
    # Public sync API
    # ------------------------------------------------------------------
    def diarize(
        self,
        audio_path: Path,
        separation: SeparationResult,
        max_speakers: int,
        settings: Any,
        recording_id: str = "",
    ) -> DiarizationResult:
        self._load_pipeline(settings)

        if self._pipeline is not None:
            try:
                turns = self._run_pyannote(audio_path, max_speakers)
                method: str = "pyannote"
            except Exception as exc:
                logger.warning(
                    "pyannote_inference_failed_falling_back",
                    extra={"error_type": type(exc).__name__},
                )
                turns = self._energy_fallback(audio_path, max_speakers)
                method = "energy_fallback"
        else:
            turns = self._energy_fallback(audio_path, max_speakers)
            method = "energy_fallback" if turns and len({t.speaker_id for t in turns}) > 1 else "single_speaker"
            if not turns:
                method = "single_speaker"

        # If Option A succeeded, align stems to speakers
        if separation.track_mode == "option_a_stems" and separation.stems and turns:
            try:
                stem_assignment = align_stems_to_speakers(separation.stems, turns)
                for idx, turn in enumerate(turns):
                    stem_path = stem_assignment.get(turn.speaker_id)
                    if stem_path is not None:
                        turns[idx] = turn.model_copy(update={"stem_path": stem_path})
            except Exception as exc:
                logger.warning(
                    "stem_alignment_failed",
                    extra={"error_type": type(exc).__name__},
                )

        turns = detect_overlaps(turns)

        speaker_ids = {t.speaker_id for t in turns if t.speaker_id != "OVERLAP"}
        total_overlap_s = sum(
            float(t.end_ts) - float(t.start_ts) for t in turns if t.overlap
        )

        logger.info(
            "diarization_complete",
            extra={
                "method": method,
                "speaker_count": len(speaker_ids),
                "turn_count": len(turns),
                "total_overlap_s": round(total_overlap_s, 3),
                "track_mode": separation.track_mode,
            },
        )

        return DiarizationResult(
            recording_id=recording_id,
            turns=turns,
            speaker_count=len(speaker_ids),
            total_overlap_s=total_overlap_s,
            method=method,  # type: ignore[arg-type]
            track_mode=separation.track_mode,
        )

    # ------------------------------------------------------------------
    # pyannote 3.1 path
    # ------------------------------------------------------------------
    def _run_pyannote(self, audio_path: Path, max_speakers: int) -> List[SpeakerTurn]:
        diarization = self._pipeline(str(audio_path), num_speakers=None,
                                     min_speakers=1, max_speakers=int(max_speakers))
        turns: List[SpeakerTurn] = []
        speaker_map: dict = {}
        for segment, _, speaker in diarization.itertracks(yield_label=True):
            if speaker not in speaker_map:
                speaker_map[speaker] = f"S{len(speaker_map) + 1}"
            start = float(segment.start)
            end = float(segment.end)
            if end <= start:
                continue
            turns.append(
                SpeakerTurn(
                    speaker_id=speaker_map[speaker],
                    start_ts=start,
                    end_ts=end,
                )
            )
        return turns

    # ------------------------------------------------------------------
    # Energy / MFCC + KMeans fallback
    # ------------------------------------------------------------------
    def _energy_fallback(
        self, audio_path: Path, max_speakers: int
    ) -> List[SpeakerTurn]:
        """VAD → MFCC centroids per segment → KMeans clustering.

        Returns turns with confidence='med' max. Falls back to a single
        speaker turn if sklearn or librosa are unavailable, or if VAD
        returns no segments.
        """
        try:
            import librosa
            import numpy as np
        except Exception as exc:
            logger.warning(
                "fallback_librosa_missing",
                extra={"error_type": type(exc).__name__},
            )
            return self._single_speaker_turn(audio_path)

        try:
            audio, sr = librosa.load(str(audio_path), sr=16000, mono=True)
        except Exception as exc:
            logger.warning(
                "fallback_load_failed",
                extra={"error_type": type(exc).__name__},
            )
            return []

        if audio.size == 0:
            return []

        duration_s = float(len(audio)) / float(sr)

        # Re-use silero-VAD via the normalizer helper for consistency
        try:
            from src.ingest.normalizer import _run_silero_vad  # type: ignore

            segments = _run_silero_vad(audio, sr)
        except Exception:
            segments = []

        if not segments:
            # Fallback: chunk audio every 2.0 s
            segments = [
                (float(t), float(min(t + 2.0, duration_s)))
                for t in np.arange(0.0, duration_s, 2.0)
            ]
            segments = [s for s in segments if s[1] - s[0] > 0.25]

        if not segments:
            return self._single_speaker_turn(audio_path)

        # Compute MFCC centroid for each segment
        centroids: List["np.ndarray"] = []
        valid_segments: List[tuple] = []
        for start_s, end_s in segments:
            start_i = int(start_s * sr)
            end_i = int(end_s * sr)
            chunk = audio[start_i:end_i]
            if chunk.size < int(0.1 * sr):
                continue
            try:
                mfcc = librosa.feature.mfcc(y=chunk, sr=sr, n_mfcc=13)
                centroids.append(mfcc.mean(axis=1))
                valid_segments.append((start_s, end_s))
            except Exception:
                continue

        if not centroids:
            return self._single_speaker_turn(audio_path)

        # Cluster with sklearn KMeans if available
        try:
            from sklearn.cluster import KMeans
        except Exception as exc:
            logger.warning(
                "fallback_sklearn_missing_single_speaker",
                extra={"error_type": type(exc).__name__},
            )
            return [
                SpeakerTurn(
                    speaker_id="S1",
                    start_ts=float(s),
                    end_ts=float(e),
                    confidence="med",
                )
                for s, e in valid_segments
            ]

        import numpy as np

        feat = np.stack(centroids, axis=0)
        n_clusters = min(2, int(max_speakers), feat.shape[0])
        n_clusters = max(1, n_clusters)

        if n_clusters == 1:
            labels = [0] * feat.shape[0]
        else:
            try:
                km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
                labels = km.fit_predict(feat).tolist()
            except Exception as exc:
                logger.warning(
                    "fallback_kmeans_failed",
                    extra={"error_type": type(exc).__name__},
                )
                labels = [0] * feat.shape[0]

        # Map cluster indices to stable S1/S2 in order of first appearance
        label_to_speaker: dict = {}
        turns: List[SpeakerTurn] = []
        for (start_s, end_s), lbl in zip(valid_segments, labels):
            key = int(lbl)
            if key not in label_to_speaker:
                label_to_speaker[key] = f"S{len(label_to_speaker) + 1}"
            turns.append(
                SpeakerTurn(
                    speaker_id=label_to_speaker[key],
                    start_ts=float(start_s),
                    end_ts=float(end_s),
                    confidence="med",
                )
            )
        return turns

    def _single_speaker_turn(self, audio_path: Path) -> List[SpeakerTurn]:
        try:
            import librosa

            duration_s = float(librosa.get_duration(path=str(audio_path)))
        except Exception:
            return []
        if duration_s <= 0:
            return []
        return [
            SpeakerTurn(
                speaker_id="S1",
                start_ts=0.0,
                end_ts=duration_s,
                confidence="med",
            )
        ]


async def diarize_audio(
    audio_path: Path,
    separation: SeparationResult,
    max_speakers: int,
    settings: Any,
    recording_id: str = "",
) -> DiarizationResult:
    """Async wrapper that runs diarization in a worker thread."""
    engine = DiarizationEngine.instance()
    return await asyncio.to_thread(
        engine.diarize, audio_path, separation, max_speakers, settings, recording_id
    )
