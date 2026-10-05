# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `aimm-configure`: primary interactive configuration command, starting with `[ai.*]` setup and writing API keys as environment-variable references
- UnitySVC notifications (`[notification.unitysvc]` with `unitysvc_api_key`): messages go to UnitySVC's `notify` service (inbox plus your saved notification destination) or to a specific service set with `unitysvc_service`
- Email preset for UnitySVC's SMTP gateway: `smtp_server = "smtp.svcpass.com"` with `smtp_password = "${UNITYSVC_API_KEY}"` sends the HTML email to your UnitySVC-registered address, an alternative to a Gmail app password

### Fixed
- `aimm` and `aimm-configure` start much faster: the OpenAI, Anthropic, inflect and Playwright packages are loaded only when needed (a cold `aimm-configure` start drops from about 13 s to under 2 s)
- `aimm-configure ai` no longer proposes a model the provider does not offer: it lists the models the check found (keeping the current one when it still works, else the newest of the same family), warns about a model that is no longer available, and offers to fix a failing `[ai.*]` section before setting up a new one
- `aimm-configure ai` checks only the default (first) AI section, lists the others, and offers to keep, update or fix it, make another section the default (moving it to the top), or create a new section, which becomes the default; other flows fall back to the next section with a warning when the default fails
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

[Unreleased]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.3...HEAD
[0.10.3]: https://github.com/BoPeng/ai-marketplace-monitor/compare/v0.10.2...v0.10.3
[0.1.0]: https://github.com/BoPeng/ai-marketplace-monitor/compare/releases/tag/v0.1.0
