"""Embedded FastAPI web UI for AI Marketplace Monitor.

Provides a browser-based configuration editor and live log viewer that
runs alongside the monitor process. See webui.server.start_webui.
"""

from .log_handler import LogBroadcastHandler
from .server import WebUIConfig, WebUIServer, start_webui

__all__ = ["LogBroadcastHandler", "WebUIConfig", "WebUIServer", "start_webui"]
