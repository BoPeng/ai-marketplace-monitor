## Configuration Guide

### Table of content:

- [Table of content:](#table-of-content)
- [AI Services](#ai-services)
- [Marketplaces](#marketplaces)
- [Users](#users)
- [Notification](#notification)
- [Items to search](#items-to-search)
- [Options that can be specified for both marketplaces and items](#options-that-can-be-specified-for-both-marketplaces-and-items)
- [Regions](#regions)
- [Additional options](#additional-options)

Here is a complete list of options that are acceptable by the program. [`example_config.toml`](example_config.toml) provides
an example with many of the options.

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

| Option            | Requirement | DataType | Description                                                                                       |
| ----------------- | ----------- | -------- | ------------------------------------------------------------------------------------------------- |
| `market_type`     | Optional    | String   | The supported marketplace. Currently, only `facebook` is supported.                               |
| `username`        | Optional    | String   | Username can be entered manually or kept in the config file.                                      |
| `password`        | Optional    | String   | Password can be entered manually or kept in the config file.                                      |
| `login_wait_time` | Optional    | Integer  | Time (in seconds) to wait before searching to allow enough time to enter CAPTCHA. Defaults to 60. |

| **Common options** | | | Options listed in the [Common options](#common-options) section below that provide default values for all items. |

Multiple marketplaces with different `name`s can be specified for different `item`s (see [Multiple marketplaces](../README.md#multiple-marketplaces)). However, because the default `marketplace` for all items are `facebook`, it is easiest to define a default marketplace called `marketplace.facebook`.

### Users

One or more `user.username` sections are allowed. The `username` need to match what are listed by option `notify` of marketplace or items. Currently emails and [PushBullet](https://www.pushbullet.com/) are supported methods of notification.

| Option             | Requirement | DataType    | Description                                                                               |
| ------------------ | ----------- | ----------- | ----------------------------------------------------------------------------------------- |
| `pushbullet_token` | Optional    | String      | Token for user                                                                            |
| `email`            | Optional    | String/List | One or more email addresses for email notificaitons                                       |
| `remind`           | Optional    | String      | Notify users again after a set time (e.g., 3 days) if a listing remains active.           |
| `smtp`             | optional    | String      | name of `SMTP` server to a separate SMTP section if there are more than one such sections |

Option `remind` defines if a user want to receive repeated notification. By default users will be notified only once.

### Notification

If an `email` is specified, we need to know how to connect to an SMTP server to send the email. An smtp section should be named like `smtp.gmail` and can have the following keys

| Option          | Requirement | DataType | Description                                             |
| --------------- | ----------- | -------- | ------------------------------------------------------- |
| `smtp_username` | Optional    | String   | SMTP username.                                          |
| `smtp_password` | Required    | String   | A password or passcode for the SMTP server.             |
| `smtp_server`   | Optional    | String   | SMTP server, usually guessed from sender email address. |
| `smtp_port`     | Optional    | Integer  | SMTP port, default to `587`                             |

Note that

1. You can add values of an `smtp` section directly into a `user` section, or keep them an separate section to be shared by multiple users.
2. We provide default `smtp_server` and `smtp_port` values for popular SMTP service providers.
3. `smtp_username` is assumed to be the first `email`.

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

### Options that can be specified for both marketplaces and items

The following options that can specified for both `marketplace` sections and `item` sections. Values in the `item` section will override value in corresponding marketplace if specified in both places.

| `Parameter`           | Required/Optional | Datatype            | Description                                                                                                                                                    |
| --------------------- | ----------------- | ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `availability`        | Optional          | String/List         | Shows output with `in` (in stock), `out` (out of stock), or `all` (both).                                                                                      |
| `condition`           | Optional          | String/List         | One or more of `new`, `used_like_new`, `used_good`, and `used_fair`.                                                                                           |
| `date_listed`         | Optional          | String/Integer/List | One of `all`, `last 24 hours`, `last 7 days`, `last 30 days`, or `0`, `1`, `7`, and `30`.                                                                      |
| `delivery_method`     | Optional          | String/List         | One of `all`, `local_pick_up`, and `shipping`.                                                                                                                 |
| `exclude_sellers`     | Optional          | String/List         | Exclude certain sellers by their names (not username).                                                                                                         |
| `max_price`           | Optional          | Integer             | Maximum price.                                                                                                                                                 |
| `max_search_interval` | Optional          | String              | Maximum interval in seconds between searches. If specified, a random time will be chosen between `search_interval` and `max_search_interval`.                  |
| `min_price`           | Optional          | Integer             | Minimum price.                                                                                                                                                 |
| `notify`              | Optional          | String/List         | Users who should be notified.                                                                                                                                  |
| `ai`                  | Optional          | String/List         | AI services to use, default to all specified services. `ai=[]` will disable ai.                                                                                |
| `radius`              | Optional          | Integer/List        | Radius of search, can be a list if multiple `search_city` are specified.                                                                                       |
| `rating`              | Optional          | Integer/List        | Notify users with listings with rating at or higher than specified rating. See [Adjust notification level](../README.md#adjust-notification-level) for details |
| `search_city`         | Required          | String/List         | One or more search cities, obtained from the URL of your search query. Required for marketplace or item if `search_region` is unspecified.                     |
| `search_interval`     | Optional          | String              | Minimal interval between searches, should be specified in formats such as `1d`, `5h`, or `1h 30m`.                                                             |
| `search_region`       | Optional          | String/List         | Search over multiple locations to cover an entire region. `regions` should be one or more pre-defined regions or regions defined in the configuration file.    |
| `seller_locations`    | Optional          | String/List         | Only allow searched items from these locations.                                                                                                                |
| `start_at`            | Optional          | String/List         | Time to start the search. Overrides `search_interval`.                                                                                                         |

Note that

1. If `notify` is not specified for both `item` and `marketplace`, all listed users will be notified.
2. `start_at` supports one or more of the following values: <br> - `HH:MM:SS` or `HH:MM` for every day at `HH:MM:SS` or `HH:MM:00` <br> - `*:MM:SS` or `*:MM` for every hour at `MM:SS` or `MM:00` <br> - `*:*:SS` for every minute at `SS`.
3. A list of two values can be specified for options `rating`, `availability`, `delivery_method`, and `date_listed`. See [First and subsequent searches](../README.md#first-and-subsequent-searches) for details.

### Regions

One or more sections of `[region.region_name]`, which defines regions to search. Multiple searches will be performed for multiple cities to cover entire regions.

| Parameter     | Required/Optional | Data Type    | Description                                                                 |
| ------------- | ----------------- | ------------ | --------------------------------------------------------------------------- |
| `search_city` | Required          | String/List  | One or more cities with names used by Facebook.                             |
| `full_name`   | Optional          | String       | A display name for the region.                                              |
| `radius`      | Optional          | Integer/List | Recommended `805` for regions using miles, and `500` for regions using kms. |
| `city_name`   | Optional          | String/List  | Corresponding city names for bookkeeping purposes only.                     |

Note that

1. `radius` has a default value of `500` (miles). You can specify different `radius` for different `search_city`.
2. Options `full_name` and `city_name` are for documentation purposes only.

### Additional options

All sections, namely `ai`, `marketplace`, `user`, `smtp`, and `region`, accepts an option `enabled`, which, if set to `false` will disable the corresponding AI service,
marketplace, SMTP server, and stop notifying corresponding user. This option works like a `comment` statement that comments out the entire sections, which allowing the
sections to be referred from elsewhere (e.g. `notify` a disable user is allowed but notification will not be sent.)

| Parameter | Required/Optional | Data Type | Description                                            |
| --------- | ----------------- | --------- | ------------------------------------------------------ |
| `enabled` | Optional          | Boolean   | Disable corresponding configuration if set to `false`. |
