"""FastAPI app factory and uvicorn-in-a-thread runner.

The monitor process stays fully synchronous. Uvicorn runs on its own
asyncio loop in a daemon thread; the LogBroadcastHandler bridges records
from the main thread to that loop via ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import secrets
import socket
import threading
import time

# Ensure the vendored toml-edit-js WASM bundle is served with the right
# Content-Type. Python's mimetypes module learned .wasm in 3.10 but
# explicit registration is safer across patch versions.
mimetypes.add_type("application/wasm", ".wasm")
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import uvicorn

from .auth import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    SESSION_TTL,
    AuthConfig,
    RateLimiter,
    SessionManager,
    hash_password,
    verify_password,
)
from .config_api import ConfigFileService
from .config_auth import extract_credentials, set_value_in_section
from .log_handler import LogBroadcastHandler


STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class WebUIConfig:
    host: str = "127.0.0.1"
    port: int = 8467
    config_files: List[Path] = field(default_factory=list)
    log_handler: LogBroadcastHandler | None = None


@dataclass
class StartupInfo:
    """Information about the running server, shown in the startup banner."""

    urls: List[str]
    username: str | None  # None in setup mode
    host: str
    port: int
    exposed: bool
    setup_mode: bool  # True if the first-run setup form should be shown


class AuthState:
    """Mutable auth state.

    In normal operation ``auth`` holds the active credentials and
    ``setup_mode`` is False. In setup mode ``auth`` is None until the
    user completes the first-run setup; after that ``auth`` is populated
    and setup mode is off. In "skipped" mode ``auth`` stays None and
    ``setup_mode`` is False — the web UI runs without authentication.
    """

    def __init__(self) -> None:
        self.auth: AuthConfig | None = None
        self.setup_mode: bool = False
        self.source: str = ""


def _resolve_auth(config: WebUIConfig) -> tuple[AuthState, StartupInfo]:
    """Build initial AuthState from the config file.

    If ``[marketplace.facebook]`` has a username and password, use those
    for web UI auth. Otherwise start in setup mode.
    """
    state = AuthState()
    extracted = extract_credentials(config.config_files)
    if extracted.username and extracted.password:
        state.auth = AuthConfig(
            username=extracted.username,
            password_hash=hash_password(extracted.password),
            secret_key=secrets.token_urlsafe(32),
        )
        state.source = "facebook"
        state.setup_mode = False
    else:
        state.auth = None
        state.setup_mode = True
        state.source = "setup"

    info = StartupInfo(
        urls=_enumerate_urls(config.host, config.port),
        username=state.auth.username if state.auth else None,
        host=config.host,
        port=config.port,
        exposed=config.host not in ("127.0.0.1", "localhost", "::1"),
        setup_mode=state.setup_mode,
    )
    return state, info


def _set_session_cookies(response: Response, token: str, csrf: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="strict",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=SESSION_TTL,
        httponly=False,  # JS reads this to echo via header
        samesite="strict",
    )


def _write_marketplace_credentials(
    config_service: ConfigFileService,
    username: str,
    password: str,
) -> None:
    """Write Facebook credentials into the config during first-run setup.

    Goes through the same atomic-write and validation path as a regular
    editor save, so we can't corrupt the file.
    """
    content, mtime = config_service.read("primary")
    new_content, _ = set_value_in_section(
        content, "marketplace.facebook", "username", username
    )
    new_content, _ = set_value_in_section(
        new_content, "marketplace.facebook", "password", password
    )
    _, ok, error = config_service.write("primary", new_content, base_mtime=mtime)
    if not ok:
        raise RuntimeError(error or "config write failed")


def _enumerate_urls(host: str, port: int) -> List[str]:
    if host in ("127.0.0.1", "localhost", "::1"):
        return [f"http://127.0.0.1:{port}"]
    if host in ("0.0.0.0", "::"):
        # Enumerate local interface addresses so the user sees every reachable URL.
        urls = [f"http://127.0.0.1:{port}"]
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None):
                addr = info[4][0]
                if addr and addr not in ("127.0.0.1", "::1"):
                    if ":" in addr:
                        urls.append(f"http://[{addr}]:{port}")
                    else:
                        urls.append(f"http://{addr}:{port}")
        except socket.gaierror:
            pass
        # De-duplicate preserving order.
        seen: set[str] = set()
        unique: List[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        return unique
    return [f"http://{host}:{port}"]


def create_app(
    config: WebUIConfig,
    state: AuthState,
    config_service: ConfigFileService,
    log_handler: LogBroadcastHandler,
) -> FastAPI:
    app = FastAPI(
        title="AI Marketplace Monitor",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # Session manager uses a stable secret for the process lifetime
    # regardless of whether auth is on at the moment. This way sessions
    # issued during setup mode remain valid after the user completes
    # setup and populates state.auth.
    process_secret = secrets.token_urlsafe(32)
    sessions = SessionManager(process_secret)
    rate_limiter = RateLimiter()

    def is_open() -> bool:
        """True if the server is running without authentication — i.e.
        the user has skipped setup. Setup mode is NOT open: endpoints
        still 401 so the frontend falls through to the setup form.
        """
        return state.auth is None and not state.setup_mode

    def require_session(
        request: Request,
        session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> str:
        if is_open():
            return "anonymous"
        if session is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        username = sessions.validate(session)
        if username is None:
            raise HTTPException(status_code=401, detail="Session expired")
        return username

    def require_csrf(
        request: Request,
        csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    ) -> None:
        if is_open():
            return  # open mode skips CSRF (nothing to protect)
        header = request.headers.get(CSRF_HEADER)
        if not header or not csrf_cookie or not secrets.compare_digest(header, csrf_cookie):
            raise HTTPException(status_code=403, detail="CSRF token mismatch")

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/api/auth/info")
    async def auth_info() -> Dict[str, Any]:
        """Unauthenticated — the login screen calls this to decide
        between sign-in and first-run setup.
        """
        return {
            "mode": state.source or "setup-mode",
            "setup_mode": state.setup_mode,
            "open": is_open(),
            "username_hint": state.auth.username if state.auth else None,
        }

    @app.post("/api/login")
    async def login(
        request: Request,
        response: Response,
        username: str = Form(...),
        password: str = Form(...),
    ) -> Dict[str, Any]:
        client_ip = request.client.host if request.client else "unknown"
        if rate_limiter.is_locked(client_ip):
            raise HTTPException(status_code=429, detail="Too many failed attempts")

        # ------- Setup mode -------
        # No credentials configured yet. Accept whatever the user types,
        # write them into [marketplace.facebook] of the config, and
        # promote the server to authenticated mode with those creds.
        if state.setup_mode and state.auth is None:
            if not username or not password:
                raise HTTPException(status_code=400, detail="Username and password required")

            try:
                _write_marketplace_credentials(config_service, username, password)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to save credentials to config: {e}",
                )

            state.auth = AuthConfig(
                username=username,
                password_hash=hash_password(password),
                secret_key=process_secret,
            )
            state.setup_mode = False
            state.source = "facebook"

            token, csrf = sessions.issue(username)
            _set_session_cookies(response, token, csrf)
            return {"username": username, "csrf": csrf, "setup_completed": True}

        # ------- Normal login -------
        if state.auth is None:
            # "Skipped" open mode — login is a no-op but still issues
            # a session so the UI shows an authenticated state.
            token, csrf = sessions.issue(username or "anonymous")
            _set_session_cookies(response, token, csrf)
            return {"username": username or "anonymous", "csrf": csrf}

        if username != state.auth.username or not verify_password(
            password, state.auth.password_hash
        ):
            rate_limiter.record_failure(client_ip)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        rate_limiter.reset(client_ip)
        token, csrf = sessions.issue(username)
        _set_session_cookies(response, token, csrf)
        return {"username": username, "csrf": csrf}

    @app.post("/api/setup/skip")
    async def setup_skip(response: Response) -> Dict[str, Any]:
        """Dismiss the first-run setup form and enter the editor without
        authentication. The server stays in open mode for the rest of
        the process lifetime.
        """
        if not state.setup_mode:
            raise HTTPException(status_code=400, detail="Not in setup mode")
        state.setup_mode = False
        state.source = "skipped"
        # Issue a cosmetic session so the UI has something to hold onto.
        token, csrf = sessions.issue("anonymous")
        _set_session_cookies(response, token, csrf)
        return {"ok": True, "open": True}

    @app.post("/api/logout")
    async def logout(response: Response) -> Dict[str, Any]:
        response.delete_cookie(SESSION_COOKIE)
        response.delete_cookie(CSRF_COOKIE)
        return {"ok": True}

    @app.get("/api/status")
    async def status(_: str = Depends(require_session)) -> Dict[str, Any]:
        files = config_service.list_files()
        return {
            "config_files": [f.__dict__ for f in files],
            "urls": _enumerate_urls(config.host, config.port),
            "auth_mode": state.source,
            "open": is_open(),
        }

    @app.get("/api/config/files")
    async def list_config_files(_: str = Depends(require_session)) -> Dict[str, Any]:
        return {"files": [f.__dict__ for f in config_service.list_files()]}

    @app.get("/api/config/file/{file_id}")
    async def get_config_file(
        file_id: str, _: str = Depends(require_session)
    ) -> Dict[str, Any]:
        try:
            content, mtime = config_service.read(file_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        from .config_api import scan_sections
        from .secrets_redact import MASK, has_mask

        sections = [
            {
                "name": s.name,
                "prefix": s.prefix,
                "suffix": s.suffix,
                "line_start": s.line_start,
                "line_end": s.line_end,
                "fields": s.fields,
            }
            for s in scan_sections(content)
        ]
        return {
            "content": content,
            "mtime": mtime,
            "has_masked_secrets": has_mask(content),
            "mask_token": MASK,
            "sections": sections,
        }

    @app.put("/api/config/file/{file_id}")
    async def put_config_file(
        file_id: str,
        body: Dict[str, Any],
        _: str = Depends(require_session),
        __: None = Depends(require_csrf),
    ) -> Dict[str, Any]:
        content = body.get("content")
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail="Missing 'content' field")
        base_mtime = body.get("base_mtime")
        try:
            new_mtime, ok, error = config_service.write(
                file_id, content, base_mtime if isinstance(base_mtime, (int, float)) else None
            )
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        if not ok:
            status_code = 409 if error and "conflict" in error else 400
            return JSONResponse(
                status_code=status_code,
                content={"ok": False, "error": error, "mtime": new_mtime},
            )
        return {"ok": True, "mtime": new_mtime}

    @app.post("/api/config/validate")
    async def validate_config(
        body: Dict[str, Any],
        _: str = Depends(require_session),
        __: None = Depends(require_csrf),
    ) -> Dict[str, Any]:
        content = body.get("content")
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail="Missing 'content' field")
        ok, error = config_service.validate(content)
        return {"valid": ok, "error": error}

    @app.post("/api/monitor/restart")
    async def restart_monitor(
        _: str = Depends(require_session),
        __: None = Depends(require_csrf),
    ) -> Dict[str, Any]:
        """Wake the monitor by touching the config file. The file watcher
        interrupts the monitor's doze() sleep, causing it to reload the
        config and run all scheduled searches immediately.
        """
        try:
            path = config_service.editable_path
            path.touch()
            return {"ok": True, "message": "Monitor woken — searching all items now."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to touch config: {e}")

    @app.get("/api/logs")
    async def get_logs(
        limit: int = 500,
        level: str = "DEBUG",
        kind: str | None = None,
        item: str | None = None,
        min_score: int | None = None,
        _: str = Depends(require_session),
    ) -> Dict[str, Any]:
        level_value = logging.getLevelName(level.upper())
        if not isinstance(level_value, int):
            level_value = 0
        return {
            "records": log_handler.snapshot(
                limit=limit,
                min_level=level_value,
                kind=kind,
                item=item,
                min_score=min_score,
            ),
            "capacity": log_handler._buffer.maxlen,
        }

    @app.websocket("/ws/stream")
    async def ws_stream(websocket: WebSocket) -> None:
        # Cookie-based auth on the WebSocket handshake.
        session = websocket.cookies.get(SESSION_COOKIE)
        if not session or sessions.validate(session) is None:
            await websocket.close(code=4401)
            return

        await websocket.accept()
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=1000)
        log_handler.subscribe(queue)
        try:
            # Send a brief hello so clients know the stream is live.
            await websocket.send_json({"type": "hello", "time": time.time()})
            while True:
                payload = await queue.get()
                await websocket.send_json({"type": "log", "record": payload})
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            log_handler.unsubscribe(queue)

    # ------------------------------------------------------------------
    # Static UI
    # ------------------------------------------------------------------
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


# ----------------------------------------------------------------------
# Thread runner
# ----------------------------------------------------------------------


class WebUIServer:
    """Runs uvicorn in a background thread."""

    def __init__(
        self,
        config: WebUIConfig,
        state: AuthState,
        config_service: ConfigFileService,
    ) -> None:
        if config.log_handler is None:
            raise ValueError("WebUIConfig.log_handler is required")
        self._config = config
        self._state = state
        self._config_service = config_service
        self._app = create_app(config, state, config_service, config.log_handler)
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        uv_config = uvicorn.Config(
            self._app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        self._server = uvicorn.Server(uv_config)

        def runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            assert self._config.log_handler is not None
            self._config.log_handler.attach_loop(loop)
            self._ready.set()
            try:
                loop.run_until_complete(self._server.serve())  # type: ignore[union-attr]
            finally:
                loop.close()

        self._thread = threading.Thread(target=runner, name="aimm-webui", daemon=True)
        self._thread.start()
        # Give the loop a moment to bind so attach_loop completes before
        # any log records are emitted.
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True


def start_webui(
    config: WebUIConfig, logger: logging.Logger | None = None
) -> tuple[WebUIServer, StartupInfo]:
    """Resolve auth, build the service, and start the server thread."""
    if config.log_handler is None:
        raise ValueError("WebUIConfig.log_handler is required")
    state, info = _resolve_auth(config)

    # Safety: setup mode / open mode requires loopback. Refuse to start
    # if the server would expose an unauthenticated editor on a LAN.
    if state.auth is None and info.exposed:
        raise RuntimeError(
            f"Refusing to start an unauthenticated web UI on {config.host}. "
            "Set credentials in [webui] or [marketplace.*] of your config, "
            "pass --webui-password, or bind to 127.0.0.1."
        )

    config_service = ConfigFileService(config.config_files, logger=logger)
    server = WebUIServer(config, state, config_service)
    server.start()
    return server, info
