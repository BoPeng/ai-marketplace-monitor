# App store files

Templates for self-hosted platforms that install aimm's Docker image (`ghcr.io/bopeng/ai-marketplace-monitor`). Progress of each store is tracked in [#417](https://github.com/BoPeng/ai-marketplace-monitor/issues/417). For Docker Compose without an app store, see [`docker-compose/`](../docker-compose/).

| Folder | Platform | Image tag |
| --- | --- | --- |
| [`unraid/`](unraid/) | Unraid Community Applications | `latest` |
| [`casaos/AIMarketplaceMonitor/`](casaos/AIMarketplaceMonitor/) | CasaOS and ZimaOS App Store | pinned; bump it with each release |
| [`portainer/`](portainer/) | Portainer app templates | `latest` |
| [`umbrel/ai-marketplace-monitor/`](umbrel/ai-marketplace-monitor/) | Umbrel App Store | pinned by digest |
| [`runtipi/ai-marketplace-monitor/`](runtipi/ai-marketplace-monitor/) | Runtipi community stores | pinned |
| [`truenas/ai-marketplace-monitor/`](truenas/ai-marketplace-monitor/) | TrueNAS SCALE apps (community train) | pinned by digest |
| [`cosmos/AI-Marketplace-Monitor/`](cosmos/AI-Marketplace-Monitor/) | Cosmos Cloud servapps market | `latest` |

For Synology and QNAP, see "NAS and container managers" in the [Docker installation guide](../docs/docker-installation.md). Each template sets the same variables as that guide: `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` (aimm's Facebook login, which also signs you in to the web UI), `UNITYSVC_API_KEY` for the default configuration, `PUID`/`PGID`, and the data folder mounted at `/data`.

## Unraid

[`unraid/ai-marketplace-monitor.xml`](unraid/ai-marketplace-monitor.xml) uses Unraid's conventions: `PUID=99`, `PGID=100` and data in `/mnt/user/appdata/ai-marketplace-monitor`. Unraid sets `TZ` itself. The passwords are masked fields.

Until it is listed in Community Applications, install it by hand: copy the file to `/boot/config/plugins/dockerMan/templates-user/my-ai-marketplace-monitor.xml` on the Unraid server, then choose it in **Docker › Add Container › Template**.

To list it, use the current [Community Apps submission portal](https://ca.unraid.net/submit), not the older forum-only submission procedure:

1. Merge the template so its `TemplateURL`, icon and documentation links resolve on `main`. This repository has an OSI-approved root `LICENSE` and a root [`ca_profile.xml`](../ca_profile.xml) with the required non-empty profile.
2. Test the template on an Unraid host: installation, web UI sign-in, Facebook login through **Open browser**, persisted configuration, restart and image updates. Record the results in #417.
3. Sign in with an Unraid account, enter this public repository in the submission flow, run **Validate** and **Scan**, and inspect the listing preview. Fix any scan findings before submitting.
4. Complete submission and track review/listing in #417. Keep the XML and profile current as the app changes.

The template currently links to GitHub issues for support. A dedicated Unraid support topic is useful; if one is created, use its URL in the template's `Support` and optionally the profile's `Forum`. The current [profile guidance](https://ca.unraid.net/submit/help/repository-info-xml) makes `Forum` optional. See the [submission requirements](https://ca.unraid.net/submit/help) and [XML reference](https://ca.unraid.net/submit/help/repository-xml).

## CasaOS / ZimaOS

[`casaos/AIMarketplaceMonitor/docker-compose.yml`](casaos/AIMarketplaceMonitor/docker-compose.yml) follows the [CasaOS App Store](https://github.com/IceWhaleTech/CasaOS-AppStore) format: CasaOS passes `$PUID`, `$PGID` and `$TZ`, and keeps the data in `/DATA/AppData/$AppID/data`.

Until it is in the store, install it with **App Store › Custom Install › Import** and paste the file; set `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` (and `UNITYSVC_API_KEY`) before installing. Installed from the store, the credentials start empty: set them in the app's settings, as the install tip says, or the web UI does not start.

To submit it, copy the folder to `Apps/AIMarketplaceMonitor/` of a fork of the CasaOS App Store, add `icon.png` (from [`docs/icon.png`](../docs/icon.png)), `screenshot-1.png` and `thumbnail.png`, point `icon`, `thumbnail` and `screenshot_link` at those files in the store repository, and run the store's current v2 build (`./scripts/build_dist.sh`) and compose validator before opening a pull request. The template includes the v2 reverse-domain `id`, app `version`, and supported `AI` category. Service-level `x-casaos` descriptions are retained for legacy CasaOS imports; the v2 build removes them. See the [contribution guide](https://github.com/IceWhaleTech/CasaOS-AppStore/blob/main/CONTRIBUTING.md) and [metadata specification](https://github.com/IceWhaleTech/CasaOS-AppStore/blob/main/docs/specs/compose-and-x-casaos.md).

## Portainer

Portainer has no app store: it lists the templates of one URL, set in **Settings › App Templates**. [`portainer/templates.json`](portainer/templates.json) is such a list (format version 3) with one container template: the web UI on port 8467, a named volume for `/data`, and fields for the Facebook credentials, the UnitySVC key, the time zone and the web UI sign-in.

- To use it, set the templates URL to `https://raw.githubusercontent.com/BoPeng/ai-marketplace-monitor/main/deploy/portainer/templates.json`, then deploy **AI Marketplace Monitor** from **App Templates**. This URL replaces Portainer's default list.
- To appear next to other apps, the file can be added as a source of a community template collection such as [Lissy93/portainer-templates](https://github.com/Lissy93/portainer-templates), whose URL many Portainer users set instead.
- To use Docker Compose instead, paste [`docker-compose/docker-compose.yml`](../docker-compose/docker-compose.yml) into **Stacks › Add stack** and enter the variables of `.env.example` under **Environment variables**. Portainer saves them in a file named `stack.env`, not `.env`, so change `env_file: .env` to `env_file: stack.env`.

## Umbrel

[`umbrel/ai-marketplace-monitor/`](umbrel/ai-marketplace-monitor/) has the `umbrel-app.yml` manifest and a `docker-compose.yml` behind Umbrel's `app_proxy`, with the image pinned by digest. Umbrel has no settings form for an app, so the Facebook credentials cannot be passed as variables. Instead, Umbrel's own login protects the app, aimm runs with `AIMM_WEBUI_AUTH=proxy` (no sign-in of its own), and you enter the Facebook username and password in `[marketplace.facebook]` of `config.toml` in aimm's config editor. `proxy` mode cannot tell Umbrel's proxy from another container on Umbrel's network that connects to aimm directly.

To submit it, copy the folder to a fork of [getumbrel/umbrel-apps](https://github.com/getumbrel/umbrel-apps), include screenshots and the source logo in the PR body, and set `submission` to the pull request's URL. Keep `gallery: []` and empty `releaseNotes` for the initial submission; the Umbrel team prepares and hosts the final store assets. Run `npm run lint:apps -- ai-marketplace-monitor --check-images` in the store repository before submitting. Follow the [current packaging guidance](https://github.com/getumbrel/umbrel-apps/blob/master/.agents/skills/umbrel-package-app/SKILL.md). To try it first, add the folder to a community app store of your own.

## Runtipi

[`runtipi/ai-marketplace-monitor/`](runtipi/ai-marketplace-monitor/) has `config.json` (with form fields for the Facebook credentials and the UnitySVC key), the dynamic `docker-compose.json`, and `metadata/` with the description and logo. Runtipi passes `TZ` and `APP_DATA_DIR`. The official store is maintained but no longer accepts new apps; see [the maintainers’ explanation](https://github.com/runtipi/runtipi/issues/2317#issuecomment-3217972183). Submit to a maintained community store that accepts contributions, or publish a custom store. #417 lists eleven candidate stores; more are discoverable in [Runtipi's App Stores discussions](https://github.com/runtipi/runtipi/discussions/categories/app-stores). Confirm the chosen store's contribution policy, copy the folder into its `apps/`, run its validation, and test the app on Runtipi before requesting inclusion. For a custom store, follow [Create your own app store](https://runtipi.io/docs/guides/create-your-own-app-store).

## TrueNAS SCALE

[`truenas/ai-marketplace-monitor/`](truenas/ai-marketplace-monitor/) is an app for the community train of [truenas/apps](https://github.com/truenas/apps), made from its current apps: `app.yaml`, `item.yaml`, `ix_values.yaml` (the image pinned by digest), `questions.yaml` (the Facebook credentials and UnitySVC key are private fields), and `templates/docker-compose.yaml` with test values. aimm runs as the `apps` user (568) with all capabilities dropped, and a permissions container gives it the data folder.

To submit it, copy the folder to `ix-dev/community/` of a fork of truenas/apps. Select the latest supported non-v1 `lib_version`, run `devbox run copy-lib`, and commit the generated `templates/library/` and refreshed `lib_version_hash` with the app **before** opening a pull request. Do not copy or edit the library by hand, or rely on CI to supply missing files. Run the catalog's validation/rendering checks and port validation, and test installation on TrueNAS SCALE. Attach the icon and screenshots to the PR (or supply their URLs); the reviewer supplies the final TrueNAS CDN URLs. Follow the [current contribution guide](https://github.com/truenas/apps/blob/master/CONTRIBUTIONS.md).

## Cosmos Cloud

[`cosmos/AI-Marketplace-Monitor/`](cosmos/AI-Marketplace-Monitor/) has `cosmos-compose.json`, whose install form asks for the Facebook credentials and the UnitySVC key, and `description.json`. Cosmos exposes the web UI through its reverse proxy; aimm's own sign-in protects it. To submit it, copy the folder to `servapps/` of a fork of [azukaar/cosmos-servapps-official](https://github.com/azukaar/cosmos-servapps-official), add `icon.png` and a `screenshots/` folder, point `cosmos-icon` at the icon's URL in that repository, and open a pull request.

## Validation and release readiness

These files are submission starting points; a successful parse or Docker smoke test does not verify a platform's installer or store acceptance. #417 records real-host tests and external submissions. Never include real credentials in committed templates or screenshots.

Before submitting, validate in the target store repository and test installation, configuration persistence, Facebook login through the browser view, restart and image updates on that platform. Supply any platform-owned assets and generated files required by its current contribution guide. CasaOS requires credentials in the app settings before its password-protected UI can start; TrueNAS and Runtipi ask for them in their installation forms. Umbrel uses its own authenticated proxy and configures Facebook in the web editor.

For every aimm release, update the pinned CasaOS/Runtipi image tags, CasaOS metadata version, Umbrel/TrueNAS app versions and multi-architecture image digests, and submit matching updates to the selected stores. Verify the digest covers both supported architectures. `latest` templates follow the published image when users update through their container manager.
