# Configuration Reference

**Table of content:**

- [AI Services](#ai-services)
- [Marketplaces](#marketplaces)
- [Users](#users)
- [Email and notifications](#email-and-notifications)
- [Email](#email)
- [Phone and chat notifications](#phone-and-chat-notifications)
- [Items to search](#items-to-search)
- [Common item and marketplace options](#common-item-and-marketplace-options)
- [Regions](#regions)
- [Translators](#translators)
- [Monitor Configuration](#monitor-configuration)
- [Additional options](#additional-options)

The AI Marketplace Monitor uses [TOML](https://toml.io/en/) configuration files to control its behavior. The system will always check for a configuration file at `~/.ai-marketplace-monitor/config.toml`. You can specify additional configuration files using the `--config` or `--config-file` option.

AIMM provides a large number of options, and most of them have default values or values derived from the rest of your configuration: an item takes its location, price range and other search options from its marketplace, and a user without `notify_with` receives every email and notification section. Two commands show your configuration in two equivalent forms, without writing anything back to disk:

- `aimm admin --expand-config` prints the **expanded** form, which writes out these inherited values in each section: every item with the options it gets from its marketplace, and every user with the sections it receives. It shows what each item and user actually uses. Built-in defaults that no section sets (such as `max_retries`) are not listed; this reference gives them for each option.
- `aimm admin --normalize-config` prints the **normalized** form, the most compact configuration that does the same: values shared by all the items of a marketplace move into the marketplace, identical sections are merged, and values that equal their default are dropped. This is the form in which `aimm configure` and the web UI's assistant write the file.

Both options also accept explicit files, for example `aimm admin --config-file my-config.toml --normalize-config`.

To avoid including sensitive information directly in the configuration file, all options that accept a string or a list of string can be specified using the `${ENV_VAR}` format. For example

```toml
[marketplace.facebook]
password = '${FACEBOOK_PASSWORD}'

[user.me]
email = ['${EMAIL_1}', '${EMAIL_2}']

[notification.pushbullet]
pushbullet_token = '${PUSHBULLET_TOKEN}'
```

_AI Marketplace Monitor_ will retrieve the value from the corresponding environment variable and raise an error if the environment variable does not exist.

Here is a complete list of options that are acceptable by the program. [`example_config.toml`](example_config.toml) provides an example with many of the options.

### AI Services

| Service | With UnitySVC | UnitySVC with your own keys (BYOK) | Without UnitySVC |
| --- | --- | --- | --- |
| **AI** that rates listings | `[ai.unitysvc]`: UnitySVC's model pool, paid per use | `[ai.unitysvc]` with an OpenAI, Anthropic or other provider's service and your key for it saved in UnitySVC; the provider bills you | `[ai.openai]`, `[ai.anthropic]`, `[ai.gemini]`, `[ai.deepseek]`, or a local model with `[ai.ollama]` |

One or more `[ai.NAME]` sections list the AI services that judge whether listings match your selection criteria. Each section accepts the following options:

| Option        | Requirement | DataType | Description                                                |
| ------------- | ----------- | -------- | ---------------------------------------------------------- |
| `provider`    | Optional    | String   | Name of the AI service provider.                           |
| `api_key`     | Optional    | String   | A program token to access the RESTful API.                 |
| `base_url`    | Optional    | String   | URL for the RESTful API                                    |
| `model`       | Optional    | String   | Language model to be used.                                 |
| `max_retries` | Optional    | Integer  | Max retry attempts if connection fails. Default to 10.     |
| `timeout`     | Optional    | Integer  | Timeout (in seconds) waiting for response from AI service. |
| `use_images`  | Optional    | Boolean  | Send the listing photo to the AI service. Default to `true`. |
| `image_detail` | Optional   | String   | Image detail level: `low`, `high`, `original`, or `auto`. Default to `low`. |
| `rate_limit`  | Optional    | String   | Most requests the service accepts, such as `"15/minute"`, `"1000/hour"` or `"1500/day"`. No limit by default. |

Note that:

1. `provider` can be [UnitySVC](https://unitysvc.com/), [OpenAI](https://openai.com/), [DeepSeek](https://www.deepseek.com/), [Gemini](https://ai.google.dev/), [Anthropic](https://www.anthropic.com/) or [Ollama](https://ollama.com/). The name of the section is used if this option is not specified, so `OpenAI` is used for section `ai.openai`.
2. You can use option `ai` to list the AI services for particular marketplaces or items.
3. aimm uses the first `[ai.*]` section (the default AI) and tries the next ones only when it fails. The order of the list in option `ai` does not matter; reorder the sections, or use `aimm configure ai` to make another section the default.
4. `use_images` (on by default) lets the AI see the main listing photo, so it can tell, for example, a tablet from a tablet case. aimm downloads the photo, shrinks it, and sends the image itself rather than its URL, because Facebook photo URLs expire and not every AI service fetches them. All providers get the photo. It requires a vision-capable model and adds image tokens to every new evaluation. UnitySVC's `balanced` tier supports images; when you choose another model, check that it accepts image input (and responds in reasonable time with one), or set `use_images = false` for it. For OpenAI-compatible providers the photo is at most 800 pixels on its longest side and costs roughly 85 tokens at `image_detail = "low"`, and up to 1,000 or more at `"high"`, which can double the cost of each request. Anthropic has no `image_detail` and charges by image size, so aimm sends it a photo of at most 400 pixels (about 200 tokens). Set `use_images = false` to evaluate listings from their text only and save these tokens. If the photo cannot be downloaded, or the service rejects a request with it for another reason than its rate limit (for example, a model that does not accept images), the listing is evaluated from its text. A request rejected for the rate limit is retried with the photo, as described under `rate_limit`.
5. `rate_limit` keeps aimm within the request limit of your plan, for example `rate_limit = "15/minute"` for a free Gemini key. The number can be per `second`, `minute`, `hour` or `day`. aimm spaces the requests evenly: `"15/minute"` sends at most one request every 4 seconds, and `"1000/hour"` one every 3.6 seconds. It does not send a burst of requests and then wait, because providers count their limits differently, and some reject a burst even when the total for the minute is within the limit. Retries count as requests, and evaluations remembered from earlier searches send none. Searches wait for the AI, so a low limit also slows down the searches. A daily limit makes a long gap (about a minute between evaluations for `"1500/day"`), even when the quota would allow a short burst, so with only a daily limit a per-minute rate that fits your usage may be faster. Whether or not `rate_limit` is set, when the service rejects a request for going over its limit, aimm waits as long as the service asks before trying again; if that is more than 5 minutes (for example a used-up daily quota), aimm uses the next AI instead.

#### With UnitySVC

[UnitySVC](https://unitysvc.com/) is a gateway to services from many providers behind one API key. By default, aimm uses its OpenAI-compatible `llm` platform service at `https://api.svcpass.com/p/llm`, paid per use. Its `model` (default `balanced`) is either a tier (`fast`, `balanced`, `coding`, `premium`), for which UnitySVC picks the provider and fails over between them, or a specific model; `aimm configure ai` lists the models your key can use. The default `balanced` tier is recommended: it is relatively inexpensive and its models support vision (image input), so they can read listing photos (see `use_images` above). The same key (`UNITYSVC_API_KEY`) is used for UnitySVC [email](#email) and [phone and chat notifications](#phone-and-chat-notifications), so one key covers rating listings and delivering the results.

A typical section for UnitySVC looks like the following, with the key kept in the `UNITYSVC_API_KEY` environment variable rather than in the file:

```toml
[ai.unitysvc]
api_key = '${UNITYSVC_API_KEY}'
```

To use a specific service from the [UnitySVC catalog](https://unitysvc.com/market) instead of the `llm` platform pool, set `base_url` to the service URL shown on its catalog page and `model` to a model the service offers:

```toml
[ai.unitysvc]
api_key = '${UNITYSVC_API_KEY}'
base_url = 'https://api.svcpass.com/<service path>'
model = '<model name>'
```

UnitySVC also lets you:

- **Switch providers without editing the config.** Set `base_url` to a self-defined alias such as `https://api.svcpass.com/a/myllm`, then point that alias at any LLM service on UnitySVC and re-point it whenever you like.
- **Log requests.** Prefix the path with `/l/` to record each call in your UnitySVC request logs, e.g. `base_url = 'https://api.svcpass.com/l/p/llm'`. This works with any path, such as `/l/a/myllm`, and is useful for checking what aimm sends and what the model returns.
- **Request formats.** aimm sends OpenAI Chat Completions requests; UnitySVC translates them for services whose upstream speaks another format, such as Anthropic's.

#### UnitySVC with your own keys (BYOK)

Many LLM services have a "Requires Secrets" channel where you bring your own key: save it once as a UnitySVC secret (Developer → Secrets, e.g. `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`), and UnitySVC injects it into requests to that provider. Your provider bills you directly; UnitySVC does not charge for these bring-your-own-key calls in normal use. Your aimm config still holds only `UNITYSVC_API_KEY`; the provider key never leaves UnitySVC. When a service has several channels, pin one by appending `@<channel>` to the service name in `base_url`.

For example, with your OpenAI key saved as the UnitySVC secret `OPENAI_API_KEY`, set `base_url` to the OpenAI service you picked in the catalog; your configuration still holds only `UNITYSVC_API_KEY`.

#### Without UnitySVC

Each provider needs its own account and API key, set in its section (preferably as an environment variable reference such as `'${OPENAI_API_KEY}'`).

1. [OpenAI](https://openai.com/), [DeepSeek](https://www.deepseek.com/), and [Gemini](https://ai.google.dev/) models sets default `base_url` and `model` for these providers.
2. [Anthropic](https://www.anthropic.com/) uses the Anthropic SDK directly (not OpenAI-compatible). The default model is `claude-sonnet-5-5`. An `api_key` is required.
3. [Gemini](https://ai.google.dev/) is accessed through Google's OpenAI-compatible endpoint. The default model is `gemini-2.5-flash`. An `api_key` is required and can be obtained from [Google AI Studio](https://aistudio.google.com/apikey).
4. Ollama models require `base_url`. A default model is set to `deepseek-r1:14b`, which seems to be good enough for this application. You can of course try [other models](https://ollama.com/library) by setting the `model` option.
5. Although only six providers are directly supported, you can use any other service provider with `OpenAI`-compatible API using customized `base_url`, `model`, and `api_key`.

A typical section for OpenAI looks like

```toml
[ai.openai]
api_key = 'sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
```

A typical section for Anthropic looks like

```toml
[ai.anthropic]
api_key = 'sk-ant-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
```

A typical section for Gemini looks like

```toml
[ai.gemini]
api_key = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
```

A typical section for a local model with Ollama looks like

```toml
[ai.ollama]
base_url = 'http://localhost:11434/v1'
model = 'deepseek-r1:14b'
```

The easiest way to set up an AI service is `aimm configure`: it is the primary interactive configuration command, checks your `[ai.*]` sections first, helps you add or update one, and writes the section with the key referenced as an environment variable.

### Marketplaces

aimm searches two marketplaces: [Facebook Marketplace](#facebook-marketplace), which needs a Facebook account, and [OfferUp](#offerup) (US only), which needs no account. One or more sections `marketplace.name` say how to search them, and provide default values for the items searched in them.

| Option             | Requirement | DataType | Description                                                                                                      |
| ------------------ | ----------- | -------- | ---------------------------------------------------------------------------------------------------------------- |
| `market_type`      | Optional    | String   | The type of marketplace: `facebook` or `offerup`. Without it, a section named after a marketplace type (`[marketplace.facebook]`, `[marketplace.offerup]`) has that type, and any other section is a Facebook marketplace. A section sets only the options its type has. |
| **Common options** |             |          | Options listed in the [Common options](#common-item-and-marketplace-options) section below that provide default values for all items. |

Multiple marketplaces with different `name`s can be specified for different `item`s (see [Multiple marketplaces](../README.md#multiple-marketplaces)). An item without `marketplace` is searched in every marketplace section; give it `marketplace` to keep it to some of them.

#### Facebook Marketplace

Searching Facebook Marketplace needs two things:

- **A Facebook account.** aimm logs in with it, and searches only while logged in. Give its login as `username` and `password` (below), or set the environment variables `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD`; one of them is required, and aimm reports a configuration error without them.
- **A browser.** aimm searches Facebook in a Chromium browser that it controls (through [Playwright](https://playwright.dev/python/)). After `pip install ai-marketplace-monitor`, install the browser once with `playwright install`; the Docker image includes it. When Facebook asks for a CAPTCHA or a security code, you complete it in that browser window, or in Docker in the **Browser** tab of the web UI.

OfferUp needs neither: without a Facebook section, aimm starts no browser and needs no Facebook login.

A Facebook section takes these options in addition to the common ones:

```toml
[marketplace.facebook]
search_city = "houston"   # Facebook's location code; aimm configure finds it for you
```

| Option             | Requirement | DataType | Description                                                                                                      |
| ------------------ | ----------- | -------- | ---------------------------------------------------------------------------------------------------------------- |
| `username`         | Required    | String   | The Facebook username. Falls back to the `FACEBOOK_USERNAME` environment variable if not set. aimm searches only while logged in. |
| `password`         | Required    | String   | The Facebook password. Falls back to the `FACEBOOK_PASSWORD` environment variable if not set.                       |
| `login_wait_time`  | Deprecated  | Integer  | Ignored. aimm now waits until the Facebook login has finished, however long a CAPTCHA or security code takes.   |
| `language`         | Optional    | String   | Language for webpages                                                                                            |

1. aimm logs in with `username` and `password`, then waits until Facebook has finished logging in before it searches: if Facebook asks for a CAPTCHA or a security code, complete it in the browser window (in Docker, the **Browser** tab of the web UI), and searches start once you are logged in. If Facebook logs aimm out later, it waits the same way and retries the page. aimm no longer searches without logging in, which worked only some of the time. `username` and `password` can be provided in three ways (in order of priority): directly in the config file, via the `${ENV_VAR}` syntax (e.g. `password = '${MY_FB_PASS}'`), or automatically from the `FACEBOOK_USERNAME` and `FACEBOOK_PASSWORD` environment variables. If none are set, aimm reports a configuration error.
2. If `language="LAN"` is specified, it must match to one of `translation` sections, defined by yourself or in the system configuration file. The system will try exact match (e.g. `es` to `es` or `zh_CN` to `zh_CN`), then partial match (e.g. `es` to `es_CO` or `es_CO` to `es`).
3. Please see [Support for non-English languages](../README.md#support-for-non-english-languages) on how to set this option and define your own translations.

#### OfferUp

aimm searches [OfferUp](https://offerup.com) (US only) without an account and without a browser, through the API OfferUp's website uses. An OfferUp section needs only a location:

```toml
[marketplace.offerup]
search_city = "77002"      # a US ZIP code or "latitude,longitude", or a list of them
radius = 30                # miles: OfferUp offers 5, 10, 20, 30 and 50 (the nearest is used)
```

- `search_city` is a US ZIP code or a `"latitude,longitude"` pair (or several), not a Facebook location code; `city_name` names them in the log. To search the same place on Facebook and OfferUp, give a table: `search_city = { facebook = "houston", offerup = "77096" }`. A region can serve OfferUp when its cities have `offerup` values (the built-in regions have Facebook codes only).
- OfferUp sections take the [common options](#common-item-and-marketplace-options); `availability`, `category`, `language`, `currency` and the login options are Facebook's. An item searched in both an OfferUp and a Facebook section uses the Facebook-only options in the Facebook section only (aimm logs a warning).
- OfferUp's search sorts newest first unless `sort_by` says otherwise, and filters by `condition` (`new`; `used_like_new` as open box or used; `used_good` and `used_fair` as used), `min_price` and `max_price` (in US dollars; other currencies are converted). It has no filter for a listing's age or delivery: `date_listed` and `delivery_method` are checked after aimm reads the listing.
- aimm reads each seller's public profile (when they joined OfferUp, rating, items sold, what buyers praise, verifications such as TruYou) for the AI and the seller filters. OfferUp does not show a seller's number of active listings.
- Without a Facebook section, aimm starts no browser (the web UI's browser view starts one on demand) and needs no Facebook credentials. The web UI then signs you in with `AIMM_WEBUI_PASSWORD` (see [Who signs you in to the web UI](docker-installation.md#who-signs-you-in-to-the-web-ui)).
- OfferUp answers only requests from the US: elsewhere, set `proxy_server` in `[monitor]` to a US proxy. aimm spaces its requests by a few seconds; if OfferUp refuses them (HTTP 403), aimm logs it and tries again at the next search.
- OfferUp's terms prohibit automated collection, as Facebook's do. aimm is meant for personal use.

### Users

One or more `user.username` sections can be defined in the configuration. The `username` is one of the usernames listed in the `notify` option of `marketplace` or `item`. A user section says who receives notifications and which `email` and `notification` sections they receive; how messages are sent belongs in those sections. Each `user` section accepts the following options

| Option              | Requirement | DataType    | Description                                                                                                                                                  |
| ------------------- | ----------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `notify_with`       | Optional    | String/List | The `email` and `notification` sections the user receives, as `email.NAME` and `notification.NAME` (a bare `NAME` works when only one kind has a section of that name). By default, all enabled sections. |
| `remind`            | Optional    | String      | Enables repeated notifications for the user after a specified duration (e.g., 3 days) if a listing remains active. By default, users are notified only once. |
| `email`             | Optional    | String/List | Where the user receives email. Not needed for `[email.unitysvc]`, which sends to the address registered with UnitySVC.                                      |
| `telegram_chat_id`  | Optional    | String      | Where the user receives Telegram messages.                                                                                                                   |
| `pushover_user_key` | Optional    | String      | The user's Pushover user key.                                                                                                                                |
| `ntfy_topic`        | Optional    | String      | The ntfy topic the user subscribes to.                                                                                                                       |

```toml
[user.me]
email = "me@example.com"
telegram_chat_id = "123456789"
notify_with = ["email.gmail", "notification.telegram"]
```

### Email and notifications

aimm sends two kinds of messages, set up in two kinds of sections:

- An **`[email.NAME]`** section sends aimm's full email: all new listings in one message, with their photos. Best for reviewing listings.
- A **`[notification.NAME]`** section is one phone or chat channel (UnitySVC, Pushbullet, Pushover, ntfy or Telegram) that sends short text messages. Best for being alerted quickly.

Each section a user receives sends on its own, with the user's values (such as `email` or `telegram_chat_id`) filled in where the section does not set them. Sections can be shared by several users, and one user can receive several sections of the same kind, for example email through both UnitySVC and Gmail:

```toml
[user.me]
email = 'me@example.com'
notify_with = ['email.unitysvc', 'email.gmail', 'notification.pushbullet']

[user.other]
email = 'other@example.com'
notify_with = ['email.gmail']

[email.unitysvc]
smtp_username = 'smtp-to-mailbox'

[email.gmail]
smtp_username = 'me@gmail.com'

[notification.pushbullet]
pushbullet_token = "${PUSHBULLET_TOKEN}"
```

If `notify_with` is not specified, the user receives every enabled email and notification section.

#### Daily digest

`digest_at` on an email or notification section (a local time `HH:MM`, e.g. `"08:00"`, like `start_at`) makes the section send, every day at that time, a summary of everything aimm did in the last 24 hours, for all items, not only the ones the user is notified for. The digest uses AI tokens: one short AI call per item with new activity, to summarize it. By default, no section sends a digest. When a user gets email, set `digest_at` on the email section only: a phone digest next to the email one is rarely wanted.

```toml
[email.unitysvc]
smtp_username = 'smtp-to-mailbox'
digest_at = '08:00'
```

An **email** section sends the full digest: a summary table, then for each item its counts, an AI-written summary (what looks promising, what sold or dropped in price, and the best bet; written by the item's AI service, with no AI call for an item with nothing new), the notified listings (title, price, rating and link), updates on earlier matches, and the top 5 listings rejected by AI (best ratings first, with a short reason). Items with nothing new are not given a section: they are listed together in one line after the others. A listing evaluated by several searches counts once. A **notification** section sends a short version for the phone: one line of totals, then each item's summary with a link to its best bet, as many items as fit (the rest are in the email digest); without summaries, the top 3 matches with links. A day without matches says how many searches aimm ran, so that silence does not look like a broken aimm.

The listings are those evaluated in the last 24 hours, so a listing that stays on the market and is evaluated again on every search can appear in more than one digest. The first digest is sent at the next `digest_at` after the option is added. Each day's digest covers the 24 hours up to that day's `digest_at`, even when it is sent later. aimm remembers, for each channel, up to when it has received the digest, so a restart does not send it twice. A channel that is behind, because aimm was not running or sending to it failed, gets one catch-up digest when aimm starts again or reloads its config, from where it left off (at most 7 days back) to the latest digest time, labeled "since Mon Oct 5 08:00" instead of "last 24 hours"; it never gets several old digests in a row. Before sending it, aimm opens the pages of listings it notified you about in the past 7 days (at most 10 per item, once a day) to see whether they sold or are pending; the digest tags them, shows price changes as `(was …)`, and lists earlier matches that sold, went pending or changed price under **Updates**.

#### Older configurations

Earlier versions of aimm put email settings in `[notification.*]` sections, channel settings (such as `smtp_password` or `pushbullet_token`) in `[user.*]` sections, and `digest_at` and `digest_with` on the user. aimm updates such a file the first time it reads it: email settings move to `[email.*]` sections (`[email.unitysvc]` for `smtp.svcpass.com`, `[email.gmail]` for `smtp.gmail.com`, otherwise the section's own name), channel settings move from users into sections, and the digest moves onto the sections that sent it. What each user receives does not change. The old file is kept as `<file>.bak`, and the log lists each change.

#### Testing notifications

To check your notification setup without waiting for a match, send a test message:

```bash
aimm admin --test-notification        # every channel of every enabled user
aimm admin --test-notification me     # the channels of [user.me] only
```

aimm sends a sample listing titled "aimm test notification", which links to the aimm repository, through each channel once (no retries). The test uses the real format of each channel, so it checks the layout as well as the connection: email gets aimm's HTML email with the listing photo (a sample photo bundled with aimm), and chat and phone channels get the text or Markdown message of their `message_format`, with the price, location, description and AI rating as in a real notification. aimm prints `✓` or `✗` with the error for each channel. It exits with 1 if any channel failed. The test is a real message (metered channels such as UnitySVC SMS may cost a little), but nothing is recorded in the cache. In Docker, run it in the container (`docker exec aimm aimm admin --test-notification`), or use **Send test** in the Settings of the web UI. After you set up a notification with `aimm configure`, the assistant offers the same test.

#### Common settings

| Option                  | Requirement | DataType        | Description                                                                                                                      |
| ----------------------- | ----------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `max_retries`           | Optional    | Integer         | Number of attempts to retry a notification. Defaults to `5`.                                                                     |
| `retry_delay`           | Optional    | Integer         | Time in seconds to wait between retry attempts. Defaults to `60`.                                                                |
| `with_description`      | Optional    | Boolean/Integer | Whether or not include description of listings. If a number is given, the description will be truncated to the specified length. |
| `rate_limit_enabled`    | Optional    | Boolean         | Enable rate limiting for this notification method. Defaults to `false` (except Telegram which defaults to `true`).              |
| `instance_rate_limit`   | Optional    | Integer         | Minimum seconds between messages for this specific configuration instance. Defaults to `1`.                                      |
| `global_rate_limit`     | Optional    | Integer         | Maximum messages per second across all notification instances (sliding window). Defaults to `10` (`30` for Telegram).            |

Note that

1. These settings apply to the email or notification section that sets them. Set in a `user` section, they apply to the user's sections that do not set them.
2. Support for `with_description` vary across notification methods due to their own limitations and strength. For example, email notification will always include description.
3. Rate limiting prevents API violations by controlling message frequency. When enabled, the system waits for the longer of `instance_rate_limit` or `global_rate_limit` before sending each message. Telegram automatically enables rate limiting with optimized defaults for individual (1.1s) and group chats (3.0s).

### Email

| Service | With UnitySVC | UnitySVC with your own keys (BYOK) | Without UnitySVC |
| --- | --- | --- | --- |
| **Email** with listing photos and the daily digest | `[email.unitysvc]` with `smtp-to-mailbox`: free, to the address of your UnitySVC account | `[email.unitysvc]` with `smtp-relay`: free; UnitySVC's SMTP Relay forwards it to your own SMTP server (Gmail, your mail provider, ...), whose address and login you save in UnitySVC, and on to the addresses you choose | `[email.gmail]` with a Gmail app password, or any other SMTP server |

An `[email.NAME]` section sends aimm's full email, to the `email` of each user who receives it. It accepts the following options:

| Option          | Requirement | DataType    | Description                                             |
| --------------- | ----------- | ----------- | ------------------------------------------------------- |
| `smtp_username` | Optional    | String      | SMTP username; required for `[email.unitysvc]`, where it names the UnitySVC service that delivers the email. |
| `smtp_password` | Required    | String      | A password or passcode for the SMTP server (preset for `[email.unitysvc]` and `[email.gmail]`). |
| `smtp_server`   | Optional    | String      | SMTP server, usually guessed from sender email address. |
| `smtp_port`     | Optional    | Integer     | SMTP port, default to `587`                             |
| `smtp_from`     | Optional    | String      | Sender address, if it must differ from the login.       |
| `digest_at`     | Optional    | String      | Local time of a daily digest; see [Daily digest](#daily-digest). |

Two section names start from a preset, so that only what differs needs to be set: `[email.unitysvc]` and `[email.gmail]`. Any other name is a plain SMTP section.

#### With UnitySVC

**`[email.unitysvc]`** sends through [UnitySVC](https://unitysvc.com/)'s SMTP gateway, a convenient alternative to a Gmail app password. The preset has `smtp_server = "smtp.svcpass.com"`, `smtp_port = 587` and `smtp_password = "${UNITYSVC_API_KEY}"`, the same key as `[ai.unitysvc]`. Set `smtp_username` to the UnitySVC service that delivers the email:

- **`smtp-to-mailbox`** (free) delivers it to the address registered and verified on your UnitySVC account (usually your own email), so `email` is not needed on the user.

  ```toml
  [email.unitysvc]
  smtp_username = 'smtp-to-mailbox'
  ```

- **`notify`** delivers it to your UnitySVC inbox and the notification destination saved in UnitySVC, as `[notification.unitysvc]` does. For the email to reach you, that destination must include `smtp-to-mailbox`.
- **`b/<broadcast name>`** sends each email to every target of a UnitySVC broadcast (up to 10), for example `smtp-to-mailbox` plus one or more SMTP Relay servers.
- Any other service on the SMTP gateway (the SMTP username shown on its catalog page), or `a/<alias>` for one of your aliases. For a service that delivers to the `To` address, set `email` on the user.

#### UnitySVC with your own SMTP account (BYOK)

UnitySVC's [SMTP Relay](https://unitysvc.com/market) forwards the email to your own SMTP server: Gmail, your domain's mail service (such as Zoho or Outlook), or a mail provider such as SendGrid or Amazon SES. It sends the email to the `email` of each user who receives the section, as your own server would, and your server's login stays in UnitySVC instead of aimm's configuration.

1. Save your server's details as secrets in your UnitySVC account: `SMTP_RELAY_HOST` (e.g. `smtp.gmail.com`), `SMTP_RELAY_USERNAME` (usually your address) and `SMTP_RELAY_PASSWORD` (an app password or API key), and if they differ from 587 and STARTTLS, `SMTP_RELAY_PORT` and `SMTP_RELAY_TLS`.
2. Set `smtp_username = 'smtp-relay'`, the relay's free channel:

```toml
[email.unitysvc]
smtp_username = 'smtp-relay'

[user.me]
email = 'me@example.com'
```

To relay through more than one server, enroll the SMTP Relay once per server (its `plus` channel, $1 per 1,000 emails). Then either:

- **Send to all of them from one section:** create a UnitySVC broadcast (a name and up to 10 targets, such as these enrollments, `smtp-relay` or `smtp-to-mailbox`) and set `smtp_username = 'b/<broadcast name>'`. The SMTP gateway sends each email to every target.
- **Use one section per server:** set each enrollment's code as `smtp_username` in its own `[email.*]` section (with `smtp_server = "smtp.svcpass.com"` and `smtp_password = "${UNITYSVC_API_KEY}"`, as the preset has).

#### Without UnitySVC

- **`[email.gmail]`** sends through Gmail. The preset has `smtp_server = "smtp.gmail.com"`, `smtp_port = 587` and `smtp_password = "${GMAIL_SMTP_PASSWORD}"`: set `smtp_username` to your Gmail address and `GMAIL_SMTP_PASSWORD` to a Gmail app password.

  ```toml
  [email.gmail]
  smtp_username = 'me@gmail.com'

  [user.me]
  email = 'me@gmail.com'
  ```

- **Any other name** is a plain SMTP section: set `smtp_server`, `smtp_username` and `smtp_password` from your email provider. aimm uses the user's `email` if `smtp_username` is not set, and guesses `smtp_server` from the sender's address.

  ```toml
  [email.outlook]
  smtp_server = 'smtp.office365.com'
  smtp_username = 'me@outlook.com'
  smtp_password = '${OUTLOOK_PASSWORD}'
  ```

See [Setting up email notifications](https://ai-marketplace-monitor.readthedocs.io/en/latest/configuration-guide.html#setting-up-email-notifications) for more on each option.

### Phone and chat notifications

| Service | With UnitySVC | UnitySVC with your own keys (BYOK) | Without UnitySVC |
| --- | --- | --- | --- |
| **Phone and chat alerts** | `[notification.unitysvc]`: free, but only to your inbox on the UnitySVC website, which is of little use on its own | the same section, forwarded to your own Discord, Slack, Telegram, Pushover, SMS or other account (100+ services), its token saved in UnitySVC | `[notification.telegram]`, Pushbullet, Pushover or ntfy, with their tokens in your configuration |

A `[notification.NAME]` section is one phone or chat channel. It sends a short text message for each batch of new listings, without photos.

#### With UnitySVC

| Option              | Requirement | DataType | Description                                                                          |
| ------------------- | ----------- | -------- | ------------------------------------------------------------------------------------ |
| `unitysvc_api_key`  | Required    | String   | UnitySVC API key (`svcpass_...`), e.g. `"${UNITYSVC_API_KEY}"`.                       |
| `unitysvc_service`  | Optional    | String   | Service path, default `notify`. Use e.g. `labs/msg-to-discord` for a specific service. |
| `message_format`    | Optional    | String   | `plain_text` (default), `markdown`, or `html`.                                       |

```toml
[notification.unitysvc]
unitysvc_api_key = '${UNITYSVC_API_KEY}'
```

- Use the same `UNITYSVC_API_KEY` as `[ai.unitysvc]` and `[email.unitysvc]`.
- The default `notify` service (free) shows messages in your UnitySVC inbox and forwards them to the notification destination saved in your UnitySVC preferences, so you can change where notifications go without touching aimm's configuration. It delivers plain text only, so `markdown` and `html` take effect only with a specific service.
- UnitySVC's notification catalog covers more than 100 channels: chat apps (Slack, Discord, Microsoft Teams, Telegram, WhatsApp, Matrix, ...), phone push (Pushover, ntfy, Pushbullet, Bark, ...), SMS (Twilio, Vonage, Plivo, ...), email (SendGrid, Mailgun, Amazon SES, SMTP, ...), and incident tools (PagerDuty, Opsgenie, ...).
- To reach several destinations at once, for example email plus SMS plus a chat app, create a UnitySVC broadcast (up to 10 targets) and use it as your notification destination, or set `unitysvc_service = "b/<broadcast name>"`.

#### UnitySVC with your own accounts (BYOK)

Without a destination of your own, `notify` only puts the messages in your inbox on the UnitySVC website, so this is the setup to use. Keep `[notification.unitysvc]` as it is, and choose your own account as the notification destination in UnitySVC: for example your Discord, Slack, Telegram or Pushover, with its token saved as a secret in your UnitySVC account. aimm's configuration still holds only `UNITYSVC_API_KEY`. To send to one of these services directly instead of through `notify`, set `unitysvc_service` to the path or enrollment that UnitySVC shows for it.

#### Without UnitySVC

Each of these channels needs its own account, and its token goes in the section (preferably as an environment variable reference); where the user receives it goes on the user.

##### Telegram notification

| Option             | Requirement | DataType | Description                                    |
| ------------------ | ----------- | -------- | ---------------------------------------------- |
| `telegram_token`   | Required    | String   | Bot token obtained from @BotFather.           |
| `telegram_chat_id` | Required    | String   | Chat ID for receiving notifications.           |

Note that

1. **Automatic Rate Limiting**: Telegram notifications automatically enable rate limiting (`rate_limit_enabled = true`) with intelligent defaults based on chat type.
2. **Smart Chat Detection**: The system automatically detects individual chats (positive chat IDs) vs group chats (negative chat IDs) and applies appropriate rate limits.
3. **Optimized Limits**: Individual chats use 1.1 seconds between messages, group chats use 3.0 seconds, with a global limit of 30 seconds across all Telegram instances.
4. **HTTP 429 Handling**: Built-in retry logic with exponential backoff for Telegram API rate limit responses.
5. **Message Splitting**: Long messages are automatically split while preserving MarkdownV2 formatting.

##### Pushbullet notification

| Option                    | Requirement | DataType | Description                   |
| ------------------------- | ----------- | -------- | ----------------------------- |
| `pushbullet_token`        | Optional    | String   | Token for user.               |
| `pushbullet_proxy_type`   | Optional    | String   | HTTP proxy type, e.g. `https` |
| `pushbullet_proxy_server` | Optional    | String   | HTTP proxy server URL         |

Please refer to [PushBullet documentation](https://github.com/richard-better/pushbullet.py/blob/master/readme-old.md) for details on the use of a proxy server for pushbullet.

##### Pushover notification

| Option               | Requirement | DataType | Description         |
| -------------------- | ----------- | -------- | ------------------- |
| `pushover_user_key`  | Optional    | String   | Pushover user key.  |
| `pushover_api_token` | Optional    | String   | Pushover API Token. |

##### Ntfy notification

| Option           | Requirement | DataType | Description                                       |
| ---------------- | ----------- | -------- | ------------------------------------------------- |
| `ntfy_server`    | Optional    | String   | ntfy server, default to `https://ntfy.sh`         |
| `ntfy_topic`     | Optional    | String   | A unique topic to receive your notification.      |
| `message_format` | Optional    | String   | Format notification as `plain_text` or `markdown` |

- According to [ntfy documentation](https://docs.ntfy.sh/publish/#markdown-formatting), markdown format is supported only by web app. Therefore, `message_format` is by default set to `plain_text`.

### Items to search

One or more `item.item_name` where `item_name` is the name of the item.

| Option             | Requirement | DataType    | Description                                                                                                                                                                                    |
| ------------------ | ----------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `search_phrases`   | Required    | String/List | One or more strings for searching the item.                                                                                                                                                    |
| `description`      | Optional    | String      | A longer description of the item that better describes your requirements (e.g., manufacture, condition, location, seller reputation, shipping options). Only used if AI assistance is enabled. |
| `keywords`         | Optional    | String/List | Excludes listings whose titles and description do not contain any of the keywords.                                                                                                             |
| `title_keywords`   | Optional    | String/List | Like `keywords`, but matched against the title only, so listings are skipped before aimm opens them. Faster, but misses listings with short titles.                                              |
| `antikeywords`     | Optional    | String/List | Excludes listings whose titles or descriptions contain any of the specified keywords.                                                                                                          |
| `marketplace`      | Optional    | String/List | The marketplace sections the item is searched in: a name or a list of names. Without it, the item is searched in every marketplace section, including ones added later. An item searched in several sections uses their locations and cannot set its own. |
| **Common options** |             |             | Options listed below. These options, if specified in the item section, will override options in the marketplace section.                                                                       |

Marketplaces may return listings that are completely unrelated to search search_phrases, but can also
return related items under different names. To select the right items, you can

1. Use `keywords` to keep only items with certain words in the title. For example, you can set `keywords = ['gopro', 'go pro']` when you search for `search_phrases = 'gopro'`.
2. Use `antikeywords` to narrow down the search. For example, setting `antikeywords=['HERO 4']` will exclude items with `HERO 4` or `hero 4`in the title or description.
3. The `keywords` and `antikeywords` options allows the specification of multiple keywords with a `OR` relationship, but it also allows complex `AND`, `OR` and `NOT` logics. See [Advanced Keyword-based filters](../README.md#advanced-keyword-based-filters) for details.
4. It is usually more effective to write a longer `description` and let the AI know what exactly you want. This will make sure that you will not get a drone when you are looking for a `DJI` camera. It is still a good idea to pre-filter listings using non-AI criteria to reduce the cost of AI services.

### Common item and marketplace options

The following options that can specified for both `marketplace` sections and `item` sections. Values in the `item` section will override value in corresponding marketplace if specified in both places.

| `Parameter`           | Required/Optional | Datatype            | Description                                                                                                                                                 |
| --------------------- | ----------------- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `availability`        | Optional          | String/List         | Shows output with `in` (in stock), `out` (out of stock), or `all` (both).                                                                                   |
| `condition`           | Optional          | String/List         | One or more of `new`, `used_like_new`, `used_good`, and `used_fair`.                                                                                        |
| `date_listed`         | Optional          | String/Integer/List | One of `all`, `last 24 hours`, `last 7 days`, `last 30 days`, or `0`, `1`, `7`, and `30`.                                                                   |
| `delivery_method`     | Optional          | String/List         | One of `all`, `local_pick_up`, and `shipping`.                                                                                                              |
| `exclude_sellers`     | Optional          | String/List         | Exclude certain sellers by their names (not username).                                                                                                      |
| `max_price`           | Optional          | Integer/String      | Maximum price, can be followed by a currency name.                                                                                                          |
| `max_search_interval` | Optional          | String              | Maximum interval in seconds between searches. A random time is chosen between `search_interval` and `max_search_interval`, which defaults to 150% of `search_interval`. Set it equal to `search_interval` for a fixed interval. |
| `min_price`           | Optional          | Integer/String      | Minimum price, can be followed by a currency name.                                                                                                          |
| `category`            | Optional          | String              | Category of search.                                                                                                                                         |
| `notify`              | Optional          | String/List         | Users who should be notified.                                                                                                                               |
| `ai`                  | Optional          | String/List         | AI services to use, default to all specified services. `ai=[]` will disable ai.                                                                             |
| `city_name`           | Optional          | String/List         | Corresponding name of `search_city`.                                                                                                                        |
| `radius`              | Optional          | Integer/List        | Radius of search in the unit Facebook shows (miles in the US, km elsewhere), rounded to the nearest choice Facebook offers (1, 2, 5, 10, 20, 40, 60, 80, 100, 250 or 500). A list sets one radius per `search_city`. See [Search radius](https://ai-marketplace-monitor.readthedocs.io/en/latest/configuration-guide.html#search-radius).                                                                                    |
| `currency`            | Optional          | Integer/List        | Currency used for the search city, can be a list if multiple `search_city` are specified.                                                                   |
| `prompt`              | Optional          | String              | Prompt to AI service that will replace the default prompt                                                                                                   |
| `extra_prompt`        | Optional          | String              | Additional prompt that will be inserted between regular and rating prompt                                                                                   |
| `ranking_prompt`      | Optional          | String              | Ranking prompt that instruct how AI rates the listings                                                                                                      |
| `rating`              | Optional          | Integer/List        | Notify users with listings with rating at or higher than specified rating. Default to 4.                                                                    |
| `search_city`         | Required          | String/Table/List   | One or more places to search around, in the marketplace's own format (for Facebook, the location code from the URL of your search query). A place can also be a table of values by marketplace type, `{ facebook = "houston", offerup = "77096" }`: each marketplace takes its own, so one item can search the same place in sections of different types. Required for marketplace or item if `search_region` is unspecified. |
| `search_interval`     | Optional          | String              | Minimal interval between searches, should be specified in formats such as `1d`, `5h`, or `1h 30m`. With `search_interval = X`, the actual interval is random between X and 1.5X unless `max_search_interval` is also set. Defaults to `30m`. |
| `search_region`       | Optional          | String/List         | Search over multiple locations to cover an entire region. `regions` should be one or more pre-defined regions or regions defined in the configuration file. Regions are for Facebook marketplaces. |
| `seller_locations`    | Optional          | String/List         | Only allow searched items from these locations.                                                                                                             |
| `seller_min_rating`   | Optional          | Number              | Exclude sellers rated below this (0 to 5) by at least 3 buyers. Sellers without ratings are kept and judged by the AI. See [Seller information](https://ai-marketplace-monitor.readthedocs.io/en/latest/configuration-guide.html#seller-information). |
| `sort_by`             | Optional          | String              | Order of search results. One of `suggested`, `new`, `price_ascend`, `price_descend`, and `distance_ascend`.                                                 |
| `start_at`            | Optional          | String/List         | Time to start the search. Overrides `search_interval`.                                                                                                      |

Note that

1. `search_city` can be found from the URL that facebook uses to search your region. For example, if the URL for your facebook search is `https://www.facebook.com/marketplace/sanfrancisco/search?query=go%20pro%2011%20deal%20site`, the `search_city` is `sanfrancisco`. This name is not necessarily the name of your city, especially for non-US cities (smaller places have numeric codes), and you can search multiple cities or an entire region. The **Assistant** in the web UI (or `aimm configure`) finds the code for you: tell it a city or ZIP code, and it looks the place up in Facebook Marketplace's location search. See [Searching multiple cities and regions](../README.md#searching-multiple-cities-and-regions) for details.
2. If `notify` is not specified for both `item` and `marketplace`, all listed users will be notified.
3. `prompt`, `extra_prompt`, `rating_prompt`, and `rating` are used to adjust how to interact with an AI service. See [Adjust prompt and notification level](../README.md#adjust-prompt-and-notification-level) for details.
4. `start_at` supports one or more of the following values: <br> - `HH:MM:SS` or `HH:MM` for every day at `HH:MM:SS` or `HH:MM:00` <br> - `*:MM:SS` or `*:MM` for every hour at `MM:SS` or `MM:00` <br> - `*:*:SS` for every minute at `SS`.
5. A list of two values can be specified for options `rating`, `availability`, `delivery_method`, and `date_listed`. See [First and subsequent searches](../README.md#first-and-subsequent-searches) for details.
6. `min_price` and `max_price` can be specified as a number (e.g. `min_price=100`) or a number followed by a currency name (e.g. `min_price='100 USD'`). If different currencies are specified for both `min_price/max_price` and `search_city` (or `region`), the `min_price` and `max_price` will be adjusted to use currency for the `search_city`. See [Searching across regions with different currencies](../README.md#searching-across-regions-with-different-currencies) for details.
7. `category` can be `vehicles`, `propertyrentals`, `apparel`, `electronics`, `entertainment`, `family`, `freestuff`, `free`, `garden`, `hobbies`, `homegoods`, `homeimprovement`, `homesales`, `musicalinstruments`, `officesupplies`, `petsupplies`, `sportinggoods`, `tickets`, `toys`, and `videogames`. If `catgory=freestuff` or `catgory=free` is set, `min_price` and `max_price` is ignored.
8. `sort_by` controls the order of the search results. `suggested` (the default) uses Facebook's own ranking, `new` lists the newest items first (useful for catching newly listed items), `price_ascend` and `price_descend` sort by price, and `distance_ascend` sorts by distance from the search city.

### Regions

One or more sections of `[region.region_name]`, which defines regions to search. Multiple searches will be performed for multiple cities to cover entire regions.

| Parameter     | Required/Optional | Data Type    | Description                                                                 |
| ------------- | ----------------- | ------------ | --------------------------------------------------------------------------- |
| `search_city` | Required          | String/Table/List | One or more cities: Facebook's location codes, or tables of values by marketplace type (`{ facebook = "houston", offerup = "77002" }`); a section using the region takes the values of its type. |
| `full_name`   | Optional          | String       | A display name for the region.                                              |
| `radius`      | Optional          | Integer/List | Radius in the unit Facebook shows; `500`, the largest choice, for large regions. |
| `currency`    | Optional          | Integer/List | Currency used for the region.                                               |
| `city_name`   | Optional          | String/List  | Corresponding names for `search_city`.                                      |

Note that

1. `radius` is in the unit Facebook shows (miles in the US, km elsewhere), and `500` is the largest radius Facebook offers. You can specify different `radius` for different `search_city`.
2. Options `full_name` and `city_name` are for documentation and logging purposes only.
3. With tables, a region can serve marketplaces of different types; every city needs a value for each type of section that uses the region. `city_name` defaults to each city's first value.

### Translators

A translator contains a list of word mappings that translate English words to corresponding words in another language. They are used by _AI Marketplace Monitor_ to extract information from webpages in non-English languages.

This section currently accept the following values for Facebook Marketplace.

| Parameter                         | Required/Optional | Data Type | Description                                                |
| --------------------------------- | ----------------- | --------- | ---------------------------------------------------------- |
| `locale`                          | Required          | String    | locale of the translation                                  |
| `enabled`                         | Optional          | Boolean   | Set to `false` to ignore this translation.                 |
| `Collection of Marketplace items` | Optional          | String    | The "arial-label" for search results.                      |
| `Condition`                       | Optional          | String    | Subtitle "condition" of an listing item.                   |
| `Description`                     | Optional          | String    | Title "description" for a rental item.                     |
| `Details`                         | Optional          | String    | Subtitle "Details" of an listing item.                     |
| `Location is approximate`         | Optional          | String    | The word below listing location.                           |
| `About this vehicle`              | Optional          | String    | The "About this vehicle" section of an automobile listing. |
| `Seller's description`            | Optional          | String    | The "Seller's description" of an automobile listing.       |
| `Joined Facebook in`              | Optional          | String    | Before the year a seller joined Facebook.                  |
| `Location:`                       | Optional          | String    | The start of the label of Marketplace's location button.   |
| `Change location`                 | Optional          | String    | The title of the location dialog.                          |
| `Radius`                          | Optional          | String    | The radius field of the location dialog.                   |
| `Apply`                           | Optional          | String    | Its Apply button.                                          |
| `Highly rated`                    | Optional          | String    | The badge of highly rated sellers.                         |
| `out of 5`                        | Optional          | String    | In the label of a seller's star rating, "4.6 out of 5".    |
| `active listing`                  | Optional          | String    | After the number of a seller's listings.                   |
| `Inventory availability status`   | Optional          | String    | The listing filter on a seller's profile.                  |
| `Sold & out of stock`             | Optional          | String    | Its choice of sold listings.                               |
| `Based on`                        | Optional          | String    | Before a seller's number of ratings.                       |
| `ratings`                         | Optional          | String    | After it.                                                  |
| `strengths`                       | Optional          | String    | The heading of what buyers appreciate.                     |
| `Seller reviews`                  | Optional          | String    | The heading of a seller's reviews.                         |
| `Like`                            | Optional          | String    | The button after each review.                              |

Note that not all words needs to be translated (the English version will be used if unspecified), and _AI Marketplace Monitor_ may be able to extract information using language-independent methods.

Please see [Support for non-English languages](../README.md#support-for-non-english-languages)

### Monitor Configuration

The optional `monitor` section allows you to define system configurations for the _AI Marketplace Monitor_. It supports options for sending your queries through one or more proxy servers, which can hide your IP address and reduce the chances of your IP being blocked, and for how long aimm keeps its history of evaluated listings.

| Option           | Requirement | DataType    | Description                              |
| ---------------- | ----------- | ----------- | ---------------------------------------- |
| `proxy_server`   | Optional    | String/List | URL for one or more proxy servers.       |
| `proxy_bypass`   | Optional    | String      | Comma-separated domains to bypass proxy. |
| `proxy_username` | Optional    | String      | username for the proxy.                  |
| `proxy_password` | Optional    | String      | password for the proxy.                  |
| `check_updates`  | Optional    | Boolean     | Check PyPI for a newer release when aimm starts, at most once a day (default `true`). The web UI's **Check for updates** button works either way. |
| `evaluation_history_days` | Optional | Integer | Days to keep the record of each evaluated listing shown in the web UI's **Listings** view (default `30`). |

- If multiple `proxy_server` URLs are specified as a list, a random one will be chosen each time. However, the proxy will not change while the _AI Marketplace Monitor_ is running.
- aimm records every listing it evaluates: excluded before the AI (by keywords, area or seller), rejected because the AI rating is below the item's `rating`, or notified. A later decision about the same listing and item replaces the earlier one, and records older than `evaluation_history_days` are removed.

### Additional options

All sections, namely `ai`, `marketplace`, `user`, `smtp`, and `region`, accepts an option `enabled`, which, if set to `false` will disable the corresponding AI service,
marketplace, SMTP server, and stop notifying corresponding user. This option works like a `comment` statement that comments out the entire sections, which allowing the
sections to be referred from elsewhere (e.g. `notify` a disable user is allowed but notification will not be sent.)

| Parameter | Required/Optional | Data Type | Description                                            |
| --------- | ----------------- | --------- | ------------------------------------------------------ |
| `enabled` | Optional          | Boolean   | Disable corresponding configuration if set to `false`. |
| `request` | Optional          | String    | Your own description of what you want from this section. Not used when searching; reserved for AI-assisted configuration. Accepted by all sections. |
