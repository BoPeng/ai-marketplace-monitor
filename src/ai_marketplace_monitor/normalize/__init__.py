"""Config normalization: expand() for AI editing (normalize() follows in Task 10)."""

from .core import expand
from .effective import check_equivalent, effective_view
from .model import Change, NormalizeError, NormalizeResult

__all__ = [
    "Change",
    "NormalizeError",
    "NormalizeResult",
    "check_equivalent",
    "effective_view",
    "expand",
]
