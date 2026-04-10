# Design notes

This document explains **why** mailguard is shaped the way it is — the
tradeoffs, the weights, and the decisions that aren't obvious from the code.
Read this before filing a bug or opening a PR that changes the scoring.

## Goals

1. **Usable without paying per email.** Paid validators charge $0.004–$0.01
   per address. For list hygiene, that's a rent extraction — the heuristics
   are public knowledge. mailguard is the open implementation of those
   heuristics.
2. **Privacy by default.** Nothing leaves the machine. No telemetry, no
   remote API call unless the operator explicitly opts in.
3. **Fault tolerance as a primary feature.** Any single layer failing must
   degrade the result, not crash the pipeline. An email with a transient DNS
   failure should come back with a reduced score and an error note — not an
   exception.
4. **Honest uncertainty.** A probe that could not be completed returns
   `None` (no signal), not `False`. Treating "blocked" as "rejected" is the
   single biggest accuracy bug in naive validators.

## Non-goals

- **Mailbox enumeration.** mailguard is not a tool for discovering which
  addresses exist at a target domain without the owner's consent.
- **Cold outreach list generation.** Input should be addresses you obtained
  legitimately. The tool cleans lists; it does not source them.
- **Real-time transactional routing.** If you need sub-10ms verdicts for
  every form submit, use a dedicated upstream service and treat mailguard as
  a nightly batch cleaner.
- **Domain-level threat intelligence.** DBL lookups give a reputation
  signal, but mailguard is not an anti-phishing or anti-spam classifier.

## The pipeline

```
email ──► syntax ──► typo ──► disposable ──► role ──► free-provider ──►
                                                                     │
                                             ┌───────────────────────┘
                                             ▼
                                          MX/DNS ──► catch-all? ──► SMTP?
                                             │
                                             ▼
                                          scoring ──► verdict
```

Every check is independent. The only hard dependencies are:

- `catch-all` requires `MX` to have succeeded (otherwise there's nothing to probe)
- `SMTP` requires `MX` to have succeeded
- `scoring` reads every layer's output

Everything else runs regardless of whether upstream layers passed — that's
deliberate. If MX fails, we still report whether the syntax was OK and
whether the domain was disposable. The operator gets all the information.

## Why SMTP is optional, not default

Port 25 outbound is firewalled on:

- Google Colab (always)
- AWS Lambda, Cloud Functions, most serverless platforms
- DigitalOcean / Linode / Vultr for new accounts (until requested unblock)
- Almost all residential ISPs
- Corporate VPNs

If SMTP were the primary signal, mailguard would return garbage on every one
of these platforms. Worse, it would return **misleading** garbage — a
blocked port looks like "every address is unreachable" if the implementer
treats connection failure as rejection.

The decision: **SMTP is a +25 / −30 modifier on a baseline that already has
~60 points from other layers.** The tool is useful without it, and strictly
better with it on hosts where it works.

## Scoring model

The score is a hand-tuned linear combination, not a learned classifier. It
should be replaced with a fitted model once we have enough labeled data —
see the [benchmarks](benchmarks/accuracy.py) for the ground-truth dataset.

### Hard blocks (set score, bypass modifiers)

| Condition | Score | Verdict |
|---|---|---|
| Invalid syntax | 0 | undeliverable |
| No MX / no A | 5 | undeliverable |
| Disposable domain | 15 | undeliverable |

### Baseline

Syntax + MX both pass → **60**

### Modifiers applied to baseline

| Signal | Delta | Rationale |
|---|---|---|
| SMTP accepted (`2xx`) | +25 | Strong positive signal on hosts where it works |
| SMTP rejected (`5xx`) | −30 | Strong negative signal; higher magnitude because false positives here are very rare |
| Catch-all domain | −15 | Any SMTP positive on this domain is untrustworthy |
| Catch-all ruled out | +10 | Small positive — SMTP probes on this domain are meaningful |
| Role-based address | −10 | Valid but low engagement; deliverable ≠ valuable |
| Free provider | +5 | Gmail/Outlook/Yahoo have strong MX guarantees |
| Typo suggestion present | −20 | Likely a finger-slip; surface the suggestion to the user |

### Verdict thresholds

| Score | Verdict |
|---|---|
| ≥ 80 | deliverable |
| 50 – 79 | risky |
| < 50 | undeliverable |

### Why these numbers?

They were chosen to satisfy these invariants on the ground-truth dataset:

- A valid corporate address with no red flags (syntax + MX + not disposable
  + not role) lands at exactly 60 — inside `risky`, not `deliverable` —
  **unless** we have additional positive signal (SMTP or catch-all-ruled-out).
  This reflects the honest fact that we don't know for certain without
  probing.
- A role address on a good domain lands at 50 — boundary of risky. Any GTM
  team that wants stricter handling can filter to `deliverable` only.
- A typo-detected address lands at 40 — below the deliverable line — but is
  still surfaced so the user can recover the lead.
- A disposable address can never exceed 15 regardless of other signals.
- An SMTP-rejected address on a non-catch-all domain lands at 30 — clearly
  undeliverable.

The numbers are **not derived from machine learning** and should not be
mistaken for an optimum. They are a defensible starting point calibrated
against the 100+ case ground truth in `tests/groundtruth.yaml`. The next
version will derive them from a labeled dataset of 1000+ real cases.

## Catch-all detection

We probe the domain with a deliberately random local part
(`mailguard-probe-<12 hex chars>@domain`). If the MX accepts, the domain is
catch-all and any other SMTP accept from that domain is untrustworthy. The
catch-all verdict is cached per domain for 7 days.

Weaknesses:

1. **Greylisting masquerades as catch-all.** A domain that returns `4xx`
   temporarily looks like catch-all if we treat "not rejected" as "accepted".
   Current code treats `4xx` as `None` (unknown), which is conservative.
2. **Rate-limiting masquerades as catch-all.** Hitting a domain hard from
   one IP can trigger temporary all-reject policies. We keep the probe count
   at one per domain per run to avoid this.
3. **Subdomain-level catch-all.** `acme.com` might not be catch-all but
   `corp.acme.com` might be. We probe at the exact domain of the address.

Planned improvement: probe 3× with different random local parts and require
all 3 to accept before declaring catch-all. 1-of-3 accept suggests
rate-limiting noise.

## Fault-tolerance invariants

Every PR must preserve these:

1. **`validate()` never raises.** Any exception inside a layer is caught,
   logged to `result.errors`, and the pipeline continues.
2. **`validate_bulk()` never raises.** One bad input never kills a batch.
3. **Results are position-stable.** `validate_bulk(emails)[i].email` must
   refer to the same input as `emails[i]`.
4. **Unsafe input returns `None` for SMTP, not a silent `True`.** See
   `checks/smtp_check.py` for the sanitisation rules.
5. **Cache failures are silent.** A broken SQLite file must not prevent
   validation — the cache layer catches all exceptions and proceeds.

## What we deliberately don't do

- **No regex-based syntax check.** `email-validator` is the canonical
  RFC 5322 / 6531 implementation; reinventing it is always a bug farm.
- **No HTTP calls during validation.** DNS + SMTP only. HTTP is only used
  by `mailguard update-lists` at the operator's explicit request.
- **No telemetry.** mailguard will never phone home. PRs that add analytics
  will be closed.
- **No required configuration file.** Every option has a sensible default.
- **No required external services.** No Redis, no Postgres, no message
  broker. The SQLite cache is optional.

## Review questions for future PRs

Before merging any PR that touches scoring or layers, answer:

1. Does `benchmarks/accuracy.py` still pass the threshold?
2. If a new layer is added, is it fault-tolerant (returns sentinel, doesn't
   raise)?
3. Is the new weight defended in this document?
4. Does it preserve the "hard block" semantics for syntax / MX / disposable?
5. Are there new tests in `tests/` covering the behaviour?

---

For the accuracy methodology and how we measure the numbers in the README,
see [`benchmarks/accuracy.py`](benchmarks/accuracy.py). For what the tool
is explicitly weak at, see [`LIMITATIONS.md`](LIMITATIONS.md).
