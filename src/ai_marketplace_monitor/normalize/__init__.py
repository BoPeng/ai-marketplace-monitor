"""Config normalization: canonical form for AI editing, compact form for people."""

from .effective import check_equivalent, effective_view
from .model import Change, NormalizeError, NormalizeResult

__all__ = ["Change", "NormalizeError", "NormalizeResult", "check_equivalent", "effective_view"]
