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
- [Advanced features](#advanced-features)
- [TODO List:](#todo-list)
- [Credits](#credits)

## Features

- Search for one or more products using specified keywords.
- Limit search by price, and location.
- Exclude irrelevant results and spammers.
- Use an AI agent (OpenAI or DeepSeek) to confirm listing matches.
- Send notifications via PushBullet.
- Search repeatedly with specified intervals.

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

One or more configuration file in [TOML format](https://toml.io/en/) is needed. The following example ([`minimal_config.toml`](minimal_config.toml)) shows the absolute minimal number of options, namely which city you are searching in, what item you are searching for, and how you want to get notified to run _ai-marketplace-monitor_.

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
acceptable_locations = [
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

[user.user1]
pushbullet_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
```

### Run the program

```sh
ai-marketplace-monitor --config /path/to/config.toml
```

or without `--config` if you have the configuration stored as `$HOME/.ai-marketplace-monitor/config.toml`

**NOTE**

1. You need to keep the terminal running to allow the program to run indefinitely.
2. You will see a browser firing up. **You may need to manually enter username and/or password (if unspecified in config file), and answer any prompt (e.g. CAPTCHA) to login**. You may want to click "OK" to save the password, etc.
3. If you continue to experience login problem, it can be helpful to remove `username` and `password` from `marketplace.facebook` to authenticate manually. You may want to set `login_wait_time` to be larger than 60 if you need more time to solve the CAPTCHA.

### Updating search

Modify the configuration file to update search criteria. The program will detect changes automatically.

## Configuration Guide

Here is a complete list of options that are acceptable by the program. [`example_config.toml`](example_config.toml) provides
an example with many of the options.

- Section `ai.openai` and/or `ai.deepseek`, optional sections listing the api-key for [Open AI](https://openai.com/) or
  [DeepSeek](https://www.deepseek.com/). Specification of these sections will enable AI-assistance. If both `ai.openai` and `ai.deepseek` are specified, the program try in the order for which they are specified.

  - `api-key`: (required), a program token to access openAI REST API.
  - `model`: (optional), by default `gpt-4o` or `deepseek-chat` will be used for `openami` or `deepseek` respectively.
  - `base_url`: (optional), in case you use another server

- Section `marketplace.facebook` shows the options for interacting with the facebook marketplace. `facebook` is currently the only marketplace that is supported.

  - `username`: (optional), you can enter manually or keep in config file
  - `password`: (optional), you can enter manually or keep in config file
  - `login_wait_time`: (optional), time to wait before searching in seconds, to give you enough time to enter CAPTCHA, default to 60.
  - `search_interval`: (optional) minimal interval in minutes between searches
  - `max_search_interval`: (optional) maximum interval in minutes between searches
  - `search_city`: (optional if defined for item) search city, which can be obtained from the URL of your search query
  - `acceptable_locations`: (optional) only allow searched items from these locations
  - `exclude_sellers`: (optional) exclude certain sellers by their names (not username)
  - `min_price`: (optional) minimum price.
  - `max_price`: (optional) maximum price.
  - `notify`: (optional) users who should be notified for all items

- One or more `user.username` sections are allowed. The `username` need to match what are listed by option `notify` of marketplace or items. PushBullet is currently the only method of notification.

  - `pushbullet_token`: (rquired) token for user

- One or more `item.item_name` where `item_name` is the name of the item.
  - `keywords`: (required) one of more keywords for searching the item
  - `description`: (optional) A longer description of the item that better describes your requirements, such as manufacture, condition, location, seller reputation,
    if you accept shipping etc. It is currently **only used if AI assistance is enabled**.
  - `marketplace`: (optional), can only be `facebook` if specified.
  - `exclude_keywords`: (optional), exclude item if the title contain any of the specified words
  - `exclude_sellers`: (optional) exclude certain sellers
  - `enabled`: (optional), stop searching this item if set to `false`
  - `min_price`: (optional) minimum price.
  - `max_price`: (optional) maximum price.
  - `exclude_by_description`: (optional) exclude items with descriptions containing any of the specified words.
  - `notify`: (optional) users who should be notified for this item
  - `acceptable_locations`: (optional) item specific acceptable location, will override marketplace `acceptable_locations` if both specified.

Note that

1. `exclude_keywords` and `exclude_by_description` will lead to string-based exclusion of items. If AI assistant is available, it is recommended that you specify these exclusion items verbally in `description`, such as "exclude items that refer me to a website for purchasing, and exclude items that only offers shipping.".
2. If `notify` is not specified for both `item` and `marketplace`, all listed users will be notified.

## Advanced features

- A file `~/.ai-marketplace-monitor/config.yml`, if it exists, will be read and merged with the specified configuration file. This allows you to save sensitive information like Facebook username, password, and PushBullet token in a separate file.
- Multiple configuration files can be specified to `--config`, which allows you to spread items into different files.
- If you would like to know how the program works, especially how it intereacts with the AI, use option `--verbose` (or `-v`).
- If you ever wonder why a listing was excluded, or just want to check a listing against your configuration, you can get the URL (or the item ID) of the listing, and run

  ```sh
  ai-marketplace-monitor --check your-url
  ```

  If you have multiple items specified in your config file, _ai-marketplace-monitor_ will check the product against the configuration of all of them. If you know the _name_ of the item in your config file, you can let the program only check the configuration of this particular item.

  ```sh
  ai-marketplace-monitor --check your-url --for item_name
  ```

  Option `--check` will load the details of the item from the cache if it was previously examined. Otherwise a browser will be started to retrieve the page.

## TODO List:

- Support more AI engines
- Develop better ways to identify spammers
- Support more notification methods.
- Support more marketplaces.

## Credits

- Some of the code was copied from [facebook-marketplace-scraper](https://github.com/passivebot/facebook-marketplace-scraper).
- This package was created with [Cookiecutter](https://github.com/cookiecutter/cookiecutter) and the [cookiecutter-modern-pypackage](https://github.com/fedejaure/cookiecutter-modern-pypackage) project template.
