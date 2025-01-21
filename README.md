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

An AI-based tool for monitoring facebook marketplace

- GitHub repo: <https://github.com/BoPeng/ai-marketplace-monitor.git>
- Documentation: <https://ai-marketplace-monitor.readthedocs.io>
- Free software: MIT

This program

1. Starts a browser (can be in headless mode)
2. Search one or more products
3. Notify one or more users of new products with phone notification

## Features

- Search for one or more products using specified keywords.
- Limit search by minimum and maximum price, and location.
- Exclude irrelevant results.
- Exclude explicitly listed spammers.
- Exclude by description.
- Exclude previously searched items and only notify about new items.
- Send notifications via PushBullet.
- Search repeatedly with specified intervals in between.
- Add/remove items dynamically by changing the configuration file.

**TODO**:

- Use embedding-based algorithms to identify likely matches.
- Use AI to identify spammers.
- Support other notification methods.
- Support other marketplaces.

**NOTE**: This is a tool for programmers, and you are expected to know some Python and command-line operations to make it work. There is no GUI.

## Quickstart

### Install `ai-marketplace-monitor`

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

### Write a configuration file

A minimal example is provided as [`minimal_config.toml`](minimal_config.toml). Basically you will need to let the program know which city you are searching in, what item you are searching for, and how you want to get notified.

```toml
[marketplace.facebook]
username = 'username'
password = 'password'
search_city = 'houston'

[item.name]
keywords = 'search word one'

[user.user1]
pushbullet_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
```

A more complete example is provided at [`example_config.toml`](example_config.toml), which allows for more complex search and notification patterns. Briefly:

- `marketplace.facebook` allows

  - `username`: (required)
  - `password`: (required)
  - `search_interval`: (optional) minimal interval in minutes between searches
  - `max_search_interval`: (optional) maximum interval in minutes between searches
  - `search_city`: (optional if defined for item) search city, which can be obtained from the URL of your search query
  - `acceptable_locations`: (optional) only allow searched items from these locations
  - `exclude_sellers`: (optional) exclude certain sellers by their names (not username)
  - `min_price`: (optional) minimum price.
  - `max_price`: (optional) maximum price.
  - `notify`: (optional) users who should be notified for all items

- `user.username` where `username` is the name listed in `notify`

  - `pushbullet_token`: (rquired) token for user

- `item.item_name` where `item_name` is the name of the item
  - `keywords`: (required) one of more keywords for searching the item
  - `marketplace`: (optional), can only be `facebook` if specified.
  - `exclude_keywords`: (optional), exclude item if the title contain any of the specified words
  - `exclude_sellers`: (optional, not implemented yet) exclude certain sellers
  - `min_price`: (optional) minimum price.
  - `max_price`: (optional) maximum price.
  - `exclude_by_description`: (optional) exclude items with descriptions containing any of the specified words.
  - `notify`: (optional) users who should be notified for this item

### Run the program

Start monitoring with the command

```sh
ai-marketplace-monitor
```

or

```
ai-marketplace-monitor --config /path/to/config.toml
```

**NOTE**

1. You need to keep the terminal running to allow the program to run indefinitely.
2. You will see a browser firing up. **You may need to manually enter any prompt (e.g. CAPTCHA) that facebook asks for authentication** in addition to the username and password that the program enters for you. You may want to click "OK" to save the password, etc.

## Advanced features

- A file `~/.ai-marketplace-monitor/config.yml`, if it exists, will be read and merged with the specified configuration file. This allows you to save sensitive information like Facebook username, password, and PushBullet token in a separate file.
- Multiple configuration files can be specified to `--config`, which allows you to spread items into different files.

## Credits

- Some of the code was copied from [facebook-marketplace-scraper](https://github.com/passivebot/facebook-marketplace-scraper).
- This package was created with [Cookiecutter](https://github.com/cookiecutter/cookiecutter) and the [cookiecutter-modern-pypackage](https://github.com/fedejaure/cookiecutter-modern-pypackage) project template.
