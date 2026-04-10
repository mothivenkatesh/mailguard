# Contributing to mailguard

Thanks for your interest! mailguard is a community project — PRs, issues, and feedback are all welcome.

## Quick start

```bash
git clone https://github.com/mothivenkatesh/mailguard
cd mailguard
pip install -e ".[all]"
pytest
```

## What to work on

- Check the [good first issue](https://github.com/mothivenkatesh/mailguard/labels/good%20first%20issue) label
- Add new disposable domains to `mailguard/data/disposable_domains.txt`
- Improve typo detection (more common domains, better distance metric)
- Add CRM adapters (HubSpot, Salesforce, Mailchimp)
- Write more tests — aim for 85%+ coverage

## Guidelines

- Every new check layer must be independent and fault-tolerant (never crash the pipeline)
- Add tests for new behaviour
- Run `ruff check mailguard tests` before pushing
- Keep dependencies minimal — no new hard deps without discussion

## Submitting a PR

1. Fork the repo
2. Create a branch: `git checkout -b feat/my-thing`
3. Commit with a clear message
4. Push and open a PR
5. Wait for CI to pass

## Code of conduct

Be kind. We follow the [Contributor Covenant](https://www.contributor-covenant.org/).
