"""Config normalization: expand() for AI editing, normalize() for what is written to disk."""

from .core import expand, normalize
from .effective import check_equivalent, effective_view
from .model import Change, NormalizeError, NormalizeResult

__all__ = [
    "Change",
    "NormalizeError",
    "NormalizeResult",
    "check_equivalent",
    "effective_view",
    "expand",
    "normalize",
]
