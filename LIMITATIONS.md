# Known limitations

mailguard is an honest tool. This file is the list of things it is **known
to get wrong or weak at**. If you're choosing a validator for your stack,
read this *before* the README — the README sells; this file tells the
truth.

If you hit one of these and it matters, please open an issue — several of
them are fixable, they're just not fixed yet.

## Hard limitations (by design)

### 1. Cannot prove a specific mailbox exists without sending mail

No email validator can. Every "verify" tool on the market uses the same
SMTP RCPT trick mailguard does, and every one of them returns garbage on
catch-all domains, greylisting domains, and providers that deliberately
accept-all for privacy (iCloud, Proton, many corporate MS365 tenants).

The only way to prove a mailbox is live is to send real mail and see if it
bounces. mailguard does not do this and will not.

### 2. Accuracy is bounded by the ground-truth dataset

The README's accuracy number comes from `benchmarks/accuracy.py` run against
`tests/groundtruth.yaml`. The dataset is ~110 labeled cases covering the
common buckets. It is **not** representative of every real-world list. Your
list will have different class balance, different domain distribution, and
different edge cases. Expect your measured accuracy to vary by ±5% from the
headline number.

**Action for users:** label 50–100 of your own known-good and known-dead
addresses, drop them into `groundtruth.yaml`, and re-run the benchmark to
calibrate for your ICP.

### 3. Port 25 is blocked almost everywhere

If you run mailguard on Google Colab, AWS Lambda, most cloud providers, or
any residential ISP, the SMTP probe will always return `None`. This is not
a mailguard bug — it's the state of the internet since ~2010. The fix is to
either:

- Run on a $5 VPS (Hetzner, Linode, OVH — port 25 usually works)
- Skip SMTP entirely and rely on the heuristic layers (still ~80% F1)

### 4. One probe per domain, per run

We do not burst probes. An email list with 10,000 addresses at `gmail.com`
still only sends one probe to Gmail's MX. This keeps us out of blacklists
but means we can't verify individual mailboxes on free providers.

## Weaknesses of current layers

### Syntax layer

- **Full RFC 5321/5322 support via `email-validator`**, which is good.
- **But** quoted local parts (`"weird name"@example.com`) are allowed by
  RFC and will pass syntax, even though most MTAs reject them. We currently
  don't downweight quoted local parts; we should.

### Typo layer

- Covers ~25 common free-provider domains. Will **not** suggest
  `stripe.com` if you typed `strlpe.com` — we only know about the common
  consumer providers.
- Uses Damerau-Levenshtein with max distance 2. Will miss 3-edit typos and
  transpositions-plus-substitutions.
- False positive risk: domains that happen to be 1 edit away from a common
  provider but are legitimate (rare, but exists). Current weight (−20) is
  conservative enough to flag-not-kill.

### Disposable layer

- Seed list of ~800 domains is **stale** by design — temp-mail providers
  spin up new domains weekly. Run `mailguard update-lists` monthly.
- Does not detect **obfuscated disposables**: subdomains of mailinator
  (`foo.mailinator.com`), custom domains pointed at mailinator's MX, or
  privacy relays like Apple's Hide-My-Email (which are arguably legitimate
  and not disposable).
- Does not detect **rolling-subdomain disposables** that use random
  subdomains of a base domain.

### Role-based layer

- Hardcoded list of ~50 English-language role prefixes. Will miss role
  addresses in other languages (`ventas@`, `soporte@`, `kontakt@`).
- Does not account for `+tags` as signaling: `sales+stripe@acme.com` is
  still a sales role address, but `jane+newsletter@acme.com` isn't. We
  currently strip the `+tag` and match against the base only.

### Free-provider layer

- Curated list of ~80 domains. Misses smaller regional providers.
- Does not know about **custom Google Workspace domains** — an address at
  `acme.com` backed by Google MX is classified as "work" even though the
  deliverability characteristics mirror Gmail.

### DNS / MX layer

- Fallback from MX to A record is **not strictly correct** per RFC — a
  domain with an A record but explicit absence of MX can be configured to
  reject mail. We treat A-record presence as weakly positive; you'll see
  ~1% false positives on this.
- DNS is cached in-process AND in SQLite. If you move between networks
  (VPN on/off), stale cache can give wrong answers. Clear with
  `python -c "from mailguard import cache; cache.clear('mx')"`.

### Catch-all detection

- **Cannot distinguish catch-all from greylisting.** A domain that
  temporarily `4xx`s our random-local probe looks indistinguishable from a
  domain that accepts everything. We treat `4xx` as unknown, which is safe
  but reduces the layer's power.
- **Single probe per domain** — if the random local part happens to
  collide with a real mailbox, we'd get a false "catch-all" signal. With 12
  hex chars of entropy this is astronomically unlikely.
- **Cached for 7 days.** If a domain enables or disables catch-all within
  that window, we'll serve stale data.

### SMTP probe

- **Does not support STARTTLS.** Some MTAs require the connection to be
  upgraded before they'll accept RCPT. We currently skip those.
- **No SPF / DKIM / DMARC awareness.** We don't attempt to predict what
  the receiving MTA will do with the `MAIL FROM` domain; some MTAs reject
  probes that fail SPF against their policy.
- **No enhanced status code parsing.** We look at the 3-digit class only.
  RFC 3463 codes like `5.1.1` vs `5.2.2` carry meaningful distinction we
  currently throw away.
- **No IPv6 fallback.** We connect by hostname; if the MX only has AAAA and
  your machine has no IPv6 route, we return `None`.

### Scoring

- **Hand-tuned weights.** Derived from intuition and a ~110-case ground
  truth, not a fitted model. This is the biggest known weakness and the
  most important thing to fix.
- **No per-domain calibration.** A 75 on a consumer domain means something
  different from a 75 on a corporate domain. We treat them the same.
- **Not probability-calibrated.** A score of 80 does **not** mean "80%
  chance of delivery." It means "within the top bucket on our ordinal
  scale." Don't feed the score directly into expected-value math.

## Things that look like bugs but are intentional

- **Validation of an empty string returns `undeliverable` with score 0,
  not an exception.** This is correct — the pipeline never raises.
- **SMTP probe on an email containing `\r\n` returns `None`, not an
  error.** The injection attempt is logged to `errors` and the other layers
  still run.
- **`is_valid` is True for `verdict == "risky"`.** Risky addresses are
  deliverable but low quality; the binary flag is for "should I reject this
  from a form" not "should I send marketing to this."
- **Gmail / Outlook addresses often come back `risky`, not `deliverable`.**
  This is correct on hosts where SMTP is blocked — we can't confirm, and
  the score reflects that honestly. Filter to `is_valid=True` to include
  them.

## What we plan to fix

Priority order:

1. Grow ground truth to 500+ labeled cases
2. Fit scoring weights with logistic regression instead of hand-tuning
3. Provider-specific paths for Gmail / Outlook / Yahoo (the big three)
4. Spamhaus DBL + URIBL + SURBL reputation signals
5. STARTTLS support in SMTP probe
6. Multilingual role prefix list
7. Probe 3× for catch-all with unanimity requirement
8. Enhanced SMTP status code parsing (RFC 3463)
9. Detection of obfuscated / rolling-subdomain disposables

PRs welcome on any of the above.

---

**If you hit something not on this list, open an issue.** This document
only covers limitations we're already aware of. The unknown ones are more
dangerous.
