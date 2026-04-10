"""mailguard — async bulk email validator with layered deliverability scoring."""

from mailguard.core import (
    ValidationResult,
    validate,
    validate_bulk,
    validate_bulk_sync,
    validate_sync,
)

__version__ = "0.2.0"
__all__ = [
    "ValidationResult",
    "validate",
    "validate_sync",
    "validate_bulk",
    "validate_bulk_sync",
    "__version__",
]
