"""Whisper ASR engine — stem-aligned per-turn decoding.

The engine is a process-wide singleton. Heavy imports (``whisper``,
``librosa``) are deferred until ``__init__`` so importing this module does
not download a model. Tests can monkeypatch ``_model`` directly without
touching the network.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from src.asr.language import detect_language
from src.asr.lexicon import MedicalLexicon
from src.asr.schemas import ASRSegment, LanguageTag

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from src.diarize.schemas import DiarizationResult, SpeakerTurn
    from src.ingest.schemas import NormalizedAudio

logger = logging.getLogger(__name__)


class WhisperEngine:
    """Singleton wrapper around the local Whisper model."""

    _instance: Optional["WhisperEngine"] = None

    def __init__(self, settings) -> None:
        # Heavy imports kept inside __init__ so the module is import-safe.
        import whisper  # type: ignore

        self._settings = settings
        self._model = whisper.load_model(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
        )
        logger.info(
            "whisper_loaded",
            extra={"model": settings.WHISPER_MODEL, "device": settings.WHISPER_DEVICE},
        )

    # ------------------------------------------------------------------ #
    # Singleton accessor
    # ------------------------------------------------------------------ #
    @classmethod
    def get_instance(cls, settings) -> "WhisperEngine":
        if cls._instance is None:
            cls._instance = cls(settings)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Test hook — drop the singleton so a new model can be loaded."""

        cls._instance = None

    # ------------------------------------------------------------------ #
    # Per-turn decode
    # ------------------------------------------------------------------ #
    def transcribe_turn(
        self,
        normalized_audio: "NormalizedAudio",
        turn: "SpeakerTurn",
        lexicon: MedicalLexicon,
        recording_id: str,
    ) -> ASRSegment:
        """Decode a single diarized turn, optionally from a separated stem."""

        import librosa  # type: ignore

        # Pick stem (Option A) when available; otherwise the full audio.
        stem_path = getattr(turn, "stem_path", None)
        if stem_path is not None and getattr(stem_path, "exists", lambda: False)():
            audio_source = stem_path
            stem_used = True
        else:
            audio_source = normalized_audio.path
            stem_used = False

        duration = float(turn.end_ts - turn.start_ts)
        if duration < 0.3:
            # Too short to bother with Whisper — emit a low-confidence stub.
            return ASRSegment(
                recording_id=recording_id,
                speaker_id=turn.speaker_id,
                start_ts=float(turn.start_ts),
                end_ts=float(turn.end_ts),
                raw_text="",
                language_tag=LanguageTag.UNKNOWN,
                whisper_avg_logprob=-1.0,
                no_speech_prob=1.0,
                confidence="low",
                stem_used=stem_used,
            )

        segment_audio, _sr = librosa.load(
            str(audio_source),
            sr=16000,
            offset=float(turn.start_ts),
            duration=duration,
            mono=True,
        )

        result = self._model.transcribe(
            segment_audio,
            language=None,  # auto-detect
            initial_prompt=lexicon.build_initial_prompt(),
            word_timestamps=True,
            task="transcribe",
        )

        raw_text = (result.get("text") or "").strip()
        segments = result.get("segments") or []
        avg_logprob = float(segments[0].get("avg_logprob", -1.0)) if segments else -1.0
        no_speech_prob = float(segments[0].get("no_speech_prob", 1.0)) if segments else 1.0
        whisper_lang = result.get("language")
        lang_prob = float(result.get("language_probability", 0.0) or 0.0)

        language_tag = detect_language(raw_text, whisper_lang, lang_prob)

        return ASRSegment(
            recording_id=recording_id,
            speaker_id=turn.speaker_id,
            start_ts=float(turn.start_ts),
            end_ts=float(turn.end_ts),
            raw_text=raw_text,  # EPHEMERAL — never log this variable
            language_tag=language_tag,
            whisper_avg_logprob=avg_logprob,
            no_speech_prob=no_speech_prob,
            confidence="high",  # overridden by normalize/confidence.py
            stem_used=stem_used,
        )

    # ------------------------------------------------------------------ #
    # Full-recording decode
    # ------------------------------------------------------------------ #
    async def transcribe_recording(
        self,
        normalized_audio: "NormalizedAudio",
        diarization: "DiarizationResult",
        lexicon: MedicalLexicon,
        recording_id: str,
    ) -> List[ASRSegment]:
        """Decode every speaker turn for a recording.

        Whisper is not thread-safe, so turns are decoded sequentially.
        Overlap-merged turns (``speaker_id == "OVERLAP"``) are skipped — they
        are handled separately by the diarize overlap module.
        """

        segments: List[ASRSegment] = []
        for turn in diarization.turns:
            if getattr(turn, "speaker_id", None) == "OVERLAP":
                continue
            seg = self.transcribe_turn(normalized_audio, turn, lexicon, recording_id)
            segments.append(seg)
        return segments
