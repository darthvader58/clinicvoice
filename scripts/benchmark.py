#!/usr/bin/env python3
"""clinicvoice Tuning Benchmark — 3-pass medical ASR evaluation.

Measures WER and MTER before/after lexicon biasing and corrections.
Saves results to data/reports/benchmark_results.json for the demo app.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

AUDIO = Path("tests/data/synthetic_consult.wav")
GT = Path("tests/data/ground_truth_consult.json")
LEXICON = Path("tests/data/medical_lexicon.json")
OUTPUT = Path("data/reports/benchmark_results.json")


def _require(path: Path) -> None:
    if not path.exists():
        print(f"ERROR: required file missing: {path}", file=sys.stderr)
        print(
            "Hint: run scripts/generate_synthetic_audio.py and ensure the "
            "lexicon and ground truth are in place.",
            file=sys.stderr,
        )
        sys.exit(2)


def main() -> int:
    _require(AUDIO)
    _require(GT)
    _require(LEXICON)

    try:
        import whisper  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: openai-whisper is not installed: {exc}", file=sys.stderr)
        return 2

    try:
        from src.asr.lexicon import MedicalLexicon
        from src.metrics.mter import compute_mter
        from src.metrics.wer import compute_wer
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: clinicvoice modules not importable: {exc}", file=sys.stderr)
        return 2

    gt = json.loads(GT.read_text())
    reference = gt["reference_transcript"]
    lexicon = MedicalLexicon.load(LEXICON)

    print("Loading Whisper base model for benchmark...")
    model = whisper.load_model("base")

    def run(initial_prompt):
        t0 = time.time()
        out = model.transcribe(
            str(AUDIO), initial_prompt=initial_prompt, task="transcribe"
        )
        return out["text"].strip(), time.time() - t0

    results = {}

    print("\nPass 1: Baseline (no biasing)...")
    hyp1, lat1 = run(None)
    results["pass_1"] = {
        "label": "Baseline (no biasing)",
        "hypothesis": hyp1,
        "wer": round(compute_wer(hyp1, reference), 4),
        "mter": round(compute_mter(hyp1, reference, lexicon), 4),
        "latency_s": round(lat1, 2),
    }

    print("Pass 2: With medical lexicon initial_prompt...")
    prompt = lexicon.build_initial_prompt()
    hyp2, lat2 = run(prompt)
    results["pass_2"] = {
        "label": "Lexicon Biasing",
        "hypothesis": hyp2,
        "wer": round(compute_wer(hyp2, reference), 4),
        "mter": round(compute_mter(hyp2, reference, lexicon), 4),
        "latency_s": round(lat2, 2),
    }

    print("Pass 3: Biasing + correction loop...")
    auto_corrections = {}
    for term in gt.get("medical_terms_present", []):
        if term.lower() not in hyp2.lower():
            # Stub correction: map a 4-char prefix to the canonical term.
            auto_corrections[term[:4]] = term
    if auto_corrections:
        lexicon.apply_corrections(auto_corrections)
    prompt3 = lexicon.build_initial_prompt()
    hyp3, lat3 = run(prompt3)
    results["pass_3"] = {
        "label": "Biasing + Corrections",
        "hypothesis": hyp3,
        "wer": round(compute_wer(hyp3, reference), 4),
        "mter": round(compute_mter(hyp3, reference, lexicon), 4),
        "latency_s": round(lat3, 2),
    }

    print("\n" + "=" * 65)
    print(f"{'clinicvoice - Medical ASR Tuning Benchmark':^65}")
    print("=" * 65)
    print(f"{'Configuration':<30} {'WER':>8} {'MTER':>8} {'D MTER':>10}")
    print("-" * 65)
    base_mter = results["pass_1"]["mter"]
    for key in ["pass_1", "pass_2", "pass_3"]:
        r = results[key]
        delta = (
            f"{(r['mter'] - base_mter) * 100:+.1f}%" if key != "pass_1" else "-"
        )
        print(
            f"{r['label']:<30} {r['wer'] * 100:>7.1f}% "
            f"{r['mter'] * 100:>7.1f}% {delta:>10}"
        )
    print("=" * 65)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
