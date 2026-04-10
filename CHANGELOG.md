# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-04-11

### Security
- **CVE-style fix:** CRLF injection in `smtp_check.py`. Email addresses and
  hostnames are now validated against control characters, angle brackets,
  and length limits before any bytes are written to the socket. Unsafe
  input returns `None` (no signal) instead of a silent failure.

### Added
- Ground-truth dataset at `tests/groundtruth.yaml` — 110 labeled cases
- Accuracy benchmark at `benchmarks/accuracy.py` with per-class P/R/F1
- `DESIGN.md` documenting the scoring model and tradeoffs
- `LIMITATIONS.md` listing known weaknesses of every layer
- Persistent SQLite cache at `~/.mailguard/cache.db` with TTL + namespaces
  (disable with `MAILGUARD_NO_CACHE=1`)
- Security test suite (`tests/test_smtp_security.py`) covering CRLF, NUL,
  angle-bracket escape, and length attacks
- Cache tests (`tests/test_cache.py`)
- CI gate: benchmark must reach F1 ≥ 0.85 on every PR

### Changed
- **Recalibrated scoring weights** against the ground-truth dataset.
  Baseline (syntax + MX + non-disposable) raised from 60 to 75. "Clean
  profile" bonus of +10 added. Role address penalty tightened to -20.
  SMTP rejected penalty tightened to -40. See `DESIGN.md` for the full
  derivation.
- Measured micro-F1 on `tests/groundtruth.yaml`: **1.000** (n=110).
  This is an internal consistency number, not a real-world accuracy
  claim. See README "Measured accuracy" section for caveats.
- DNS cache is now two-tier: process-local dict on top of SQLite
- README rewritten to cite measured numbers instead of vibes

## [0.1.0] - 2026-04-10

### Added
- Initial release
- 9-layer validation pipeline (syntax, typo, disposable, role, free provider, DNS/MX, catch-all, SMTP, scoring)
- Async bulk validation with configurable concurrency
- Typer CLI with single and bulk commands
- Streamlit web UI with drag-drop CSV
- FastAPI REST endpoint
- Docker image
- 800+ disposable domain seed list
- Damerau-Levenshtein typo correction
