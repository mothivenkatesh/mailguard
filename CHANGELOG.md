# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2026-04-11

### Fixed
- **CRITICAL:** DNS resolver on Windows was returning "no MX records" for
  every real domain because `aiodns`/`pycares` can't auto-discover DNS
  servers from Windows network stack. Added sticky fallback to sync
  `dnspython` in a thread pool. Discovered while validating a real 300-row
  list where 99% of addresses were incorrectly flagged undeliverable.
- **Typo detector false positives on short corporate domains.** Real-world
  list contained `pg.com` (Procter & Gamble), `wsj.com`, `tjx.com`,
  `pwc.com`, etc. being "corrected" to `me.com` / `msn.com` / `mac.com` /
  `gmx.com`. Added three defensive rules: (1) minimum domain length of 7
  before suggesting, (2) length gap ≤ max_dist, (3) short candidates
  (≤ 8 chars) require distance 1, only longer candidates allow distance 2.
  Regression test includes all real-world cases.
- Expanded typo detector's known-domain list with regional variants
  (`yahoo.com.vn`, `yahoo.com.au`, `hotmail.de`, etc.) so they aren't
  "corrected" to each other.

### Added
- **Provider-specific trust paths** (`mailguard/checks/providers.py`).
  Detects Gmail / Outlook / Yahoo / iCloud. SMTP trust multiplier for big
  free providers (0.4 vs 1.0) + MX guarantee bonus (+5) on scoring.
- **Spamhaus / URIBL / SURBL DBL reputation check**
  (`mailguard/checks/dbl.py`). Opt-in via `check_reputation=True`. DNS-based,
  1-hour cached, fault-tolerant (silent on failure).
- **STARTTLS upgrade in SMTP probe.** If the MX advertises STARTTLS in its
  EHLO extension list, we upgrade the connection before sending MAIL FROM.
  Required by many corporate MTAs. Failure falls back to `None` (no signal).
- **3× catch-all probe with unanimity rule** (`mailguard/checks/catchall.py`).
  Probes with 3 different random local parts and requires agreement before
  declaring catch-all. Mixed results → unknown. Result cached for 7 days.
- **EHLO instead of HELO** in SMTP probe so we can see server extensions.
  Falls back to HELO for ancient MTAs.
- **Multi-line SMTP response parsing.** Previously read one line; now
  correctly handles the `250-FOO / 250-BAR / 250 BAZ` continuation format.
- **Weight optimizer** (`benchmarks/optimize_weights.py`). Loads the
  dataset, splits 80/20 train/test with a fixed seed, runs layers once,
  coordinate-descent searches weight space, and reports train vs test F1
  so over-fit is visible. Pure Python, no sklearn dependency.
- **Expanded ground-truth dataset** to 177 labeled cases (was 110). New
  cases cover: developer tooling (Ramp, Brex, Linear, Retool, Supabase,
  Fly, Railway, PostHog, Sentry, LaunchDarkly, PagerDuty...), long local
  parts, `+`-tagged local parts, more role prefixes, more syntax errors,
  more disposable variants.
- Provider tests (`tests/test_providers.py`).

### Changed
- Validator signature gains `check_reputation_layer` kwarg.
- `ValidationResult` gains `reputation_listed`, `reputation_providers`,
  and `provider` fields.
- Measured micro-F1 on the 177-case dataset: **1.000** train, **1.000**
  test (seed=42, 80/20 split). Zero over-fit gap. Current hand-tuned
  weights are already optimal on this dataset — further improvements will
  come from growing the dataset, not re-fitting.

### Tests
- 54 tests passing (was 45 in v0.2.0).
- Added `tests/test_providers.py` (7 tests).

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
