# App store files

Templates for self-hosted platforms that install aimm's Docker image (`ghcr.io/bopeng/ai-marketplace-monitor`). Progress of each store is tracked in [#417](https://github.com/BoPeng/ai-marketplace-monitor/issues/417). For Docker Compose without an app store, see [`docker-compose/`](../docker-compose/).

| Folder | Platform | Image tag |
| --- | --- | --- |
| [`unraid/`](unraid/) | Unraid Community Applications | `latest` |
| [`casaos/AIMarketplaceMonitor/`](casaos/AIMarketplaceMonitor/) | CasaOS and ZimaOS App Store | pinned; bump it with each release |
| [`portainer/`](portainer/) | Portainer app templates | `latest` |

Each template sets the same variables as the [Docker installation guide](../docs/docker-installation.md): `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` (aimm's Facebook login, which also signs you in to the web UI), `UNITYSVC_API_KEY` for the default configuration, `PUID`/`PGID`, and the data folder mounted at `/data`.

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
