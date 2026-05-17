from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import List, Tuple

from src.ingest.schemas import NormalizedAudio

logger = logging.getLogger("clinicvoice.ingest.normalizer")

_VAD_MODEL = None
_VAD_UTILS = None


def _bandpass_filter(audio, sr: int, low: int = 300, high: int = 3400):
    import numpy as np
    from scipy.signal import butter, sosfiltfilt

    nyq = sr / 2
    high = min(high, int(nyq) - 1)
    sos = butter(5, [low, high], btype="bandpass", fs=sr, output="sos")
    return np.asarray(sosfiltfilt(sos, audio), dtype="float32")


def _loudness_normalize(audio, target_db: float = -20.0):
    import numpy as np

    rms = float(np.sqrt(np.mean(np.square(audio), dtype="float64")))
    if rms <= 1e-9:
        return audio
    target_rms = 10 ** (target_db / 20.0)
    scaled = audio * (target_rms / rms)
    peak = float(np.max(np.abs(scaled))) if scaled.size else 0.0
    if peak > 0.99:
        scaled = scaled * (0.99 / peak)
    return scaled.astype("float32")


def _ensure_vad():
    global _VAD_MODEL, _VAD_UTILS
    if _VAD_MODEL is not None:
        return _VAD_MODEL, _VAD_UTILS
    import torch

    model, utils = torch.hub.load(
        "snakers4/silero-vad",
        "silero_vad",
        trust_repo=True,
    )
    _VAD_MODEL, _VAD_UTILS = model, utils
    return _VAD_MODEL, _VAD_UTILS


def _run_silero_vad(audio, sr: int) -> List[Tuple[float, float]]:
    try:
        import torch

        model, utils = _ensure_vad()
        get_speech_timestamps = utils[0]
        audio_tensor = torch.from_numpy(audio).float()
        timestamps = get_speech_timestamps(audio_tensor, model, sampling_rate=sr)
        return [(float(t["start"]) / sr, float(t["end"]) / sr) for t in timestamps]
    except Exception as exc:
        logger.warning(
            "vad_failed_continuing_without_segments",
            extra={"error_type": type(exc).__name__},
        )
        return []


def _normalize_sync(input_path: Path, scenario: str) -> NormalizedAudio:
    import librosa
    import numpy as np
    import soundfile as sf

    original_bytes = input_path.read_bytes()
    file_hash = hashlib.sha256(original_bytes).hexdigest()

    audio, sr = librosa.load(str(input_path), sr=16000, mono=True)
    audio = np.asarray(audio, dtype="float32")

    noise_reduced = False
    if scenario == "hallway" and audio.size > int(0.5 * sr):
        try:
            import noisereduce as nr

            noise_sample = audio[: int(0.5 * sr)]
            audio = nr.reduce_noise(
                y=audio,
                sr=sr,
                y_noise=noise_sample,
                stationary=False,
                prop_decrease=0.75,
                n_fft=1024,
                win_length=512,
            ).astype("float32")
            audio = _bandpass_filter(audio, sr, low=300, high=3400)
            noise_reduced = True
        except Exception as exc:
            logger.warning(
                "hallway_denoise_failed_continuing_raw",
                extra={"error_type": type(exc).__name__},
            )

    audio = _loudness_normalize(audio, target_db=-20.0)

    norm_path = input_path.parent / f"{input_path.stem}_norm.wav"
    sf.write(str(norm_path), audio, sr, subtype="PCM_16")

    speech_segments = _run_silero_vad(audio, sr)
    duration_s = float(len(audio)) / float(sr) if sr else 0.0

    logger.info(
        "audio_normalized",
        extra={
            "file_hash_prefix": file_hash[:12],
            "sample_rate": sr,
            "duration_s": round(duration_s, 3),
            "noise_reduced": noise_reduced,
            "vad_segment_count": len(speech_segments),
            "scenario": scenario,
        },
    )

    return NormalizedAudio(
        path=norm_path,
        sample_rate=int(sr),
        duration_s=duration_s,
        file_hash=file_hash,
        speech_segments=speech_segments,
        noise_reduced=noise_reduced,
    )


async def normalize_audio(input_path: Path, scenario: str) -> NormalizedAudio:
    return await asyncio.to_thread(_normalize_sync, input_path, scenario)
