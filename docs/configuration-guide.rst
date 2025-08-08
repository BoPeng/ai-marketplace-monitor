===================
Configuration Guide
===================

This section covers advanced configuration options and setup procedures for AI Marketplace Monitor.

Setting Up Email Notifications
==============================

To send email notifications, you need to specify recipient email addresses in the `email` of a `user` or a notification setting. You can configure multiple users with individual or multiple email addresses like this:

.. code-block:: toml

    [user.user1]
    email = 'user1@gmail.com'

    [user.user2]
    email = ['user2@gmail.com', 'user2@outlook.com']

SMTP Configuration
------------------

An SMTP server is required for sending emails, for which you will need to know `smtp_server`, `smtp_port`, `smtp_username` and `smtp_password`. Generally speaking, you will need to create a notification section with the information obtained from your email service provider.

.. code-block:: toml

    [notification.myprovider]
    smtp_username = 'username@EMAIL.COM' # default to email
    smtp_server = 'smtp.EMAIL.COM'       # default to smtp.EMAIL.COM
    smtp_port = 587                      # default for most providers
    smtp_password = 'mypassword'

`ai-marketplace-monitor` will try to use `email` if `smtp_username` is unspecified, and determine `smtp_username` and `smtp_server` automatically from the sender email address. For example, your Gmail setup could be as simple as:

.. code-block:: toml

    [notification.gmail]
    smtp_password = 'abcdefghijklmnop'

You can specify `smtp_password` directly in the `user` section if you are not sharing the `notification` setting with other users.

.. code-block:: toml

    [user.me]
    email = 'myemail@gmail.com'
    smtp_password = 'abcdefghijklmnop'

.. note::
   - **Gmail Users**: You will need to create a separate app password for your Google account as `smtp_password`.
   - **Commercial Users**: If you are a subscriber to our Pro or Business Plans, detailed instructions on configuring the SMTP service we provide will be sent to you via email.

Setting Up PushOver Notifications
=================================

To enable PushOver notifications, follow these steps:

1. **Install the PushOver app** on your mobile device.
2. **Create a PushOver account** at `pushover.net <https://pushover.net>`_. After registration, you will find your **User Key** labeled as `Your User Key` — this is your `pushover_user_key`.
3. **Create a new application** (you can name it `AIMarketplaceMonitor`). After creation, you will receive an **API Token/Key**, referred to as `pushover_api_token`.

Configuration Options
--------------------

Once you have both the user key and API token, add them to your configuration file using one of the following formats:

**Option 1: Embed directly under your user profile**

.. code-block:: toml

    [user.me]
    pushover_user_key = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    pushover_api_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

**Option 2: Use a dedicated notification section**

.. code-block:: toml

    [notification.pushover]
    pushover_user_key = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    pushover_api_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

    [user.me]
    notify_with = 'pushover'

Description Settings
-------------------

By default, notifications include the **title**, **price**, **location**, **description**, and **AI-generated comments** (if enabled). To exclude or limit the length of the **listing description**, you can add the `with_description` option to your config.

You can set `with_description` to:

- `True` — to include the **full description**.
- `False` — to exclude the description (default behavior).
- A **number** — to include only the **first N characters** of the description.

For example:

.. code-block:: toml

    [user.me]
    pushover_user_key = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    pushover_api_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    with_description = 100

This will include up to the first 100 characters of each listing's description in your notifications.

Setting Up Telegram Notifications
=================================

To enable Telegram notifications, you'll need to create a Telegram bot and obtain a chat ID.

Step 1: Create a Telegram Bot
-----------------------------

1. **Open Telegram** and search for `@BotFather` (the official bot for creating other bots).
2. **Start a conversation** with BotFather by clicking "Start" or sending `/start`.
3. **Create a new bot** by sending the command `/newbot`.
4. **Choose a bot name** when prompted (e.g., "AI Marketplace Monitor").
5. **Choose a bot username** that ends with "bot" (e.g., "my_marketplace_monitor_bot").
6. **Save your bot token** - BotFather will provide a token that looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`. **Keep this token secure and never share it publicly.**

Step 2: Get Your Chat ID
------------------------

You need to find your chat ID to receive messages. Here are two methods:

**Method 1: Using @userinfobot**

1. Search for `@userinfobot` in Telegram and start a conversation.
2. Send any message to the bot.
3. The bot will reply with your user information, including your **Chat ID** (a number like `123456789`).

**Method 2: Using the Telegram Bot API**

1. Start a conversation with your newly created bot (search for its username).
2. Send any message to your bot (e.g., "Hello").
3. Open this URL in your browser, replacing `YOUR_BOT_TOKEN` with your actual token::

       https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates

4. Look for the `"chat":{"id":` field in the response - this number is your chat ID.

Step 3: Configure Your Settings
-------------------------------

Add your Telegram credentials to your configuration file using one of these formats:

**Option 1: Direct configuration under user profile**

.. code-block:: toml

    [user.me]
    telegram_token = '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11'
    telegram_chat_id = '123456789'

**Option 2: Using a dedicated notification section**

.. code-block:: toml

    [notification.telegram]
    telegram_token = '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11'
    telegram_chat_id = '123456789'

    [user.me]
    notify_with = 'telegram'

**Option 3: Using environment variables for security**

.. code-block:: toml

    [user.me]
    telegram_token = '${TELEGRAM_BOT_TOKEN}'
    telegram_chat_id = '${TELEGRAM_CHAT_ID}'

Then set the environment variables:

.. code-block:: bash

    export TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    export TELEGRAM_CHAT_ID="123456789"

Telegram Troubleshooting
------------------------

**401 Unauthorized Error**

- **Cause**: Invalid or incorrect bot token
- **Solution**:
  1. Verify your bot token is correct (it should look like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)
  2. Make sure there are no extra spaces or characters
  3. Create a new bot with @BotFather if the token is lost

**403 Forbidden Error**

- **Cause**: Bot doesn't have permission to send messages to the chat
- **Solution**:
  1. Start a conversation with your bot by searching for its username in Telegram
  2. Send at least one message to the bot (e.g., "/start" or "Hello")
  3. Verify the chat ID is correct

**400 Bad Request Error**

- **Cause**: Invalid chat ID format or the chat doesn't exist
- **Solution**:
  1. Double-check your chat ID is a number (positive for users, negative for groups)
  2. For group chats, make sure the bot is added to the group
  3. Use the getUpdates method to verify your chat ID

AI Prompt Customization
=======================

_ai-marketplace-monitor_ asks AI services to evaluate listings against the criteria that you specify with prompts in four parts:

**Part 1: Buyer Intent**

.. code-block:: text

    A user wants to buy a ... with search phrase ... description ..., price range ...,
    with keywords .... and exclude ...

**Part 2: Listing Details**

.. code-block:: text

    The user found a listing titled ... priced at ..., located ... posted at ...
    with description ...

**Part 3: Instruction to AI**

.. code-block:: text

    Evaluate how well this listing matches the user's criteria. Assess the description,
    MSRP, model year, condition, and seller's credibility.

**Part 4: Rating Instructions**

.. code-block:: text

    Rate from 1 to 5 based on the following:

    1 - No match: Missing key details, wrong category/brand, or suspicious activity (e.g., external links).
    2 - Potential match: Lacks essential info (e.g., condition, brand, or model); needs clarification.
    3 - Poor match: Some mismatches or missing details; acceptable but not ideal.
    4 - Good match: Mostly meets criteria with clear, relevant details.
    5 - Great deal: Fully matches criteria, with excellent condition or price.

    Conclude with:
    "Rating [1-5]: [summary]"
    where [1-5] is the rating and [summary] is a brief recommendation (max 30 words)."

Custom Prompts
--------------

Depending on your specific needs, you can replace part 3 and part 4 of the prompt with options `prompt` and `rating_prompt`, and add an extra prompt before rating prompt with option `extra_prompt`. These options can be specified at the `marketplace` and `item` levels, with the latter overriding the former.

For example, you can add:

.. code-block:: toml

    [marketplace.facebook]
    extra_prompt = """Exclude any listing that recommend visiting an external website \
       for purchase."""

to describe suspicious listings in a marketplace, and:

.. code-block:: toml

    [item.ipadpro]
    prompt = """Find market value for listing on market places like Ebay \
        or Facebook marketplace and compare the price of the listing, considering \
        the description, selling price, model year, condition, and seller's \
        credibility. Evaluate how well this listing matches the user's criteria.
      """

Rating Thresholds
----------------

When AI services are used, the program by default notifies you of all listing with a rating of 3 or higher. You can change this behavior by setting for example:

.. code-block:: toml

    rating = 4

to see only listings that match your criteria well. Note that all listings after non-AI-based filtering will be returned if no AI service is specified or non-functional.

Advanced Keyword-Based Filters
==============================

Options `keywords` and `antikeywords` are used to filter listings according to specified keywords. In the simplest form, these options support a single string. For example:

.. code-block:: toml

    keywords = 'drone'
    antikeywords = 'Parrot'

will select all listings with `drone` in title or description, and `Parrot` not in title or description.

Boolean Operators
----------------

You can use multiple keywords and operators `AND`, `OR`, and `NOT` in the parameter. For example:

.. code-block:: toml

    keywords = 'DJI AND drone'

looks for listings with both `DJI` and `drone` in title or description.

If you have multiple keywords specified in a list, they are by default joint by `OR`. That is to say:

.. code-block:: toml

    keywords = ['drone', 'DJI', 'Orqa']
    antikeywords = ['Parrot', 'Autel']

is equivalent to:

.. code-block:: toml

    keywords = 'drone OR DJI OR Orqa'
    antikeywords = 'Parrot OR Autel'

which means selecting listings that contains `drone` or `DJI` or `Orga` in title or description, but exclude those listings with `Parrot` or `Autel` in title or description.

Complex Expressions
-------------------

These criteria will however, not exclude listings for a `DJI Camera`. If you would like to make sure that `drone` is selected, you can use:

.. code-block:: toml

    keywords = 'drone AND (DJI OR Orqa)'
    antikeywords = 'Parrot OR Autel'

If you have special characters and spaces in your keywords, you will need to quote them, such as:

.. code-block:: toml

    keywords = '("Go Pro" OR gopro) AND HERO'

.. note::
   1. A list of logical operations are allowed, and they are assumed to be joint by `OR`. For example, `['gopro AND (11 or 12)', 'DJI AND OSMO']` searches for either a gopro version 11 or 12, or a DJI OSMO camera.
   2. You can construct very complex logical operations using `AND`, `OR` and `NOT`, but it is usually recommended to use simple keyword-based filtering and let AI handle more subtle selection criteria.

Multi-Location and Region Search
================================

`search_city` is the name, sometimes numbers, used by Facebook marketplace to represent a city. To get the value of `search_city` for your region, visit facebook marketplace, perform a search, and the city should be the name after `marketplace` (e.g. `XXXXX` in a URL like `https://www.facebook.com/marketplace/XXXXX/search?query=YYYY`).

Multiple Cities
---------------

Multiple searches will be performed if multiple cities are provided to option `search_city`. You can also specify `seller_locations` to limit the location of sellers. These locations are names of cities as displayed on the listing pages.

.. code-block:: toml

    [item.name]
    search_city = ['city1', 'city2']
    seller_locations = ['city1', 'city2', 'city3', 'city4']

You can also increase the radius of search using:

.. code-block:: toml

    [item.name]
    search_city = ['city1', 'city2']
    radius = 50

Pre-defined Regions
------------------

However, if you would like to search for a larger region (e.g. the USA), it is much easier to define `region`s with a list of `search_city` and large `radius`.

_ai-marketplace-monitor_ defines the following regions in its system:

- `usa` for USA (without AK or HI), with currency `USD`
- `usa_full` for USA, with currency `USD`
- `can` for Canada, with currency `CAD`
- `mex` for Mexico, with currency `MXN`
- `bra` for Brazil, with currency `BRL`
- `arg` for Argentina, with currency `ARS`
- `aus` for Australia, with currency `AUD`
- `aus_miles` for Australia using 500 miles radius, with currency `AUD`
- `nzl` for New Zealand, with currency `NZD`
- `ind` for India, with currency `INR`
- `gbr` for United Kingdom, with currency `GBP`
- `fra` for France, with currency `EUR`
- `spa` for Spain, with currency `EUR`

Now, if you would like to search an item across the US, you can:

.. code-block:: toml

    [item.name]
    search_region = 'usa'
    seller_locations = []
    delivery_method = 'shipping'

Under the hood, _ai-marketplace-monitor_ will simply replace `search_region` with corresponding pre-defined `search_city`, `radius`, and `currency`. Note that `seller_locations` does not make sense and need to be set to empty for region-based search, and it makes sense to limit the search to listings that offer shipping.

Multi-Currency Support
======================

_AI Marketplace Monitor_ does not enforce any specific currency format for price filters. It assumes that the `min_price` and `max_price` values are provided in the currency commonly used in the specified `search_city`. For example, in the configurations below:

.. code-block:: toml

    [item.item1]
    min_price = 100
    search_city = 'newyork' # for demonstration only, city name for newyork might differ

.. code-block:: toml

    [item.item1]
    min_price = 100
    search_city = 'paris' # for demonstration only, city name for paris might differ

The `min_price` is interpreted as 100 `USD` for New York and 100 `EUR` for Paris, based on the typical local currency of each city.

Explicit Currency Configuration
------------------------------

If you perform a search across cities that use different currencies, you can explicitly define the currencies using the `currency` option:

.. code-block:: toml

    [item.item1]
    min_price = '100 USD'
    search_city = ['paris', 'newyork']
    currency = ['EUR', 'USD']

In this example, the system will perform two searches and convert the `min_price` of `100` `USD` into the equivalent amount in `EUR` when searching `item1` around Paris, using historical exchange rates provided by the Currency Converter package.

All pre-defined regions has a defined `currency`. If you would like to search across regions with different currencies, you can:

.. code-block:: toml

    [item.item1]
    min_price = '100 EUR'
    search_region = ['fra', 'gbr']

and _AI Marketplace Monitor_ will automatically convert `100 EUR` to `GBP` when searching United Kingdom.

.. note::
   1. The following currency codes are supported: `USD`, `JPY`, `BGN`, `CYP`, `EUR`, `CZK`, `DKK`, `EEK`, `GBP`, `HUF`, `LTL`, `LVL`, `MTL`, `PLN`, `ROL`, `RON`, `SEK`, `SIT`, `SKK`, `CHF`, `ISK`, `NOK`, `HRK`, `RUB`, `TRL`, `TRY`, `AUD`, `BRL`, `CAD`, `CNY`, `HKD`, `IDR`, `ILS`, `INR`, `KRW`, `MXN`, `MYR`, `NZD`, `PHP`, `SGD`, `THB`, `ZAR`, and `ARS`.
   2. Currency conversion only occurs if currencies are explicitly defined and differ between cities or from the currency used in `min_price`/`max_price`.
   3. Conversion rates are intended for basic filtering and may not reflect real-time market values.

Self-hosted AI with Ollama
==========================

If you have access to a decent machine and prefer not to pay for AI services from OpenAI or other vendors, you can opt to install Ollama locally and access it using the `provider = "ollama"`. If you have ollama on your local host, you can use:

.. code-block:: toml

    [ai.ollama]
    base_url = "http://localhost:11434/v1"
    model = "deepseek-r1:14b"
    timeout = 120

.. note::
   1. Depending on your hardware configuration, you can choose any of the models listed at `ollama.com/library <https://ollama.com/library>`_. The default model is `deepseek-r1:14b` because it appears to work better than `llama-3.1:8b`.
   2. You need to `pull` the model before you can use it.

Anonymous Search with Proxy
===========================

You can search Facebook Marketplace anonymously by disabling login:

- Do not provide a `username` or `password` in the `facebook` section
- (optional) Set `login_wait_time = 0` to stop waiting for login
- (optional) Use the `--headless` command line option to run `ai-marketplace-monitor` without a browser window.

Proxy Configuration
-------------------

If you would like to use a proxy server, you can:

- Sign up for a VPN or proxy service.
- Configure the proxy settings in the `monitor` section of your configuration file as follows:

.. code-block:: toml

    [monitor]
    proxy_server = '${PROXY_SERVER}'
    proxy_username = '${PROXY_USERNAME}'
    proxy_password = '${PROXY_PASSWORD}'

Replace `${PROXY_SERVER}`, `${PROXY_USERNAME}`, and `${PROXY_PASSWORD}` with your proxy service details, or setting the corresponding environment variables.
