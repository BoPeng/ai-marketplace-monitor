The Docker image runs aimm on a server, a NAS or any machine without a screen. It bundles Python, Playwright Chromium, a virtual display and a noVNC client, so you can complete Facebook's CAPTCHA or security code from the web UI. You can start it with a single `docker run` command, or with Docker Compose, which keeps your settings in two files next to each other: `docker-compose.yml` and `.env`.

## Prerequisites

- [Docker Engine](https://docs.docker.com/engine/install/) with the Compose plugin (`docker compose version` prints a version)
- A Facebook account for aimm to log in with
- A [UnitySVC](https://unitysvc.com) API key. The default configuration uses it both for the AI that rates listings and for email and phone/chat notifications. You can switch to other providers later.

## Quick start with docker run

If aimm is already installed on this machine, or you prefer to keep your credentials in environment variables, run:

```bash
docker run -d --name aimm \
  -p 8467:8467 \
  -v "$HOME/.ai-marketplace-monitor:/root/.ai-marketplace-monitor" \
  -e FACEBOOK_USERNAME -e FACEBOOK_PASSWORD \
  -e UNITYSVC_API_KEY \
  --restart unless-stopped \
  ghcr.io/bopeng/ai-marketplace-monitor:latest
```

The `-e` flags pass `FACEBOOK_USERNAME`, `FACEBOOK_PASSWORD` and `UNITYSVC_API_KEY` (if you use UnitySVC) from your shell to the container; `config.toml` refers to them as `${FACEBOOK_USERNAME}` and so on. Make sure they contain only the intended values: when Docker exposes the web UI, the Facebook username and password also protect it and its browser view.

Mounting `~/.ai-marketplace-monitor` shares your existing config, cache and logs between an aimm installed on the host and the container, so you can switch between them, one at a time (see Troubleshooting below). Continue with First run below; in the commands there, use `docker exec aimm ...` instead of `docker compose exec aimm ...`, and `docker logs aimm` to see the log.

To build the image yourself instead of pulling it, run `docker build -t aimm .` in a checkout of the repository.

## Set up with Docker Compose

Create a directory for aimm, for example `~/aimm`, and add a `.env` file with your credentials:

```bash
mkdir -p ~/aimm && cd ~/aimm
cat > .env <<'EOF'
FACEBOOK_USERNAME='you@example.com'
FACEBOOK_PASSWORD='your-facebook-password'
UNITYSVC_API_KEY='svcpass_...'
EOF
chmod 600 .env
```

Put each value in single quotes so that Docker Compose does not treat a `$` in a password as a variable.

Then add `docker-compose.yml`:

```yaml
services:
  aimm:
    image: ghcr.io/bopeng/ai-marketplace-monitor:latest
    container_name: aimm
    restart: unless-stopped
    ports:
      - "8467:8467"
    environment:
      - TZ=America/Chicago  # your time zone, for the daily digest
      - FACEBOOK_USERNAME=${FACEBOOK_USERNAME}
      - FACEBOOK_PASSWORD=${FACEBOOK_PASSWORD}
      - UNITYSVC_API_KEY=${UNITYSVC_API_KEY}
    volumes:
      # config.toml, cache and logs
      - ./data:/root/.ai-marketplace-monitor
```

Docker Compose reads `.env` from the same directory and fills in the `${...}` values in `environment`. Then start aimm:

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

To reach aimm over HTTPS, put it behind a reverse proxy and remove the `ports` section so that port 8467 is reachable only through the proxy. The proxy must pass WebSocket connections, which the log stream and the browser view use. For example, with [Traefik](https://traefik.io) on a Docker network named `proxy`:

```yaml
services:
  aimm:
    image: ghcr.io/bopeng/ai-marketplace-monitor:latest
    container_name: aimm
    restart: unless-stopped
    environment:
      - TZ=America/Chicago
      - FACEBOOK_USERNAME=${FACEBOOK_USERNAME}
      - FACEBOOK_PASSWORD=${FACEBOOK_PASSWORD}
      - UNITYSVC_API_KEY=${UNITYSVC_API_KEY}
    volumes:
      - ./data:/root/.ai-marketplace-monitor
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.aimm.rule=Host(`aimm.example.com`)"
      - "traefik.http.routers.aimm.entrypoints=websecure"
      - "traefik.http.routers.aimm.tls.certresolver=letsencrypt"
      - "traefik.http.services.aimm.loadbalancer.server.port=8467"

networks:
  proxy:
    external: true
```

Anyone who can reach the URL sees the aimm sign-in page, which is protected only by your Facebook credentials. You can also put the site behind your proxy's own authentication (for example a forward-auth middleware).

## Update

When a new release is out, the web UI header shows **⬆ aimm X available**, which opens Settings with an **Update** button. It installs the release inside the running container and restarts aimm; the page reloads when it is back. The update lives in the container: it survives a restart, but recreating the container from an older image brings back the old version, and the button offers the update again.

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
- **"Environment variable ... is not set" or "UnitySVC requires a string api_key"**: a `${VAR}` in `config.toml` names a variable that is not in the container's `environment`. Add it to `.env` and to `docker-compose.yml`, then run `docker compose up -d`.
- **The web UI does not load**: check the log with `docker compose logs aimm` (or `docker logs aimm`).
- **Run aimm commands in the container**, for example `docker compose exec aimm aimm check <listing>`, not with an aimm installed on the host. aimm's cache is an SQLite database, and the two would write it through the mounted directory at the same time and could damage it. If aimm stops with "cannot be read", run `docker compose exec aimm aimm admin --clear-cache all` and restart the container.
