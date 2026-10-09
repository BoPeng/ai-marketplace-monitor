"""AIMM_WEBUI_AUTH: let a reverse proxy sign users in, and check what it vouches for."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ai_marketplace_monitor.webui import server as webui_server
from ai_marketplace_monitor.webui.config_api import ConfigFileService
from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler
from ai_marketplace_monitor.webui.proxy_auth import (
    ProxyAuth,
    ProxyAuthError,
    webui_auth_mode,
)
from ai_marketplace_monitor.webui.server import (
    AuthState,
    StartupInfo,
    WebUIConfig,
    _resolve_auth,
    create_app,
    start_webui,
)

ORIGIN = {"origin": "http://testserver"}
AUDIENCE = "aimm-client"
ISSUER = "https://auth.example.com/application/o/aimm/"
EXPOSED = "0.0.0.0"  # noqa: S104 - the web UI as Docker runs it


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FACEBOOK_USERNAME",
        "FACEBOOK_PASSWORD",
        "AIMM_WEBUI_AUTH",
        "AIMM_WEBUI_USER_HEADER",
        "AIMM_WEBUI_PROXY_SECRET",
        "AIMM_WEBUI_JWKS_URL",
        "AIMM_WEBUI_JWT_AUDIENCE",
        "AIMM_WEBUI_CF_TEAM",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text("[marketplace.facebook]\nsearch_city = 'dallas'\n", encoding="utf-8")
    return path


def client_for(config_path: Path, proxy: ProxyAuth) -> TestClient:
    handler = LogBroadcastHandler()
    state = AuthState()
    state.exposed = True
    state.proxy = proxy
    app = create_app(
        WebUIConfig(host=EXPOSED, config_files=[config_path], log_handler=handler),
        state,
        ConfigFileService([config_path]),
        handler,
    )
    return TestClient(app)


# --- signed JWTs (authentik, cloudflare) ------------------------------------------------------
class Keys:
    """A signing key and a stand-in for PyJWKClient that serves its public half."""

    def __init__(self) -> None:
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def get_signing_key_from_jwt(self, token: str) -> Any:
        public = jwt.algorithms.RSAAlgorithm.to_jwk(self.private.public_key(), as_dict=True)
        return jwt.PyJWK.from_dict({**public, "alg": "RS256", "kid": "k1"})

    def token(self, **claims: Any) -> str:
        """A token for aimm's Authentik application unless the claims say otherwise."""
        payload: Dict[str, Any] = {
            "exp": int(time.time()) + 300,
            "aud": AUDIENCE,
            "iss": ISSUER,
            **claims,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return jwt.encode(payload, self.private, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture(scope="module")
def keys() -> Keys:
    return Keys()


def authentik(keys: Keys) -> ProxyAuth:
    return ProxyAuth(
        mode="authentik",
        jwt_header="X-Authentik-Jwt",
        jwks_url=ISSUER + "jwks/",
        audience=AUDIENCE,
        issuer=ISSUER,
        jwks_client=keys,
    )


# --- settings ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value, mode",
    [(None, "password"), ("", "password"), ("proxy", "proxy"), (" Authelia ", "authelia")],
)
def test_auth_mode_from_environment(value: str | None, mode: str) -> None:
    assert webui_auth_mode({} if value is None else {"AIMM_WEBUI_AUTH": value}) == mode


def test_unknown_auth_mode_is_an_error() -> None:
    with pytest.raises(ValueError, match="use password, proxy, authelia, authentik, cloudflare"):
        webui_auth_mode({"AIMM_WEBUI_AUTH": "none"})


def test_settings_of_each_mode() -> None:
    assert ProxyAuth.from_environment({}) is None
    bare = ProxyAuth.from_environment({"AIMM_WEBUI_AUTH": "proxy"})
    assert bare is not None and not bare.verified
    authelia = ProxyAuth.from_environment({"AIMM_WEBUI_AUTH": "authelia"})
    assert authelia is not None and authelia.user_header == "Remote-User"
    assert not authelia.verified  # a plain header can be forged around the proxy
    custom = ProxyAuth.from_environment(
        {
            "AIMM_WEBUI_AUTH": "authelia",
            "AIMM_WEBUI_USER_HEADER": "X-WebAuth-User",
            "AIMM_WEBUI_PROXY_SECRET": "s3cret",
        }
    )
    assert custom is not None and custom.user_header == "X-WebAuth-User" and custom.verified
    cf = ProxyAuth.from_environment(
        {
            "AIMM_WEBUI_AUTH": "cloudflare",
            "AIMM_WEBUI_CF_TEAM": "myteam",
            "AIMM_WEBUI_JWT_AUDIENCE": "aud",
        }
    )
    assert cf is not None and cf.verified
    assert cf.jwks_url == "https://myteam.cloudflareaccess.com/cdn-cgi/access/certs"
    assert cf.issuer == "https://myteam.cloudflareaccess.com"
    assert cf.jwt_header == "Cf-Access-Jwt-Assertion"
    ak = ProxyAuth.from_environment(
        {
            "AIMM_WEBUI_AUTH": "authentik",
            "AIMM_WEBUI_JWKS_URL": ISSUER + "jwks/",
            "AIMM_WEBUI_JWT_AUDIENCE": AUDIENCE,
        }
    )
    assert ak is not None and ak.issuer == ISSUER and ak.audience == AUDIENCE
    custom_issuer = ProxyAuth.from_environment(
        {
            "AIMM_WEBUI_AUTH": "authentik",
            "AIMM_WEBUI_JWKS_URL": "https://auth.example.com/keys.json",
            "AIMM_WEBUI_JWT_AUDIENCE": AUDIENCE,
            "AIMM_WEBUI_JWT_ISSUER": "https://auth.example.com/",
        }
    )
    assert custom_issuer is not None and custom_issuer.issuer == "https://auth.example.com/"


@pytest.mark.parametrize(
    "environ, missing",
    [
        ({"AIMM_WEBUI_AUTH": "authentik"}, "AIMM_WEBUI_JWKS_URL"),
        # tokens of every application signed with the same key would let their holders in
        ({"AIMM_WEBUI_AUTH": "authentik", "AIMM_WEBUI_JWKS_URL": ISSUER + "jwks/"}, "AUDIENCE"),
        (
            {
                "AIMM_WEBUI_AUTH": "authentik",
                "AIMM_WEBUI_JWKS_URL": "https://auth.example.com/keys.json",
                "AIMM_WEBUI_JWT_AUDIENCE": AUDIENCE,
            },
            "AIMM_WEBUI_JWT_ISSUER",
        ),
        ({"AIMM_WEBUI_AUTH": "cloudflare", "AIMM_WEBUI_JWT_AUDIENCE": "a"}, "AIMM_WEBUI_CF_TEAM"),
        ({"AIMM_WEBUI_AUTH": "cloudflare", "AIMM_WEBUI_CF_TEAM": "t"}, "AIMM_WEBUI_JWT_AUDIENCE"),
    ],
)
def test_modes_refuse_to_start_without_their_settings(
    environ: Dict[str, str], missing: str
) -> None:
    with pytest.raises(ValueError, match=missing):
        ProxyAuth.from_environment(environ)


# --- checks -----------------------------------------------------------------------------------
def test_authelia_needs_the_user_header() -> None:
    auth = ProxyAuth(mode="authelia", user_header="Remote-User")
    assert auth.identify({"Remote-User": "alice"}) == "alice"
    with pytest.raises(ProxyAuthError, match="Remote-User header is missing"):
        auth.identify({})
    with pytest.raises(ProxyAuthError):
        auth.identify({"Remote-User": "  "})


def test_proxy_secret_is_checked_in_every_mode() -> None:
    for auth in (
        ProxyAuth(mode="proxy", secret="s3cret"),
        ProxyAuth(mode="authelia", user_header="Remote-User", secret="s3cret"),
    ):
        with pytest.raises(ProxyAuthError, match="X-Aimm-Proxy-Secret"):
            auth.identify({"Remote-User": "alice"})
        with pytest.raises(ProxyAuthError, match="X-Aimm-Proxy-Secret"):
            auth.identify({"Remote-User": "alice", "X-Aimm-Proxy-Secret": "guess"})
        assert auth.identify({"Remote-User": "alice", "X-Aimm-Proxy-Secret": "s3cret"})


def test_a_signed_jwt_names_the_user(keys: Keys) -> None:
    auth = authentik(keys)
    token = keys.token(preferred_username="alice", email="a@example.com")
    identity = auth.verify({"X-Authentik-Jwt": token})
    assert identity.user == "alice" and identity.expires_at is not None
    assert auth.identify({"X-Authentik-Jwt": keys.token(email="b@x")}) == "b@x"
    # the header modes have nothing that expires
    assert ProxyAuth(mode="proxy").verify({}).expires_at is None


def _hs256_token() -> str:
    """A symmetric token, as a forger would make with a public key: must not pass."""
    claims = {"sub": "a", "aud": "aimm-client", "exp": int(time.time()) + 60}
    return jwt.encode(claims, "x" * 32, algorithm="HS256", headers={"kid": "k1"})


@pytest.mark.parametrize(
    "make_token, reason",
    [
        (lambda k: None, "header is missing"),
        (lambda k: "not-a-jwt", "not valid"),
        (lambda k: k.token(sub="a", exp=int(time.time()) - 3600), "expired"),
        # issued for another application signed with the same key
        (lambda k: k.token(sub="a", aud="another-app"), "not valid"),
        (
            lambda k: k.token(sub="a", iss="https://auth.example.com/application/o/other/"),
            "not valid",
        ),
        (lambda k: k.token(sub="a", aud=None), "not valid"),
        (lambda k: k.token(sub="a", iss=None), "not valid"),
        (lambda k: Keys().token(sub="a"), "not valid"),  # someone else's key
        (lambda k: _hs256_token(), "not valid"),
        (lambda k: k.token(), "does not name a user"),
    ],
)
def test_invalid_jwts_are_rejected(keys: Keys, make_token: Any, reason: str) -> None:
    token = make_token(keys)
    headers = {} if token is None else {"X-Authentik-Jwt": token}
    with pytest.raises(ProxyAuthError, match=reason):
        authentik(keys).identify(headers)


def test_cloudflare_checks_the_issuer(keys: Keys) -> None:
    auth = ProxyAuth(
        mode="cloudflare",
        jwt_header="Cf-Access-Jwt-Assertion",
        jwks_url="https://myteam.cloudflareaccess.com/cdn-cgi/access/certs",
        issuer="https://myteam.cloudflareaccess.com",
        audience="aud-tag",
        jwks_client=keys,
    )
    good = keys.token(aud="aud-tag", iss="https://myteam.cloudflareaccess.com", email="a@x")
    assert auth.identify({"Cf-Access-Jwt-Assertion": good}) == "a@x"
    other = keys.token(aud="aud-tag", iss="https://evil.cloudflareaccess.com", email="a@x")
    with pytest.raises(ProxyAuthError, match="not valid"):
        auth.identify({"Cf-Access-Jwt-Assertion": other})


# --- the web UI -------------------------------------------------------------------------------
def test_proxy_modes_apply_only_when_exposed(
    monkeypatch: pytest.MonkeyPatch, config_path: Path
) -> None:
    monkeypatch.setenv("AIMM_WEBUI_AUTH", "authelia")
    state, info = _resolve_auth(WebUIConfig(host="127.0.0.1", config_files=[config_path]))
    assert state.proxy is None and not info.proxy_auth  # loopback is open anyway
    state, info = _resolve_auth(WebUIConfig(host=EXPOSED, config_files=[config_path]))
    assert state.proxy is not None and info.proxy_auth and not info.proxy_verified
    assert "Remote-User" in info.proxy_check
    assert state.auth is None and info.username is None


def test_exposed_web_ui_starts_without_credentials_behind_a_proxy(
    monkeypatch: pytest.MonkeyPatch, config_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(webui_server.WebUIServer, "start", lambda self: None)
    config = WebUIConfig(
        host=EXPOSED, config_files=[config_path], log_handler=LogBroadcastHandler()
    )
    with pytest.raises(RuntimeError, match="AIMM_WEBUI_AUTH"):
        start_webui(config)
    logger = logging.getLogger("monitor-test")
    monkeypatch.setenv("AIMM_WEBUI_AUTH", "proxy")
    with caplog.at_level(logging.INFO, logger="monitor-test"):
        _, info = start_webui(config, logger=logger)
    assert info.proxy_auth and "set AIMM_WEBUI_PROXY_SECRET" in caplog.text
    caplog.clear()
    monkeypatch.setenv("AIMM_WEBUI_PROXY_SECRET", "s3cret")
    with caplog.at_level(logging.INFO, logger="monitor-test"):
        start_webui(config, logger=logger)
    assert "X-Aimm-Proxy-Secret" in caplog.text and "directly can send" not in caplog.text
    # a mode missing its settings does not start
    monkeypatch.setenv("AIMM_WEBUI_AUTH", "authentik")
    with pytest.raises(ValueError, match="AIMM_WEBUI_JWKS_URL"):
        start_webui(config)


def test_bare_proxy_mode_signs_in_without_a_password(config_path: Path) -> None:
    client = client_for(config_path, ProxyAuth(mode="proxy"))
    info = client.get("/api/auth/info").json()
    assert info["open"] is True and info["proxy_error"] is None
    assert client.get("/api/status").status_code == 401  # still no access without a session
    assert client.post("/api/login").status_code == 200
    status = client.get("/api/status").json()
    assert status["auth_mode"] == "proxy" and status["open"] is True and status["user"] is None


def test_authelia_mode_checks_every_request(config_path: Path) -> None:
    client = client_for(config_path, ProxyAuth(mode="authelia", user_header="Remote-User"))
    alice = {"Remote-User": "alice"}
    # not through the proxy: the sign-in screen says why, and nothing works
    error = client.get("/api/auth/info").json()["proxy_error"]
    assert "Remote-User header is missing" in error
    assert client.post("/api/login").status_code == 401
    login = client.post("/api/login", headers=alice)
    assert login.status_code == 200 and login.json()["username"] == "alice"
    status = client.get("/api/status", headers=alice).json()
    assert status["auth_mode"] == "authelia" and status["user"] == "alice"
    # the session cookie alone is not enough: the proxy must vouch for every request
    assert client.get("/api/status").status_code == 401


def test_proxy_modes_still_require_the_csrf_token(config_path: Path) -> None:
    """Proxy credentials ride along with cross-site requests; the CSRF token stops them."""
    client = client_for(config_path, ProxyAuth(mode="authelia", user_header="Remote-User"))
    alice = {"Remote-User": "alice"}
    csrf = client.post("/api/login", headers=alice).json()["csrf"]
    assert client.post("/api/monitor/pause", headers=alice).status_code == 403
    response = client.post("/api/monitor/pause", headers={**alice, "X-CSRF-Token": csrf})
    assert response.status_code != 403


def test_websockets_check_the_proxy_origin_and_session(config_path: Path) -> None:
    client = client_for(config_path, ProxyAuth(mode="authelia", user_header="Remote-User"))
    alice = {"Remote-User": "alice"}
    client.post("/api/login", headers=alice)
    for headers, code in (
        (ORIGIN, 4401),  # not through the proxy
        ({**alice, "origin": "http://evil.example"}, 4403),  # a page on another site
    ):
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws/stream", headers=headers):
                pass
        assert closed.value.code == code
    with client.websocket_connect("/ws/stream", headers={**alice, **ORIGIN}):
        pass


def test_authentik_mode_signs_in_the_user_of_the_jwt(config_path: Path, keys: Keys) -> None:
    client = client_for(config_path, authentik(keys))
    token = {"X-Authentik-Jwt": keys.token(preferred_username="alice")}
    assert client.post("/api/login", headers=token).json()["username"] == "alice"
    assert client.get("/api/status", headers=token).json()["user"] == "alice"
    forged = {"X-Authentik-Jwt": Keys().token(preferred_username="mallory")}
    assert client.get("/api/status", headers=forged).status_code == 401
    other_app = {"X-Authentik-Jwt": keys.token(preferred_username="bob", aud="another-app")}
    assert client.get("/api/status", headers=other_app).status_code == 401


def test_websocket_ends_when_the_token_expires(config_path: Path, keys: Keys) -> None:
    """An open connection must not outlive the proxy's token: it controls the browser."""
    client = client_for(config_path, authentik(keys))
    login = {"X-Authentik-Jwt": keys.token(preferred_username="alice")}
    client.post("/api/login", headers=login)
    expiring = {
        "X-Authentik-Jwt": keys.token(preferred_username="alice", exp=int(time.time()) + 2)
    }
    started = time.time()
    with client.websocket_connect("/ws/stream", headers={**expiring, **ORIGIN}) as ws:
        assert ws.receive_json()["type"] == "hello"
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                ws.receive_json()
    assert closed.value.code == 4401
    assert 1 <= time.time() - started < 10
    # a connection whose token outlives it is not cut short
    with client.websocket_connect("/ws/stream", headers={**login, **ORIGIN}) as ws:
        assert ws.receive_json()["type"] == "hello"


def test_banner_shows_the_check(capsys: pytest.CaptureFixture) -> None:
    from ai_marketplace_monitor.commands.common import print_webui_banner

    def banner(verified: bool) -> str:
        print_webui_banner(
            StartupInfo(
                urls=["http://127.0.0.1:8467"],
                username=None,
                host=EXPOSED,
                port=8467,
                exposed=True,
                proxy_auth=True,
                proxy_check="AIMM_WEBUI_AUTH=authelia: each request needs the Remote-User header",
                proxy_verified=verified,
            )
        )
        return capsys.readouterr().out

    out = banner(False)
    assert "Remote-User" in out and "AIMM_WEBUI_PROXY_SECRET" in out and "user:" not in out
    assert "AIMM_WEBUI_PROXY_SECRET" not in banner(True)
