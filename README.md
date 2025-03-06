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

An intelligent tool that monitors Facebook Marketplace listings using AI to help you find the best deals. Get instant notifications when items matching your criteria are posted, with AI-powered analysis of each listing.

![Search In Action](docs/search_in_action.png)

Example notification from PushBullet:

```
Found 1 new gopro from facebook
[Great deal (5)] Go Pro hero 12
$180, Houston, TX
https://facebook.com/marketplace/item/1234567890
AI: Great deal; A well-priced, well-maintained camera meets all search criteria, with extra battery and charger.
```

**Table of content:**

- [✨ Key Features](#-key-features)
- [Usage](#usage)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Set up a notification method (optional)](#set-up-a-notification-method-optional)
  - [Sign up with an AI service or build your own (optional)](#sign-up-with-an-ai-service-or-build-your-own-optional)
  - [Configuration](#configuration)
  - [Run the program](#run-the-program)
  - [Updating search](#updating-search)
  - [Cost of operations](#cost-of-operations)
- [Advanced features](#advanced-features)
  - [Setting up email notification](#setting-up-email-notification)
  - [Adjust prompt and notification level](#adjust-prompt-and-notification-level)
  - [Advanced Keyword-based filters](#advanced-keyword-based-filters)
  - [Searching multiple cities and regions](#searching-multiple-cities-and-regions)
  - [Check individual listing](#check-individual-listing)
  - [Multiple marketplaces](#multiple-marketplaces)
  - [First and subsequent searches](#first-and-subsequent-searches)
  - [Showing statistics](#showing-statistics)
  - [Self-hosted Ollama Model](#self-hosted-ollama-model)
  - [Cache Management](#cache-management)
  - [Support for different layouts of facebook listings](#support-for-different-layouts-of-facebook-listings)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [Support](#support)
- [License](#license)
- [Credits](#credits)

## ✨ Key Features

🔍 **Smart Search**

- Search multiple products using keywords
- Filter by price and location
- Exclude irrelevant results and spammers
- Support for different Facebook Marketplace layouts

🤖 **AI-Powered**

- Intelligent listing evaluation
- Smart recommendations
- Multiple AI service providers supported
- Self-hosted model option (Ollama)

📱 **Notifications**

- PushBullet and PushOver notifications
- HTML email notifications with images
- Customizable notification levels
- Repeated notification options

🌎 **Location Support**

- Multi-city search
- Pre-defined regions (USA, Canada, etc.)
- Customizable search radius
- Flexible seller location filtering

## Usage

### Prerequisites

- Python 3.x installed.
- Internet connection

### Installation

Install the program by

```sh
pip install ai-marketplace-monitor
```

Install a browser for Playwright using the command:

```sh
playwright install
```

### Set up a notification method (optional)

If you would like to receive notification from your phone via PushBullet

- Sign up for [PushBullet](https://www.pushbullet.com/) or [PushOver](https://pushover.net/)
- Install the app on your phone
- Go to the PushBullet website and obtain necessary token(s)

If you would like to receive email notification, obtain relevant SMTP settings from your email provider. See [Setting up email notification](#setting-up-email-notification) for details.

### Sign up with an AI service or build your own (optional)

You can sign up for an AI service (e.g. [OpenAI](https://openai.com/) and [DeepSeek](https://www.deepseek.com/)) by

- Sign up for an account
- Go to the API keys section of your profile, generate a new API key, and copy it

You can also connect to any other AI service that provides an OpenAI compatible API, or host your own large language model using Ollama (see [Self-hosted Ollama Model](#self-hosted-ollama-model) for details.)

### Configuration

One or more configuration file in [TOML format](https://toml.io/en/) is needed. The following example ([`minimal_config.toml`](docs/minimal_config.toml)) shows the absolute minimal number of options, namely which city you are searching in, what item you are searching for, and how you get notified with matching listings.

```toml
[marketplace.facebook]
search_city = 'houston'

[item.name]
search_phrases = 'Go Pro Hero 11'

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
search_phrases = 'Go Pro Hero 11'
description = '''A new or used Go Pro version 11, 12 or 13 in
    good condition. No other brand of camera is acceptable.
    Please exclude sellers who offer shipping or asks to
    purchase the item from his website.'''
keywords = "('Go Pro' OR gopro) AND (11 OR 12 OR 13)"
min_price = 100
max_price = 200

[item.name2]
search_phrases = 'something rare'
description = '''A rare item that has to be searched nationwide and be shipped.
    listings from any location are acceptable.'''
search_region = 'usa'
delivery_method = 'shipping'
seller_locations = []

[user.user1]
email = 'you@gmail.com'
smtp_password = 'xxxxxxxxxxxxxxxx'
```

For a complete list of options, please see the [configuration documentation](docs/README.md).

### Run the program

```sh
ai-marketplace-monitor
```

or use option `--config` for a non-standard configuration file.

Use `Ctrl-C` to terminate the program.

**NOTE**

1. You need to keep the terminal running to allow the program to run indefinitely.
2. You will see a browser firing up. **You may need to manually enter username and/or password (if unspecified in config file), and answer any prompt (e.g. CAPTCHA) to login**. You may want to click "OK" to save the password, etc.

### Updating search

It is recommended that you **check the log messages and make sure that it includes and excludes listings as expected**. Modify the configuration file to update search criteria if needed. The program will detect changes and restart the search automatically.

### Cost of operations

1. _AI Markplace Monitor_ is distributed under an MIT license. You are free to use, modify, and even use the program for commercial purposes.
2. While the program itself is free, access to optional external services such as PushBullet, PushOver, OpenAI, DeepSeek, or other AI services may incur costs.

## Advanced features

### Setting up email notification

Sending email notifications requires recipient email addresses, which are specified in `email` of `user` or a notification setting. For example, you can send email notifications to multiple users with multiple email addresses as

```toml
[user.user1]
email = 'user1@gmail.com'

[user.user2]
email = ['user2@gmail.com', 'user2@outlook.com']
```

You then need a SMTP server that helps you to send the emails, for which you will need to know `smtp_server`, `smtp_port`, `smtp_username` and `smtp_password`. Generally speaking, you will need to create a notification section with the information obtained from your email service provider.

```toml
[notification.myprovider]
# default to sender email
smtp_username = 'username@EMAIL.COM'
# default to smtp.EMAIL.COM
smtp_server = 'smtp.EMAIL.COM'
smtp_port = 587
smtp_password = 'mypassword'
```

`ai-marketplace-monitor` will try to determine `smtp_username` and `smtp_server` from the sender email address if they are unspecified.

If you have a GMAIL account,

- `smtp_username` is your gmail address, which is assumed to be the first `email` if left unspecified (assume that you are sending notification to yourself)
- `smtp_server` and `smtp_port`: Assumed to be `smtp.gmail.com` and `587`.
- `smtp_password`: You cannot use your gmail password. Instead, you will need to go to your Google `Account Manager`, select `Security`, search for `App passwords` (you may need to enable two-step authentication first), create an app (e.g. `ai-marketplace-monitor`), and copy the app password.

That is to say, you `smtp` setting for your gmail account should look like

```toml
[notification.gmail]
smtp_username = 'myemail@gmail.com'
smtp_password = 'abcdefghijklmnop'
```

If you use an gmail account and only notify yourself, you can simply do

```toml
[user.me]
email = 'myemail@gmail.com'
smtp_password = 'abcdefghijklmnop'
```

### Adjust prompt and notification level

_ai-marketplace-monitor_ asks AI services to evaluate listings against the criteria that you specify with prompts in four parts:

Part 1: buyer intent

```
A user wants to buy a ... with search phrase ... description ..., price range ...,
with keywords .... and exclude ...
```

Part 2: listing details

```
The user found a listing titled ... priced at ..., located ... posted at ...
with description ...
```

Part 3: instruction to AI

```
Evaluate how well this listing matches the user's criteria. Assess the description,
MSRP, model year, condition, and seller's credibility.
```

Part 4: rating instructions

```
Rate from 1 to 5 based on the following:

1 - No match: Missing key details, wrong category/brand, or suspicious activity (e.g., external links).
2 - Potential match: Lacks essential info (e.g., condition, brand, or model); needs clarification.
3 - Poor match: Some mismatches or missing details; acceptable but not ideal.
4 - Good match: Mostly meets criteria with clear, relevant details.
5 - Great deal: Fully matches criteria, with excellent condition or price.

Conclude with:
"Rating [1-5]: [summary]"
where [1-5] is the rating and [summary] is a brief recommendation (max 30 words)."
```

Depending on your specific needs, you can replace part 3 and part 4 of the prompt with options `prompt` and `rating_prompt`, and add an extra prompt before rating prompt with option `extra_prompt`. These options can be specified at the `marketplace` and `item` levels, with the latter overriding the former.

For example, you can add

```toml
[marketplace.facebook]
extra_prompt = """Exclude any listing that recommend visiting an external website \
   for purchase."""
```

to describe suspicious listings in a marketplace, and

```toml
[item.ipadpro]
prompt = """Find market value for listing on market places like Ebay \
    or Facebook marketplace and compare the price of the listing, considering \
    the description, selling price, model year, condition, and seller's \
    credibility. Evaluate how well this listing matches the user's criteria.
  """
```

With these settings, the part 3 of the prompt for item `ipadpro` will be replaced
with `prompt` for `item.ipadpro` and the `extra_prompt` from `marketplace.facebook`.

When AI services are used, the program by default notifies you of all listing with a rating of 3 or higher. You can change this behavior by setting for example

```toml
rating = 4
```

to see only listings that match your criteria well. Note that all listings after non-AI-based filtering will be returned if no AI service is specified or non-functional.

### Advanced Keyword-based filters

Options `keywords` and `antikeywords` are used to filter listings according to specified keywords. In the simplest form, these options support a single string. For example,

```toml
keywords = 'drone'
antikeywords = 'Parrot'
```

will select all listings with `drone` in title or description, and `Parrot` not in title or description. You can use multiple keywords and operators `AND`, `OR`, and `NOT` in the parameter. For example

```toml
keywords = 'DJI AND drone'
```

looks for listings with both `DJI` and `drone` in title or description.

If you have multiple keywords specified in a list, they are by default joint by `OR`. That is to say,

```toml
keywords = ['drone', 'DJI', 'Orqa']
antikeywords = ['Parrot', 'Autel']
```

is equivalent to

```toml
keywords = 'drone OR DJI OR Orqa'
antikeywords = 'Parrot OR Autel'
```

which means selecting listings that contains `drone` or `DJI` or `Orga` in title or description, but exclude those listings with `Parrot` or `Autel` in title or description.

These criteria will however, not exclude listings for a `DJI Camera`. If you would like to make sure that `drone` is selected, you can use

```toml
keywords = 'drone AND (DJI OR Orqa)'
antikeywords = 'Parrot OR Autel'
```

If you have special characters and spaces in your keywords, you will need to quote them, such as

```toml
keywords = '("Go Pro" OR gopro) AND HERO'
```

**NOTE**:

1. A list of logical operations are allowed, and they are assumed to be joint by `OR`. For example, `['gopro AND (11 or 12)', 'DJI AND OSMO']` searches for either a gopro version 11 oe 12, or a DJI COMO camera.
2. You can construct very complex logical operations using `AND`, `OR` and `NOT`, but it is usually recommended to use simple keyword-based filtering and let AI handle more subtle selection criteria.

### Searching multiple cities and regions

`search_city` is the name, sometimes numbers, used by Facebook marketplace to represent a city. To get the value of `search_city` for your region, visit facebook, marketplace, perform a search, and the city should be the name after `marketplace` (e.g. `XXXXX` in a URL like `https://www.facebook.com/marketplace/XXXXX/search?query=YYYY`).

Multiple searches will be performed if multiple cities are provided to option `search_city`. You can also specify `seller_locations` to limit the location of sellers. These locations are names of cities as displayed on the listing pages.

```toml
[item.name]
search_city = ['city1', 'city2']
seller_locations = ['city1', 'city2', 'city3', 'city4']
```

You can also increase the radius of search using

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

Another way to check individual IDs is to enter interactive mode when the _ai-marketplace-monitor_ is running. If you press `Esc`, then confirm with `c` when prompted, you can enter the `URL` and `item_name` interactively and check the URL. Enter `exit` to exit the interactive session after you are done. However, using this method requires OS to allow the program to monitor your keyboard. It would not work on a terminal accessed through SSH, and you have to allow the terminal that you use to run _ai-marketplace-monitor_ to monitor keyboard from the _Privacy and Security_ settings on MacOS.

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
search_phrases = 'local item for default market "facebook"'

[item.rare_item1]
marketplace = 'nationwide'
search_phrases = 'rare item1'

[item.rare_item2]
marketplace = 'nationwide'
search_phrases = 'rare item2'
```

If no `marketplace` is defined for an item, it will use the first defined marketplace, which is `houston` in this example.

### First and subsequent searches

A list of two values can be specified for options `rating`, `availability`, `date_listed`, and `delivery_method`, with the first one used for the first search, and second one used for the rest of searches. This allows the use of different search strategies for first and subsequent searches. For example, an initial more lenient search for all listings followed by searches for only new listings can be specified as

```
rating = [2, 4]
availability = ["all", "in"]
date_listed = ["all", "last 24 hours"]
```

### Showing statistics

_ai-marketplace-monitor_ shows statistics such as the number of pages searched, number of listings examined and excluded, number of matching lists found and number of users notified when you exit the program. If you would like to see the statistics during monitoring, press `Esc` and wait till the current search to end.

Counters are persistent across program runs. If you would like to reset the counters, use

```
ai-marketplace-monitor --clear-cache counters
```

### Self-hosted Ollama Model

If you have access to a decent machine and prefer not to pay for AI services from OpenAI or other vendors. You can opt to install Ollama locally and access it using the `provider = "ollama"`. If you have ollama on your local host, you can use

```
[ai.ollama]
base_url = "http://localhost:11434/v1"
model = "deepseek-r1:14b"
timeout = 120
```

Note that

1. Depending on your hardware configuration, you can choose any of the models listed [here](https://ollama.com/search). The default model is `deepseek-r1:14b` becaue it appears to work better than `llama-3.1:8b`.
2. You need to `pull` the model before you can use it.

### Cache Management

_ai-marketplace-monitor_ caches listing details, ai inquiries, and user notifications to avoid repeated queries to marketplaces, AI services, and repeated notification. If for any reason you would like to clear the cache, you can use commands such as

```
ai-marketplace-monitor --clear-cache listing-details
```

to clear the cache. The following cache types are supported

- `listing-details`
- `ai-inquiries`
- `user-notification`
- `counters`

`--clear-cache all` is also possible but not recommended.

### Support for different layouts of facebook listings

Facebook marketplace supports a wide variety of products and use different layouts for them. _ai_marketplace_monitor_ can extract description from common listings such as household items and automobiles, but you may encounter items that this program cannot handle.

Although I certainly do not have the bandwidth to support all possible layouts, I have listed detailed steps on how to debug and resolve the issue on [issue 29](https://github.com/BoPeng/ai-marketplace-monitor/issues/29).

## Troubleshooting

1. **Browser Login**

   - You may need to manually enter credentials on first run
   - Answer any CAPTCHA prompts if presented
   - Consider saving password in browser if prompted

2. **Notifications**

   - Check `rating` level if receiving too many/few alerts
   - For email issues, verify SMTP settings and credentials
   - For PushBullet or PushOver, verify token is correct

3. **AI Services**
   - Ensure API keys are valid
   - Check network connectivity
   - Verify model names if using custom models

For more issues, please check our [Issues](https://github.com/BoPeng/ai-marketplace-monitor/issues) page.

## Contributing

Contributions are welcome! Here are some ways you can contribute:

- 🐛 Report bugs and issues
- 💡 Suggest new features
- 🔧 Submit pull requests
- 📚 Improve documentation
- 🌍 Add support for new regions
- 🤖 Add support for new AI providers
- 📱 Add new notification methods

Please read our [Contributing Guidelines](CONTRIBUTING.md) before submitting a Pull Request.

## Support

- 📖 Read the [Documentation](https://ai-marketplace-monitor.readthedocs.io/)
- 🤝 Join our [Discussions](https://github.com/BoPeng/ai-marketplace-monitor/discussions)
- 🐛 Report [Issues](https://github.com/BoPeng/ai-marketplace-monitor/issues)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Credits

- Some of the code was copied from [facebook-marketplace-scraper](https://github.com/passivebot/facebook-marketplace-scraper).
- Region definitions were copied from [facebook-marketplace-nationwide](https://github.com/gmoz22/facebook-marketplace-nationwide/), which is released under an MIT license as of Jan 2025.
- This package was created with [Cookiecutter](https://github.com/cookiecutter/cookiecutter) and the [cookiecutter-modern-pypackage](https://github.com/fedejaure/cookiecutter-modern-pypackage) project template.
