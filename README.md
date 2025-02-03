# AI Marketplace Monitor

<div align="center">

[![PyPI - Version](https://img.shields.io/pypi/v/ai-marketplace-monitor.svg)](https://pypi.python.org/pypi/ai-marketplace-monitor)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/ai-marketplace-monitor.svg)](https://pypi.python.org/pypi/ai-marketplace-monitor)
[![Tests](https://github.com/BoPeng/ai-marketplace-monitor/workflows/tests/badge.svg)](https://github.com/BoPeng/ai-marketplace-monitor/actions?workflow=tests)
[![Codecov](https://codecov.io/gh/BoPeng/ai-marketplace-monitor/branch/main/graph/badge.svg)](https://codecov.io/gh/BoPeng/ai-marketplace-monitor)
[![Read the Docs](https://readthedocs.org/projects/ai-marketplace-monitor/badge/)](https://ai-marketplace-monitor.readthedocs.io/)
[![PyPI - License](https://img.shields.io/pypi/l/ai-marketplace-monitor.svg)](https://pypi.python.org/pypi/ai-marketplace-monitor)

[![Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4baaaa.svg)](https://www.contributor-covenant.org/version/2/1/code_of_conduct/)

</div>

## Overview

An AI-based tool for monitoring Facebook Marketplace. With the aids from AI, this tool automates the process of searching for specific products, filtering out irrelevant listings, and notifying you of new matches via PushBullet.

## Table of content:

- [Overview](#overview)
- [Table of content:](#table-of-content)
- [Features](#features)
- [Quickstart](#quickstart)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Set up PushBullet](#set-up-pushbullet)
  - [Sign up with OpenAI (optional)](#sign-up-with-openai-optional)
  - [Sign up with DeepSeek (optional)](#sign-up-with-deepseek-optional)
  - [Write a configuration file](#write-a-configuration-file)
  - [Run the program](#run-the-program)
  - [Updating search](#updating-search)
- [Configuration Guide](#configuration-guide)
  - [AI Agents](#ai-agents)
  - [Marketplaces](#marketplaces)
  - [Users](#users)
  - [Items to search](#items-to-search)
  - [Options that can be specified for both marketplaces and items](#options-that-can-be-specified-for-both-marketplaces-and-items)
  - [Regions](#regions)
- [Advanced features](#advanced-features)
  - [Multiple configuration files](#multiple-configuration-files)
  - [Adjust notification level](#adjust-notification-level)
  - [Searching multiple cities and regions](#searching-multiple-cities-and-regions)
  - [Check individual listing](#check-individual-listing)
  - [Multiple marketplaces](#multiple-marketplaces)
  - [First and subsequent searches](#first-and-subsequent-searches)
  - [Support for different layouts of facebook listings](#support-for-different-layouts-of-facebook-listings)
- [TODO List:](#todo-list)
- [Credits](#credits)

## Features

- Search for one or more products using specified keywords.
- Limit search by price, and location.
- Exclude irrelevant results and spammers.
- Use an AI service provider (OpenAI or DeepSeek) to evaluate listing matches and give recommendations.
- Send notifications via PushBullet.
- Search repeatedly with specified intervals.
- Search multiple cities, even pre-defined regions (e.g. USA)

## Quickstart

### Prerequisites

- Python 3.x installed.

### Installation

Install the program by

```sh
pip install ai-marketplace-monitor
```

Install a browser for Playwright using the command:

```sh
playwright install
```

### Set up PushBullet

- Sign up for [PushBullet](https://www.pushbullet.com/)
- Install the app on your phone
- Go to the PushBullet website and obtain a token

### Sign up with OpenAI (optional)

If you would like to use the OpenAI AI assistant,

- Sign up for a pro account of open AI
- Go to the API keys section of your profile, generate a new API key, and copy it

### Sign up with DeepSeek (optional)

If you would like to use the DeepSeek AI assistant,

- Sign up for a deepseek account
- Generate an API key from the API keys section and copy it

### Write a configuration file

One or more configuration file in [TOML format](https://toml.io/en/) is needed. The following example ([`minimal_config.toml`](minimal_config.toml)) shows the absolute minimal number of options, namely which city you are searching in, what item you are searching for, and how you get notified with matching listings.

```toml
[marketplace.facebook]
search_city = 'houston'

[item.name]
keywords = 'Go Pro Hero 11'

[user.user1]
pushbullet_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
```

The configuration file needs to be put as `$HOME/.ai-marketplace-monitor/config.toml`, or be specified via option `--config`.

A more realistic example using openAI would be

```toml
[ai.openai]
api_key = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

[marketplace.facebook]
search_city = 'houston'
username = 'your@email.com'
seller_locations = [
    "sugar land",
    "stafford",
    "missouri city",
    "pearland"
]

[item.name]
keywords = 'Go Pro Hero 11'
description = '''A new or used Go Pro version 11, 12 or 13 in
    good condition. No other brand of camera is acceptable.
    Please exclude sellers who offers shipping or asks to
    purchase the item from his website.'''
min_price = 100
max_price = 200

[item.name2]
keywords = 'something rare'
description = '''A rare item that has to be searched nationwide and be shipped.
    listings from any location are acceptable.'''
search_region = 'usa'
delivery_method = 'shipping'
seller_locations = []

[user.user1]
pushbullet_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
```

### Run the program

```sh
ai-marketplace-monitor
```

or use option `--config` for a non-standard configuration file. The terminal output will look similar to

![Search In Action](docs/search_in_action.png)

which shows how _ai-marketplace-monitor_ excludes listings for various reasons, and askes OpenAI to evaluate a potential matching one.

Use `Ctrl-C` to terminate the program.

**NOTE**

1. You need to keep the terminal running to allow the program to run indefinitely.
2. You will see a browser firing up. **You may need to manually enter username and/or password (if unspecified in config file), and answer any prompt (e.g. CAPTCHA) to login**. You may want to click "OK" to save the password, etc.
3. If you continue to experience login problem, it can be helpful to remove `username` and `password` from `marketplace.facebook` to authenticate manually. You may want to set `login_wait_time` to be larger than 60 if you need more time to solve the CAPTCHA.

### Updating search

It is recommended that you **check the log messages and make sure that it includes and excluded listings as expected**. Modify the configuration file to update search criteria if needed. The program will detect changes and restart the search automatically.

## Configuration Guide

Here is a complete list of options that are acceptable by the program. [`example_config.toml`](example_config.toml) provides
an example with many of the options.

### AI Agents

One of more sections to list the AI agent that can be used to judge if listings match your selection criteria. The options should have header such as `[ai.openai]` or `[ai.deepseek]`, and have the following keys:

| Option     | Requirement | DataType | Description                                |
| ---------- | ----------- | -------- | ------------------------------------------ |
| `provider` | Optional    | String   | Name of the AI service provider.           |
| `api-key`  | Required    | String   | A program token to access the RESTful API. |
| `base_url` | Optional    | String   | URL for the RESTful API                    |
| `model`    | Optional    | String   | Language model to be used.                 |

Note that:

1. `provider` can be [Open AI](https://openai.com/) or
   [DeepSeek](https://www.deepseek.com/), which sets default `base_url` and `model` for these providers. The name of the provider will be used if this option is not specified so `OpenAI` will be used for section `ai.openai`.
2. If more than one `ai` sections are provided, the program will try all of them in the order for which they are specified.
3. Although only OpenAI and DeepSeek are supported, you can use any other provider with `OpenAI`-compatible API using customized `base_url`, `model`, and `api-key`.

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
| **Common options** |             |          | Options listed in the [Common options](#common-options) section below that provide default values for all items. |

Because the default `marketplace` for all items are `facebook`, it is easiest to define a single section called `marketplace.facebook`.

### Users

One or more `user.username` sections are allowed. The `username` need to match what are listed by option `notify` of marketplace or items. [PushBullet](https://www.pushbullet.com/) is currently the only method of notification.

| Option             | Requirement | DataType | Description    |
| ------------------ | ----------- | -------- | -------------- |
| `pushbullet_token` | Required    | String   | Token for user |

### Items to search

One or more `item.item_name` where `item_name` is the name of the item.

| Option                   | Requirement | DataType    | Description                                                                                                                                                                                    |
| ------------------------ | ----------- | ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `keywords`               | Required    | String/List | One or more strings for searching the item.                                                                                                                                                    |
| `description`            | Optional    | String      | A longer description of the item that better describes your requirements (e.g., manufacture, condition, location, seller reputation, shipping options). Only used if AI assistance is enabled. |
| `enabled`                | Optional    | Boolean     | Stops searching this item if set to `false`.                                                                                                                                                   |
| `include_keywords`       | Optional    | String/List | Excludes listings that do not contain any of the keywords.                                                                                                                                     |
| `exclude_keywords`       | Optional    | String/List | Excludes listings whose titles contain any of the specified strings.                                                                                                                           |
| `exclude_by_description` | Optional    | String/List | Excludes items with descriptions containing any of the specified strings.                                                                                                                      |
| `marketplace`            | Optional    | String      | Name of the marketplace, default to `facebook` that points to a `marketplace.facebook` sectiion.                                                                                               |
| **Common options**       |             |             | Options listed below. These options, if specified in the item section, will override options in the marketplace section.                                                                       |

Marketplaces may return listings that are completely unrelated to search keywords, but can also
return related items under different names. To select the right items, you can

1. Use `include_keywords` to keep only items with certain words in the title. For example, you can set `include_keywords = ['gopro', 'go pro']` when you search for `keywords = 'gopro'`.
2. Use `exclude_keywords` to narrow down the search. For example, setting `exclude_keywords=['HERO 4']` will exclude items with `HERO 4` or `hero 4`in the title.
3. It is usually more effective to write a longer `description` and let the AI know what exactly you want. This will make sure that you will not get a drone when you are looking for a `DJI` camera.

### Options that can be specified for both marketplaces and items

The following options that can specified for both `marketplace` sections and `item` sections. Values in the `item` section will override value in corresponding marketplace if specified in both places.

| `Parameter`           | Required/Optional | Datatype            | Description                                                                                                                                                 |
| --------------------- | ----------------- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `availability`        | Optional          | String/List         | Shows output with `in` (in stock), `out` (out of stock), or `all` (both).                                                                                   |
| `condition`           | Optional          | String/List         | One or more of `new`, `used_like_new`, `used_good`, and `used_fair`.                                                                                        |
| `date_listed`         | Optional          | String/Integer/List | One of `all`, `last 24 hours`, `last 7 days`, `last 30 days`, or `0`, `1`, `7`, and `30`.                                                                   |
| `delivery_method`     | Optional          | String/List         | One of `all`, `local_pick_up`, and `shipping`.                                                                                                              |
| `exclude_sellers`     | Optional          | String/List         | Exclude certain sellers by their names (not username).                                                                                                      |
| `max_price`           | Optional          | Integer             | Maximum price.                                                                                                                                              |
| `max_search_interval` | Optional          | Integer/String      | Maximum interval in seconds between searches. If specified, a random time will be chosen between `search_interval` and `max_search_interval`.               |
| `min_price`           | Optional          | Integer             | Minimum price.                                                                                                                                              |
| `notify`              | Optional          | String/List         | Users who should be notified.                                                                                                                               |
| `radius`              | Optional          | Integer/List        | Radius of search, can be a list if multiple `search_city` are specified.                                                                                    |
| `rating`              | Optional          | Integer/List        | Notify users with listigns with rating at or higher than specified rating. See [Adjust notification level](#adjust-notification-level) for details          |
| `search_city`         | Required          | String/List         | One or more search cities, obtained from the URL of your search query. Required for marketplace or item if `search_region` is unspecified.                  |
| `search_interval`     | Optional          | Integer/String      | Minimal interval in seconds between searches. Can use human-friendly strings like `1d`, `5h`, or `1h 30m`.                                                  |
| `search_region`       | Optional          | String/List         | Search over multiple locations to cover an entire region. `regions` should be one or more pre-defined regions or regions defined in the configuration file. |
| `seller_locations`    | Optional          | String/List         | Only allow searched items from these locations.                                                                                                             |
| `start_at`            | Optional          | String/List         | Time to start the search. Overrides `search_interval`.                                                                                                      |

Note that

1. If `notify` is not specified for both `item` and `marketplace`, all listed users will be notified.
2. `start_at` supports one or more of the following values: <br> - `HH:MM:SS` or `HH:MM` for every day at `HH:MM:SS` or `HH:MM:00` <br> - `*:MM:SS` or `*:MM` for every hour at `MM:SS` or `MM:00` <br> - `*:*:SS` for every minute at `SS`.
3. A list of two values can be specified for options `rating`, `availability`, `delivery_method`, and `date_listed`. See [First and subsequent searches](#first-and-subsequent-searches) for details.

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

## Advanced features

### Multiple configuration files

You can use multiple configuration files. For example, you can add all credentials to `~/.ai-marketplace-monitor/config.yml` and use separate configuration files for items for different users.

### Adjust notification level

We ask AI services to evaluate listings against the criteria that you specify and rate the listing as

1: **No match**: The item does not match at all, for example, is a product in a different category, a brand that the user specifically excluded.
2: **Potential match**: There is not enough information to make a good judgement. Maybe the description is too terse, and there is no indication of the model and year of the product.
3: **Poor match**: The item is acceptable but not a good match, which can be due to higher than average price, item condition, or poor description from the seller.
4: **Good match**: The item matches the selection criteria well and is a potential good deal.
5: **Great deal**: The item is a very good deal, for example with good condition and very competitive price.

When AI services are used, the program by default notifies you of all listing with a rating of 3 or higher. You can change this behavior by setting for example

```toml
rating = 2
```

to see more potential listings. Note that all listings after non-AI-based filtering will be returned if no AI service is specified.

### Searching multiple cities and regions

You can search an item from multiple cities and pick up from sellers from multiple locations using a list of `search_city`

```toml
[item.name]
search_city = ['city1', 'city2']
seller_locations = ['city1', 'city2', 'city3', 'city4']
```

and you can also increase the radius of search using

```toml
[item.name]
search_city = ['city1', 'city2']
radius = 50
```

However, if you would like to search for a larger region (e.g. the USA), it is much easier to define `region`s with a list of `search_city` and large `radius`.

_ai-marketplace-monitor_ defines the following regions in its system
[config.toml](https://github.com/BoPeng/ai-marketplace-monitor/blob/main/src/ai_marketplace_monitor/config.toml):

- `usa` for USA (without AK or HI)
- `usa_full` for USA
- `can` for Canada
- `mex` for Mexico
- `bra` for Brazil
- `arg` for Argentina
- `aus` for Australia
- `aus_miles` for Australia using 500 miles radius
- `nzl` for New Zealand
- `ind` for India
- `gbr` for United Kingdom
- `fra` for France
- `spa` for Spain

Now, if you would like to search an item across the US, you can

```toml
[item.name]
search_region = 'usa'
seller_locations = []
delivery_method = 'shipping'
```

Under the hood, _ai-marketplace-monitor_ will simply replace `search_region` with corresponding pre-defined `search_city` and `radius`. Note that `seller_locations` does not make sense and need to be set to empty for region-based search, and it makes sense to limit the search to listings that offer shipping.

### Check individual listing

If you ever wonder why a listing was excluded, or just want to check a listing against your configuration, you can get the URL (or the item ID) of the listing, and run

```sh
ai-marketplace-monitor --check your-url
```

If you have multiple items specified in your config file, _ai-marketplace-monitor_ will check the product against the configuration of all of them. If you know the _name_ of the item in your config file, you can let the program only check the configuration of this particular item.

```sh
ai-marketplace-monitor --check your-url --for item_name
```

Option `--check` will load the details of the item from the cache if it was previously examined. Otherwise a browser will be started to retrieve the page.

### Multiple marketplaces

Although facebook is currently the only supported marketplace, you can create multiple marketplaces such as`marketplace.city1` and `marketplace.city2` with different options such as `search_city`, `search_region`, `seller_locations`, and `notify`. You will need to add options like `marketplace='city1'` in the items section to link these items to the right marketplace.

For example

```toml
[marketplace.facebook]
search_city = 'houston'
seller_locations = ['houston', 'sugarland']

[marketplace.nationwide]
search_region = 'usa'
seller_location = []
delivery_method = 'shipping'

[item.default_item]
keywords = 'local item for default market "facebook"'

[item.rare_item1]
marketplace = 'nationwide'
keywords = 'rare item1'

[item.rare_item2]
marketplace = 'nationwide'
keywords = 'rare item2'
```

### First and subsequent searches

A list of two values can be specified for options `rating`, `availability`, `date_listed`, and `delivery_method`, with the first one used for the first search, and second one used for the rest of searches. This allows the use of different search strategies for first and subsequent searches. For example, an initial more lenient search for all listings followed by searches for only new listings can be specified as

```
rating = [2, 4]
availability = ["all", "in"]
date_listed = ["all", "last 24 hours"]
```

### Support for different layouts of facebook listings

Facebook marketplace supports a wide variety of products and use different layouts for them. _ai_marketplace_monitor_ can extract description from normal household items, rental items, and automobiles, but you may encounter items that this program cannot handle.

Although I certainly do not have the bandwidth to add support for all possible layouts, I have listed detailed steps on how to debug and resolve the issue on [issue 29](https://github.com/BoPeng/ai-marketplace-monitor/issues/29).

## TODO List:

- Support more AI engines
- Develop better ways to identify spammers
- Support more notification methods.
- Support more marketplaces such as NextDoor and Craigslist

The structure of this project makes it relatively easy to support more notification methods, AI engines, and marketplaces, but I will mostly rely on PRs to add these features.

## Credits

- Some of the code was copied from [facebook-marketplace-scraper](https://github.com/passivebot/facebook-marketplace-scraper).
- Region definitions were copied from [facebook-marketplace-nationwide](https://github.com/gmoz22/facebook-marketplace-nationwide/), which is released under an MIT license as of Jan 2025.
- This package was created with [Cookiecutter](https://github.com/cookiecutter/cookiecutter) and the [cookiecutter-modern-pypackage](https://github.com/fedejaure/cookiecutter-modern-pypackage) project template.
