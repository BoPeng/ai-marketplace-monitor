"""Section builders, by section type."""

from typing import Dict

from ..sections import SectionBuilder
from .ai import ScriptedAIBuilder

BUILDERS: Dict[str, SectionBuilder] = {"ai": ScriptedAIBuilder()}
