"""Fit scoring weights against the ground-truth dataset via coordinate descent.

Method:
    1. Load all cases, shuffle with a fixed seed, split 80/20 into train/test.
    2. Run the validation layers ONCE per case — we only need to compute
       scores from layer outputs, so no need to re-run DNS on every iteration.
    3. Define the scoring function as a pure function of (layer outputs, weights).
    4. Coordinate descent: repeatedly optimize each weight by searching over
       a small grid of integer values, keeping the best for train F1.
    5. Report train and test F1 so we can see over-fitting.

Usage:
    python benchmarks/optimize_weights.py
    python benchmarks/optimize_weights.py --seed 7 --iters 4

Exit code 0 always — this is a research script, not a gate.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# UTF-8 stdout for Windows consoles
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmarks.accuracy import load_cases  # noqa: E402
from mailguard.core import validate_bulk_sync  # noqa: E402


@dataclass
class Weights:
    baseline: int = 75
    clean_bonus: int = 10
    smtp_accept: int = 15
    smtp_reject: int = 40  # penalty magnitude
    catchall_penalty: int = 20
    catchall_negative_bonus: int = 5
    role_penalty: int = 20
    free_bonus: int = 5
    typo_penalty: int = 20

    def as_dict(self) -> dict[str, int]:
        return {
            "baseline": self.baseline,
            "clean_bonus": self.clean_bonus,
            "smtp_accept": self.smtp_accept,
            "smtp_reject": self.smtp_reject,
            "catchall_penalty": self.catchall_penalty,
            "catchall_negative_bonus": self.catchall_negative_bonus,
            "role_penalty": self.role_penalty,
            "free_bonus": self.free_bonus,
            "typo_penalty": self.typo_penalty,
        }


def score(layer_outputs: dict, w: Weights) -> tuple[int, str]:
    """Replicate core._score_and_verdict as a pure function of weights."""
    if not layer_outputs["syntax_ok"]:
        return 0, "undeliverable"
    if not layer_outputs["mx_ok"]:
        return 5, "undeliverable"
    if layer_outputs["disposable"]:
        return 15, "undeliverable"

    s = w.baseline
    is_clean = (
        not layer_outputs["role_based"]
        and not layer_outputs["typo_suggestion"]
        and layer_outputs["catch_all"] is not True
    )
    if is_clean:
        s += w.clean_bonus

    if layer_outputs["smtp_ok"] is True:
        s += w.smtp_accept
    elif layer_outputs["smtp_ok"] is False:
        s -= w.smtp_reject

    if layer_outputs["catch_all"] is True:
        s -= w.catchall_penalty
    elif layer_outputs["catch_all"] is False:
        s += w.catchall_negative_bonus

    if layer_outputs["role_based"]:
        s -= w.role_penalty

    if layer_outputs["free_provider"]:
        s += w.free_bonus

    if layer_outputs["typo_suggestion"]:
        s -= w.typo_penalty

    s = max(0, min(100, s))
    if s >= 80:
        return s, "deliverable"
    if s >= 50:
        return s, "risky"
    return s, "undeliverable"


def f1_score(labeled: list[tuple[dict, str]], w: Weights) -> float:
    """Micro-F1 (== accuracy for single-label)."""
    correct = sum(1 for lo, exp in labeled if score(lo, w)[1] == exp)
    return correct / max(len(labeled), 1)


def optimize(labeled: list[tuple[dict, str]], iters: int = 3) -> Weights:
    """Coordinate descent over integer weights."""
    w = Weights()
    search_ranges = {
        "baseline": list(range(60, 91, 5)),
        "clean_bonus": list(range(0, 21, 2)),
        "smtp_accept": list(range(5, 31, 5)),
        "smtp_reject": list(range(20, 61, 5)),
        "catchall_penalty": list(range(10, 36, 5)),
        "catchall_negative_bonus": list(range(0, 16, 2)),
        "role_penalty": list(range(10, 36, 5)),
        "free_bonus": list(range(0, 16, 2)),
        "typo_penalty": list(range(10, 36, 5)),
    }
    best_f1 = f1_score(labeled, w)
    print(f"  start F1 = {best_f1:.4f}  weights = {w.as_dict()}")

    for it in range(iters):
        improved = False
        for name, values in search_ranges.items():
            current = getattr(w, name)
            best_val = current
            for v in values:
                setattr(w, name, v)
                f1 = f1_score(labeled, w)
                if f1 > best_f1:
                    best_f1 = f1
                    best_val = v
                    improved = True
            setattr(w, name, best_val)
        print(f"  iter {it + 1}  F1 = {best_f1:.4f}")
        if not improved:
            break
    return w


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--iters", type=int, default=4)
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--concurrency", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=6.0)
    args = parser.parse_args()

    cases = load_cases(ROOT / "tests" / "groundtruth.yaml")
    print(f"loaded {len(cases)} cases")

    rng = random.Random(args.seed)
    shuffled = list(cases)
    rng.shuffle(shuffled)
    split = int(len(shuffled) * (1 - args.test_fraction))
    train_cases = shuffled[:split]
    test_cases = shuffled[split:]
    print(f"train={len(train_cases)}  test={len(test_cases)}")

    print("\nrunning layers once (all cases)...")
    all_emails = [c["email"] for c in shuffled]
    t0 = time.time()
    results = validate_bulk_sync(
        all_emails, concurrency=args.concurrency, timeout=args.timeout
    )
    print(f"  done in {time.time() - t0:.1f}s")

    # Build (layer_outputs, expected) tuples
    def to_layer_outputs(r) -> dict:
        return {
            "syntax_ok": r.syntax_ok,
            "mx_ok": r.mx_ok,
            "disposable": r.disposable,
            "role_based": r.role_based,
            "free_provider": r.free_provider,
            "typo_suggestion": r.typo_suggestion,
            "catch_all": r.catch_all,
            "smtp_ok": r.smtp_ok,
        }

    labeled_all = [(to_layer_outputs(r), c["expected"]) for c, r in zip(shuffled, results)]
    labeled_train = labeled_all[:split]
    labeled_test = labeled_all[split:]

    print("\noptimizing weights on train...")
    w = optimize(labeled_train, iters=args.iters)

    train_f1 = f1_score(labeled_train, w)
    test_f1 = f1_score(labeled_test, w)
    print()
    print("=" * 60)
    print(f"train F1: {train_f1:.4f}  (n={len(labeled_train)})")
    print(f"test  F1: {test_f1:.4f}  (n={len(labeled_test)})")
    print(f"gap:      {abs(train_f1 - test_f1):.4f}   (over-fit if > ~0.05)")
    print("=" * 60)
    print("\noptimal weights:")
    for k, v in w.as_dict().items():
        print(f"  {k:<25}  {v}")

    print("\n→ to apply: copy these values into mailguard/core.py::_score_and_verdict")
    print(f"  and document the measured test F1 ({test_f1:.4f}) in DESIGN.md")

    # Save
    out = ROOT / "benchmarks" / "optimized_weights.json"
    out.write_text(json.dumps({
        "seed": args.seed,
        "train_n": len(labeled_train),
        "test_n": len(labeled_test),
        "train_f1": round(train_f1, 4),
        "test_f1": round(test_f1, 4),
        "weights": w.as_dict(),
    }, indent=2))
    print(f"\nsaved → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
