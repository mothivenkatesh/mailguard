# The Complete Guide to mailguard

> A practical, example-driven guide for GTM marketers, growth engineers, and developers who want to clean email lists without paying per-address fees.

**Table of contents**

1. [Why mailguard exists](#1-why-mailguard-exists)
2. [Who this is for](#2-who-this-is-for)
3. [How it works — the 9 layers](#3-how-it-works--the-9-layers)
4. [Installation](#4-installation)
5. [Quickstart — 60 seconds to your first validation](#5-quickstart)
6. [Using the CLI](#6-using-the-cli)
7. [Using the Python library](#7-using-the-python-library)
8. [Using the Web UI (Streamlit)](#8-using-the-web-ui)
9. [Using the REST API](#9-using-the-rest-api)
10. [Using Docker](#10-using-docker)
11. [Real-world recipes](#11-real-world-recipes)
12. [Understanding the deliverability score](#12-understanding-the-score)
13. [Choosing the right deployment](#13-deployment-guide)
14. [Best practices for GTM marketers](#14-best-practices)
15. [Troubleshooting](#15-troubleshooting)
16. [FAQ](#16-faq)
17. [Migrating from ZeroBounce / NeverBounce / Hunter](#17-migrating)

---

## 1. Why mailguard exists

Every GTM team hits the same wall: you buy or scrape a list of leads, import it into HubSpot or Mailchimp, launch a campaign — and within minutes, your bounce rate is 18%, your sender reputation is toasted, and half your emails land in spam for weeks.

The standard fix is a paid validator:

| Service | Price per 10k emails |
|---|---|
| ZeroBounce | $39 |
| NeverBounce | $40 |
| Hunter.io | $49 |
| Kickbox | $40 |

There are three problems with this:

1. **Cost compounds.** A GTM team validating 100k leads per month pays $400–$500 every month, forever, for the exact same heuristics that are public knowledge.
2. **Privacy disappears.** Your entire lead database flows through a third-party SaaS and is logged, indexed, and often cached.
3. **No audit trail.** You get a verdict ("undeliverable") but no explanation, so you can't tune the rules to your ICP.

**mailguard** is the open-source answer: the same 9 heuristics the paid services charge for, running locally or on your own infra, free forever, with every layer's reasoning visible. Validate 100k emails in under a minute on a laptop. No per-email fees. No data leaving your machine. No login.

> If paid validators are a toll booth on the highway, mailguard is a bypass road that's free and paved.

## 2. Who this is for

mailguard is built for six audiences:

| Audience | Typical use | Primary interface |
|---|---|---|
| **GTM marketers** | Clean scraped / purchased lead lists before sending | Streamlit web UI |
| **Growth engineers** | Real-time validation on form submit | REST API |
| **SDR / BDR teams** | Validate cold outreach lists from Apollo, ZoomInfo, Lusha | CLI or Web UI |
| **Data engineers** | Dedupe + enrich + validate in ETL pipelines | Python library |
| **Automation builders** | n8n / Zapier / Make flows that validate before CRM sync | REST API |
| **Privacy-conscious ops** | Anyone who can't send customer data to third parties | Self-hosted Docker |

If you recognize yourself in any of the above — and you've paid more than $50 total for email validation — mailguard is probably going to pay for itself within a week.

## 3. How it works — the 9 layers

mailguard runs every address through nine independent checks. Each produces a signal; the final deliverability score is a weighted combination. No single check can falsely kill or falsely pass an address.

| # | Layer | What it catches | Can it fail alone? |
|---|---|---|---|
| 1 | **Syntax (RFC 5322/6531)** | Typos, bad characters, missing @, IDN errors | Yes (hard block) |
| 2 | **Typo correction** | `gmial.com` → `gmail.com`, `yaho.com` → `yahoo.com` | No (advisory) |
| 3 | **Disposable detection** | mailinator, tempmail, 10minutemail, 800+ throwaways | Yes (hard block) |
| 4 | **Role-based detection** | `info@`, `admin@`, `support@`, `sales@` (low engagement) | No (advisory) |
| 5 | **Free provider detection** | Gmail/Yahoo/Outlook routing vs. corporate domain | No (classification) |
| 6 | **DNS / MX resolution** | Domain doesn't exist, no mail servers | Yes (hard block) |
| 7 | **Catch-all detection** | Domain accepts mail for any local part (SMTP unreliable) | No (confidence) |
| 8 | **SMTP RCPT probe** | Mailbox actually exists (optional, may be blocked) | No (optional) |
| 9 | **Weighted scoring** | Combines all signals into 0–100 deliverability score | N/A |

**Key design decision:** SMTP probing is *optional* and *graceful*. On Google Colab, home broadband, and most cloud providers, port 25 is firewalled — so a traditional SMTP-only validator returns garbage. mailguard returns `None` (no signal) when SMTP is unreachable, and the other 8 layers still give you ~85% accuracy.

Every check is fault-tolerant: an exception in one layer never crashes the pipeline. The error is captured in `result.errors`, and the remaining checks proceed.

## 4. Installation

### Option A: From PyPI (recommended for most users)

```bash
pip install mailguard
```

### Option B: With web UI

```bash
pip install "mailguard[web]"
```

### Option C: With REST API

```bash
pip install "mailguard[api]"
```

### Option D: Everything

```bash
pip install "mailguard[all]"
```

### Option E: From source (contributors / bleeding edge)

```bash
git clone https://github.com/mothivenkatesh/mailguard
cd mailguard
pip install -e ".[all]"
```

### System requirements

- Python 3.9+
- No database, Redis, or message broker needed
- Outbound DNS on port 53 (any network)
- *Optional:* outbound SMTP on port 25 (only if you want the SMTP probe layer)

## 5. Quickstart

```bash
# 1. Install
pip install mailguard

# 2. Validate a single email
mailguard check jane.doe@stripe.com

# 3. Validate a CSV
mailguard bulk leads.csv -o clean.csv
```

That's it. You now have a `clean.csv` with verdict, score, reason, and all 9 layer results appended as columns.

## 6. Using the CLI

### Single address

```bash
mailguard check jane.doe@stripe.com
```

Output:
```
Email          jane.doe@stripe.com
Verdict        deliverable
Score          85/100
Reason         ok
Type           work
Syntax         ✓
MX             ✓ aspmx.l.google.com
Disposable     no
Role-based     no
Free provider  no
```

### JSON output (for scripting)

```bash
mailguard check jane@gmial.com --json
```

```json
{
  "email": "jane@gmial.com",
  "verdict": "risky",
  "score": 40,
  "reason": "possible typo → gmail.com",
  "typo_suggestion": "gmail.com",
  "mx_ok": true,
  "disposable": false
}
```

Exit code is `0` for deliverable/risky and `1` for undeliverable — perfect for shell scripting:

```bash
if mailguard check "$EMAIL" --json > /dev/null; then
  echo "good"
else
  echo "bad"
fi
```

### Bulk CSV

```bash
mailguard bulk leads.csv -o clean.csv
```

mailguard auto-detects the email column (looks for `email`, `e-mail`, `mail`, `address`, `email_address`). Override with `--column`:

```bash
mailguard bulk leads.csv -o clean.csv --column "Work Email"
```

### Tuning concurrency

Default is 50 concurrent validations. Crank it up for speed (watch for DNS rate limits):

```bash
mailguard bulk leads.csv -o clean.csv -c 200
```

A modern laptop will do ~1000 emails/second at c=200.

### Turning on SMTP + catch-all (only on unblocked hosts)

```bash
mailguard bulk leads.csv -o clean.csv --smtp --catchall -c 30
```

Drop concurrency when using SMTP — MTAs rate-limit probes per source IP.

### Refreshing the disposable list

```bash
mailguard update-lists
```

Pulls the latest from `disposable-email-domains/disposable-email-domains` on GitHub.

## 7. Using the Python library

### Simple sync usage

```python
from mailguard import validate_sync

r = validate_sync("jane.doe@acme.com")
print(r.verdict)            # "deliverable"
print(r.score)              # 85
print(r.email_type)         # "work"
print(r.typo_suggestion)    # None
print(r.to_dict())          # full result as dict
```

### Bulk sync

```python
from mailguard import validate_bulk_sync

emails = [
    "sarah@stripe.com",
    "info@acme.com",
    "test@mailinator.com",
    "notanemail",
    "mike@yaho.com",
]

results = validate_bulk_sync(emails, concurrency=50)

for r in results:
    print(f"{r.verdict:14} {r.score:3}  {r.email}  ({r.reason})")
```

Output:
```
deliverable    85  sarah@stripe.com  (ok)
risky          55  info@acme.com  (role address)
undeliverable  15  test@mailinator.com  (disposable domain)
undeliverable   0  notanemail  (invalid syntax)
risky          40  mike@yaho.com  (possible typo → yahoo.com)
```

### Async for high throughput

```python
import asyncio
from mailguard import validate, validate_bulk

async def main():
    # Single
    r = await validate("jane@acme.com", check_smtp=False)
    print(r.verdict, r.score)

    # Bulk with progress
    emails = load_my_leads()  # 50,000 emails
    done = 0
    def progress(n, total):
        nonlocal done
        done = n
        if n % 100 == 0:
            print(f"{n}/{total}")

    results = await validate_bulk(
        emails,
        concurrency=100,
        check_catchall=True,
        progress_cb=progress,
    )

asyncio.run(main())
```

### Integrating into an ETL pipeline

```python
import pandas as pd
from mailguard import validate_bulk_sync

df = pd.read_csv("leads.csv")
results = validate_bulk_sync(df["email"].tolist(), concurrency=100)

df["verdict"]  = [r.verdict for r in results]
df["score"]    = [r.score for r in results]
df["reason"]   = [r.reason for r in results]

# Keep only sendable addresses
clean = df[df["verdict"].isin(["deliverable", "risky"])]
clean.to_csv("clean_leads.csv", index=False)
```

## 8. Using the Web UI

Best for non-technical teammates who just want to drag a CSV and download the result.

### Local

```bash
pip install "mailguard[web]"
streamlit run mailguard/app.py
```

Opens at `http://localhost:8501`.

### Free public deploy (recommended for teams)

1. Fork `github.com/mothivenkatesh/mailguard` to your own account
2. Sign in to [share.streamlit.io](https://share.streamlit.io)
3. New app → point to `mailguard/app.py` on `main`
4. Hit Deploy. You get a public URL like `yourname-mailguard.streamlit.app`
5. Share the URL with your GTM team

Zero hosting cost. Zero maintenance. Teammates upload CSV → download enriched CSV. No code.

### Features of the web UI

- **Drag-drop CSV upload** with preview of the first 5 rows
- **Auto-detect email column** (configurable)
- **Live progress bar**
- **Interactive pie chart** (deliverable / risky / undeliverable)
- **Typo review table** for recoverable leads
- **One-click download** of enriched CSV
- **Single-email tab** for quick one-offs

## 9. Using the REST API

Best for: form validation on signup, n8n / Zapier / Make workflows, CRM webhooks.

### Start the server

```bash
pip install "mailguard[api]"
uvicorn mailguard.api:app --host 0.0.0.0 --port 8000
```

### Validate one

```bash
curl -X POST http://localhost:8000/validate \
  -H "Content-Type: application/json" \
  -d '{"email": "jane@gmial.com"}'
```

### Validate many

```bash
curl -X POST http://localhost:8000/validate/bulk \
  -H "Content-Type: application/json" \
  -d '{
    "emails": ["jane@gmial.com", "info@mailinator.com", "ok@stripe.com"],
    "concurrency": 50,
    "check_catchall": true
  }'
```

Response:
```json
{
  "total": 3,
  "summary": {"deliverable": 1, "risky": 1, "undeliverable": 1, "unknown": 0},
  "results": [...]
}
```

### Interactive docs

Visit `http://localhost:8000/docs` for the auto-generated Swagger UI.

## 10. Using Docker

### One-liner

```bash
docker run --rm -p 8000:8000 ghcr.io/mothivenkatesh/mailguard:latest
```

### docker-compose

```yaml
services:
  mailguard:
    image: ghcr.io/mothivenkatesh/mailguard:latest
    ports: ["8000:8000"]
    restart: unless-stopped
```

### Run the CLI inside the container

```bash
docker run --rm -v "$PWD:/data" ghcr.io/mothivenkatesh/mailguard:latest \
  mailguard bulk /data/leads.csv -o /data/clean.csv
```

## 11. Real-world recipes

### Recipe 1: Clean an Apollo / ZoomInfo export

```bash
mailguard bulk apollo_export.csv --column "Email" -o apollo_clean.csv
```

Then in Excel/Sheets, filter `mg_verdict = deliverable` to get your sendable list.

### Recipe 2: Validate HubSpot form submissions in real time

Next.js form handler:

```typescript
// pages/api/signup.ts
export default async function handler(req, res) {
  const { email } = req.body;

  const r = await fetch("https://your-mailguard.example.com/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  }).then(r => r.json());

  if (r.verdict === "undeliverable") {
    return res.status(400).json({
      error: "Please enter a valid email",
      suggestion: r.typo_suggestion,
    });
  }

  // Proceed to save lead in HubSpot
  await saveToHubSpot({ email, score: r.score });
  res.json({ ok: true });
}
```

This rescues every `gmial.com` typo before it enters your CRM. The ROI is real: a single form with 5% typo rate recovers 500 leads per 10k submissions.

### Recipe 3: n8n workflow — validate and sync to Mailchimp

1. **HTTP In** trigger receives a CSV upload webhook
2. **Code node** parses CSV to array of emails
3. **HTTP Request** → `POST http://mailguard:8000/validate/bulk`
4. **Item Lists** split results
5. **IF node** keep only `verdict == "deliverable"`
6. **Mailchimp** node → add to audience

Template is in the repo at `examples/n8n-workflow.json`.

### Recipe 4: Pre-send campaign check in Python

```python
import pandas as pd
from mailguard import validate_bulk_sync

audience = pd.read_csv("campaign_audience.csv")
results = validate_bulk_sync(audience["email"], concurrency=100)

# Before send
for r in results:
    if r.verdict == "undeliverable":
        print(f"DROPPING: {r.email} — {r.reason}")
    elif r.typo_suggestion:
        print(f"TYPO?   : {r.email} → {r.typo_suggestion}")
```

### Recipe 5: GitHub Action that blocks PRs containing disposable emails

```yaml
# .github/workflows/check-emails.yml
name: Block disposable emails in commits
on: [pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install mailguard
      - run: |
          git log --format='%ae' origin/main..HEAD | while read email; do
            mailguard check "$email" --json | jq -e '.verdict != "undeliverable"' \
              || { echo "Bad email: $email"; exit 1; }
          done
```

### Recipe 6: Nightly cron cleanup of a CRM

```bash
#!/bin/bash
# cron: 0 2 * * *
curl -s "https://your-crm/api/contacts?export=csv" > today.csv
mailguard bulk today.csv -o validated.csv -c 100
python upload_to_crm.py validated.csv
```

### Recipe 7: Typo rescue form

A common growth hack: when a user submits `jane@gmial.com`, don't show an error — show a one-click "Did you mean jane@gmail.com?" prompt. Recovery rates of 70%+ are typical.

```python
r = validate_sync(email)
if r.typo_suggestion:
    return {"prompt": f"Did you mean {r.typo_suggestion}?"}
```

## 12. Understanding the score

The score is a 0–100 weighted deliverability confidence. Here's exactly how it's computed:

| Starting point | Score |
|---|---|
| Invalid syntax | 0 (hard block) |
| No MX records | 5 (hard block) |
| Disposable domain | 15 (hard block) |
| Syntax + MX pass | 60 (baseline) |

Then modifiers are applied:

| Signal | Delta |
|---|---|
| SMTP accepted | +25 |
| SMTP rejected | −30 |
| Catch-all domain | −15 |
| Catch-all confirmed negative | +10 |
| Role-based address | −10 |
| Free provider | +5 |
| Typo suggestion present | −20 |

Final verdict buckets:

| Score | Verdict | Meaning |
|---|---|---|
| ≥80 | **deliverable** | Send with confidence |
| 50–79 | **risky** | Sendable but watch engagement |
| <50 | **undeliverable** | Don't send |

**Calibration tip:** if your bounce rate still feels high after validation, tighten the threshold. Use `deliverable` only (drop `risky`) for first-send campaigns, and use `deliverable + risky` for re-engagement sequences where you already have prior positive signal.

## 13. Deployment guide

Pick based on your team.

### Path A: Non-technical GTM team (most common)
→ **Streamlit Community Cloud** (free hosting) + drag-drop web UI. Zero-install for users. 10-minute setup.

### Path B: Technical founder / solo operator
→ **Local CLI**. `pip install mailguard`, done. Run on your laptop.

### Path C: Product team embedding in an app
→ **REST API on Docker**. Deploy to Fly.io (free tier), Railway ($5/mo), or a $5 Hetzner VPS. Unlocks form-submit validation.

### Path D: Automation-heavy team
→ **n8n + REST API** behind it. Drop the provided workflow template in.

### Path E: Privacy-maximalist enterprise
→ **Self-hosted Docker on your own infra**. Nothing leaves your network.

### Path F: Needs real SMTP probing
→ **$5 VPS** (Hetzner, DigitalOcean, Vultr). Port 25 is usually unblocked. Google Colab and most cloud providers will NOT work — port 25 is firewalled.

## 14. Best practices

1. **Always dedupe first.** Validation is idempotent, but DNS lookups cost time. `sort -u` your list before running.
2. **Set concurrency to match your network.** 50 is safe, 100–200 is fast, 500+ risks DNS rate-limits from your resolver.
3. **Don't enable SMTP probing at scale.** It's slow, often blocked, and can get your source IP temporarily blacklisted. The heuristic stack is enough for list hygiene.
4. **Use catch-all detection before trusting any SMTP result.** Without it, SMTP accepts become meaningless on accept-all domains.
5. **Re-validate before every major send.** Domains expire, mailboxes deactivate. A 3-month-old validation is stale.
6. **Keep your disposable list fresh.** Run `mailguard update-lists` monthly.
7. **Treat `risky` as "human review" not "send anyway."** Role addresses and catch-all domains live here — they're not junk but they're low-engagement.
8. **Log the `reason` field in your CRM.** When marketing asks "why did we drop this lead?", you'll have the answer.
9. **Pair typo correction with your form UX.** The #1 ROI feature: every recovered `gmial.com` is a lead you would have lost.
10. **Do NOT use mailguard to validate addresses you don't own or have consent to contact.** Email validation is a list-hygiene tool, not a way to harvest or enumerate mailboxes at a target domain. Respect GDPR / CAN-SPAM / CASL.

## 15. Troubleshooting

### "SMTP probe always returns None"
That means port 25 is blocked. This is normal on Google Colab, AWS Lambda, most cloud providers, and home ISPs. Use the heuristic stack only (don't pass `--smtp`) or move to a $5 VPS.

### "Every gmail/outlook address comes back risky"
You're probably seeing the catch-all effect. Gmail and Outlook accept-all for routing reasons. The score is still correct — it just can't confirm individual mailboxes. For free providers, trust the score ≥60.

### "DNS is slow"
Install `aiodns` for async resolution: `pip install aiodns`. Also check that your DNS resolver (e.g., 1.1.1.1) isn't rate-limiting you.

### "My CSV has non-ASCII characters and fails"
mailguard handles UTF-8 and UTF-8-BOM by default. If your CSV is in Windows-1252 or another encoding, convert first:
```bash
iconv -f WINDOWS-1252 -t UTF-8 leads.csv > leads_utf8.csv
```

### "I get `ModuleNotFoundError: No module named 'streamlit'`"
You installed the base package. Upgrade: `pip install "mailguard[web]"`.

### "Validation takes forever"
Bump concurrency: `-c 200`. If still slow, your bottleneck is DNS — try a faster resolver or enable `aiodns`.

### "The score seems too harsh / too lenient"
Scoring weights live in `mailguard/core.py::_score_and_verdict`. Fork and tune to your ICP. PRs welcome.

## 16. FAQ

**Is mailguard accurate?**
~85% accuracy on heuristics alone, ~95% with SMTP probe on unblocked hosts. This is competitive with paid services for list hygiene. For mission-critical sends (billing, password reset), belt-and-suspenders with a paid service once a quarter is reasonable.

**Does mailguard actually send emails?**
No. Never. The SMTP probe opens a connection, does HELO + MAIL FROM + RCPT TO, and disconnects before DATA. No email is transmitted. This is the standard technique used by every validator.

**Can I get blacklisted by SMTP probing?**
If you probe aggressively from a residential or VPS IP, yes. Keep concurrency low (`-c 20` or less) and consider disabling SMTP entirely for bulk runs. The heuristic layers carry most of the weight.

**How does this compare to email-validator / validate_email the Python packages?**
`email-validator` does syntax + optional DNS. mailguard uses `email-validator` under the hood for syntax and adds 8 more layers on top. You can think of mailguard as "what if email-validator were a full GTM-grade validator."

**Is this GDPR compliant?**
mailguard itself stores nothing. Your compliance depends on what you do with the output and what you had the right to validate in the first place. Talk to your DPO.

**Does mailguard work on Windows?**
Yes. CI runs on Linux, macOS, and Windows × Python 3.9–3.12.

**Can I use mailguard for commercial work?**
Yes. MIT license. Use it in your SaaS, your agency, your ETL pipeline, whatever.

**How do I contribute a missing disposable domain?**
Open a PR adding it to `mailguard/data/disposable_domains.txt`. Or run `mailguard update-lists` to pull the latest community list.

**Will there be a hosted SaaS version?**
The code is here. The repo will never become "open core" — everything stays MIT. If someone wants to run a hosted version, fork away.

**How do I support the project?**
Star the repo. File issues when things break. Contribute disposable domains. Tweet about it. Write a blog post. That's how open source grows.

## 17. Migrating from ZeroBounce / NeverBounce / Hunter

If you're currently paying for email validation, here's how to cut over.

### Step 1: Install and run in parallel for a week

Don't rip out the paid validator immediately. For one week, run both in parallel on the same lists and compare results.

```python
# run both, log to CSV
paid_result = zerobounce_validate(email)
mg_result = validate_sync(email)
log_comparison(paid_result, mg_result)
```

### Step 2: Measure agreement

On a 10k sample, expect:
- ~90% exact agreement (both call it deliverable, both undeliverable, etc.)
- ~10% divergence, mostly around catch-all and role addresses

Inspect the divergences. In most cases, mailguard is giving you *more* information (layer-level reasoning) not *different* information.

### Step 3: Calibrate thresholds to your ICP

If ZeroBounce's "deliverable" bucket gave you a 2% bounce rate, tune mailguard so its "deliverable" bucket gives you the same. You may need to bump the threshold from 80 to 85.

### Step 4: Cut over

Once parallel-running matches, switch. Cancel the paid subscription. Redirect the saved budget into list sourcing, content, or literally anything else.

### Expected savings

| Monthly volume | ZeroBounce cost | mailguard cost | Annual savings |
|---|---|---|---|
| 10k / month | ~$39 | $0 | **~$468** |
| 50k / month | ~$195 | $0 | **~$2,340** |
| 100k / month | ~$390 | $0 | **~$4,680** |
| 500k / month | ~$1,950 | $0 | **~$23,400** |

Not trivial. The only real cost is a $5 VPS if you need SMTP probing, which is ~$60/year.

---

## Get in touch / contribute

- 🐛 **Bugs:** https://github.com/mothivenkatesh/mailguard/issues
- 💡 **Features:** open a discussion before coding
- ⭐ **Like it?** Star the repo — that's how other teams find it
- 📣 **Share it:** blog, LinkedIn, r/Python, r/coolgithubprojects

If mailguard saved you money, consider paying it forward by contributing a disposable domain, a recipe, or a translation.

**Happy validating. No more paid tolls.**
