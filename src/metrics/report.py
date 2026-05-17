"""MetricsReporter — writes a metrics run as JSON + CSV side-by-side."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class MetricsReporter:
    """Serialize a MetricsRun to disk as JSON (+ flat CSV summary)."""

    CSV_FIELDS = [
        "recording_id",
        "run_at",
        "wer",
        "medical_term_error_rate",
        "der_proxy",
        "si_sdr",
        "track_mode",
    ]

    def generate_report(
        self,
        recording_id: str,
        wer: float,
        mter: float,
        der_proxy: float,
        si_sdr: Optional[float],
        term_errors: List[Dict[str, Any]],
        speaker_quality: Dict[str, Any],
        track_mode: str,
        output_path: Path,
    ) -> Dict[str, Any]:
        output_path = Path(output_path)
        report: Dict[str, Any] = {
            "recording_id": recording_id,
            "run_at": datetime.now(timezone.utc).isoformat(),
            "track_mode": track_mode,
            "wer": round(float(wer), 4),
            "medical_term_error_rate": round(float(mter), 4),
            "der_proxy": round(float(der_proxy), 4),
            "si_sdr": round(float(si_sdr), 2) if si_sdr is not None else None,
            "term_errors": term_errors or [],
            "speaker_attribution": speaker_quality or {},
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2))

        csv_path = output_path.with_suffix(".csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.CSV_FIELDS)
            writer.writeheader()
            writer.writerow({k: report.get(k) for k in self.CSV_FIELDS})

        return report
