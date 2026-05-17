"""Source-separation: SI-SDR math + SeparationResult Pydantic schema."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def test_si_sdr_computation():
    from src.metrics.sisnr import compute_si_sdr

    rng = np.random.default_rng(0)
    clean = rng.standard_normal(16000).astype(np.float32)
    noisy = clean + 0.1 * rng.standard_normal(16000).astype(np.float32)
    si_sdr = compute_si_sdr(noisy, clean)
    assert isinstance(si_sdr, float)
    # The noisy signal is close to the clean reference, so SI-SDR is positive.
    assert si_sdr > 0


def test_separation_result_schema():
    pytest.importorskip("src.ingest.schemas")
    from src.ingest.schemas import SeparationResult, StemAsset

    result = SeparationResult(
        track_mode="option_a_stems",
        stems=[
            StemAsset(speaker_id="S1", path=Path("/tmp/stem_S1.wav"), si_sdr=8.5)
        ],
        si_sdr_max=8.5,
        si_sdr_threshold_used=5.0,
    )
    assert result.track_mode == "option_a_stems"
    assert result.stems[0].si_sdr == 8.5


def test_option_b_fallback_schema():
    pytest.importorskip("src.ingest.schemas")
    from src.ingest.schemas import SeparationResult

    result = SeparationResult(
        track_mode="option_b_single",
        stems=[],
        si_sdr_max=2.1,
        si_sdr_threshold_used=5.0,
    )
    assert result.track_mode == "option_b_single"
    assert result.stems == []
