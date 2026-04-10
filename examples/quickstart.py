"""Minimal usage example."""
from mailguard import validate_bulk_sync, validate_sync

# Single email
r = validate_sync("jane@gmial.com")
print(f"{r.email}: {r.verdict} (score {r.score})")
if r.typo_suggestion:
    print(f"  Did you mean: {r.typo_suggestion}?")

# Bulk
emails = [
    "sarah.chen@stripe.com",
    "info@acme.com",
    "test@mailinator.com",
    "notanemail",
    "mike@yaho.com",
]
results = validate_bulk_sync(emails, concurrency=20)
for r in results:
    print(f"{r.verdict:14} {r.score:3}  {r.email}  ({r.reason})")
