# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.10.11] - 2026-10-09

### Added
- The daily digest summarizes each item with AI: one to three sentences on what looks promising, what sold, went pending or dropped in price, and the best bet. It uses the item's AI services (in the order of its `ai` option) with one short call per item with new activity; an item with nothing new gets "Nothing new in the last 24 hours (N searches)." without a call. Summaries are shared by every user and channel of the same digest. When the AI fails, the digest is sent without them, and aimm stops asking for the rest of that digest so that an outage does not hold up searches.
- aimm tracks the status of listings it notified you about. Search results update when a listing was last seen and its price, and before a digest aimm opens the pages of listings notified in the past 7 days (at most 10 per item, once a day, 5 seconds apart) to see whether they sold or are pending. The digest tags them `Sold` or `Pending`, shows price changes as `(was $X)`, and lists earlier matches that sold, went pending or changed price under **Updates**.
- `AIMM_LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`; `INFO` by default) sets what the terminal or container log and the web UI's Logs tab show, for example in Docker, which runs without `--verbose`. `--verbose` still means `DEBUG`; the log file keeps everything.

### Changed
- The email digest is laid out per item: its counts, the AI summary, the notified listings, updates on earlier matches, and the top 5 listings rejected by AI. Items with nothing new are listed together in one line at the end, and the "By item" table is gone. Phone and chat digests show each item's summary with a link to its best bet, as many items as fit in 1,000 characters.
- Without `max_search_interval`, the time between searches is now random between `search_interval` and 1.5 × `search_interval` (it was up to a fixed hour, so a `search_interval` of an hour or more had no randomness). The "Next job" log line shows both intervals.
- The web UI's Logs tab follows the log level: it no longer shows `DEBUG` messages unless aimm runs with `--verbose` or `AIMM_LOG_LEVEL=DEBUG`, so they do not push useful history out of the retained log. Long messages are folded to a short preview until clicked, and AI responses are logged as one line with the answer and the tokens used instead of the whole response.
- The web UI's Configure chat starts from a card with the section picker and a **Start chat** button. Messages are typed in a multi-line box that appears only during a chat (Enter sends, Shift+Enter adds a line), answer buttons sit in the question they answer, a typing indicator shows while aimm works, and formatted messages render as lists, bold and code.
- The documentation explains that aimm's AI tasks (configuration, rating listings and digest summaries) need a mid-tier model that reads images, not a top-tier one, and that the daily digest uses AI tokens.

## [0.10.10] - 2026-10-09

### Added
- Docker Compose files in [`docker-compose/`](docker-compose/): `docker-compose.yml`, used as is, reads every setting from `.env` (credentials, API keys, `TZ`, `PUID`/`PGID`, `AIMM_PORT`); `.env.example` is its template; and `docker-compose.traefik.yml`, saved as `docker-compose.override.yml`, serves aimm through Traefik. The [Docker installation guide](docs/docker-installation.md) covers `docker run` and Docker Compose, the first run, a reverse proxy, updates and troubleshooting, and explains what one UnitySVC key covers.
- The Docker image reports its health: `GET /api/health` answers without signing in, and the image's `HEALTHCHECK` uses it, so `docker ps` and NAS app managers show the container as `healthy` or `unhealthy`.
- The image carries OCI labels (title, description, source, documentation, license), and `docs/icon.png` is a square app icon, for app stores such as Unraid, CasaOS, Umbrel and TrueNAS.
- `AIMM_WEBUI_AUTH` lets a reverse proxy sign users in to the web UI instead of aimm's Facebook username and password, and checks on every request and WebSocket that the proxy did: `authentik` and `cloudflare` verify the provider's signed token for aimm's application (audience and issuer) and end open connections when it expires; `authelia` requires the `Remote-User` header; `proxy` requires nothing. `AIMM_WEBUI_PROXY_SECRET`, sent by the proxy as `X-Aimm-Proxy-Secret`, protects the unsigned modes from requests that bypass the proxy. The default, `password`, is unchanged. See "Let the reverse proxy sign you in" in the [Docker installation guide](docs/docker-installation.md).

### Changed
- The Docker image runs aimm as an unprivileged `aimm` user instead of root. `PUID` and `PGID` (default `1000`) give that user your IDs so that files in the data folder stay yours; the container also runs as a fixed user (`--user`), with `cap_drop: ALL` plus `SETUID`/`SETGID`, and on shares that refuse `chown` but are writable (NFS `root_squash`, SMB). `docker exec aimm aimm ...` runs as the same user. `PUID`/`PGID` of 0 are refused.
- The Docker data folder is `/data` (new `AIMM_HOME` variable). A folder still mounted at `/root/.ai-marketplace-monitor` keeps working, and the log asks you to mount it at `/data` instead; on the first start the folder is given to `PUID:PGID`.
- The web UI's **Update** button appears only when aimm can update its own installation (the image's own user); otherwise update by pulling the image.
- The Dockerfile moved to `docker/Dockerfile`; build with `docker build -f docker/Dockerfile -t aimm .` from the repository root.
- The web UI's ⏸ now stops the monitor and ▶ starts it again: the config is reloaded and all items are searched right away, so changes saved while stopped take effect. ▶ refuses to start while the config on disk is invalid. Entering the CLI interactive session also stops the monitor, and leaving it restarts it. The browser, and so the Facebook login, is kept.
- The config file created on first run uses UnitySVC: `[ai.unitysvc]` with the `balanced` model rates listings, and `[user.me]` receives UnitySVC email with photos (`[notification.unitysvc_email]`) and UnitySVC phone/chat messages (`[notification.unitysvc]`), plus a daily digest at 08:00. `[marketplace.facebook]` logs in with the `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` environment variables, so with Docker only `FACEBOOK_USERNAME`, `FACEBOOK_PASSWORD` and `UNITYSVC_API_KEY` need to be set.

### Fixed
- The web UI read `username = "${FACEBOOK_USERNAME}"` and `password = "${FACEBOOK_PASSWORD}"` as literal text: when exposed (as in Docker), its login was `${FACEBOOK_USERNAME}` / `${FACEBOOK_PASSWORD}` instead of your Facebook credentials, and the startup banner showed `user: ${FACEBOOK_USERNAME}`. It now reads the variables, as the Facebook login does; an unset variable falls back to `FACEBOOK_USERNAME` / `FACEBOOK_PASSWORD`.
- A user receiving more than one notification no longer logs "Overriding ... for user" warnings for channel defaults (retries, rate limits, message format) that have the same value.
- AI agents are replaced, not duplicated, when the config is reloaded.

### Security
- In the Docker image, the VNC server listens on `127.0.0.1` only; the browser view is reachable only through the signed-in web UI.

## [0.10.9] - 2026-10-08

### Added
- A **Listings** view in the web UI shows every evaluated listing, its AI rating and reason, and whether it was notified, rejected by AI or excluded. Evaluation history is retained for 30 days by default, configurable with `evaluation_history_days`.
- Optional daily digests summarize searches, matches, rejected listings and exclusions. Set `digest_at` on a user to choose the local delivery time and `digest_with` to choose channels. Email receives the full digest; phone and chat channels receive a shorter summary. Delivery progress is remembered across restarts, with a single catch-up digest for missed days.
- A **Settings** dialog in the web UI provides version and update information, per-user test notifications, cache counts and clearing, CSV export, and logout where applicable. The header version and update notice also open Settings.
- `aimm admin --test-notification [USER]` sends a sample listing through each configured channel and reports success or failure for each. Tests use the real notification format, make one attempt per channel, and leave notification caches unchanged. The web UI offers the same test, and `aimm configure` offers it after saving notification changes.

### Changed
- The web UI's Configure pane has one **Start Chat** / **End Chat** button instead of **Start** and **Cancel**, which did not say that they start and stop the configuration chat (not a search). The section box reads "section (optional)".

### Removed
- The `--headless` option of `aimm`, `aimm run` and `aimm check`. aimm needs a visible browser so that you can complete Facebook's login checks (CAPTCHA, security code), which a hidden browser cannot show. To run aimm on a machine without a screen, use the Docker image: it has a virtual display, and its web UI shows you the browser.
- The documentation for searching without logging in to Facebook, which 0.10.8 no longer allows.

### Fixed
- Ending a configuration chat while it set up an AI service reported "No AI service is configured yet." and "Stopped with errors." It now reports "Chat ended.", and the web UI says so whichever step the chat was at.

## [0.10.8] - 2026-10-07

### Added
- The **▶** button in the web UI header is now a pause/resume toggle: **⏸** stops searching after the current listing, like pressing a key in the terminal, and **▶** resumes and searches all items right away. The status chip shows when aimm is paused. A restart resumes searching.
- While aimm waits for the Facebook login, the web UI shows a banner that says where to complete the CAPTCHA or security code. In Docker it has an **Open browser** button that opens aimm's browser (noVNC) in a new tab, so you do not have to find the **Browser** button in the header. The log message fits where aimm runs: Docker, a visible browser window, or `--headless`, which cannot show a CAPTCHA.

### Changed
- The README's quick start and Docker instructions describe the login flow: aimm types your Facebook username and password, you complete any CAPTCHA or security code (in Docker, through **Open browser**), and searches start once you are logged in.
- aimm waits after logging in until Facebook has really logged it in (the `c_user` cookie is set and the page is not a login, checkpoint or two-step verification page), however long a CAPTCHA or security code takes, and reminds you every five minutes. It used to wait a fixed minute and then search with a half-finished login, so Facebook redirected search and listing pages to its login page. The web UI shows "waiting for Facebook login" meanwhile.
- If Facebook logs aimm out later, it waits for the login the same way and retries the search or listing, instead of reporting that the listing "might be missing key information or not in English".
- Facebook `username` and `password` are required (in `[marketplace.facebook]` or the `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` environment variables): aimm no longer searches without logging in, which worked only some of the time.

### Deprecated
- `login_wait_time` is ignored, with a warning: aimm now waits until the login has finished.

### Fixed
- "Failed to get search results" was logged as an error after every search, including successful ones. A search that finds nothing now logs a "No search results" warning.
- A corrupted cache database (`cache.db`) no longer stops every `aimm` command, including `aimm admin --clear-cache`, with "database disk image is malformed". `aimm run` and `aimm check` now stop at startup with a message saying how to fix it, and `aimm admin --clear-cache all` removes the damaged cache files (`cache.db`, its `-wal`/`-shm` files and large-value folders) when the database cannot be read or cleared. The cache can be damaged when aimm on the host and aimm in Docker use `~/.ai-marketplace-monitor` at the same time.

## [0.10.7] - 2026-10-07

### Added
- The web UI header shows the running aimm version.
- In Docker, an **Update** button next to the version installs a newer release inside the container (`pip install` plus the matching Chromium) and restarts aimm; the page reloads when aimm is back. If the install fails, aimm keeps running the current version and the web UI shows the error.

### Fixed
- The Docker update instructions (README and the "newer release" notice) now recreate the container after `docker pull`. `docker restart` kept running the old image, so the update never took effect.
- The web UI editor shows the config file as soon as the Configure assistant saves it. It used to reload only when the Configure session ended, so after a save followed by "Is there anything else you'd like to change?" the editor kept showing the old file.

## [0.10.6] - 2026-10-07

### Changed
- The AI now sees each listing's main photo by default (`use_images = true`), so it can tell, for example, an iPad from an iPad keyboard case. aimm downloads the photo, shrinks it (at most 800 pixels; 400 for Anthropic, which charges by image size), and sends the image itself instead of its URL, which expires and which not every AI service fetches. Anthropic now gets the photo too, so all providers can read listing photos. Set `use_images = false` to evaluate listings from their text only and save tokens.
- Listings are notified at AI rating 4 (good match) or higher by default, instead of 3. Set `rating = 3` to also be notified of poor matches.
- `aimm configure` summaries now show whether an AI reads listing photos and which ratings a marketplace notifies, with the option to change each.
- `aimm configure` now offers UnitySVC email (`smtp.svcpass.com` with `smtp_username = "smtp-to-mailbox"`) first when the user wants email, with Gmail as the next option and instructions for creating a Gmail app password. UnitySVC HTTP notifications are offered for phone and chat alerts (Discord, Slack, SMS, push), not email.
- Notification summaries in `aimm configure` tell UnitySVC email (with listing photos) apart from UnitySVC phone/chat notifications (text only).
- `aimm configure` handles requests such as "switch my notifications to UnitySVC email" by replacing the old channel for the users who received it, instead of adding a second one.
- The AI documentation and `aimm configure ai` recommend UnitySVC's `balanced` tier, which is relatively inexpensive and supports image input, and advise checking image support when choosing another model.
- The web UI no longer hides settings such as `api_key = "${UNITYSVC_API_KEY}"`: a value that is a single `${VAR}` reference only names the environment variable that holds the secret, so it is shown as is, and as text in the form editor. Literal secrets are still shown as `<REDACTED>`.

### Fixed
- Listing descriptions are read correctly from Facebook's newer item pages when a category adds attributes after Condition, such as "Has Bluetooth" for electronics or "Bicycle Type" for bikes. aimm used to take the first such attribute (e.g. "Has BluetoothYes") as the description, so the AI never saw the seller's text.

## [0.10.5] - 2026-10-07

### Added
- Discord community links in the README support section, the general discussion issue template, and the startup messages for `aimm run` and `aimm configure`.
- `aimm configure` now opens with a summary of the current configuration, includes clearer section summaries, and gives better keyword guidance when building item sections.

### Changed
- Docker documentation now recommends `UNITYSVC_API_KEY`, explains how local environment variables are passed into the container, and walks through using the web UI plus the temporary Browser/noVNC tab for Facebook login or CAPTCHA prompts.
- The Docker web UI Browser link now passes an explicit host, port and `ws/vnc` path to noVNC.
- The release workflow no longer attempts the TestPyPI upload that failed during production releases.

### Fixed
- Docker images now send the `aimm` child process logs to `docker logs aimm`, so web UI and config startup errors are visible without entering the container.
- The built-in noVNC bridge no longer forces the `binary` WebSocket subprotocol when the packaged noVNC client did not request it, fixing Browser tab connection failures in Docker.
- The noVNC bridge now closes both sides of the TCP/WebSocket proxy when either side disconnects.

## [0.10.4] - 2026-10-05

### Added
- `aimm configure` as the primary AI-assisted configuration command. It can configure AI services, marketplace searches, items, notifications, users, monitor settings, regions, and translations, then validates and writes only confirmed changes.
- Section-scoped configuration commands such as `aimm configure ai`, `aimm configure marketplace.NAME`, `aimm configure item.NAME`, and `aimm configure notification` for focused edits.
- Web UI Configure chat that uses the same AI-assisted configuration flow from the browser.
- Mirascope-backed tool calling and playbooks for provider-independent AI-assisted configuration, with optional house rules in `~/.ai-marketplace-monitor/playbooks/`.
- UnitySVC AI support with model discovery, service aliases, and one `UNITYSVC_API_KEY` that can access almost arbitrary AI models through UnitySVC.
- UnitySVC notifications (`[notification.unitysvc]`) with 100+ notification channels through UnitySVC's `notify` service or a specific `unitysvc_service`.
- Email preset for UnitySVC's SMTP gateway: `smtp_server = "smtp.svcpass.com"` with `smtp_password = "${UNITYSVC_API_KEY}"` sends HTML email to your UnitySVC-registered address, as an alternative to a Gmail app password.
- Dedicated CLI subcommands: `aimm run`, `aimm check`, `aimm admin`, and `aimm configure`; bare `aimm` and `ai-marketplace-monitor` run the monitor loop.
- Update reminder: once a day the monitor checks PyPI and, when a newer release is out, logs the upgrade command for this installation (pip, pipx, `uv tool` or Docker) and shows a badge in the web UI header. Turn it off with `check_updates = false` in `[monitor]` or `AIMM_NO_UPDATE_CHECK=1`.
- `use_images = true` on an `[ai.*]` section sends the listing's main photo to the AI along with the text (OpenAI-compatible providers; `image_detail` defaults to `"low"` to keep the cost small). If a request with an image fails, the listing is evaluated from its text.

### Fixed
- Facebook listing descriptions no longer include injected ad and video text, and a page layout that finds no description no longer wins over one that does.
- `aimm` and `aimm configure` start much faster: the OpenAI, Anthropic, inflect and Playwright packages are loaded only when needed.
- `aimm configure ai` no longer proposes a model the provider does not offer: it lists the models the check found, warns about unavailable models, and offers to fix a failing `[ai.*]` section before setting up a new one.
- `aimm configure ai` checks only the default AI section, lists the others, and offers to keep, update or fix it, make another section the default, or create a new section.
- UnitySVC setup asks for the base URL (default `https://api.svcpass.com/p/llm`) and offers the models that URL lists, tiers and specific models alike, instead of a fixed list of four tiers; every provider's model list is fetched during setup when its key is set
- The model menu also accepts a typed model name; when requests to a base URL are not found (404) but the same request works under `<base_url>/v1`, setup says so and offers to save the `/v1` URL
- The default Anthropic model is now `claude-sonnet-5-5` (`claude-sonnet-4-20250514` is no longer offered)

## [0.10.3] - 2026-10-05

### Added
- Translation sections accept `enabled = false` to ignore a translation
- UnitySVC AI provider (`[ai.unitysvc]` or `provider = "unitysvc"`), using UnitySVC's OpenAI-compatible `llm` platform service with the `balanced` tier by default
- Option `request` on every config section to record, in your own words, what the section is for; reserved for upcoming AI-assisted configuration ([#362](https://github.com/BoPeng/ai-marketplace-monitor/issues/362))
- `--normalize-config` and `--expand-config` CLI inspection modes, plus `--config-file` as an alias for `--config`, for checking canonical and expanded config output without writing files ([#369](https://github.com/BoPeng/ai-marketplace-monitor/pull/369))

### Changed
- Config normalization now compacts user-specified defaults back to the minimal canonical form while preserving non-default selections and behavior-relevant order ([#369](https://github.com/BoPeng/ai-marketplace-monitor/pull/369))
- Expanded configs now make each item's bound marketplace explicit so item sections are self-contained for AI-assisted edits ([#369](https://github.com/BoPeng/ai-marketplace-monitor/pull/369))

### Fixed
- Spanish translation swapped the "About this vehicle" and "Seller's description" headings, so vehicle details and seller descriptions were not extracted from Spanish-language listings
- `docs/example_config.toml` used an invalid `search_city` value and could not be loaded
- Durations such as `search_interval = '1d'` could be computed one second short when the clock ticked during parsing

## [0.10.2] - 2026-07-17

### Added
- Option `sort_by` to order Facebook search results by `suggested`, `new` (newest first), `price_ascend`, `price_descend`, or `distance_ascend` ([#323](https://github.com/BoPeng/ai-marketplace-monitor/issues/323))
- Web UI "Export CSV" button that downloads all found (notified) listings with link, price, rating, and details ([#334](https://github.com/BoPeng/ai-marketplace-monitor/issues/334))
- Docker image bundling Xvfb + Playwright Chromium + noVNC, with a "Browser" button in the web UI that exposes the live Chromium session for solving Facebook CAPTCHA / interactive logins ([#310](https://github.com/BoPeng/ai-marketplace-monitor/issues/310))
- GitHub Actions workflow publishing multi-arch (amd64/arm64) images to `ghcr.io/bopeng/ai-marketplace-monitor`

### Fixed
- WebUI startup failure on older FastAPI versions ([#315](https://github.com/BoPeng/ai-marketplace-monitor/pull/315))
- Stale runtime version reporting ([#314](https://github.com/BoPeng/ai-marketplace-monitor/pull/314))

### Documentation
- Note Python 3.10+ requirement in Quick Start ([#311](https://github.com/BoPeng/ai-marketplace-monitor/pull/311))
- Fix broken WEBUI.md link in README

## [0.10.1]

### Added
- Built-in web UI for config editing and live monitoring (FastAPI + CodeMirror)
- TOML syntax highlighting in config editor
- Live log streaming with filtering by level, item, AI score, and text
- Guided forms for adding/editing AI backends, items, users, and marketplaces
- `--webui-host` and `--webui-port` CLI options for remote access
- No password required on localhost; credentials required for remote access
- `FACEBOOK_USERNAME` / `FACEBOOK_PASSWORD` environment variable fallback for credentials
- Graceful handling of missing `${ENV_VAR}` references (warning instead of error)

## [0.10.0]

### Added
- Anthropic/Claude as an AI backend provider with support for Claude models (default: `claude-sonnet-4-20250514`)
- [issue 235](https://github.com/BoPeng/ai-marketplace-monitor/issues/235) Configurable rate limiting framework for all notification types
  - Rate limiting infrastructure moved from Telegram-specific to base notification class
  - Automatic rate limiting for Telegram with intelligent chat type detection (1.1s individual, 3.0s group)
  - Configurable instance-level and global rate limiting for all notification methods
  - Opt-in rate limiting for email, PushBullet, PushOver, and other notification types
  - Comprehensive test coverage for rate limiting behavior
- Support for `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` environment variables as fallback credentials
- PyPI trusted publisher (OIDC) for release workflow

## [0.9.12]

- [Issue 289](https://github.com/BoPeng/ai-marketplace-monitor/issues/289). Fix 30s timeout delay in get_seller for anonymous mode.
- Change release workflow trigger from tag push to release creation.

## [0.9.11]

- [Issue 264](https://github.com/BoPeng/ai-marketplace-monitor/pull/264). Support different browsers.

## [0.9.10]

- [Issue 264](https://github.com/BoPeng/ai-marketplace-monitor/pull/264). Validate `search_city`.

## [0.9.9]

- [Issue 259](https://github.com/BoPeng/ai-marketplace-monitor/pull/259). Disallow keyboard monitoring by default.

## [0.9.8]

- [Issue 248](https://github.com/BoPeng/ai-marketplace-monitor/pull/248). Fix an issue with premature keyword filtering. Thanks to @adawalli

## [0.9.7]

- Add support for telegram [PR 231](https://github.com/BoPeng/ai-marketplace-monitor/pull/231). thanks to @adawalli

## [0.9.6]

- Fix searching across regions.
- Switch from `poetry` to `uv` for development.

## [0.9.5]

- [issue 155](https://github.com/BoPeng/ai-marketplace-monitor/issues/155) Fix output of pushbullet
- [issue 150](https://github.com/BoPeng/ai-marketplace-monitor/issues/150) Support option `category`

## [0.9.4] - 2025-04-15

- [issue 132](https://github.com/BoPeng/ai-marketplace-monitor/issues/132) Improve PushOver notification

## [0.9.3] - 2025-04-15

- [issue 102](https://github.com/BoPeng/ai-marketplace-monitor/issues/102) Fix pushover support and add more documentation

## [0.9.2] - 2025-04-07

- [issue 122](https://github.com/BoPeng/ai-marketplace-monitor/issues/122) Support searching across regions with different currencies

## [0.9.1] - 2025-03-13

- Re-release AI Marketplace Monitor under a AGPL license

## [0.8.8] - 2025-03-12

- Allow option date_listed to accept numeric value #96
- Fix importing pushover #91

## [0.8.6] - 2025-03-03

- Allow support for multiple languages.

## [0.8.5] - 2025-03-03

- Allow [pushover](https://pushover.net/) notification

## [0.8.2] - 2025-03-02

- Reorganize notification settings
- Support the use of environment variables for passwords
- Support browser proxy

**BREAKING CHANGES**

- Rename `smtp` sections to `notification`
- Rename parameter `smtp` to `notify_with`

## [0.7.11] - 2025-03-01

- Fix a bug on the handling of logical expressions for `keywords` and `antikeywords`.
- Add support for another auto layout page

## [0.8.9] - 2025-02-21

- Add options `prompt`, `extra_prompt` and `rating_prompt`

## [0.7.7] - 2025-02-17

- Expand the use of `enabled=False` to all sections
- Allow complex `AND` `OR` and `NOT` operations for `keywords` and `antikeywords`.

## [0.7.4] - 2025-02-10

- Rename `keywords` to `search_phrases`, `include_keywords` to `keywords` and `exclude_keywords` to `antikeywords` [#45]
- Separate statistics by item name [#46]

## [0.7.3] - 2025-02-07

- Allow email notification

## [0.7.0] - 2025-02-06

- Re-retrieve details of listings if there are title or price change
- Allow sending reminders for available items after specified time. (#41)
- Display counters

## [0.6.5] - 2025-02-05

- Allow checking URLs during monitoring (#34)
- Add option `ai` that allows the specification of AI models to use for certain marketplaces or items.
- Support locally hosted Ollama models
- Support DeepSeek-r1 model with `<think>` tags.
- Add option `timeout` to AI request.
- Expand command line option `--clear-cache`

## [0.6.2] - 2025-02-03

- Support extracting details from automobile listings.

## [0.6.1] - 2025-02-02

- Allow multiple `start_at`

## [0.6.0] - 2025-02-01

- Allow some parameters to different from initial and subsequent searches.
- Allow the AI to return a rating and some comments, and use the rating to determine if the user should be notified.

## [0.5.3] - 2025-01-31

- Add command line option `--diable-javascript` which can be helpful in some cases.
- Add option `include_keywords` to fine-tune the behavior of `keywords`.
- Add option `provider` to allow the specfication of more AI service providers.
- Allow `market_type` to marketplaces and allow multiple marketplaces.

## [0.5.1] - 2025-01-30

- Change the unit of `search-interval` to seconds to allow for more frequent search, although that is not recommended.
- Rename option `acceptable_locations` to `seller_locations`

## [0.5.0] - 2025-01-29

- Allow each time to add its own `search_interval`
- Add options such as `delivery_method`, `radius`, and `condition`
- Add options to define and use regions for searching large regions

## [0.4.5] - 2025-01-27

- Add option `--check` and `--for` to check particular listings

## [0.4.3] - 2025-01-26

- Add support for DeepSeek

## [0.4.0] - 2025-01-25

- Allow section `[ai.openai]`
- Use openAI to confirm if the item matches what user requests
- Slightly better logging

## [0.3.3] - 2025-01-21

- Allow option `enabled` for items
- Notify all users if no `notify` is specified for item or marketplace
- Compare string after normalization (#8)
- Stop sleeping if config files are changed. Allowing more interactive modification of search terms.
- Give more time after logging in, allow option `login_wait_time`.
- Allow entering username and password manually

## [0.2.0] - 2025-01-21

- Allow the definition of a reusable config file from `~/.ai-marketplace-monitor/config.toml`
- Allow options `exclude_sellers` and `exclude_by_description`
- Fix a bug that prevents the sending of phone notification

## [0.1.0] - 2025-01-20

### Added

- First release on PyPI.

[Unreleased]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.11...HEAD
[0.10.11]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.10...v0.10.11
[0.10.10]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.9...v0.10.10
[0.10.9]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.8...v0.10.9
[0.10.8]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.7...v0.10.8
[0.10.7]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.6...v0.10.7
[0.10.6]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.5...v0.10.6
[0.10.5]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.4...v0.10.5
[0.10.4]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.3...v0.10.4
[0.10.3]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.2...v0.10.3
[0.1.0]: https://github.com/BoPeng/ai-marketplace-monitor/compare/releases/tag/v0.1.0
