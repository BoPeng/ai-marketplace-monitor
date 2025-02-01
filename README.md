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
  - [Check individual listing](#check-individual-listing)
  - [Multiple marketplaces](#multiple-marketplaces)
- [TODO List:](#todo-list)
- [Credits](#credits)

## Features

- Search for one or more products using specified keywords.
- Limit search by price, and location.
- Exclude irrelevant results and spammers.
- Use an AI service provider (OpenAI or DeepSeek) to confirm listing matches.
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

- `provider`: (optional), the section name will be used if this is unspecified, so `ai.deepseek` will assume a provider of `deepseek`.
- `api-key`: (required), a program token to access openAI REST API.
- `base_url`: (optional), in case you use another server
- `model`: (optional), by default `gpt-4o` or `deepseek-chat` will be used for `Openami` or `DeepSeek` respectively.

Note that:

1. `provider` can be [Open AI](https://openai.com/) or
   [DeepSeek](https://www.deepseek.com/). However, with the use of `base_url`, `model`, and `api-key`, you can use this program with any services that provides an `OpenAI`-compatible API.
2. If more than one `ai` sections are provided, the program will try all of them in the order for which they are specified.

### Marketplaces

One or more sections `marketplace.name` show the options for interacting with the facebook marketplace.

- `market_type`: (optional), `facebook` is currently the only supported marketplace.
- `username`: (optional), you can enter manually or keep in config file
- `password`: (optional), you can enter manually or keep in config file
- `login_wait_time`: (optional), time to wait before searching in seconds, to give you enough time to enter CAPTCHA, default to 60.
- **Common options** listed in the section [Common options](#common-options) below. These options, if specified in the marketplace section, will by default be applied to all items.

Because the default `marketplace` for all items are `facebook`, you will most likely have a single section called `marketplace.facebook`.

### Users

One or more `user.username` sections are allowed. The `username` need to match what are listed by option `notify` of marketplace or items. PushBullet is currently the only method of notification.

- `pushbullet_token`: (rquired) token for user

### Items to search

One or more `item.item_name` where `item_name` is the name of the item.

- `keywords`: (required) one of more keywords for searching the item.
- `description`: (optional) A longer description of the item that better describes your requirements, such as manufacture, condition, location, seller reputation,
  if you accept shipping etc. It is currently **only used if AI assistance is enabled**.
- `enabled`: (optional), stop searching this item if set to `false`
- `include_keywords`: (optional), exclude listings that does not contain any of the keywords.
- `exclude_keywords`: (optional), exclude listings whose titles contain any of the specified words
- `exclude_by_description`: (optional) exclude items with descriptions containing any of the specified words.
- `marketplace`: (optional), can only be `facebook` if specified.
- **Common options** listed below. These options, if specified in the item section, will override options in the markerplace section.

Facebook may return listings that are completely unrelated to search keywords, but can also
return related items under different names. To fix this problem, you can

1. Use `include_keywords` to keep only items with certain words in the title. For example, you can set `include_keywords = ['gopro', 'go pro']` when you search for `keywords = 'gopro'`.
2. Use `exclude_keywords` to narrow down the search. For example, setting `exclude_keywords=['HERO 4']` will exclude items with `HERO 4` or `hero 4`in the title.
3. It is usually more effective to write a longer `description` and let the AI know what exactly you want. This will make sure that you will not get a drone when you are looking for a camera.

### Options that can be specified for both marketplaces and items

The following options that can specified for both `marketplace` sections and `item` sections. Options defined in marketplaces provide default options for all items searched in that marketplace. Options defined for individual items will override options provided in marketplaces.

- `seller_locations`: (optional) only allow searched items from these locations
- `condition`: (optional) one or more of `new`, `used_like_new`, `used_good`, and `used_fair`.
- `date_listed`: (optional) one of `All`, `Last 24 hours`, `Last 7 days`, `Last 30 days`, or `0`, `1`, `7`, and `30`.
- `delivery_method`: (optional) one of `all`, `local_pick_up`, and `shipping`.
- `exclude_sellers`: (optional) exclude certain sellers by their names (not username)
- `min_price`: (optional) minimum price.
- `max_price`: (optional) maximum price.
- `notify`: (optional) users who should be notified
- `radius`: (optional) radius of search, can be a list if multiple `search_city` are specified.
- `search_city`: (required for marketplace or item if `search_region` is unspecified) one or more search city, which can be obtained from the URL of your search query.
- `search_region`: (optional) search over multiple locations to cover an entire region. `regions` should be one or more pre-defined regions, or regions defined in the configuration file.
- `search_interval`: (optional) minimal interval in seconds between searches, you can also write human friendly strings like `1d`, `5h`, or `1h 30m`.
- `max_search_interval`: (optional) maximum interval in seconds between searches

Note that

1. `exclude_keywords` and `exclude_by_description` will lead to string-based exclusion of items. If AI assistant is available, it is recommended that you specify these exclusion items verbally in `description`, such as "exclude items that refer me to a website for purchasing, and exclude items that only offers shipping.".
2. If `notify` is not specified for both `item` and `marketplace`, all listed users will be notified.

### Regions

One or more sections of `[region.region_name]`, which defines regions to search. Multiple searches will be performed for multiple cities to cover entire regions.

- `search_city`: (required), one or more cities with names used by facebook
- `full_name`: (optional) a display name for the region.
- `radius`: (optional), recommend 805 for regions using miles, and 500 using kms, default to `805`
- `city_name`: (optional), corresponding city names for bookkeeping purpose only.

Note that

1. Under the hood, _ai-marketplace-monitor_ will simply set `radius` and expand regions into `search_city` of marketplace or items with `search_region`. Options `full_name` and `city_name` are not used.
2. If you are searching one or more regions by specifying `search_region`, make sure that you set `seller_locations=[]` or leave it unspecified in both `item` and `marketplace.facebook`.
3. _ai-marketplace-monitor_ ships with the following regions:

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

   These regions are defined in the system
   [config.toml](https://github.com/BoPeng/ai-marketplace-monitor/blob/main/src/ai_marketplace_monitor/config.toml). You can define your own regions following the style there. Please feel free to submit PRs to add regions that can be of interest to others.

## Advanced features

### Multiple configuration files

You can use multiple configuration files. For example, you can add all credentials to `~/.ai-marketplace-monitor/config.yml` and use separate configuration files for items for different users.

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
