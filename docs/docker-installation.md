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

## NAS and container managers

The sections below install aimm on NAS and home-server systems and with container managers. Where aimm is not yet listed in a platform's app store, they install it from the templates in the repository's [`deploy/`](https://github.com/BoPeng/ai-marketplace-monitor/tree/main/deploy) folder, which is only a little more work. On every platform, aimm keeps its config, cache and logs in the folder or volume mounted at `/data`, and you continue with First run below.

Synology and QNAP have no app store for Docker apps; their container managers run Docker Compose files, and their image search finds aimm on Docker Hub as `bopeng/ai-marketplace-monitor` (amd64 and arm64, the same tags as `ghcr.io/bopeng/ai-marketplace-monitor`).

### Synology (Container Manager, DSM 7.2 or later)

Container Manager runs a **Project** inside a folder, so the files from Set up with Docker Compose above work as they are, `.env` included:

1. In File Station, create a folder for aimm, for example `docker/aimm`. Upload [`docker-compose.yml`](https://github.com/BoPeng/ai-marketplace-monitor/blob/main/docker-compose/docker-compose.yml) and [`.env.example`](https://github.com/BoPeng/ai-marketplace-monitor/blob/main/docker-compose/.env.example) to it, then rename `.env.example` to `.env` in File Station (a file whose name starts with a dot is hard to create on a computer). Fill in `.env` before uploading it, or with the Text Editor package.
2. Set `PUID` and `PGID` in `.env` to the user that should own aimm's files. Over SSH, `id <user>` shows them; the first user created on DSM is usually `1026`, group `users` (`100`).
3. **Container Manager › Project › Create**: give it a name, choose the folder as its path, select **Use existing docker-compose.yml**, and finish the wizard. Container Manager pulls the image and starts aimm; the `data` folder appears next to the files.
4. Open `http://<NAS address>:8467` and continue with First run below. The project's **Container** tab shows the log.

To update, open the project, **Action › Stop**, then **Action › Build** (it pulls the newer image), and start it again.

### QNAP (Container Station 3)

Container Station's **Applications** keep the YAML you paste in their own folder, so a `.env` file next to it is not read. Use a self-contained file instead:

1. In File Station, create a folder for aimm's data, for example `Container/aimm/data` (the share `Container` is `/share/Container`).
2. Find the IDs of the user that should own the files: over SSH, `id <user>`. New QNAP users usually start at `1000`, group `everyone` (`100`).
3. **Container Station › Applications › Create**, name it `aimm`, and paste the following, with your values:

   ```yaml
   services:
     aimm:
       image: bopeng/ai-marketplace-monitor:latest
       container_name: aimm
       restart: unless-stopped
       environment:
         FACEBOOK_USERNAME: "you@example.com"
         FACEBOOK_PASSWORD: "your-facebook-password"
         UNITYSVC_API_KEY: "svcpass_..."
         TZ: "America/Chicago"
         PUID: "1000"
         PGID: "100"
       ports:
         - "8467:8467"
       volumes:
         - /share/Container/aimm/data:/data
   ```

   Write any `$` in a value as `$$`; Compose reads a single `$` as the start of a variable.
4. **Create**, then open `http://<NAS address>:8467` and continue with First run below. The application's container shows the log.

To update, open the application and choose **Recreate** (or remove it and create it again with the same YAML); the data folder keeps your config, cache and logs.

### Unraid

aimm is approved for **Community Applications** and appears on the **Apps** tab (search for *AI Marketplace Monitor*) once its catalog is next updated. Until then, add its template by hand:

1. Open the terminal (**>_** in the header) and save the template where Unraid keeps your own templates:

   ```bash
   wget -O /boot/config/plugins/dockerMan/templates-user/my-ai-marketplace-monitor.xml https://raw.githubusercontent.com/BoPeng/ai-marketplace-monitor/main/deploy/unraid/ai-marketplace-monitor.xml
   ```

2. **Docker › Add Container**, and under **Template** choose *ai-marketplace-monitor* from the user templates.
3. Fill in the Facebook username and password, and replace the placeholder UnitySVC API key with yours. The data goes to `/mnt/user/appdata/ai-marketplace-monitor`, owned by Unraid's `nobody:users` (`99`/`100`).
4. **Apply**, then open the web UI from the container's icon.

To update, use **Check for Updates** on the **Docker** tab, then **Apply update**.

### TrueNAS SCALE (Community Edition 24.10 or later)

aimm is proposed for the community train of TrueNAS's app catalog ([truenas/apps#6044](https://github.com/truenas/apps/issues/6044)). Until it is listed, add it as a custom app: TrueNAS runs a Compose file that you paste, and [`deploy/truenas/install-via-yaml.yaml`](https://github.com/BoPeng/ai-marketplace-monitor/blob/main/deploy/truenas/install-via-yaml.yaml) is one for aimm.

1. **Datasets**: select your pool, **Add Dataset**, name it `aimm` and choose the **Apps** preset. The dataset then belongs to the `apps` user (568), which aimm runs as.
2. If you have not used apps yet, choose a pool for them: **Apps › Configuration › Choose Pool**.
3. **Apps › Discover Apps**, the **⋮** menu next to **Custom App** › **Install via YAML**. Name the app `aimm` and paste the contents of [`install-via-yaml.yaml`](https://raw.githubusercontent.com/BoPeng/ai-marketplace-monitor/main/deploy/truenas/install-via-yaml.yaml):

   ```yaml
   services:
     aimm:
       image: ghcr.io/bopeng/ai-marketplace-monitor:latest
       restart: unless-stopped
       user: "568:568"
       environment:
         FACEBOOK_USERNAME: "you@example.com"
         FACEBOOK_PASSWORD: "your-facebook-password"
         UNITYSVC_API_KEY: "svcpass_XXXXX"
         TZ: "America/Chicago"
       ports:
         - "8467:8467"
       volumes:
         - /mnt/<pool>/aimm:/data
   ```

   Replace `<pool>` with your pool's name, fill in your Facebook login, UnitySVC API key and time zone, and write any `$` in a value as `$$`.
4. **Save**. When the app is **Running**, open `http://<TrueNAS address>:8467`.

To change a setting later, open the app and choose **Edit**. TrueNAS notices when a newer image is published and offers an **Update** for the app, as for catalog apps; the dataset keeps your data.

### CasaOS and ZimaOS

aimm is submitted to the CasaOS App Store. Until it is listed, import its template:

1. **App Store**, then **Custom Install** (the **+** at the top right) › **Import**.
2. Paste the contents of [`casaos/AIMarketplaceMonitor/docker-compose.yml`](https://raw.githubusercontent.com/BoPeng/ai-marketplace-monitor/main/deploy/casaos/AIMarketplaceMonitor/docker-compose.yml) and submit. CasaOS fills in the install form from it.
3. Fill in the Facebook username and password, and replace the placeholder UnitySVC API key with yours, **before** installing: the web UI does not start without the Facebook credentials. The data goes to `/DATA/AppData/<app>/data`.
4. **Install**, then open aimm from its tile on the dashboard.

### Cosmos

aimm is submitted to the Cosmos servapps market. Until it is listed, import its template: **ServApps › Import Compose File**, paste the contents of [`cosmos/AI-Marketplace-Monitor/cosmos-compose.json`](https://raw.githubusercontent.com/BoPeng/ai-marketplace-monitor/main/deploy/cosmos/AI-Marketplace-Monitor/cosmos-compose.json), and fill in the form it shows (the Facebook username and password, and your UnitySVC API key). Cosmos puts the data in a volume and serves the web UI through its reverse proxy.

### Umbrel

aimm is submitted to the Umbrel App Store ([getumbrel/umbrel-apps#6175](https://github.com/getumbrel/umbrel-apps/pull/6175)). Listed there, it will sign you in with a password that Umbrel shows for the app, and you will enter the Facebook credentials in its config editor. Until then, run it with Portainer, which the Umbrel App Store has:

1. In the Umbrel **App Store**, install **Portainer**, open it and sign in with the username and password that Umbrel shows for it.
2. Install aimm from Portainer's **App Templates** as described in Portainer below: set the community template list, choose **AI Marketplace Monitor**, fill in the form and deploy. Keep the template's named volume for `/data`: Umbrel's Portainer keeps only named volumes when it restarts or updates.
3. Open `http://umbrel.local:8467` (or your Umbrel's address with port 8467).

aimm then runs as a container of Portainer's, outside Umbrel's apps: Umbrel's login does not protect it, aimm's own sign-in does, and you update it in Portainer. Before installing aimm from the Umbrel App Store later, remove this container: both use port 8467.

### Portainer

Portainer is a web interface for managing Docker containers and Compose stacks. Its **App Templates** come from one list, set in **Settings › App Templates**. aimm is not in Portainer's default list, but it is in [Lissy93/portainer-templates](https://github.com/Lissy93/portainer-templates), a community collection of several hundred apps:

1. In **Settings › App Templates**, set **URL** to `https://raw.githubusercontent.com/Lissy93/portainer-templates/main/templates.json` and save. This replaces Portainer's default list.
2. In **App Templates**, choose **AI Marketplace Monitor**. Fill in the Facebook username and password, replace the placeholder UnitySVC API key with yours, and set the time zone. **Web UI sign-in** chooses whether aimm asks for the Facebook login (the default) or a web UI password of its own (`local`), or leaves the sign-in to your reverse proxy (see Who signs you in to the web UI below).
3. **Deploy the container**, then open `http://<host>:8467` and continue with First run below. The config, cache and logs are in a named volume mounted at `/data`.

To list only aimm instead, use `https://raw.githubusercontent.com/BoPeng/ai-marketplace-monitor/main/deploy/portainer/templates.json` as the URL. Portainer shows the form's passwords as plain text fields; its template format cannot mask them.

To update, open the container, choose **Recreate** and turn on **Re-pull image**; the volume keeps your data.

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

### Who signs you in to the web UI

`AIMM_WEBUI_AUTH`, in `.env` (or with `-e` for `docker run`), chooses who signs you in to the web UI:

- `facebook` (the default; `password` is its old name): aimm asks for the Facebook username and password, the same ones it logs in to Facebook with.
- `local`: aimm asks for a username and password of the web UI's own, `AIMM_WEBUI_USERNAME` (`admin` by default) and `AIMM_WEBUI_PASSWORD`, whatever the Facebook credentials are. aimm refuses to start without `AIMM_WEBUI_PASSWORD`. The web UI starts even before you have set the Facebook credentials, which you can then enter in its config editor. App platforms use this to show a password they generate.
- A reverse proxy that signs users in, as below.

### Let the reverse proxy sign you in

If your reverse proxy already signs users in, aimm does not need to ask for a password as well. Set `AIMM_WEBUI_AUTH` to the proxy that signs you in. aimm then checks, on every request, what that proxy adds once you are signed in, so a request that goes around the proxy is refused:

| `AIMM_WEBUI_AUTH` | Each request must carry | Settings |
| --- | --- | --- |
| `facebook` (default) | aimm's own sign-in, with the Facebook username and password | |
| `local` | aimm's own sign-in, with the web UI's own username and password | `AIMM_WEBUI_PASSWORD` (required) and `AIMM_WEBUI_USERNAME` (`admin` by default) |
| `authentik` | the signed token in `X-Authentik-Jwt` from Authentik's proxy outpost, issued for aimm's application | `AIMM_WEBUI_JWKS_URL`: the provider's JWKS URL, e.g. `https://auth.example.com/application/o/aimm/jwks/`. `AIMM_WEBUI_JWT_AUDIENCE`: the provider's client ID. The issuer is taken from the JWKS URL (`https://auth.example.com/application/o/aimm/`); set `AIMM_WEBUI_JWT_ISSUER` if your URL has another form |
| `cloudflare` | the signed token in `Cf-Access-Jwt-Assertion` from Cloudflare Access | `AIMM_WEBUI_CF_TEAM`: your team name (`<team>.cloudflareaccess.com`). `AIMM_WEBUI_JWT_AUDIENCE`: the application's AUD tag |
| `authelia` | the `Remote-User` header from Authelia's forward auth | Optional `AIMM_WEBUI_USER_HEADER` for another header, e.g. the one a basic-auth middleware sets |
| `proxy` | nothing | |

`authentik` and `cloudflare` verify a token that the identity provider signs, and that it was issued for aimm (its audience and issuer), so a forged request, or a token for another application, is refused even if it reaches aimm's port directly. When the token expires, aimm also ends the web UI's open connections: the log reconnects by itself with the proxy's new token, and you reopen the browser view or start the Configure chat again. `authelia` and `proxy` cannot tell your proxy from anyone else who reaches the port. For them, also set `AIMM_WEBUI_PROXY_SECRET` to a long random value (for example from `openssl rand -hex 32`), and have the proxy add it to every request as the `X-Aimm-Proxy-Secret` header, for example with Traefik's `headers` middleware (`customRequestHeaders`), nginx's `proxy_set_header` or Caddy's `header_up`. Without the secret, aimm logs a warning, and you must make sure that port 8467 is reachable only through the proxy: anyone who reaches it directly controls aimm and sees its browser, which is logged in to your Facebook account.

aimm still logs in to Facebook with `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD`, so keep them set. The web UI keeps protecting itself against requests from other websites, so a page you visit cannot use your proxy sign-in to change aimm's settings. Settings shows who the proxy signed in.

Container managers:

- **Umbrel** puts its own login in front of apps, but does not tell aimm who signed in, and another container on Umbrel's network can reach aimm without it. The template in `deploy/umbrel/` therefore keeps Umbrel authentication enabled and also uses `AIMM_WEBUI_AUTH=local`, with the username `umbrel` and the password Umbrel generates and shows for the app. Configure the Facebook credentials in aimm's web config editor.
- **CasaOS** signs you in to its dashboard, not to the apps, which are published on the host's ports. Keep `facebook`, or use `local` for a web UI password of its own.

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
- **More or less detail in the log**: set `AIMM_LOG_LEVEL` in `.env` (or with `-e` for `docker run`) to `DEBUG`, `INFO` (the default), `WARNING` or `ERROR`, then run `docker compose up -d`. It sets what the container log and the web UI's Logs tab show; `ai-marketplace-monitor.log` in the data folder always records everything.
- **The container shows as `unhealthy`**: the web UI does not answer. See the log; the image checks `http://127.0.0.1:8467/api/health` inside the container every 30 seconds.
- **"cannot write the data folder /data"**: the container was started as a user (`user:`) that does not own the mounted folder. Give it to that user (`sudo chown -R <uid>:<gid> data`), or remove `user:` and set `PUID` and `PGID` instead.
- **With `cap_drop: ALL`** (a hardened setup), add `cap_add: [SETUID, SETGID]` so that the container can switch to the `aimm` user, or start it as a fixed user with `user:`. Without `CHOWN`, aimm cannot change the owner of files in the data folder; it still starts if it can write them, and otherwise asks you to fix their permissions on the host. The same applies to NFS shares with `root_squash` and to SMB shares.
- **Run aimm commands in the container**, for example `docker compose exec aimm aimm check <listing>`, not with an aimm installed on the host. aimm's cache is an SQLite database, and the two would write it through the mounted directory at the same time and could damage it. If aimm stops with "cannot be read", run `docker compose exec aimm aimm admin --clear-cache all` and restart the container.
