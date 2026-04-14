"""Top-level package for ai-marketplace-monitor."""

from importlib.metadata import PackageNotFoundError, version

__author__ = """Bo Peng"""
__email__ = "ben.bob@gmail.com"

try:
    __version__ = version("ai-marketplace-monitor")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
