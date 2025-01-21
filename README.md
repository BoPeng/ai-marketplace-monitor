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
3. Notify you (and others) of new products with phone notification

## Features

- Search one or more products with specified keywords
- Limit search by price, and location
- Exclude irrelevant results
- Exclude previous searched items and only notify new items
- Send notification via PushBullet
- Search repeatedly with specified intervals in between
- Add/remove items dynamically by changing the confirmation file.

TODO:

- Exclude explicitly listed spammers
- Use embedding-based algorithm to identify likely matches
- Use AI to identify spammers
- Support other notification methods
- Support other marketplaces

**NOTE**: This is a recipe for programmers, and you are expected to know some Python and command-line operations to make it work. There is no GUI.

## Quickstart

### Set up a python environment

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

A minimal example is provided as [`minimal_config.toml`](minimal_config.toml). Basically you will need to let the program know which city you are searching, what item you are searching for, and how do you want to get notified.

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

A more complete example is provided at [`example_config.toml`](example_config.toml), which allows more complex search and notification patterns.

### Run the program

Start monitoring with the command

```sh
ai-marketplace-monitor
```

You will need to specify the path to the configuration file if it is not named `config.toml`.

**NOTE**

1. You need to keep the terminal running to allow the program to run indefinitely.
2. You will see a browser firing up. **You may need to manually enter any prompt that facebook asks for authentication** in addition to the username and password that the program enters for you. You may want to click "OK" for save password etc.

## Credits

- The idea and some of the code was copied from [facebook-marketplace-scraper](https://github.com/passivebot/facebook-marketplace-scraper).
- This package was created with [Cookiecutter][cookiecutter] and the [fedejaure/cookiecutter-modern-pypackage][cookiecutter-modern-pypackage] project template.
