# App store files

Templates for self-hosted platforms that install aimm's Docker image (`ghcr.io/bopeng/ai-marketplace-monitor`). Progress of each store is tracked in [#417](https://github.com/BoPeng/ai-marketplace-monitor/issues/417). For Docker Compose without an app store, see [`docker-compose/`](../docker-compose/).

| Folder | Platform | Image tag |
| --- | --- | --- |
| [`unraid/`](unraid/) | Unraid Community Applications | `latest` |
| [`casaos/AIMarketplaceMonitor/`](casaos/AIMarketplaceMonitor/) | CasaOS and ZimaOS App Store | pinned; bump it with each release |

Each template sets the same variables as the [Docker installation guide](../docs/docker-installation.md): `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` (aimm's Facebook login, which also signs you in to the web UI), `UNITYSVC_API_KEY` for the default configuration, `PUID`/`PGID`, and the data folder mounted at `/data`.

## Unraid

[`unraid/ai-marketplace-monitor.xml`](unraid/ai-marketplace-monitor.xml) uses Unraid's conventions: `PUID=99`, `PGID=100` and data in `/mnt/user/appdata/ai-marketplace-monitor`. Unraid sets `TZ` itself. The passwords are masked fields.

Until it is listed in Community Applications, install it by hand: copy the file to `/boot/config/plugins/dockerMan/templates-user/my-ai-marketplace-monitor.xml` on the Unraid server, then choose it in **Docker › Add Container › Template**.

To list it, Community Applications needs a support thread on the Unraid forums and this repository submitted as a template repository.

## CasaOS / ZimaOS

[`casaos/AIMarketplaceMonitor/docker-compose.yml`](casaos/AIMarketplaceMonitor/docker-compose.yml) follows the [CasaOS App Store](https://github.com/IceWhaleTech/CasaOS-AppStore) format: CasaOS passes `$PUID`, `$PGID` and `$TZ`, and keeps the data in `/DATA/AppData/$AppID/data`.

Until it is in the store, install it with **App Store › Custom Install › Import** and paste the file; set `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` (and `UNITYSVC_API_KEY`) before installing. Installed from the store, the credentials start empty: set them in the app's settings, as the install tip says, or the web UI does not start.

To submit it, copy the folder to `Apps/AIMarketplaceMonitor/` of a fork of the CasaOS App Store, add `icon.png` (from [`docs/icon.png`](../docs/icon.png)), `screenshot-1.png` and `thumbnail.png`, point `icon`, `thumbnail` and `screenshot_link` at those files in the store repository, and open a pull request.
