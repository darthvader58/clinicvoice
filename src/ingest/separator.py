from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.ingest.schemas import NormalizedAudio, SeparationResult, StemAsset

if TYPE_CHECKING:
    from src.diarize.schemas import SpeakerTurn

logger = logging.getLogger("clinicvoice.ingest.separator")

try:
    from asteroid.models import ConvTasNet as _ConvTasNet
    _ASTEROID_OK = True
    _ASTEROID_IMPORT_ERR: Optional[str] = None
except Exception as _exc:
    _ConvTasNet = None
    _ASTEROID_OK = False
    _ASTEROID_IMPORT_ERR = type(_exc).__name__

_separator_model = None


def _get_model(model_name: str):
    global _separator_model
    if not _ASTEROID_OK:
        raise RuntimeError(
            f"asteroid unavailable ({_ASTEROID_IMPORT_ERR}); cannot run Option A"
        )
    if _separator_model is None:
        logger.info("loading_separator_model", extra={"model": model_name})
        _separator_model = _ConvTasNet.from_pretrained(model_name)
        _separator_model.eval()
    return _separator_model


def _compute_si_sdr(estimate, mixture) -> float:
    import torch
    from torchmetrics.audio import ScaleInvariantSignalDistortionRatio

    metric = ScaleInvariantSignalDistortionRatio()
    est = estimate.detach().cpu() if hasattr(estimate, "detach") else estimate
    mix = mixture.detach().cpu() if hasattr(mixture, "detach") else mixture
    if est.dim() == 1:
        est = est.unsqueeze(0)
    if mix.dim() == 1:
        mix = mix.unsqueeze(0)
    min_len = min(est.shape[-1], mix.shape[-1])
    return float(metric(est[..., :min_len], mix[..., :min_len]).item())


def _separate_sync(
    normalized_audio: NormalizedAudio,
    settings: Any,
    output_dir: Path,
) -> SeparationResult:
    import librosa
    import soundfile as sf
    import torch

    threshold = float(getattr(settings, "SEPARATION_SI_SDR_THRESHOLD", 5.0))
    model_name = getattr(
        settings,
        "ASTEROID_MODEL",
        "JorisCos/ConvTasNet_Libri2Mix_sepclean_16k",
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    if not _ASTEROID_OK:
        logger.warning(
            "asteroid_missing_degraded_to_option_b",
            extra={"error_type": _ASTEROID_IMPORT_ERR},
        )
        return SeparationResult(
            track_mode="option_b_single",
            stems=[],
            si_sdr_max=0.0,
            si_sdr_threshold_used=threshold,
        )

    try:
        model = _get_model(model_name)
    except Exception as exc:
        logger.warning(
            "separator_load_failed_degraded_to_option_b",
            extra={"error_type": type(exc).__name__},
        )
        return SeparationResult(
            track_mode="option_b_single",
            stems=[],
            si_sdr_max=0.0,
            si_sdr_threshold_used=threshold,
        )

    audio, sr = librosa.load(str(normalized_audio.path), sr=16000, mono=True)
    mixture = torch.from_numpy(audio).float().unsqueeze(0)

    try:
        with torch.no_grad():
            estimates = model(mixture)
    except Exception as exc:
        logger.warning(
            "separation_forward_failed_degraded_to_option_b",
            extra={"error_type": type(exc).__name__},
        )
        return SeparationResult(
            track_mode="option_b_single",
            stems=[],
            si_sdr_max=0.0,
            si_sdr_threshold_used=threshold,
        )

    if estimates.dim() == 3:
        sources = estimates[0]
    elif estimates.dim() == 2:
        sources = estimates
    else:
        sources = estimates.view(-1, estimates.shape[-1])

    stems: List[StemAsset] = []
    si_sdrs: List[float] = []

    for i in range(sources.shape[0]):
        est = sources[i].unsqueeze(0)
        si_sdr_val = _compute_si_sdr(est, mixture)
        si_sdrs.append(si_sdr_val)
        stem_path = output_dir / f"stem_S{i + 1}.wav"
        sf.write(str(stem_path), sources[i].detach().cpu().numpy(), sr, subtype="PCM_16")
        stems.append(StemAsset(
            speaker_id=f"S{i + 1}",
            path=stem_path,
            si_sdr=si_sdr_val,
        ))

    si_sdr_max = max(si_sdrs) if si_sdrs else 0.0

    if si_sdr_max >= threshold:
        logger.info(
            "separation_success",
            extra={
                "track_mode": "option_a_stems",
                "si_sdr_max": round(si_sdr_max, 2),
                "threshold": threshold,
                "n_stems": len(stems),
            },
        )
        return SeparationResult(
            track_mode="option_a_stems",
            stems=stems,
            si_sdr_max=si_sdr_max,
            si_sdr_threshold_used=threshold,
        )

    logger.warning(
        "separation_degraded_to_option_b",
        extra={
            "si_sdr_max": round(si_sdr_max, 2),
            "threshold": threshold,
            "n_stems_discarded": len(stems),
        },
    )
    for stem in stems:
        try:
            stem.path.unlink(missing_ok=True)
        except Exception:
            pass

    return SeparationResult(
        track_mode="option_b_single",
        stems=[],
        si_sdr_max=si_sdr_max,
        si_sdr_threshold_used=threshold,
    )


async def separate_speakers(
    normalized_audio: NormalizedAudio,
    settings: Any,
    output_dir: Path,
) -> SeparationResult:
    return await asyncio.to_thread(_separate_sync, normalized_audio, settings, output_dir)


def align_stems_to_speakers(
    stems: List[StemAsset],
    speaker_turns: List["SpeakerTurn"],
) -> Dict[str, Path]:
    if not stems or not speaker_turns:
        return {}

    import librosa
    import numpy as np

    energy: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for turn in speaker_turns:
        duration = max(0.0, float(turn.end_ts) - float(turn.start_ts))
        if duration <= 0:
            continue
        for stem in stems:
            try:
                stem_audio, _ = librosa.load(
                    str(stem.path),
                    sr=16000,
                    offset=float(turn.start_ts),
                    duration=duration,
                )
            except Exception:
                continue
            if stem_audio.size == 0:
                continue
            rms = float(np.sqrt(np.mean(np.square(stem_audio, dtype="float64"))))
            energy[turn.speaker_id][stem.speaker_id] += rms

    assignment: Dict[str, Path] = {}
    used_stems: set = set()
    stem_by_id = {s.speaker_id: s.path for s in stems}

    ranked_speakers = sorted(
        energy.keys(),
        key=lambda spk: max(energy[spk].values(), default=0.0),
        reverse=True,
    )
    for spk_id in ranked_speakers:
        ranked = sorted(energy[spk_id].items(), key=lambda kv: kv[1], reverse=True)
        for stem_id, _ in ranked:
            if stem_id in used_stems:
                continue
            if stem_id not in stem_by_id:
                continue
            assignment[spk_id] = stem_by_id[stem_id]
            used_stems.add(stem_id)
            break

    return assignment
