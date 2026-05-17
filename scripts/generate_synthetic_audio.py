#!/usr/bin/env python3
"""Generate synthetic test audio for clinicvoice.

Produces tests/data/synthetic_hallway.wav (~15-20s) and
tests/data/synthetic_consult.wav (~30-40s).

Preferred path: gTTS + pydub for real speech.
Fallback (no internet, no gTTS): sine-wave generator using numpy +
soundfile that still emits valid 16 kHz mono WAVs with multiple segments
at different frequencies. Use --use-fallback to force the fallback.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np

SR = 16000
OUT_DIR = Path("tests/data")
HALLWAY_PATH = OUT_DIR / "synthetic_hallway.wav"
CONSULT_PATH = OUT_DIR / "synthetic_consult.wav"


HALLWAY_LINES: List[Tuple[str, float, int]] = [
    # (text, speed_factor, pitch_freq_for_fallback)
    (
        "Dr. Sharma, the patient in room 4 needs the potassium levels checked "
        "before end of shift. She has hypertension and the metoprolol dosage "
        "needs to be reviewed.",
        0.95,
        180,
    ),
    (
        "Got it. Please check the INR as well. Her warfarin needs adjustment.",
        1.05,
        240,
    ),
]

CONSULT_LINES: List[Tuple[str, float, int]] = [
    (
        "The ECG shows tachycardia and signs of atrial fibrillation. "
        "Troponin is elevated at 2.5.",
        1.0,
        180,
    ),
    (
        "I am prescribing metformin 500 mg twice daily for the diabetes "
        "mellitus. Follow up in two weeks.",
        0.95,
        220,
    ),
    (
        "Should we also check the creatinine and eGFR given the CKD history?",
        1.05,
        260,
    ),
    (
        "Yes, and add atorvastatin 40 mg. Check the INR before starting warfarin.",
        1.0,
        200,
    ),
]


# ---------------------------------------------------------------------------
# Fallback synthesizer (numpy + soundfile) — produces valid WAVs without
# touching the network.
# ---------------------------------------------------------------------------


def _tone(freq: float, dur_s: float, sr: int = SR, amp: float = 0.18) -> np.ndarray:
    t = np.linspace(0.0, dur_s, int(sr * dur_s), endpoint=False)
    # Mild AM to make each "speaker" sound a little more like speech.
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 3.5 * t)
    signal = amp * envelope * np.sin(2 * np.pi * freq * t)
    return signal.astype(np.float32)


def _silence(dur_s: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(sr * dur_s), dtype=np.float32)


def _add_noise(audio: np.ndarray, snr_db: float = -25.0) -> np.ndarray:
    signal_power = float(np.mean(audio**2)) + 1e-9
    noise_power = signal_power / (10 ** (snr_db / 10))
    noise = np.random.default_rng(42).standard_normal(len(audio)).astype(np.float32)
    noise *= np.sqrt(noise_power)
    return (audio + noise).astype(np.float32)


def _save_wav(path: Path, audio: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import soundfile as sf

        sf.write(str(path), audio, sr, subtype="PCM_16")
    except Exception:
        # Final fallback: stdlib wave + int16
        import wave

        clipped = np.clip(audio, -1.0, 1.0)
        ints = (clipped * 32767.0).astype(np.int16)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(ints.tobytes())


def _fallback_hallway() -> np.ndarray:
    """~16 seconds: speaker A then speaker B with hallway noise overlaid."""
    parts: List[np.ndarray] = []
    parts.append(_tone(HALLWAY_LINES[0][2], 8.0))
    parts.append(_silence(0.4))
    parts.append(_tone(HALLWAY_LINES[1][2], 6.0))
    audio = np.concatenate(parts)
    return _add_noise(audio, snr_db=-25.0)


def _fallback_consult() -> np.ndarray:
    """~32 seconds with 4 'speakers' interleaved and one short overlap."""
    parts: List[np.ndarray] = []
    parts.append(_tone(CONSULT_LINES[0][2], 7.0))
    parts.append(_silence(0.3))
    parts.append(_tone(CONSULT_LINES[1][2], 8.0))
    parts.append(_silence(0.3))
    parts.append(_tone(CONSULT_LINES[2][2], 6.0))
    parts.append(_silence(0.3))
    parts.append(_tone(CONSULT_LINES[3][2], 8.0))
    audio = np.concatenate(parts)

    # Inject a 0.4s overlap between speaker 3 and speaker 4 at ~22.0 s.
    overlap = _tone(CONSULT_LINES[3][2] * 1.07, 0.4)
    start = int(22.0 * SR)
    end = start + len(overlap)
    if end <= len(audio):
        audio[start:end] = audio[start:end] + overlap

    return _add_noise(audio, snr_db=-30.0)


# ---------------------------------------------------------------------------
# gTTS path
# ---------------------------------------------------------------------------


def _try_gtts(lines: List[Tuple[str, float, int]], gap_ms: int = 300):
    """Returns a pydub AudioSegment or None if gTTS/pydub aren't usable."""
    try:
        import io

        from gtts import gTTS  # type: ignore
        from pydub import AudioSegment  # type: ignore
    except Exception:
        return None

    combined = AudioSegment.silent(duration=0, frame_rate=SR)
    for text, speed, _freq in lines:
        try:
            tts = gTTS(text=text, lang="en")
            buf = io.BytesIO()
            tts.write_to_fp(buf)
            buf.seek(0)
            seg = AudioSegment.from_file(buf, format="mp3").set_frame_rate(SR).set_channels(1)
            if speed and abs(speed - 1.0) > 1e-3:
                seg = seg._spawn(
                    seg.raw_data,
                    overrides={"frame_rate": int(seg.frame_rate * speed)},
                ).set_frame_rate(SR)
            combined += seg + AudioSegment.silent(duration=gap_ms, frame_rate=SR)
        except Exception:
            return None
    return combined


def _gtts_to_numpy(seg) -> np.ndarray:
    samples = np.array(seg.get_array_of_samples()).astype(np.float32)
    if seg.channels > 1:
        samples = samples.reshape(-1, seg.channels).mean(axis=1)
    samples /= float(1 << (8 * seg.sample_width - 1))
    return samples


def _write_hallway(use_fallback: bool) -> None:
    seg = None if use_fallback else _try_gtts(HALLWAY_LINES, gap_ms=400)
    if seg is None:
        audio = _fallback_hallway()
    else:
        audio = _gtts_to_numpy(seg)
        audio = _add_noise(audio, snr_db=-25.0)
    _save_wav(HALLWAY_PATH, audio)
    print(f"  wrote {HALLWAY_PATH} ({len(audio) / SR:.1f}s)")


def _write_consult(use_fallback: bool) -> None:
    seg = None if use_fallback else _try_gtts(CONSULT_LINES, gap_ms=300)
    if seg is None:
        audio = _fallback_consult()
    else:
        audio = _gtts_to_numpy(seg)
    _save_wav(CONSULT_PATH, audio)
    print(f"  wrote {CONSULT_PATH} ({len(audio) / SR:.1f}s)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate clinicvoice synthetic test audio.")
    ap.add_argument(
        "--use-fallback",
        action="store_true",
        help="Skip gTTS and use the sine-wave fallback generator.",
    )
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating synthetic audio:")
    _write_hallway(args.use_fallback)
    _write_consult(args.use_fallback)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
