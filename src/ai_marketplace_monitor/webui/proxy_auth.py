"""Let a reverse proxy sign users in to an exposed web UI (``AIMM_WEBUI_AUTH``).

``facebook`` (the default; ``password`` is its old name) signs users in with the marketplace
username and password, and ``local`` with a web UI password of its own (``AIMM_WEBUI_USERNAME``,
``AIMM_WEBUI_PASSWORD``). The other modes skip aimm's sign-in and instead check, on every request,
what the proxy adds once it has signed the user in:

- ``proxy``: nothing. Only safe when the web UI's port is reachable through the proxy alone.
- ``authelia``: a user header (``Remote-User``, or ``AIMM_WEBUI_USER_HEADER``). Not signed:
  anyone who reaches the port directly can send it, unless ``AIMM_WEBUI_PROXY_SECRET`` is set.
- ``authentik``: the signed JWT in ``X-Authentik-Jwt``, verified with the keys at
  ``AIMM_WEBUI_JWKS_URL`` (never the URL the request names), for aimm's application only:
  its audience (``AIMM_WEBUI_JWT_AUDIENCE``, the provider's client ID) and issuer (derived
  from the JWKS URL, or ``AIMM_WEBUI_JWT_ISSUER``). Applications can share a signing key, so
  without these a token issued for another application would let its holder in.
- ``cloudflare``: the signed JWT in ``Cf-Access-Jwt-Assertion``, verified with the keys of
  Cloudflare Access team ``AIMM_WEBUI_CF_TEAM`` and the application's ``AIMM_WEBUI_JWT_AUDIENCE``.

``AIMM_WEBUI_PROXY_SECRET`` works with every proxy mode: the proxy must also send it in the
``X-Aimm-Proxy-Secret`` header, which someone bypassing the proxy does not know.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Any, Mapping, NamedTuple

AUTH_FACEBOOK = "facebook"
AUTH_LOCAL = "local"
AUTH_PASSWORD = "password"  # the old name of AUTH_FACEBOOK, still accepted
AUTH_PROXY = "proxy"
AUTH_AUTHELIA = "authelia"
AUTH_AUTHENTIK = "authentik"
AUTH_CLOUDFLARE = "cloudflare"
AUTH_MODES = (
    AUTH_FACEBOOK,
    AUTH_LOCAL,
    AUTH_PROXY,
    AUTH_AUTHELIA,
    AUTH_AUTHENTIK,
    AUTH_CLOUDFLARE,
)
_OLD_NAMES = {AUTH_PASSWORD: AUTH_FACEBOOK}

SECRET_HEADER = "X-Aimm-Proxy-Secret"
AUTHENTIK_JWT_HEADER = "X-Authentik-Jwt"
CLOUDFLARE_JWT_HEADER = "Cf-Access-Jwt-Assertion"
# asymmetric only: never HS* (the key would be public) or "none"
JWT_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "EdDSA"]


class ProxyAuthError(Exception):
    """The request did not come through the reverse proxy's sign-in."""


class Identity(NamedTuple):
    """Who the reverse proxy signed in, and until when its proof is valid."""

    user: str
    expires_at: float | None = None  # a JWT's exp; None when the proxy's proof does not expire


def webui_auth_mode(environ: Mapping[str, str] | None = None) -> str:
    """The AIMM_WEBUI_AUTH setting, by its current name; raises ValueError for an unknown value."""
    environ = os.environ if environ is None else environ
    mode = environ.get("AIMM_WEBUI_AUTH", "").strip().lower() or AUTH_FACEBOOK
    mode = _OLD_NAMES.get(mode, mode)
    if mode not in AUTH_MODES:
        raise ValueError(
            f"AIMM_WEBUI_AUTH={mode!r} is not supported; use {', '.join(AUTH_MODES)}."
        )
    return mode


@dataclass
class ProxyAuth:
    """What an exposed web UI checks on each request when a reverse proxy signs users in."""

    mode: str
    user_header: str | None = None  # authelia
    secret: str | None = None  # AIMM_WEBUI_PROXY_SECRET
    jwt_header: str | None = None  # authentik, cloudflare
    jwks_url: str | None = None
    audience: str | None = None
    issuer: str | None = None
    jwks_client: Any = field(default=None, repr=False)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> "ProxyAuth | None":
        """None when aimm signs users in itself; raises ValueError when a mode lacks its settings."""
        environ = os.environ if environ is None else environ
        mode = webui_auth_mode(environ)
        if mode in (AUTH_FACEBOOK, AUTH_LOCAL):
            return None

        def setting(name: str) -> str | None:
            return environ.get(name, "").strip() or None

        def required(name: str) -> str:
            value = setting(name)
            if value is None:
                raise ValueError(f"AIMM_WEBUI_AUTH={mode} needs {name}.")
            return value

        auth = cls(mode=mode, secret=setting("AIMM_WEBUI_PROXY_SECRET"))
        if mode == AUTH_AUTHELIA:
            auth.user_header = setting("AIMM_WEBUI_USER_HEADER") or "Remote-User"
        elif mode == AUTH_AUTHENTIK:
            auth.jwt_header = AUTHENTIK_JWT_HEADER
            auth.jwks_url = required("AIMM_WEBUI_JWKS_URL")
            auth.audience = required("AIMM_WEBUI_JWT_AUDIENCE")
            # https://auth.example.com/application/o/<slug>/jwks/ is the key set of the
            # provider whose tokens name https://auth.example.com/application/o/<slug>/
            issuer = setting("AIMM_WEBUI_JWT_ISSUER")
            if issuer is None and auth.jwks_url.rstrip("/").endswith("/jwks"):
                issuer = auth.jwks_url.rstrip("/")[: -len("jwks")]
            if issuer is None:
                raise ValueError(
                    f"AIMM_WEBUI_AUTH={mode} needs AIMM_WEBUI_JWT_ISSUER: it cannot be derived"
                    f" from AIMM_WEBUI_JWKS_URL={auth.jwks_url}."
                )
            auth.issuer = issuer
        elif mode == AUTH_CLOUDFLARE:
            team = required("AIMM_WEBUI_CF_TEAM").removeprefix("https://").rstrip("/")
            if "." not in team:
                team += ".cloudflareaccess.com"
            auth.jwt_header = CLOUDFLARE_JWT_HEADER
            auth.jwks_url = f"https://{team}/cdn-cgi/access/certs"
            auth.issuer = f"https://{team}"
            auth.audience = required("AIMM_WEBUI_JWT_AUDIENCE")
        return auth

    @property
    def verified(self) -> bool:
        """True when a request cannot pass by going around the proxy."""
        return self.jwt_header is not None or self.secret is not None

    def describe(self) -> str:
        if self.jwt_header:
            check = f"a signed {self.jwt_header}"
        elif self.user_header:
            check = f"the {self.user_header} header"
        else:
            check = "nothing from the proxy"
        if self.secret:
            check += f" and {SECRET_HEADER}"
        return f"AIMM_WEBUI_AUTH={self.mode}: each request needs {check}"

    def identify(self, headers: Mapping[str, str]) -> str:
        """The signed-in user the proxy vouches for; raises ProxyAuthError otherwise."""
        return self.verify(headers).user

    def verify(self, headers: Mapping[str, str]) -> Identity:
        """The signed-in user and until when; raises ProxyAuthError otherwise."""
        if self.secret is not None:
            sent = headers.get(SECRET_HEADER) or ""
            if not secrets.compare_digest(sent.encode(), self.secret.encode()):
                raise ProxyAuthError(
                    "This request did not come through the reverse proxy"
                    f" ({SECRET_HEADER} is missing or wrong)."
                )
        if self.jwt_header is not None:
            return self._verify_jwt(headers.get(self.jwt_header))
        if self.user_header is not None:
            user = (headers.get(self.user_header) or "").strip()
            if not user:
                raise ProxyAuthError(
                    f"Not signed in through {self.mode}: the {self.user_header} header is missing."
                )
            return Identity(user)
        return Identity("proxy")

    def _verify_jwt(self, token: str | None) -> Identity:
        import jwt  # only needed in the JWT modes

        if not token:
            raise ProxyAuthError(
                f"Not signed in through {self.mode}: the {self.jwt_header} header is missing."
            )
        if self.jwks_client is None:
            # caches the keys, and fetches them again for a key it does not know (rotation)
            self.jwks_client = jwt.PyJWKClient(self.jwks_url or "", lifespan=3600)
        try:
            key = self.jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=JWT_ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                # for aimm's application only: a key can sign tokens for several
                options={"require": ["exp", "aud", "iss"]},
                leeway=30,
            )
        except jwt.PyJWKClientConnectionError as e:
            raise ProxyAuthError(f"Cannot fetch the signing keys from {self.jwks_url}: {e}") from e
        except jwt.PyJWTError as e:
            raise ProxyAuthError(f"The {self.jwt_header} token is not valid: {e}") from e
        for claim in ("preferred_username", "email", "sub"):
            if claims.get(claim):
                return Identity(str(claims[claim]), float(claims["exp"]))
        raise ProxyAuthError(f"The {self.jwt_header} token does not name a user.")
