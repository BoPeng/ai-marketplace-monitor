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

This program is a command line tool that

1. Starts a browser
2. Search one or more products from facebook marketplace indefinitely
3. Notify you of new products with phone notification

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

Yes, I know, there is no AI-related features yet... I am working on them, and you are welcome to [contribute](https://github.com/BoPeng/ai-marketplace-monitor/issues).

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

One or more configuration file in [TOML format](https://toml.io/en/) is needed. The following example ([`minimal_config.toml`](minimal_config.toml)) shows the absolute minimal number of options, namely which city you are searching in, what item you are searching for, and how you want to get notified to run _ai-marketplace-monitor_. A more complete example is provided at [`example_config.toml`](example_config.toml).

```toml
[marketplace.facebook]
search_city = 'houston'

[item.name]
keywords = 'search word one'

[user.user1]
pushbullet_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
```

The configuration file needs to be put as `$HOME/.ai-marketplace-monitor/config.toml`, or be specified via option `--config`.

Here is a complete list of options that are acceptable by the program:

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
  - `marketplace`: (optional), can only be `facebook` if specified.
  - `exclude_keywords`: (optional), exclude item if the title contain any of the specified words
  - `exclude_sellers`: (optional) exclude certain sellers
  - `enabled`: (optional), stop searching this item if set to `false`
  - `min_price`: (optional) minimum price.
  - `max_price`: (optional) maximum price.
  - `exclude_by_description`: (optional) exclude items with descriptions containing any of the specified words.
  - `notify`: (optional) users who should be notified for this item

Note that

1. Strings will be normalized (remove space and special characters, change to lower case) before comparison, so you do not have to specify both `go pro` and `gopro` for keyword or exclusion searches.
2. If `notify` is not specified for both `item` and `marketplace`, all listed users will be notified.

### Run the program

Start monitoring with the command

```sh
ai-marketplace-monitor
```

if you have the configuration stored as `$HOME/.ai-marketplace-monitor/config.toml`, or

```
ai-marketplace-monitor --config /path/to/config.toml
```

**NOTE**

1. You need to keep the terminal running to allow the program to run indefinitely.
2. You will see a browser firing up. **You may need to manually enter username and/or password (if unspecified in config file), and answer any prompt (e.g. CAPTCHA) to login**. You may want to click "OK" to save the password, etc.
3. If you continue to experience login problem, it can be helpful to remove `username` and `password` from `marketplace.facebook` to authenticate manually. You may want to set `login_wait_time` to be larger than 60 if you need more time to solve the CAPTCHA.

### Updating search

Once the most troublesome step, namely logging into facebook is completed, the program will run indefinitely to search for the items, and notify you with the most relevant listings. If you need to change keywords, block sellers, add/remove locations, or add new items to search, you can modify the configuration file. The program will automatically detect changes in configuration files and act accordingly.

## Advanced features

- A file `~/.ai-marketplace-monitor/config.yml`, if it exists, will be read and merged with the specified configuration file. This allows you to save sensitive information like Facebook username, password, and PushBullet token in a separate file.
- Multiple configuration files can be specified to `--config`, which allows you to spread items into different files.

## Credits

- Some of the code was copied from [facebook-marketplace-scraper](https://github.com/passivebot/facebook-marketplace-scraper).
- This package was created with [Cookiecutter](https://github.com/cookiecutter/cookiecutter) and the [cookiecutter-modern-pypackage](https://github.com/fedejaure/cookiecutter-modern-pypackage) project template.
