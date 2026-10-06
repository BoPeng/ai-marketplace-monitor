"""Top-level package for ai-marketplace-monitor."""

from importlib.metadata import PackageNotFoundError, version

__author__ = """Bo Peng"""
__email__ = "ben.bob@gmail.com"

# where users ask questions and share ideas (shown by aimm run and aimm configure)
DISCORD_URL = "https://discord.gg/2GJhstD7av"
COMMUNITY_MESSAGE = f"Questions or ideas? Join the aimm community on Discord: {DISCORD_URL}"

try:
    __version__ = version("ai-marketplace-monitor")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
