# Configuration Guide

**Table of content:**

- [AI Services](#ai-services)
- [Marketplaces](#marketplaces)
- [Users](#users)
- [Notification](#notification)
- [Items to search](#items-to-search)
- [Common item and marketplace options](#common-item-and-marketplace-options)
- [Regions](#regions)
- [Additional options](#additional-options)

The AI Marketplace Monitor uses [TOML](https://toml.io/en/) configuration files to control its behavior. The system will always check for a configuration file at `~/.ai-marketplace-monitor/config.toml`. You can specify additional configuration files using the `--config` option.

To avoid including sensitive information directly in the configuration file, all options that accept a string or a list of string can be specified using the `${ENV_VAR}` format. For example

```toml
[marketplace.facebook]
password = '${FACEBOOK_PASSWORD}'

[user.me]
email = ['${EMAIL_1}', '${EMAIL_2}']
pushbullet_token = '${PUSBULLET_TOKEN}'
```

_AI Marketplace Monitor_ will retrieve the value from the corresponding environment variable and raise an error if the environment variable does not exist.

Here is a complete list of options that are acceptable by the program. [`example_config.toml`](example_config.toml) provides an example with many of the options.

### Monitor Configuration

The optional `monitor` section allows you to define system configurations for the _AI Marketplace Monitor_. It supports options for sending your queries through one or more proxy servers, which can hide your IP address and reduce the chances of your IP being blocked.

| Option           | Requirement | DataType    | Description                              |
| ---------------- | ----------- | ----------- | ---------------------------------------- |
| `proxy_server`   | Optional    | String/List | URL for one or more proxy servers.       |
| `proxy_bypass`   | Optional    | String      | Comma-separated domains to bypass proxy. |
| `proxy_username` | Optional    | String      | username for the proxy.                  |
| `proxy_password` | Optional    | String      | password for the proxy.                  |

- If multiple `proxy_server` URLs are specified as a list, a random one will be chosen each time. However, the proxy will not change while the _AI Marketplace Monitor_ is running.

### AI Services

One of more sections to list the AI agent that can be used to judge if listings match your selection criteria. The options should have header such as `[ai.openai]` or `[ai.deepseek]`, and have the following keys:

| Option        | Requirement | DataType | Description                                                |
| ------------- | ----------- | -------- | ---------------------------------------------------------- |
| `provider`    | Optional    | String   | Name of the AI service provider.                           |
| `api-key`     | Optional    | String   | A program token to access the RESTful API.                 |
| `base_url`    | Optional    | String   | URL for the RESTful API                                    |
| `model`       | Optional    | String   | Language model to be used.                                 |
| `max_retries` | Optional    | Integer  | Max retry attempts if connection fails. Default to 10.     |
| `timeout`     | Optional    | Integer  | Timeout (in seconds) waiting for response from AI service. |

Note that:

1. `provider` can be [OpenAI](https://openai.com/),
   [DeepSeek](https://www.deepseek.com/), or [Ollama](https://ollama.com/). The name of the ai service will be used if this option is not specified so `OpenAI` will be used for section `ai.openai`.
2. [OpenAI](https://openai.com/) and [DeepSeek](https://www.deepseek.com/) models sets default `base_url` and `model` for these providers.
3. Ollama models require `base_url`. A default model is set to `deepseek-r1:14b`, which seems to be good enough for this application. You can of course try [other models](https://ollama.com/library) by setting the `model` option.
4. Although only three providers are supported, you can use any other service provider with `OpenAI`-compatible API using customized `base_url`, `model`, and `api-key`.
5. You can use option `ai` to list the AI services for particular marketplaces or items.

A typical section for OpenAI looks like

```toml
[ai.openai]
api_key = 'sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
```

### Marketplaces

One or more sections `marketplace.name` show the options for interacting with various marketplaces.

| Option             | Requirement | DataType | Description                                                                                                      |
| ------------------ | ----------- | -------- | ---------------------------------------------------------------------------------------------------------------- |
| `market_type`      | Optional    | String   | The supported marketplace. Currently, only `facebook` is supported.                                              |
| `username`         | Optional    | String   | Username can be entered manually or kept in the config file.                                                     |
| `password`         | Optional    | String   | Password can be entered manually or kept in the config file.                                                     |
| `login_wait_time`  | Optional    | Integer  | Time (in seconds) to wait before searching to allow enough time to enter CAPTCHA. Defaults to 60.                |
| `language`         | Optional    | String   | Language for webpages                                                                                            |
| **Common options** |             |          | Options listed in the [Common options](#common-options) section below that provide default values for all items. |

1. Multiple marketplaces with different `name`s can be specified for different `item`s (see [Multiple marketplaces](../README.md#multiple-marketplaces)). However, because the default `marketplace` for all items are `facebook`, it is easiest to define a default marketplace called `marketplace.facebook`.
2. If `language="LAN"` is specified, it must correspond to a `translation.LAN` section, defined by yourself or in the system configuration file. Please see [Support for non-English languages](../README.md#support-for-non-english-languages)

### Users

One or more `user.username` sections can be defined in the configuration. The `username` one of the usernames listed in the `notify` option of `marketplace` or `item`. Each `user` section accepts the following options

| Option        | Requirement | DataType    | Description                                                                                                                                                  |
| ------------- | ----------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `notify_with` | Optional    | String/List | Specifies one or more notification methods to be used for this user. If left unspecified, all available notification methods will be used.                   |
| `remind`      | Optional    | String      | Enables repeated notifications for the user after a specified duration (e.g., 3 days) if a listing remains active. By default, users are notified only once. |

Note that

1. **Default Notification Behavior**: If the `notify_with` option is not specified, the system will use all available notification methods for the user.
2. **Inline Notification Settings**: Notification settings can be defined directly under the user section. Any settings described in the [Notification](#notification) section can be applied to a user's configuration.
3. **Repeated Notifications**: The `remind` option allows users to receive repeated notifications after a specified time interval. If not set, users will only be notified once about a listing.

### Notification

_AI Marketplace Monitor_ supports various notification methods, allowing you to configure notifications in a flexible way. You can define notification settings directly within the `user` sections or create dedicated `notification.NAME` sections and reference them using the `notify_with` option. This provides flexibility for single-user setups or shared configurations across multiple users.

#### Direct Notification Settings in User Sections

Define notification details directly within the user section. This approach is ideal for single-user configurations.

```toml
[user.me]
pushbullet_token = "xxxxxxxxxxxxxxxx"
email = 'myemail@gmail.com'
smtp_password = 'abcdefghijklmnop'
```

#### Shared Notification Settings in Dedicated Sections

Define notification methods in their own `notification.NAME` sections and reference them using the notify_with option. This approach is better for sharing settings across multiple users.

```toml
[user.me]
email = 'myemail@gmail.com'
notify_with = ['gmail', 'pushbullet']

[user.other]
email = 'other.email@gmail.com'
notify_with = ['gmail']

[notification.gmail]
smtp_password = 'abcdefghijklmnop'

[notification.pushbullet]
pushbullet_token = "xxxxxxxxxxxxxxxx"
```

Note that:

1. Under the hood, _AI Marketplace Monitor_ merges all notification options into the user section. This allows you to share partial settings across users (e.g. `smtp_password`) while customizing specific details (e.g. `email`).
2. If `notify_with` is not specified, the system will automatically include all notification settings for the user, so the `notify_with` option for `user.me` could be ignored.
3. AI Marketplace Monitor does not support multiple notifications of the same type for a single user. For example, the following configuration is not supported:

```toml
[user.me]
notify_with = ['pushbullet1', 'pushbullet2']
```

If you need to send notifications through multiple instances of the same type (e.g., multiple Pushbullet tokens), you must create separate users for each instance. For example:

```toml
[user.me]
notify_with = 'pushbullet1'

[user.other]
notify_with = 'pushbullet2'

[notification.pushbullet1]
pushbullet_token = "xxxxxxxxxxxxxxxx"

[notification.pushbullet2]
pushbullet_token = "yyyyyyyyyyyyyyyy"
```

#### Pushbullet notification

| Option                    | Requirement | DataType | Description                   |
| ------------------------- | ----------- | -------- | ----------------------------- |
| `pushbullet_token`        | Optional    | String   | Token for user.               |
| `pushbullet_proxy_type`   | Optional    | String   | HTTP proxy type, e.g. `https` |
| `pushbullet_proxy_server` | Optional    | String   | HTTP proxy server URL         |

Please refer to [PushBullet documentation](https://github.com/richard-better/pushbullet.py/blob/master/readme-old.md) for details on the use of a proxy server for pushbullet.

#### Pushover notification

| Option               | Requirement | DataType | Description         |
| -------------------- | ----------- | -------- | ------------------- |
| `pushover_user_id`   | Optional    | String   | Pushover user key.  |
| `pushover_api_token` | Optional    | String   | Pushover API Token. |

### Email notification

| Option          | Requirement | DataType    | Description                                             |
| --------------- | ----------- | ----------- | ------------------------------------------------------- |
| `email`         | Optional    | String/List | One or more email addresses for email notifications     |
| `smtp_username` | Optional    | String      | SMTP username.                                          |
| `smtp_password` | Required    | String      | A password or passcode for the SMTP server.             |
| `smtp_server`   | Optional    | String      | SMTP server, usually guessed from sender email address. |
| `smtp_port`     | Optional    | Integer     | SMTP port, default to `587`                             |

Note that

1. We provide default `smtp_server` and `smtp_port` values for popular SMTP service providers.
2. `smtp_username` is assumed to be the first `email`.

See [Setting up email notification](../README.md#setting-up-email-notification) for details on how to set up email notification.

### Items to search

One or more `item.item_name` where `item_name` is the name of the item.

| Option             | Requirement | DataType    | Description                                                                                                                                                                                    |
| ------------------ | ----------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `search_phrases`   | Required    | String/List | One or more strings for searching the item.                                                                                                                                                    |
| `description`      | Optional    | String      | A longer description of the item that better describes your requirements (e.g., manufacture, condition, location, seller reputation, shipping options). Only used if AI assistance is enabled. |
| `keywords`         | Optional    | String/List | Excludes listings whose titles and description do not contain any of the keywords.                                                                                                             |
| `antikeywords`     | Optional    | String/List | Excludes listings whose titles or descriptions contain any of the specified keywords.                                                                                                          |
| `marketplace`      | Optional    | String      | Name of the marketplace, default to `facebook` that points to a `marketplace.facebook` sectiion.                                                                                               |
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
| `max_price`           | Optional          | Integer             | Maximum price.                                                                                                                                              |
| `max_search_interval` | Optional          | String              | Maximum interval in seconds between searches. If specified, a random time will be chosen between `search_interval` and `max_search_interval`.               |
| `min_price`           | Optional          | Integer             | Minimum price.                                                                                                                                              |
| `notify`              | Optional          | String/List         | Users who should be notified.                                                                                                                               |
| `ai`                  | Optional          | String/List         | AI services to use, default to all specified services. `ai=[]` will disable ai.                                                                             |
| `city_name`           | Optional          | String/List         | Corresponding name of `search_city`.                                                                                                                        |
| `radius`              | Optional          | Integer/List        | Radius of search, can be a list if multiple `search_city` are specified.                                                                                    |
| `prompt`              | Optional          | String              | Prompt to AI service that will replace the default prompt                                                                                                   |
| `extra_prompt`        | Optional          | String              | Additional prompt that will be inserted between regular and rating prompt                                                                                   |
| `ranking_prompt`      | Optional          | String              | Ranking prompt that instruct how AI rates the listings                                                                                                      |
| `rating`              | Optional          | Integer/List        | Notify users with listings with rating at or higher than specified rating.                                                                                  |
| `search_city`         | Required          | String/List         | One or more search cities, obtained from the URL of your search query. Required for marketplace or item if `search_region` is unspecified.                  |
| `search_interval`     | Optional          | String              | Minimal interval between searches, should be specified in formats such as `1d`, `5h`, or `1h 30m`.                                                          |
| `search_region`       | Optional          | String/List         | Search over multiple locations to cover an entire region. `regions` should be one or more pre-defined regions or regions defined in the configuration file. |
| `seller_locations`    | Optional          | String/List         | Only allow searched items from these locations.                                                                                                             |
| `start_at`            | Optional          | String/List         | Time to start the search. Overrides `search_interval`.                                                                                                      |

Note that

1. `search_city` can be found from the URL that facebook uses to search your region. For example, if the URL for your facebook search is `https://www.facebook.com/marketplace/sanfrancisco/search?query=go%20pro%2011%20deal%20site`, the `search_city` is `sanfrancisco`. This name is not necessarily the name of your city, especially for non-US cities, and you can search multiple cities or an entire region. See [Searching multiple cities and regions](../README.md#searching-multiple-cities-and-regions) for details.
2. If `notify` is not specified for both `item` and `marketplace`, all listed users will be notified.
3. `prompt`, `extra_prompt`, `rating_prompt`, and `rating` are used to adjust how to interact with an AI service. See [Adjust prompt and notification level](../README.md#adjust-prompt-and-notification-level) for details.
4. `start_at` supports one or more of the following values: <br> - `HH:MM:SS` or `HH:MM` for every day at `HH:MM:SS` or `HH:MM:00` <br> - `*:MM:SS` or `*:MM` for every hour at `MM:SS` or `MM:00` <br> - `*:*:SS` for every minute at `SS`.
5. A list of two values can be specified for options `rating`, `availability`, `delivery_method`, and `date_listed`. See [First and subsequent searches](../README.md#first-and-subsequent-searches) for details.

### Regions

One or more sections of `[region.region_name]`, which defines regions to search. Multiple searches will be performed for multiple cities to cover entire regions.

| Parameter     | Required/Optional | Data Type    | Description                                                                 |
| ------------- | ----------------- | ------------ | --------------------------------------------------------------------------- |
| `search_city` | Required          | String/List  | One or more cities with names used by Facebook.                             |
| `full_name`   | Optional          | String       | A display name for the region.                                              |
| `radius`      | Optional          | Integer/List | Recommended `805` for regions using kms, and `500` for regions using miles. |
| `city_name`   | Optional          | String/List  | Corresponding names for `search_city`.                                      |

Note that

1. `radius` has a default value of `500` (miles). You can specify different `radius` for different `search_city`.
2. Options `full_name` and `city_name` are for documentation and logging purposes only.

### Additional options

All sections, namely `ai`, `marketplace`, `user`, `smtp`, and `region`, accepts an option `enabled`, which, if set to `false` will disable the corresponding AI service,
marketplace, SMTP server, and stop notifying corresponding user. This option works like a `comment` statement that comments out the entire sections, which allowing the
sections to be referred from elsewhere (e.g. `notify` a disable user is allowed but notification will not be sent.)

| Parameter | Required/Optional | Data Type | Description                                            |
| --------- | ----------------- | --------- | ------------------------------------------------------ |
| `enabled` | Optional          | Boolean   | Disable corresponding configuration if set to `false`. |
