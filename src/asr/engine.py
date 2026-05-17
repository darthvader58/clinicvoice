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
        language: str = "auto",
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
        if duration < 1.0:
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

        # Decide the language: explicit user hint > Whisper auto-detect.
        # Feeding an English prompt to non-English audio forces Whisper into
        # English or makes it parrot the prompt, so we only inject the
        # medical lexicon prompt when the language is (or resolves to) English.
        import whisper as _whisper  # type: ignore

        detected_lang: Optional[str] = None
        lang_prob = 1.0  # treat user-forced language as fully confident
        if language and language != "auto":
            detected_lang = language
        else:
            lang_prob = 0.0
            try:
                clip = _whisper.pad_or_trim(segment_audio)
                n_mels = getattr(getattr(self._model, "dims", None), "n_mels", 80)
                mel = _whisper.log_mel_spectrogram(clip, n_mels=n_mels).to(
                    self._model.device
                )
                _, probs = self._model.detect_language(mel)
                detected_lang = max(probs, key=probs.get)
                lang_prob = float(probs[detected_lang])
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "language_detect_failed",
                    extra={"error_type": type(exc).__name__},
                )

        initial_prompt = (
            lexicon.build_initial_prompt()
            if detected_lang == "en" and lang_prob > 0.5
            else None
        )

        result = self._model.transcribe(
            segment_audio,
            language=detected_lang,
            initial_prompt=initial_prompt,
            word_timestamps=True,
            task="transcribe",
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            condition_on_previous_text=False,
            logprob_threshold=-1.0,
        )

        raw_text = (result.get("text") or "").strip()
        segments = result.get("segments") or []
        avg_logprob = float(segments[0].get("avg_logprob", -1.0)) if segments else -1.0
        no_speech_prob = float(segments[0].get("no_speech_prob", 1.0)) if segments else 1.0
        whisper_lang = result.get("language") or detected_lang

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
        language: str = "auto",
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
            seg = self.transcribe_turn(
                normalized_audio, turn, lexicon, recording_id, language=language
            )
            segments.append(seg)
        return segments
