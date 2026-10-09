"""FastAPI app factory and uvicorn-in-a-thread runner.

The monitor process stays fully synchronous. Uvicorn runs on its own
asyncio loop in a daemon thread; the LogBroadcastHandler bridges records
from the main thread to that loop via ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import mimetypes
import os
import secrets
import socket
import sqlite3
import threading
import time
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import uvicorn
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
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .. import __version__
from ..configure.flow import (
    ConfigureAddressError,
    configure_front_door,
    configure_section,
    validate_section_address,
)
from ..configure.ui import JsonSetupUI, SetupClosedError
from ..control import control
from ..evaluations import SORT_KEYS, STAGES, filter_evaluations, iter_evaluations
from ..notification import NotificationConfig
from ..update_check import (
    can_restart,
    current_notice,
    restart_later,
    self_update_status,
    start_self_update,
)
from ..user import UserConfig, send_test_notifications
from ..utils import (
    CacheCorruptedError,
    cache,
    cache_counts,
    clear_cache,
    hilight,
    is_cache_broken,
)
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
from .config_auth import extract_credentials
from .evaluations_export import MAX_LIMIT, iter_evaluations_csv
from .found_export import iter_found_csv, iter_found_rows
from .log_handler import LogBroadcastHandler
from .proxy_auth import AUTH_PROXY, ProxyAuth, ProxyAuthError

# Ensure the vendored toml-edit-js WASM bundle is served with the right
# Content-Type. Python's mimetypes module learned .wasm in 3.10 but
# explicit registration is safer across patch versions.
mimetypes.add_type("application/wasm", ".wasm")

STATIC_DIR = Path(__file__).parent / "static"
# Errors from loading the config or reading the cache are logged, not returned: responses
# carry these fixed messages, which point to the log.
CONFIG_ERROR = "The configuration cannot be loaded; see the log for the error."
CACHE_ERROR = "The cache database cannot be read; see the log for the error."


def _host_port(host: str, default_port: int) -> tuple[str, int]:
    """Return a normalized host and port from a Host-style header."""
    parsed = urlparse(f"//{host}")
    if parsed.hostname is None:
        return "", default_port
    try:
        port = parsed.port
    except ValueError:
        return "", default_port
    return parsed.hostname.rstrip(".").lower(), port or default_port


def _origin_matches_host(origin: str | None, host: str | None) -> bool:
    """True when a browser WebSocket Origin matches the request Host."""
    if not origin or not host:
        return False
    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return False
    try:
        origin_port = parsed.port
    except ValueError:
        return False
    default_port = 443 if parsed.scheme == "https" else 80
    origin_host = parsed.hostname.rstrip(".").lower()
    request_host, request_port = _host_port(host, default_port)
    return origin_host == request_host and (origin_port or default_port) == request_port


def _select_vnc_subprotocol(header: str | None) -> str | None:
    """Return a WebSocket subprotocol only when the client requested it."""
    if not header:
        return None
    requested = {part.strip().lower() for part in header.split(",")}
    return "binary" if "binary" in requested else None


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
    username: str | None  # None in open and proxy mode
    host: str
    port: int
    exposed: bool
    proxy_auth: bool = False  # a reverse proxy signs users in (AIMM_WEBUI_AUTH)
    proxy_check: str = ""  # what each request must carry, for the banner
    proxy_verified: bool = False  # requests cannot pass by going around the proxy


class AuthState:
    """Mutable auth state.

    On loopback (default) the web UI is always open — no password
    required.  When ``--webui-host`` exposes the server on a
    non-loopback interface, ``auth`` must be set (credentials from
    a marketplace config section or environment variables).
    """

    def __init__(self) -> None:
        self.auth: AuthConfig | None = None
        self.exposed: bool = False
        # AIMM_WEBUI_AUTH other than password: a reverse proxy signs users in, so an exposed
        # web UI asks for no password but checks what the proxy adds on every request.
        # Sessions and CSRF tokens are still required: proxy credentials (cookies, cached
        # basic auth) are sent with cross-site requests too.
        self.proxy: ProxyAuth | None = None

    @property
    def proxy_auth(self) -> bool:
        return self.proxy is not None


def _resolve_auth(config: WebUIConfig) -> tuple[AuthState, StartupInfo]:
    """Build initial AuthState from config files and environment.

    On loopback the UI is always open.  When exposed (--webui-host),
    credentials are required — checked from ``[marketplace.*]`` config
    sections, then ``FACEBOOK_USERNAME`` / ``FACEBOOK_PASSWORD`` env
    vars.
    """
    exposed = config.host not in ("127.0.0.1", "localhost", "::1")
    state = AuthState()
    state.exposed = exposed
    if exposed:
        state.proxy = ProxyAuth.from_environment()

    if exposed and not state.proxy_auth:
        extracted = extract_credentials(config.config_files)
        if extracted.username and extracted.password:
            state.auth = AuthConfig(
                username=extracted.username,
                password_hash=hash_password(extracted.password),
                secret_key=secrets.token_urlsafe(32),
            )
        # If exposed with no credentials, start_webui() will reject this.

    info = StartupInfo(
        urls=_enumerate_urls(config.host, config.port),
        username=state.auth.username if state.auth else None,
        host=config.host,
        port=config.port,
        exposed=exposed,
        proxy_auth=state.proxy_auth,
        proxy_check=state.proxy.describe() if state.proxy else "",
        proxy_verified=bool(state.proxy and state.proxy.verified),
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


def _enumerate_urls(host: str, port: int) -> List[str]:
    if host in ("127.0.0.1", "localhost", "::1"):
        return [f"http://127.0.0.1:{port}"]
    if host in ("0.0.0.0", "::"):  # noqa: S104 — intentional bind-all
        # Enumerate local interface addresses so the user sees every reachable URL.
        urls = [f"http://127.0.0.1:{port}"]
        try:
            hostname = socket.gethostname()
            for info in socket.getaddrinfo(hostname, None):
                addr = str(info[4][0])
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

    process_secret = secrets.token_urlsafe(32)
    sessions = SessionManager(process_secret)
    rate_limiter = RateLimiter()

    def is_open() -> bool:
        """True when running on loopback — no password, session or CSRF token required."""
        return not state.exposed

    def no_password() -> bool:
        """True when signing in needs no password: on loopback, or behind a proxy."""
        return is_open() or state.proxy_auth

    def proxy_user(headers: Any) -> str | None:
        """The user the reverse proxy signed in; None when no proxy signs users in.

        Raises ProxyAuthError when the request did not come through the proxy's sign-in.
        """
        return state.proxy.identify(headers) if state.proxy is not None else None

    def require_session(
        request: Request,
        session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    ) -> str:
        if is_open():
            return "anonymous"
        # every request, not only signing in: ending the proxy session ends access to aimm
        try:
            user = proxy_user(request.headers)
        except ProxyAuthError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e
        if session is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        username = sessions.validate(session)
        if username is None:
            raise HTTPException(status_code=401, detail="Session expired")
        return user or username

    def require_csrf(
        request: Request,
        csrf_cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE),
    ) -> None:
        if is_open():
            return  # open mode skips CSRF (nothing to protect)
        header = request.headers.get(CSRF_HEADER)
        if not header or not csrf_cookie or not secrets.compare_digest(header, csrf_cookie):
            raise HTTPException(status_code=403, detail="CSRF token mismatch")

    def websocket_rejection_code(websocket: WebSocket) -> int | None:
        if not _origin_matches_host(
            websocket.headers.get("origin"), websocket.headers.get("host")
        ):
            return 4403
        if is_open():
            return None
        try:
            proxy_user(websocket.headers)
        except ProxyAuthError:
            return 4401
        session = websocket.cookies.get(SESSION_COOKIE)
        if session and sessions.validate(session) is not None:
            return None
        return 4401

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/api/health")
    async def health() -> Dict[str, Any]:
        """For Docker's HEALTHCHECK and app stores: the web UI is up. Needs no session."""
        return {"ok": True}

    @app.get("/api/auth/info")
    def auth_info(request: Request) -> Dict[str, Any]:
        """Return auth mode info for the frontend login screen."""
        proxy_error = None
        try:
            proxy_user(request.headers)
        except ProxyAuthError as e:
            proxy_error = str(e)  # shown instead of a sign-in form that cannot help
        return {
            # the frontend signs in without asking for a password
            "open": no_password(),
            "username_hint": state.auth.username if state.auth else None,
            "proxy_error": proxy_error,
        }

    @app.post("/api/login")
    def login(
        request: Request,
        response: Response,
        username: str = Form(""),
        password: str = Form(""),
    ) -> Dict[str, Any]:
        # Loopback, or behind a reverse proxy that signs users in: no password needed.
        if no_password():
            try:
                user = proxy_user(request.headers)
            except ProxyAuthError as e:
                raise HTTPException(status_code=401, detail=str(e)) from e
            username = user or "anonymous"
            token, csrf = sessions.issue(username)
            _set_session_cookies(response, token, csrf)
            return {"username": username, "csrf": csrf}

        # Exposed — credentials required.
        client_ip = request.client.host if request.client else "unknown"
        if rate_limiter.is_locked(client_ip):
            raise HTTPException(status_code=429, detail="Too many failed attempts")

        assert state.auth is not None  # enforced by start_webui()
        if username != state.auth.username or not verify_password(
            password, state.auth.password_hash
        ):
            rate_limiter.record_failure(client_ip)
            raise HTTPException(status_code=401, detail="Invalid credentials")

        rate_limiter.reset(client_ip)
        token, csrf = sessions.issue(username)
        _set_session_cookies(response, token, csrf)
        return {"username": username, "csrf": csrf}

    @app.post("/api/logout")
    async def logout(response: Response) -> Dict[str, Any]:
        response.delete_cookie(SESSION_COOKIE)
        response.delete_cookie(CSRF_COOKIE)
        return {"ok": True}

    @app.get("/api/status")
    async def status(user: str = Depends(require_session)) -> Dict[str, Any]:
        files = config_service.list_files()
        return {
            "version": __version__,
            "config_files": [f.__dict__ for f in files],
            "urls": _enumerate_urls(config.host, config.port),
            "auth_mode": (
                "open"
                if is_open()
                else state.proxy.mode if state.proxy is not None else "authenticated"
            ),
            "open": no_password(),  # nothing to log out of
            # who is signed in; bare proxy mode does not know
            "user": (
                None
                if is_open() or (state.proxy is not None and state.proxy.mode == AUTH_PROXY)
                else user
            ),
            "vnc_enabled": os.environ.get("AIMM_ENABLE_VNC") == "1"
            and Path(os.environ.get("AIMM_NOVNC_DIR", "/usr/share/novnc")).is_dir(),
            "update": current_notice(),  # a newer release, if the update check found one
            "self_update": self_update_status(),
            "monitor": control.status(),  # paused, or waiting for the Facebook login
        }

    @app.post("/api/monitor/pause")
    async def pause_monitor(
        _: str = Depends(require_session),
        __: None = Depends(require_csrf),
    ) -> Dict[str, Any]:
        """Stop the monitor after the current listing, until started again (not kept across restarts)."""
        if not control.is_paused():
            control.pause()
            logging.getLogger("monitor").info(
                "[Pause] Stopping from the web UI: the monitor stops after the current listing."
            )
            # wake the monitor if it is sleeping until the next search, so it stops now
            with contextlib.suppress(OSError):
                config_service.editable_path.touch()
        return {"ok": True, **control.status()}

    @app.post("/api/monitor/resume", response_model=None)
    async def resume_monitor(
        _: str = Depends(require_session),
        __: None = Depends(require_csrf),
    ) -> Dict[str, Any]:
        """Start the monitor again: it reloads the config and searches all items now.

        The monitor stays stopped if the config on disk is invalid, so it does not start
        into a loop waiting for the config to be fixed.
        """
        try:
            ok, error = config_service.validate(
                config_service.editable_path.read_text(encoding="utf-8")
            )
        except OSError as e:
            logging.getLogger("monitor").error(f"[Pause] Cannot read the config: {e}")
            ok, error = False, "the configuration file cannot be read; see the log"
        if not ok:
            return JSONResponse(  # type: ignore[return-value]
                status_code=400,
                content={
                    "ok": False,
                    "error": f"The configuration is invalid, fix it before starting: {error}",
                    **control.status(),
                },
            )
        control.resume()
        return {"ok": True, **control.status()}

    @app.post("/api/update")
    async def update_aimm(
        _: str = Depends(require_session),
        __: None = Depends(require_csrf),
    ) -> Dict[str, Any]:
        """Install the newer release in the Docker container and restart aimm."""
        try:
            version = start_self_update(logging.getLogger("monitor"))
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        return {"ok": True, "version": version}

    # ------------------------------------------------------------------
    # Settings: test notifications, clear the cache
    # ------------------------------------------------------------------
    def load_users() -> Dict[str, UserConfig] | None:
        """The users of the config as the monitor reads it (notifications merged in).

        None if the config cannot be loaded (the error is logged).
        """
        from ..config import Config

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # unset variables: the test reports the channel
                return Config(list(config.config_files)).user
        except Exception as e:
            logging.getLogger("monitor").error(
                f"""{hilight("[Settings]", "fail")} The configuration cannot be loaded: {e}"""
            )
            return None

    # Sync defs (not async): FastAPI runs them in a threadpool, so loading the config,
    # sending test messages and scanning the cache never block the event loop.
    @app.get("/api/notifications/users")
    def notification_users(_: str = Depends(require_session)) -> Dict[str, Any]:
        users = load_users()
        if users is None:
            return {"ok": False, "error": CONFIG_ERROR, "users": []}
        return {
            "ok": True,
            "users": [
                {
                    "name": name,
                    "enabled": user.enabled is not False,
                    "channels": [c.notify_method for c in NotificationConfig.channels(user)],
                }
                for name, user in users.items()
            ],
        }

    @app.post("/api/notifications/test")
    def test_notifications(
        body: Dict[str, Any],
        _: str = Depends(require_session),
        __: None = Depends(require_csrf),
    ) -> Dict[str, Any]:
        """Send a test message through each channel of a user; nothing goes to the cache."""
        name = body.get("user")
        if not isinstance(name, str) or not name:
            raise HTTPException(status_code=400, detail="Missing 'user' field")
        users = load_users()
        if users is None:
            raise HTTPException(status_code=409, detail=CONFIG_ERROR)
        if name not in users:
            raise HTTPException(status_code=404, detail=f"There is no user {name}.")
        results = send_test_notifications(users, name, logger=logging.getLogger("monitor"))[name]
        return {
            "ok": bool(results) and all(r.ok for r in results),
            "user": name,
            "results": [asdict(r) for r in results],
        }

    @app.get("/api/cache")
    def cache_status(_: str = Depends(require_session)) -> Dict[str, Any]:
        """Entries of each type in the cache, or why the cache cannot be read."""
        try:
            if is_cache_broken(cache):
                raise CacheCorruptedError(str(cache.error))  # type: ignore[attr-defined]
            return {"broken": False, "counts": cache_counts(cache)}
        except (CacheCorruptedError, sqlite3.DatabaseError) as e:
            logging.getLogger("monitor").error(
                f"""{hilight("[Cache]", "fail")} The cache cannot be read: {e}"""
            )
            return {"broken": True, "error": CACHE_ERROR, "counts": {}}

    @app.post("/api/cache/clear")
    def clear_cache_entries(
        body: Dict[str, Any],
        _: str = Depends(require_session),
        __: None = Depends(require_csrf),
    ) -> Dict[str, Any]:
        """Clear one type of entries, or ``all``.

        Clearing a corrupted cache removes its files, and the running aimm can only open a new
        cache when it starts: in Docker it restarts, elsewhere the user restarts it.
        """
        clear_type = body.get("type")
        if not isinstance(clear_type, str) or not clear_type:
            raise HTTPException(status_code=400, detail="Missing 'type' field")
        logger = logging.getLogger("monitor")
        result = clear_cache(cache, clear_type)
        if not result.ok:
            raise HTTPException(status_code=400, detail=result.message)
        if result.error:
            logger.error(
                f"""{hilight("[Clear Cache]", "fail")} The cache cannot be read: {result.error}"""
            )
        logger.info(
            f"""{hilight("[Clear Cache]", "succ")} {clear_type}: {result.message} (web UI)"""
        )
        restart = None
        if result.removed:
            if can_restart():
                restart_later(logger)
                restart = "restarting"
            else:
                restart = "needed"
        return {"ok": True, "message": result.message, "restart": restart}

    @app.get("/api/config/files")
    async def list_config_files(_: str = Depends(require_session)) -> Dict[str, Any]:
        return {"files": [f.__dict__ for f in config_service.list_files()]}

    @app.get("/api/config/file/{file_id}")
    async def get_config_file(file_id: str, _: str = Depends(require_session)) -> Dict[str, Any]:
        try:
            content, mtime = config_service.read(file_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from None
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

    @app.put("/api/config/file/{file_id}", response_model=None)
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
            raise HTTPException(status_code=404, detail=str(e)) from None
        if not ok:
            status_code = 409 if error and "conflict" in error else 400
            return JSONResponse(  # type: ignore[return-value]
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
        """Wake the monitor by touching the config file.

        The file watcher interrupts the monitor's doze() sleep, causing
        it to reload the config and run all scheduled searches immediately.
        """
        try:
            path = config_service.editable_path
            path.touch()
            return {"ok": True, "message": "Monitor woken — searching all items now."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to touch config: {e}") from e

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
        # Require a same-origin browser handshake; when exposed, also require
        # a valid session cookie.
        rejection_code = await run_in_threadpool(websocket_rejection_code, websocket)
        if rejection_code is not None:
            await websocket.close(code=rejection_code)
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
        except Exception:  # noqa: S110 — client disconnected; nothing to handle
            pass
        finally:
            log_handler.unsubscribe(queue)

    @app.websocket("/ws/configure")
    async def ws_configure(websocket: WebSocket, section: str | None = None) -> None:
        """Run the AI-assisted configuration UI over a JSON WebSocket."""
        rejection_code = await run_in_threadpool(websocket_rejection_code, websocket)
        if rejection_code is not None:
            await websocket.close(code=rejection_code)
            return

        await websocket.accept()
        config_paths = list(config.config_files)
        ended_by_user: List[bool] = []  # End Chat: report "ended", however the flow returns

        def config_stamp() -> List[int | None]:
            return [p.stat().st_mtime_ns if p.exists() else None for p in config_paths]

        saved_stamp = config_stamp()

        async def send(payload: Dict[str, Any]) -> None:
            nonlocal saved_stamp
            # The session can write the config and keep going ("anything else?"),
            # so tell the page as soon as a file changes, not when the session ends.
            stamp = config_stamp()
            try:
                if stamp != saved_stamp:
                    saved_stamp = stamp
                    await websocket.send_json({"type": "config_saved"})
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect) as e:
                raise SetupClosedError from e

        async def send_if_open(payload: Dict[str, Any]) -> None:
            try:
                await send(payload)
            except SetupClosedError:
                pass

        async def receive() -> Dict[str, Any]:
            try:
                payload = await websocket.receive_json()
            except (RuntimeError, WebSocketDisconnect) as e:
                raise SetupClosedError from e
            if not isinstance(payload, dict):
                return {"type": "invalid", "value": payload}
            if payload.get("type") in ("cancel", "close"):
                ended_by_user.append(True)
            return payload

        ui = JsonSetupUI(send, receive, monitor_running=True)  # the web UI runs in the monitor

        try:
            if section:
                validate_section_address(section)
                exit_code = await configure_section(ui, config_paths, section)
            else:
                exit_code = await configure_front_door(ui, config_paths)
            done: Dict[str, Any] = {"type": "done", "exit_code": exit_code}
            if ended_by_user:
                done["cancelled"] = True
            await send_if_open(done)
        except SetupClosedError:
            await send_if_open({"type": "done", "exit_code": 0, "cancelled": True})
        except ConfigureAddressError as e:
            await send_if_open(
                {"type": "message", "kind": "error", "text": str(e), "markdown": False}
            )
            await send_if_open({"type": "done", "exit_code": 1})
        except Exception as e:
            await send_if_open(
                {
                    "type": "message",
                    "kind": "error",
                    "text": f"Configuration failed: {e}",
                    "markdown": False,
                }
            )
            await send_if_open({"type": "done", "exit_code": 1})

    # ------------------------------------------------------------------
    # Optional noVNC bridge (Docker deployments)
    # ------------------------------------------------------------------
    novnc_dir = os.environ.get("AIMM_NOVNC_DIR", "/usr/share/novnc")
    vnc_host = os.environ.get("AIMM_VNC_HOST", "127.0.0.1")
    vnc_port = int(os.environ.get("AIMM_VNC_PORT", "5900"))
    if os.environ.get("AIMM_ENABLE_VNC") == "1" and Path(novnc_dir).is_dir():
        app.mount("/vnc", StaticFiles(directory=novnc_dir, html=True), name="vnc")

        @app.websocket("/ws/vnc")
        async def ws_vnc(websocket: WebSocket) -> None:
            rejection_code = await run_in_threadpool(websocket_rejection_code, websocket)
            if rejection_code is not None:
                await websocket.close(code=rejection_code)
                return
            await websocket.accept(
                subprotocol=_select_vnc_subprotocol(
                    websocket.headers.get("sec-websocket-protocol")
                )
            )
            try:
                reader, writer = await asyncio.open_connection(vnc_host, vnc_port)
            except OSError:
                await websocket.close(code=1011)
                return

            async def ws_to_tcp() -> None:
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        writer.write(data)
                        await writer.drain()
                except WebSocketDisconnect:
                    pass
                finally:
                    writer.close()
                    with contextlib.suppress(Exception):
                        await writer.wait_closed()

            async def tcp_to_ws() -> None:
                try:
                    while True:
                        chunk = await reader.read(65536)
                        if not chunk:
                            break
                        await websocket.send_bytes(chunk)
                finally:
                    try:
                        await websocket.close()
                    except Exception:  # noqa: S110 — already closed
                        pass

            tasks = {asyncio.create_task(ws_to_tcp()), asyncio.create_task(tcp_to_ws())}
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, *pending, return_exceptions=True)

    # ------------------------------------------------------------------
    # Static UI
    # ------------------------------------------------------------------
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    # Sync def (not async): FastAPI runs it in a threadpool and Starlette
    # iterates the sync generator there too, so the blocking cache scan never
    # runs on the event loop. The body streams row-by-row rather than buffering
    # the whole CSV, keeping memory bounded for large exports.
    @app.get("/api/found.csv")
    def export_found_csv(_: str = Depends(require_session)) -> StreamingResponse:
        filename = f"found-items-{time.strftime('%Y%m%d-%H%M%S')}.csv"
        return StreamingResponse(
            iter_found_csv(iter_found_rows(cache)),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def check_stage(stage: str | None) -> str | None:
        stage = stage or None
        if stage is not None and stage not in STAGES:
            raise HTTPException(
                status_code=400, detail=f"stage must be one of {', '.join(STAGES)}"
            )
        return stage

    def check_sort(sort: str, order: str) -> bool:
        """Validate the sort key and return whether the order is descending."""
        if sort not in SORT_KEYS:
            raise HTTPException(
                status_code=400, detail=f"sort must be one of {', '.join(SORT_KEYS)}"
            )
        if order not in ("desc", "asc"):
            raise HTTPException(status_code=400, detail="order must be desc or asc")
        return order == "desc"

    # Sync defs, like the CSV export above: the cache scan runs in a threadpool.
    @app.get("/api/evaluations")
    def get_evaluations(
        item: str | None = None,
        stage: str | None = None,
        since: float | None = None,
        min_rating: int | None = None,
        q: str | None = None,
        sort: str = "time",
        order: str = "desc",
        limit: int = 500,
        _: str = Depends(require_session),
    ) -> Dict[str, Any]:
        stage = check_stage(stage)
        descending = check_sort(sort, order)
        records = list(iter_evaluations(local_cache=cache))
        # sorted before the limit, so "highest rated" means across all matches
        matched = filter_evaluations(
            records,
            since=since,
            item=item or None,
            stage=stage,
            min_rating=min_rating,
            text=q,
            sort=sort,
            descending=descending,
        )
        limit = max(1, min(limit, MAX_LIMIT))
        return {
            "records": [r.to_dict() for r in matched[:limit]],
            "total": len(matched),
            "items": sorted({r.item for r in records}),
        }

    @app.get("/api/evaluations.csv")
    def export_evaluations_csv(
        item: str | None = None,
        stage: str | None = None,
        since: float | None = None,
        min_rating: int | None = None,
        q: str | None = None,
        sort: str = "time",
        order: str = "desc",
        _: str = Depends(require_session),
    ) -> StreamingResponse:
        stage = check_stage(stage)
        descending = check_sort(sort, order)
        matched = filter_evaluations(
            iter_evaluations(local_cache=cache),
            since=since,
            item=item or None,
            stage=stage,
            min_rating=min_rating,
            text=q,
            sort=sort,
            descending=descending,
        )
        filename = f"evaluations-{time.strftime('%Y%m%d-%H%M%S')}.csv"
        return StreamingResponse(
            iter_evaluations_csv(matched),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

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

    if state.proxy is not None:
        log = logger or logging.getLogger("monitor")
        if state.proxy.verified:
            log.info(f"""{hilight("[WebUI]", "info")} {state.proxy.describe()}.""")
        else:
            log.warning(
                f"""{hilight("[WebUI]", "fail")} {state.proxy.describe()}, which anyone who"""
                f" reaches port {config.port} directly can send: they would control aimm and"
                " see its browser. Make the port reachable only through your reverse proxy,"
                " or set AIMM_WEBUI_PROXY_SECRET."
            )
    # --webui-host requires credentials. Refuse to expose without auth.
    elif state.exposed and state.auth is None:
        raise RuntimeError(
            f"--webui-host {config.host} requires authentication. "
            "Set username/password in a [marketplace.*] config section "
            "or set FACEBOOK_USERNAME and FACEBOOK_PASSWORD environment "
            "variables. Omit --webui-host to run on 127.0.0.1 without "
            "a password, or set AIMM_WEBUI_AUTH (proxy, authelia, authentik "
            "or cloudflare) if a reverse proxy signs users in."
        )

    config_service = ConfigFileService(config.config_files, logger=logger)
    server = WebUIServer(config, state, config_service)
    server.start()
    return server, info
