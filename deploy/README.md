# App store files

Templates for self-hosted platforms that install aimm's Docker image (`ghcr.io/bopeng/ai-marketplace-monitor`). Progress of each store is tracked in [#417](https://github.com/BoPeng/ai-marketplace-monitor/issues/417). For Docker Compose without an app store, see [`docker-compose/`](../docker-compose/).

| Folder | Platform | Image tag |
| --- | --- | --- |
| [`unraid/`](unraid/) | Unraid Community Applications | `latest` |
| [`casaos/AIMarketplaceMonitor/`](casaos/AIMarketplaceMonitor/) | CasaOS and ZimaOS App Store | pinned; bump it with each release |
| [`portainer/`](portainer/) | Portainer app templates | `latest` |
| [`umbrel/ai-marketplace-monitor/`](umbrel/ai-marketplace-monitor/) | Umbrel App Store | pinned by digest |
| [`runtipi/ai-marketplace-monitor/`](runtipi/ai-marketplace-monitor/) | Runtipi App Store | pinned |
| [`truenas/ai-marketplace-monitor/`](truenas/ai-marketplace-monitor/) | TrueNAS SCALE apps (community train) | pinned by digest |
| [`cosmos/AI-Marketplace-Monitor/`](cosmos/AI-Marketplace-Monitor/) | Cosmos Cloud servapps market | `latest` |

For Synology and QNAP, see "NAS and container managers" in the [Docker installation guide](../docs/docker-installation.md). Each template sets the same variables as that guide: `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` (aimm's Facebook login, which also signs you in to the web UI), `UNITYSVC_API_KEY` for the default configuration, `PUID`/`PGID`, and the data folder mounted at `/data`.

## Unraid

[`unraid/ai-marketplace-monitor.xml`](unraid/ai-marketplace-monitor.xml) uses Unraid's conventions: `PUID=99`, `PGID=100` and data in `/mnt/user/appdata/ai-marketplace-monitor`. Unraid sets `TZ` itself. The passwords are masked fields.

Until it is listed in Community Applications, install it by hand: copy the file to `/boot/config/plugins/dockerMan/templates-user/my-ai-marketplace-monitor.xml` on the Unraid server, then choose it in **Docker › Add Container › Template**.

To list it, Community Applications needs a support thread on the Unraid forums and this repository submitted as a template repository.

## CasaOS / ZimaOS

[`casaos/AIMarketplaceMonitor/docker-compose.yml`](casaos/AIMarketplaceMonitor/docker-compose.yml) follows the [CasaOS App Store](https://github.com/IceWhaleTech/CasaOS-AppStore) format: CasaOS passes `$PUID`, `$PGID` and `$TZ`, and keeps the data in `/DATA/AppData/$AppID/data`.

Until it is in the store, install it with **App Store › Custom Install › Import** and paste the file; set `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` (and `UNITYSVC_API_KEY`) before installing. Installed from the store, the credentials start empty: set them in the app's settings, as the install tip says, or the web UI does not start.

To submit it, copy the folder to `Apps/AIMarketplaceMonitor/` of a fork of the CasaOS App Store, add `icon.png` (from [`docs/icon.png`](../docs/icon.png)), `screenshot-1.png` and `thumbnail.png`, point `icon`, `thumbnail` and `screenshot_link` at those files in the store repository, and open a pull request.

## Portainer

Portainer has no app store: it lists the templates of one URL, set in **Settings › App Templates**. [`portainer/templates.json`](portainer/templates.json) is such a list (format version 3) with one container template: the web UI on port 8467, a named volume for `/data`, and fields for the Facebook credentials, the UnitySVC key, the time zone and the web UI sign-in.

- To use it, set the templates URL to `https://raw.githubusercontent.com/BoPeng/ai-marketplace-monitor/main/deploy/portainer/templates.json`, then deploy **AI Marketplace Monitor** from **App Templates**. This URL replaces Portainer's default list.
- To appear next to other apps, the file can be added as a source of a community template collection such as [Lissy93/portainer-templates](https://github.com/Lissy93/portainer-templates), whose URL many Portainer users set instead.
- To use Docker Compose instead, paste [`docker-compose/docker-compose.yml`](../docker-compose/docker-compose.yml) into **Stacks › Add stack** and enter the variables of `.env.example` under **Environment variables**. Portainer saves them in a file named `stack.env`, not `.env`, so change `env_file: .env` to `env_file: stack.env`.

## Umbrel

[`umbrel/ai-marketplace-monitor/`](umbrel/ai-marketplace-monitor/) has the `umbrel-app.yml` manifest and a `docker-compose.yml` behind Umbrel's `app_proxy`, with the image pinned by digest. Umbrel has no settings form for an app, so the Facebook credentials cannot be passed as variables. Instead, Umbrel's own login protects the app, aimm runs with `AIMM_WEBUI_AUTH=proxy` (no sign-in of its own), and you enter the Facebook username and password in `[marketplace.facebook]` of `config.toml` in aimm's config editor. `proxy` mode cannot tell Umbrel's proxy from another container on Umbrel's network that connects to aimm directly.

To submit it, copy the folder to a fork of [getumbrel/umbrel-apps](https://github.com/getumbrel/umbrel-apps), add the icon and gallery images to [getumbrel/umbrel-apps-gallery](https://github.com/getumbrel/umbrel-apps-gallery) as its guidelines say, and set `submission` to the pull request's URL. To try it first, add the folder to a community app store of your own.

## Runtipi

[`runtipi/ai-marketplace-monitor/`](runtipi/ai-marketplace-monitor/) has `config.json` (with form fields for the Facebook credentials and the UnitySVC key), the dynamic `docker-compose.json`, and `metadata/` with the description and logo. Runtipi passes `TZ` and `APP_DATA_DIR`. To submit it, copy the folder to `apps/` of a fork of [runtipi/runtipi-appstore](https://github.com/runtipi/runtipi-appstore) and open a pull request; to try it first, add it to an app store repository of your own.

## TrueNAS SCALE

[`truenas/ai-marketplace-monitor/`](truenas/ai-marketplace-monitor/) is an app for the community train of [truenas/apps](https://github.com/truenas/apps), made from its current apps: `app.yaml`, `item.yaml`, `ix_values.yaml` (the image pinned by digest), `questions.yaml` (the Facebook credentials and UnitySVC key are private fields), and `templates/docker-compose.yaml` with test values. aimm runs as the `apps` user (568) with all capabilities dropped, and a permissions container gives it the data folder.

To submit it, copy the folder to `ix-dev/community/` of a fork of truenas/apps and let its tooling add `templates/library` and refresh `lib_version_hash` (its CI runs `apps_catalog_hash_generate`), then open a pull request.

## Cosmos Cloud

[`cosmos/AI-Marketplace-Monitor/`](cosmos/AI-Marketplace-Monitor/) has `cosmos-compose.json`, whose install form asks for the Facebook credentials and the UnitySVC key, and `description.json`. Cosmos exposes the web UI through its reverse proxy; aimm's own sign-in protects it. To submit it, copy the folder to `servapps/` of a fork of [azukaar/cosmos-servapps-official](https://github.com/azukaar/cosmos-servapps-official), add `icon.png` and a `screenshots/` folder, point `cosmos-icon` at the icon's URL in that repository, and open a pull request.
