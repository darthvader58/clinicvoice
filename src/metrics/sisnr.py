"""SI-SDR wrapper around torchmetrics. Falls back to a pure-numpy
implementation if torchmetrics/torch are unavailable at runtime."""
from __future__ import annotations

import numpy as np


def _si_sdr_numpy(estimate: np.ndarray, reference: np.ndarray) -> float:
    """Reference numpy implementation: scale-invariant SDR in dB."""
    est = np.asarray(estimate, dtype=np.float64).ravel()
    ref = np.asarray(reference, dtype=np.float64).ravel()
    n = min(len(est), len(ref))
    if n == 0:
        return 0.0
    est = est[:n] - est[:n].mean()
    ref = ref[:n] - ref[:n].mean()
    ref_energy = float(np.dot(ref, ref)) + 1e-12
    alpha = float(np.dot(est, ref)) / ref_energy
    target = alpha * ref
    noise = est - target
    target_energy = float(np.dot(target, target)) + 1e-12
    noise_energy = float(np.dot(noise, noise)) + 1e-12
    return 10.0 * float(np.log10(target_energy / noise_energy))


def compute_si_sdr(
    estimate: np.ndarray, mixture: np.ndarray, sr: int = 16000
) -> float:
    """Compute scale-invariant SDR (dB) of `estimate` against `mixture`.

    The `mixture` argument is treated as the reference signal — callers
    typically pass the clean source when scoring a separated stem.
    """
    try:
        import torch
        from torchmetrics.audio import ScaleInvariantSignalDistortionRatio

        metric = ScaleInvariantSignalDistortionRatio()
        min_len = min(len(estimate), len(mixture))
        if min_len == 0:
            return 0.0
        est_t = torch.as_tensor(
            np.asarray(estimate)[:min_len], dtype=torch.float32
        ).unsqueeze(0)
        mix_t = torch.as_tensor(
            np.asarray(mixture)[:min_len], dtype=torch.float32
        ).unsqueeze(0)
        return float(metric(est_t, mix_t).item())
    except Exception:
        return _si_sdr_numpy(estimate, mixture)
