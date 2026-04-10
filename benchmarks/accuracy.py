"""Accuracy benchmark for mailguard.

Loads ``tests/groundtruth.yaml``, runs the full validation pipeline against
every labeled case, and prints precision/recall/F1 per verdict class plus an
overall micro-F1. Numbers in the README must be backed by this script and
cite the commit hash they were measured at.

Usage:
    python benchmarks/accuracy.py
    python benchmarks/accuracy.py --smtp            # include SMTP probe
    python benchmarks/accuracy.py --json results.json
    python benchmarks/accuracy.py --fail-below 0.80 # CI gate

Exit codes:
    0 — F1 >= --fail-below threshold
    1 — F1 below threshold
    2 — dataset missing / load error
"""
from __future__ import annotations

import argparse
import json
import sys
import time

# Make stdout UTF-8 capable on Windows (cp1252 default breaks on → and similar).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass
from collections import Counter
from pathlib import Path
from typing import Any

# Tiny hand-written YAML subset loader — avoids adding PyYAML as a dep.
# Only supports the exact structure of groundtruth.yaml (flat list of flow
# mappings). For anything more complex, install PyYAML and swap this out.

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "tests" / "groundtruth.yaml"

sys.path.insert(0, str(ROOT))
from mailguard.core import validate_bulk_sync  # noqa: E402


def _strip_quotes(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in {'"', "'"}:
        return v[1:-1]
    return v


def _parse_flow_mapping(line: str) -> dict[str, str]:
    """Parse a single ``{ key: val, key: val }`` flow mapping."""
    line = line.strip()
    if not (line.startswith("{") and line.endswith("}")):
        raise ValueError(f"not a flow mapping: {line!r}")
    inner = line[1:-1].strip()
    out: dict[str, str] = {}
    # Split on commas, but ignore commas inside quoted strings
    buf: list[str] = []
    in_quote: str | None = None
    for ch in inner:
        if in_quote:
            buf.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in {'"', "'"}:
            in_quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            _add_kv(out, "".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        _add_kv(out, "".join(buf))
    return out


def _add_kv(out: dict[str, str], pair: str) -> None:
    pair = pair.strip()
    if not pair:
        return
    if ":" not in pair:
        raise ValueError(f"bad kv: {pair!r}")
    k, _, v = pair.partition(":")
    out[k.strip()] = _strip_quotes(v)


def load_cases(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"dataset not found: {path}")
    cases: list[dict[str, str]] = []
    in_cases = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.strip() == "cases:":
            in_cases = True
            continue
        if not in_cases:
            continue
        stripped = line.lstrip()
        if stripped.startswith("- "):
            cases.append(_parse_flow_mapping(stripped[2:]))
    return cases


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def main() -> int:
    parser = argparse.ArgumentParser(description="mailguard accuracy benchmark")
    parser.add_argument("--smtp", action="store_true", help="run SMTP probe layer")
    parser.add_argument("--catchall", action="store_true", help="run catch-all probe")
    parser.add_argument("--concurrency", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--json", type=str, default=None, help="write results JSON")
    parser.add_argument("--fail-below", type=float, default=None,
                        help="exit 1 if micro-F1 below this value")
    args = parser.parse_args()

    try:
        cases = load_cases(DATASET)
    except Exception as e:
        print(f"error loading dataset: {e}", file=sys.stderr)
        return 2

    n = len(cases)
    if n == 0:
        print("dataset is empty", file=sys.stderr)
        return 2

    print(f"loaded {n} labeled cases from {DATASET.name}")
    label_counts = Counter(c["expected"] for c in cases)
    for k, v in sorted(label_counts.items()):
        print(f"  {k:15} {v}")
    print()

    emails = [c["email"] for c in cases]
    print(f"running validation (smtp={args.smtp}, catchall={args.catchall}, "
          f"concurrency={args.concurrency})...")
    t0 = time.time()
    results = validate_bulk_sync(
        emails,
        concurrency=args.concurrency,
        check_smtp=args.smtp,
        check_catchall=args.catchall,
        timeout=args.timeout,
    )
    elapsed = time.time() - t0
    throughput = n / elapsed if elapsed else 0.0
    print(f"done in {elapsed:.2f}s  ({throughput:.0f} emails/sec)\n")

    # Build confusion structure
    labels = ["deliverable", "risky", "undeliverable"]
    confusion: dict[str, Counter[str]] = {lbl: Counter() for lbl in labels}
    mismatches: list[dict[str, Any]] = []

    for case, r in zip(cases, results):
        expected = case["expected"]
        predicted = r.verdict if r.verdict in labels else "undeliverable"
        confusion[expected][predicted] += 1
        if expected != predicted:
            mismatches.append({
                "email": case["email"],
                "expected": expected,
                "predicted": predicted,
                "score": r.score,
                "reason": r.reason,
                "note": case.get("note", ""),
            })

    # Per-class metrics
    print("=" * 72)
    print(f"{'CLASS':<16}{'SUPPORT':>10}{'PRECISION':>14}{'RECALL':>12}{'F1':>10}")
    print("-" * 72)
    macro_f1 = 0.0
    total_correct = 0
    for lbl in labels:
        support = sum(confusion[lbl].values())
        tp = confusion[lbl][lbl]
        fp = sum(confusion[other][lbl] for other in labels if other != lbl)
        fn = support - tp
        p, r_, f1 = prf(tp, fp, fn)
        total_correct += tp
        macro_f1 += f1
        print(f"{lbl:<16}{support:>10}{p:>14.3f}{r_:>12.3f}{f1:>10.3f}")
    macro_f1 /= len(labels)
    micro_f1 = total_correct / n  # accuracy (micro-F1 == accuracy for single-label)
    print("-" * 72)
    print(f"{'micro-F1 (acc)':<16}{n:>10}{'':>14}{'':>12}{micro_f1:>10.3f}")
    print(f"{'macro-F1':<16}{'':>10}{'':>14}{'':>12}{macro_f1:>10.3f}")
    print("=" * 72)

    if mismatches:
        print(f"\n{len(mismatches)} mismatches (first 20):")
        for m in mismatches[:20]:
            print(
                f"  expected={m['expected']:<14} got={m['predicted']:<14} "
                f"score={m['score']:>3}  {m['email']}  "
                f"({m['reason']})"
            )

    if args.json:
        payload = {
            "n": n,
            "elapsed_seconds": round(elapsed, 3),
            "throughput_per_sec": round(throughput, 1),
            "smtp": args.smtp,
            "catchall": args.catchall,
            "micro_f1": round(micro_f1, 4),
            "macro_f1": round(macro_f1, 4),
            "confusion": {k: dict(v) for k, v in confusion.items()},
            "mismatches": mismatches,
        }
        Path(args.json).write_text(json.dumps(payload, indent=2))
        print(f"\nwrote {args.json}")

    if args.fail_below is not None and micro_f1 < args.fail_below:
        print(f"\nFAIL: micro-F1 {micro_f1:.3f} < threshold {args.fail_below}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
