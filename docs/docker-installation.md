The Docker image runs aimm on a server, a NAS or any machine without a screen. It bundles Python, Playwright Chromium, a virtual display and a noVNC client, so you can complete Facebook's CAPTCHA or security code from the web UI. You can start it with a single `docker run` command, or with Docker Compose: the repository's [`docker-compose/`](https://github.com/BoPeng/ai-marketplace-monitor/tree/main/docker-compose) folder has `docker-compose.yml`, which you use as is, and `.env.example`, a template for the `.env` file that holds your credentials and settings.

## Prerequisites

- [Docker Engine](https://docs.docker.com/engine/install/) with the Compose plugin (`docker compose version` prints a version)
- A Facebook account for aimm to log in with
- For the default configuration, a [UnitySVC](https://unitysvc.com) account and an API key (`svcpass_...`), for `UNITYSVC_API_KEY`. Sign up at [unitysvc.com](https://unitysvc.com) and create an API key in your account. If you configure other providers directly instead (see below), you do not need them.

### Why a UnitySVC key

The default configuration needs only this one key, for both the AI that rates listings and the email and phone/chat notifications:

- **AI from any provider**: OpenAI, Anthropic and other AI engines, either as UnitySVC platform services or with your own provider keys (BYOK, "bring your own key"). For BYOK, save the provider's key once as a secret in your UnitySVC account (Developer → Secrets, e.g. `OPENAI_API_KEY`); it stays in UnitySVC, and your aimm configuration and `.env` still hold only `UNITYSVC_API_KEY`. See [AI Services](https://github.com/BoPeng/ai-marketplace-monitor/blob/main/docs/README.md#ai-services).
- **Notifications**: email with photos and short messages to your phone, Discord, Slack and 100+ other channels, through UnitySVC's platform services or your own accounts. See [UnitySVC notification](https://github.com/BoPeng/ai-marketplace-monitor/blob/main/docs/README.md#unitysvc-notification).

You can also skip UnitySVC and configure OpenAI, Gmail and other services in `config.toml` directly, with their keys in `.env`.

## Quick start with docker run

If aimm is already installed on this machine, or you prefer to keep your credentials in environment variables, run:

```bash
docker run -d --name aimm \
  -p 8467:8467 \
  -v "$HOME/.ai-marketplace-monitor:/data" \
  -e FACEBOOK_USERNAME -e FACEBOOK_PASSWORD \
  -e UNITYSVC_API_KEY \
  --restart unless-stopped \
  ghcr.io/bopeng/ai-marketplace-monitor:latest
```

The `-e` flags pass `FACEBOOK_USERNAME`, `FACEBOOK_PASSWORD` and `UNITYSVC_API_KEY` (if you use UnitySVC) from your shell to the container; `config.toml` refers to them as `${FACEBOOK_USERNAME}` and so on. Make sure they contain only the intended values: when Docker exposes the web UI, the Facebook username and password also protect it and its browser view.

Mounting `~/.ai-marketplace-monitor` at `/data` shares your existing config, cache and logs between an aimm installed on the host and the container, so you can switch between them, one at a time (see Troubleshooting below). aimm runs in the container as an unprivileged user with ID 1000. On a Linux host where your user ID is not 1000 (see `id -u`), add `-e PUID="$(id -u)" -e PGID="$(id -g)"` so that the files in the folder stay yours; Docker Desktop on macOS and Windows does not need it. If you created the container with the folder mounted at `/root/.ai-marketplace-monitor`, as older versions of this guide said, it still works, and the log asks you to mount it at `/data` instead. Continue with First run below; in the commands there, use `docker exec aimm ...` instead of `docker compose exec aimm ...`, and `docker logs aimm` to see the log.

To build the image yourself instead of pulling it, run `docker build -f docker/Dockerfile -t aimm .` from the root of a checkout of the repository.

## Set up with Docker Compose

Create a directory for aimm, for example `~/aimm`, and download the two files into it:

```bash
mkdir -p ~/aimm && cd ~/aimm
curl -fsSLO https://raw.githubusercontent.com/BoPeng/ai-marketplace-monitor/main/docker-compose/docker-compose.yml
curl -fsSL -o .env https://raw.githubusercontent.com/BoPeng/ai-marketplace-monitor/main/docker-compose/.env.example
chmod 600 .env
```

Edit `.env` and fill in `FACEBOOK_USERNAME`, `FACEBOOK_PASSWORD`, `UNITYSVC_API_KEY` and your time zone, `TZ`. Keep each value in single quotes so that a `$` in a password is not read as a variable. Every variable in `.env` reaches aimm, so an API key for another provider only needs a line there too.

aimm runs in the container as an unprivileged user with ID 1000 and keeps its config, cache and logs in `./data`. When it starts, it gives `./data` to that user. On a Linux host where your user ID is not 1000 (see `id -u`), set `PUID` and `PGID` in `.env` to your user and group IDs, so that the files in `./data` stay yours. Docker Desktop on macOS and Windows does not need them. If your platform starts containers as a fixed user instead (`user:` in Compose), give `./data` to that user.

Then start aimm:

```bash
docker compose up -d
docker compose logs -f aimm
```

## First run

On first start, aimm creates `config.toml` in the mounted directory (`data/config.toml` with Docker Compose) unless one is there already. The default configuration:

- logs in to Facebook with `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD`, and searches around Houston (`search_city`)
- rates listings with UnitySVC AI (`[ai.unitysvc]`, model `balanced`, which also reads listing photos)
- sends each match as an email with photos (`[notification.unitysvc_email]`) to the address registered with UnitySVC, and as a short message (`[notification.unitysvc]`) to your UnitySVC inbox and the destination you saved in UnitySVC (Discord, Slack, SMS, phone push, ...)
- sends a daily digest at 08:00 (`digest_at`)
- searches for an example item, `[item.example]`

The settings that hold secrets name environment variables, such as `api_key = "${UNITYSVC_API_KEY}"`, so the file contains no passwords.

Then:

1. Open [http://localhost:8467](http://localhost:8467) (or `http://<server>:8467`) and sign in with your Facebook username and password, the values of `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD`. Because Docker exposes the web UI on the network, aimm requires these credentials for the web UI and for its browser view.
2. Change `search_city` and replace `[item.example]` with what you are looking for. Edit them in the web UI's editor, or have the **Configure** chat set them up for you. aimm picks up a saved change on its own; there is no need to restart it.
3. aimm types your Facebook username and password into its browser. If Facebook asks for a CAPTCHA or a security code, a banner appears in the web UI: click **Open browser** and complete the check there. Searches start once you are logged in.
4. To check your notifications, use **Send test** in Settings, or run `docker compose exec aimm aimm admin --test-notification`.

## Behind a reverse proxy

To reach aimm over HTTPS, put it behind a reverse proxy so that port 8467 is reachable only through the proxy. The proxy must pass WebSocket connections, which the log stream and the browser view use. For [Traefik](https://traefik.io) on a Docker network named `proxy`, download `docker-compose.traefik.yml` as `docker-compose.override.yml`, which Docker Compose merges into `docker-compose.yml` by itself, and set `AIMM_DOMAIN` in `.env`:

```bash
curl -fsSL -o docker-compose.override.yml https://raw.githubusercontent.com/BoPeng/ai-marketplace-monitor/main/docker-compose/docker-compose.traefik.yml
echo "AIMM_DOMAIN='aimm.example.com'" >> .env
docker compose up -d
```

The override removes the published port and adds the Traefik labels. Change its entrypoint (`websecure`) and certificate resolver (`letsencrypt`) to the names your Traefik uses. It needs Docker Compose 2.24 or later.

Anyone who can reach the URL sees the aimm sign-in page, which is protected only by your Facebook credentials. You can also put the site behind your proxy's own authentication (for example a forward-auth middleware).

### Let the reverse proxy sign you in

If your reverse proxy already signs users in, aimm does not need to ask for the Facebook username and password as well. Set `AIMM_WEBUI_AUTH` in `.env` (or with `-e` for `docker run`) to the proxy that signs you in. aimm then checks, on every request, what that proxy adds once you are signed in, so a request that goes around the proxy is refused:

| `AIMM_WEBUI_AUTH` | Each request must carry | Settings |
| --- | --- | --- |
| `password` (default) | aimm's own sign-in, with the Facebook username and password | |
| `authentik` | the signed token in `X-Authentik-Jwt` from Authentik's proxy outpost | `AIMM_WEBUI_JWKS_URL`: the provider's JWKS URL, e.g. `https://auth.example.com/application/o/aimm/jwks/`. Optional `AIMM_WEBUI_JWT_AUDIENCE`: the provider's client ID |
| `cloudflare` | the signed token in `Cf-Access-Jwt-Assertion` from Cloudflare Access | `AIMM_WEBUI_CF_TEAM`: your team name (`<team>.cloudflareaccess.com`). `AIMM_WEBUI_JWT_AUDIENCE`: the application's AUD tag |
| `authelia` | the `Remote-User` header from Authelia's forward auth | Optional `AIMM_WEBUI_USER_HEADER` for another header, e.g. the one a basic-auth middleware sets |
| `proxy` | nothing | |

`authentik` and `cloudflare` verify a token that the identity provider signs, so a forged request is refused even if it reaches aimm's port directly. `authelia` and `proxy` cannot tell your proxy from anyone else who reaches the port. For them, also set `AIMM_WEBUI_PROXY_SECRET` to a long random value (for example from `openssl rand -hex 32`), and have the proxy add it to every request as the `X-Aimm-Proxy-Secret` header, for example with Traefik's `headers` middleware (`customRequestHeaders`), nginx's `proxy_set_header` or Caddy's `header_up`. Without the secret, aimm logs a warning, and you must make sure that port 8467 is reachable only through the proxy: anyone who reaches it directly controls aimm and sees its browser, which is logged in to your Facebook account.

aimm still logs in to Facebook with `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD`, so keep them set. The web UI keeps protecting itself against requests from other websites, so a page you visit cannot use your proxy sign-in to change aimm's settings. Settings shows who the proxy signed in.

Container managers:

- **Umbrel** puts its own login in front of apps, but does not tell the app who signed in, and aimm cannot check it. Keep `password`, or turn off Umbrel's login for aimm (`PROXY_AUTH_ADD: "false"`).
- **CasaOS** signs you in to its dashboard, not to the apps, which are published on the host's ports. Keep `password`.

## Update

When a new release is out, the web UI header shows **⬆ aimm X available**, which opens Settings with an **Update** button. It installs the release inside the running container and restarts aimm; the page reloads when it is back. The update lives in the container: it survives a restart, but recreating the container from an older image brings back the old version, and the button offers the update again. The button is there only when aimm runs as the image's own user, ID 1000; with another `PUID`, or `--user`, update the image instead.

To update the image itself, pull it and recreate the container. Restarting the container keeps running the old image. With Docker Compose:

```bash
docker compose pull
docker compose up -d
```

With `docker run`:

```bash
docker pull ghcr.io/bopeng/ai-marketplace-monitor:latest
docker rm -f aimm
```

and run the `docker run` command again. Your config, cache and logs are kept in the mounted directory. The web UI header shows the running version, as does `docker exec aimm aimm --version`.

## Troubleshooting

- **The web UI says the credentials are wrong**: sign in with the values of `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD`. Check that the container received them with `docker compose exec aimm printenv FACEBOOK_USERNAME`. If you changed `.env`, run `docker compose up -d` to recreate the container; `docker compose restart` keeps the old environment.
- **"Environment variable ... is not set" or "UnitySVC requires a string api_key"**: a `${VAR}` in `config.toml` names a variable that is not in the container's environment. With Docker Compose, add it to `.env`, then run `docker compose up -d`; with `docker run`, pass it with `-e`.
- **The web UI does not load**: check the log with `docker compose logs aimm` (or `docker logs aimm`).
- **The container shows as `unhealthy`**: the web UI does not answer. See the log; the image checks `http://127.0.0.1:8467/api/health` inside the container every 30 seconds.
- **"cannot write the data folder /data"**: the container was started as a user (`user:`) that does not own the mounted folder. Give it to that user (`sudo chown -R <uid>:<gid> data`), or remove `user:` and set `PUID` and `PGID` instead.
- **With `cap_drop: ALL`** (a hardened setup), add `cap_add: [SETUID, SETGID]` so that the container can switch to the `aimm` user, or start it as a fixed user with `user:`. Without `CHOWN`, aimm cannot change the owner of files in the data folder; it still starts if it can write them, and otherwise asks you to fix their permissions on the host. The same applies to NFS shares with `root_squash` and to SMB shares.
- **Run aimm commands in the container**, for example `docker compose exec aimm aimm check <listing>`, not with an aimm installed on the host. aimm's cache is an SQLite database, and the two would write it through the mounted directory at the same time and could damage it. If aimm stops with "cannot be read", run `docker compose exec aimm aimm admin --clear-cache all` and restart the container.
