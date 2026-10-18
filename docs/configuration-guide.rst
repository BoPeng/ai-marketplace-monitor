===================
Configuration Guide
===================

This section covers advanced configuration options and setup procedures for AI Marketplace Monitor.

Choosing Your Services
======================

AIMM searches Facebook Marketplace, which needs a Facebook account for AIMM to log in with (``FACEBOOK_USERNAME`` and ``FACEBOOK_PASSWORD``) and a browser that AIMM controls (installed with ``playwright install``), and OfferUp (US only), which needs neither. To rate listings and to tell you about them, it uses three kinds of external service, each set up in one of three ways:

.. list-table::
   :header-rows: 1
   :widths: 16 28 28 28

   * - Service
     - With UnitySVC
     - UnitySVC with your own keys (BYOK)
     - Without UnitySVC
   * - **AI** that rates listings
     - ``[ai.unitysvc]``: UnitySVC's model pool, paid per use
     - ``[ai.unitysvc]`` with an OpenAI, Anthropic or other provider's service and your key for it saved in UnitySVC; the provider bills you
     - ``[ai.openai]``, ``[ai.anthropic]``, ``[ai.gemini]``, ``[ai.deepseek]``, or a local model with ``[ai.ollama]``
   * - **Email** with listing photos and the daily digest
     - ``[email.unitysvc]`` with ``smtp-to-mailbox``: free, to the address of your UnitySVC account
     - ``[email.unitysvc]`` with ``smtp-relay``: free; UnitySVC's SMTP Relay forwards it to your own SMTP server (Gmail, your mail provider, ...), whose address and login you save in UnitySVC, and on to the addresses you choose
     - ``[email.gmail]`` with a Gmail app password, or any other SMTP server
   * - **Phone and chat alerts**
     - ``[notification.unitysvc]``: free, but only to your inbox on the UnitySVC website, which is of little use on its own
     - the same section, forwarded to your own Discord, Slack, Telegram, Pushover, SMS or other account (100+ services), its token saved in UnitySVC
     - ``[notification.telegram]``, Pushbullet, Pushover or ntfy, with their tokens in your configuration

Each service is set up on its own, so you can mix the options. The sections below follow the same order: UnitySVC first, then your own keys through UnitySVC, then the options without UnitySVC.

Why UnitySVC
============

AIMM has adopted `UnitySVC <https://unitysvc.com/>`_, a gateway that reaches AI models, email, phone and chat notifications and other online services through one API key (``UNITYSVC_API_KEY``). UnitySVC is run by the maintainer of AIMM. We recommend it because:

- **AIMM no longer has to integrate every provider.** Instead of carrying the code, settings and dependencies of each AI provider and notification service, AIMM talks to one gateway. New models and the 100+ notification services UnitySVC reaches become available to AIMM without a new version of AIMM.
- **Deploying AIMM is simpler.** A Docker or app-store installation needs a single secret to rate listings, email them with their photos and alert your phone.
- **Your credentials stay in one place.** The keys of your own accounts, such as an OpenAI key, a Telegram bot token or an SMTP password, are saved once in your UnitySVC account instead of in AIMM's configuration file or environment. They are not copied to every machine that runs AIMM, and you can change or revoke one without touching AIMM. The services you set up are not tied to AIMM either: your own scripts, apps and other tools can use them with the same key, through UnitySVC's API, command-line tool or SDK.
- **You can keep the accounts you already have.** With your own keys (BYOK), UnitySVC forwards each request to your account, and that provider bills you as before. The email and notification services AIMM uses by default are free, and UnitySVC's own AI is paid per use.

AIMM continues to support the services it already integrates without UnitySVC: OpenAI, Anthropic, Gemini, DeepSeek and a local Ollama for AI, any SMTP server for email, and Telegram, Pushbullet, Pushover and ntfy for notifications. New AI providers and notification channels are reached through UnitySVC instead of being added to AIMM.

Setting Up AI
=============

.. list-table::
   :header-rows: 1
   :widths: 16 28 28 28

   * - Service
     - With UnitySVC
     - UnitySVC with your own keys (BYOK)
     - Without UnitySVC
   * - **AI** that rates listings
     - ``[ai.unitysvc]``: UnitySVC's model pool, paid per use
     - ``[ai.unitysvc]`` with an OpenAI, Anthropic or other provider's service and your key for it saved in UnitySVC; the provider bills you
     - ``[ai.openai]``, ``[ai.anthropic]``, ``[ai.gemini]``, ``[ai.deepseek]``, or a local model with ``[ai.ollama]``

With UnitySVC
-------------

``[ai.unitysvc]`` uses UnitySVC's ``llm`` model pool, paid per use. Its default ``balanced`` tier is relatively inexpensive and reads listing photos:

.. code-block:: toml

    [ai.unitysvc]
    api_key = '${UNITYSVC_API_KEY}'

``aimm configure ai`` lists the models and tiers your key can use. See `AI Services <https://ai-marketplace-monitor.readthedocs.io/en/latest/configuration.html#ai-services>`_ for every option.

UnitySVC with your own keys (BYOK)
----------------------------------

Save your provider's key once as a secret in your UnitySVC account (Developer → Secrets, e.g. ``OPENAI_API_KEY`` or ``ANTHROPIC_API_KEY``), and point ``base_url`` at that provider's service in the `UnitySVC catalog <https://unitysvc.com/market>`_. Your provider bills you directly, and AIMM's configuration still holds only ``UNITYSVC_API_KEY``:

.. code-block:: toml

    [ai.unitysvc]
    api_key = '${UNITYSVC_API_KEY}'
    base_url = 'https://api.svcpass.com/<service path>'
    model = '<model name>'

Without UnitySVC
----------------

``[ai.openai]``, ``[ai.anthropic]``, ``[ai.gemini]`` and ``[ai.deepseek]`` each need an API key from that provider:

.. code-block:: toml

    [ai.openai]
    api_key = '${OPENAI_API_KEY}'

Self-hosted AI with Ollama
~~~~~~~~~~~~~~~~~~~~~~~~~~

If you have access to a decent machine and prefer not to pay for AI services from OpenAI or other vendors, you can opt to install Ollama locally and access it using the `provider = "ollama"`. If you have ollama on your local host, you can use:

.. code-block:: toml

    [ai.ollama]
    base_url = "http://localhost:11434/v1"
    model = "deepseek-r1:14b"
    timeout = 120 # specified in seconds

.. note::
   1. Depending on your hardware configuration, you can choose any of the models listed at `ollama.com/library <https://ollama.com/library>`_. The default model is `deepseek-r1:14b` because it appears to work better than `llama-3.1:8b`.
   2. You need to `pull` the model before you can use it.

Setting Up Email Notifications
==============================

.. list-table::
   :header-rows: 1
   :widths: 16 28 28 28

   * - Service
     - With UnitySVC
     - UnitySVC with your own keys (BYOK)
     - Without UnitySVC
   * - **Email** with listing photos and the daily digest
     - ``[email.unitysvc]`` with ``smtp-to-mailbox``: free, to the address of your UnitySVC account
     - ``[email.unitysvc]`` with ``smtp-relay``: free; UnitySVC's SMTP Relay forwards it to your own SMTP server (Gmail, your mail provider, ...), whose address and login you save in UnitySVC, and on to the addresses you choose
     - ``[email.gmail]`` with a Gmail app password, or any other SMTP server

AIMM's email (all new listings in one message, with their photos) is sent by an ``[email.NAME]`` section, to the ``email`` of each user who receives it. You can configure multiple users with individual or multiple email addresses like this:

.. code-block:: toml

    [user.user1]
    email = 'user1@gmail.com'

    [user.user2]
    email = ['user2@gmail.com', 'user2@outlook.com']

.. _unitysvc-smtp:

With UnitySVC
-------------

``[email.unitysvc]`` sends email through UnitySVC's SMTP gateway with your ``UNITYSVC_API_KEY``, without the app password Gmail needs, which many users find hard to create:

.. code-block:: toml

    [email.unitysvc]
    smtp_username = 'smtp-to-mailbox'

    [user.me]
    notify_with = 'email.unitysvc'

``[email.unitysvc]`` is a preset: AIMM fills in the server (``smtp.svcpass.com``), the port (587) and the password ``${UNITYSVC_API_KEY}``, and ``email`` is not needed. ``smtp_username`` names the UnitySVC service that delivers the email: ``smtp-to-mailbox`` sends it to the email address registered and verified on your UnitySVC account (Settings → Account), which is usually your own Gmail anyway. The email is the same HTML email with listing images.

Notes on the UnitySVC services:

- ``smtp_username = 'smtp-to-mailbox'`` skips the inbox and emails your **UnitySVC-registered address** directly, free of charge, keeping the HTML body and listing images. That is the verified primary email under Settings → Account on UnitySVC, not the address in ``email``: make sure it is set and verified.
- ``smtp_username = 'notify'`` delivers to your UnitySVC inbox and your saved notification destination, as the HTTP ``notify`` service does. To receive these notifications by email, your notification destination on UnitySVC must include ``smtp-to-mailbox``: set it as the destination, or add it to a broadcast used as the destination.
- ``smtp_username = 'b/<broadcast name>'`` sends each email to every target of a UnitySVC broadcast (up to 10), for example ``smtp-to-mailbox`` plus several SMTP Relay servers (see below).
- ``smtp_username`` can also be any other service that accepts the SMTP gateway (use the SMTP username shown on its catalog page), or ``a/<alias>`` for one of your aliases. For services that deliver to the ``To`` address, set ``email``.
- Who receives the email depends on the service: ``smtp-to-mailbox`` sends it to your registered address, ``notify`` to your saved notification destination, and the SMTP Relay (``smtp-relay``, below) to the ``email`` of each user who receives the section. ``email`` is optional for the first two, where it only fills the ``To`` header, and required for the relay.

UnitySVC with your own SMTP account (BYOK)
------------------------------------------

UnitySVC's SMTP Relay forwards the email to your own SMTP server: Gmail, your domain's mail service (such as Zoho or Outlook), or a mail provider such as SendGrid or Amazon SES. It sends the email to the ``email`` of each user who receives the section, and your server's login stays in UnitySVC instead of AIMM's configuration. Save the server's details as secrets in your UnitySVC account: ``SMTP_RELAY_HOST`` (e.g. ``smtp.gmail.com``), ``SMTP_RELAY_USERNAME`` (usually your address) and ``SMTP_RELAY_PASSWORD`` (an app password or API key), and if they differ from 587 and STARTTLS, ``SMTP_RELAY_PORT`` and ``SMTP_RELAY_TLS``. Then set ``smtp_username = 'smtp-relay'``, the relay's free channel:

.. code-block:: toml

    [email.unitysvc]
    smtp_username = 'smtp-relay'

    [user.me]
    email = 'me@example.com'

To relay through several SMTP servers at once, enroll the SMTP Relay once per server (its paid ``plus`` channel), put the enrollments in a UnitySVC broadcast, and set ``smtp_username = 'b/<broadcast name>'``: the gateway sends each email through every server.

Without UnitySVC
----------------

Gmail
~~~~~

``[email.gmail]`` is a preset too: AIMM fills in the server (``smtp.gmail.com``), the port (587) and the password ``${GMAIL_SMTP_PASSWORD}``. Set your Gmail address as ``smtp_username``, and a Gmail app password as the environment variable ``GMAIL_SMTP_PASSWORD``:

.. code-block:: toml

    [email.gmail]
    smtp_username = 'myemail@gmail.com'

    [user.me]
    email = 'myemail@gmail.com'

Other email providers
~~~~~~~~~~~~~~~~~~~~~

Any other ``[email.NAME]`` section is a plain SMTP account, with the ``smtp_server``, ``smtp_port``, ``smtp_username`` and ``smtp_password`` of your email service provider:

.. code-block:: toml

    [email.myprovider]
    smtp_username = 'username@EMAIL.COM' # default to email
    smtp_server = 'smtp.EMAIL.COM'       # default to smtp.EMAIL.COM
    smtp_port = 587                      # default for most providers
    smtp_password = '${MYPROVIDER_PASSWORD}'

`ai-marketplace-monitor` will try to use `email` if `smtp_username` is unspecified, and determine `smtp_server` automatically from the sender email address.

Daily digest
------------

``digest_at`` on an email section (a local time such as ``'08:00'``) sends, every day at that time, the full digest of the last 24 hours: matches, rejected listings and an AI summary of each item. A ``[notification.*]`` section can send a short digest too, but next to an email digest it is rarely wanted.

.. code-block:: toml

    [email.unitysvc]
    smtp_username = 'smtp-to-mailbox'
    digest_at = '08:00'

.. note::
   - **Gmail Users**: You will need to create a separate app password for your Google account as `smtp_password`.
   - **Commercial Users**: If you are a subscriber to our Pro or Business Plans, detailed instructions on configuring the SMTP service we provide will be sent to you via email.

Setting Up Phone and Chat Notifications
=======================================

.. list-table::
   :header-rows: 1
   :widths: 16 28 28 28

   * - Service
     - With UnitySVC
     - UnitySVC with your own keys (BYOK)
     - Without UnitySVC
   * - **Phone and chat alerts**
     - ``[notification.unitysvc]``: free, but only to your inbox on the UnitySVC website, which is of little use on its own
     - the same section, forwarded to your own Discord, Slack, Telegram, Pushover, SMS or other account (100+ services), its token saved in UnitySVC
     - ``[notification.telegram]``, Pushbullet, Pushover or ntfy, with their tokens in your configuration

With UnitySVC
-------------

UnitySVC notifications reach more than 100 notification channels and apps: chat apps (Slack, Discord, Microsoft Teams, Telegram, WhatsApp, Matrix, ...), phone push (Pushover, ntfy, Pushbullet, Bark, ...), SMS (Twilio, Vonage, Plivo, ...), email (SendGrid, Mailgun, Amazon SES, SMTP, ...), and incident tools (PagerDuty, Opsgenie, ...).

These notifications are short text messages without listing photos, best for phone and chat alerts. To receive AIMM's full email, with all new listings and their photos in one message, use :ref:`UnitySVC email <unitysvc-smtp>` instead.

By default, messages go to UnitySVC's ``notify`` service, which shows them in your inbox on the UnitySVC website and forwards them to every destination set in your UnitySVC notification preferences. No enrollment is needed, so you can change where notifications go on UnitySVC without touching your AIMM config.

A configuration that uses UnitySVC for both the AI and the notifications:

.. code-block:: toml

    [ai.unitysvc]
    api_key = '${UNITYSVC_API_KEY}'

    [notification.unitysvc]
    unitysvc_api_key = '${UNITYSVC_API_KEY}'

    [user.me]
    notify_with = 'notification.unitysvc'

.. note::
   - The ``notify`` service delivers plain text only: the inbox stores plain text and forwarded copies are sent as text. Keep the default ``message_format = 'plain_text'`` with ``notify``; ``markdown`` or ``html`` take effect only with a specific service such as ``labs/msg-to-discord``.

UnitySVC with your own accounts (BYOK)
--------------------------------------

Without a destination of your own, ``notify`` only puts the messages in your inbox on the UnitySVC website, so this is the setup to use. Choose your own account as the notification destination in UnitySVC, for example your Discord, Slack, Telegram or Pushover, with its token saved as a secret in your UnitySVC account. AIMM's configuration still holds only ``UNITYSVC_API_KEY``, and you can change the destination on UnitySVC at any time without touching it.

To send to one specific UnitySVC service instead, set ``unitysvc_service`` to its path. Such a message skips the inbox.

.. code-block:: toml

    [notification.discord]
    unitysvc_api_key = '${UNITYSVC_API_KEY}'
    unitysvc_service = 'labs/msg-to-discord'
    message_format = 'markdown'

The channels AIMM supports without UnitySVC each have a UnitySVC counterpart. Save your account's secrets in UnitySVC, then either add the service as a destination in your notification preferences (and keep ``notify``), or send to it directly with ``unitysvc_service``:

.. list-table::
   :header-rows: 1

   * - Instead of
     - UnitySVC service
     - Secrets to save in UnitySVC
     - ``unitysvc_service``
   * - Telegram
     - ``labs/msg-to-telegram``
     - ``TELEGRAM_BOT_TOKEN``, ``TELEGRAM_CHAT_ID``
     - ``labs/msg-to-telegram``
   * - ntfy
     - ``labs/msg-to-ntfy``
     - ``NTFY_TOPIC``, and ``_NTFY_BASE`` for your own ntfy server
     - ``labs/msg-to-ntfy``
   * - Pushover
     - ``labs/msg-to-pushover``
     - ``PUSHOVER_TOKEN``, ``PUSHOVER_USER_KEY``; then enroll in the service once
     - ``e/<enrollment code>``
   * - Pushbullet
     - ``labs/msg-to-pushbullet``
     - ``PUSHBULLET_ACCESSTOKEN``; then enroll in the service once
     - ``e/<enrollment code>``

To send each alert to several of your accounts at once, for example Discord, Telegram and SMS, set them all as destinations in your UnitySVC notification preferences, or create a UnitySVC **broadcast** with up to 10 targets. You can save the broadcast as your notification destination and keep the default ``notify`` service, or send to it directly:

.. code-block:: toml

    [notification.everywhere]
    unitysvc_api_key = '${UNITYSVC_API_KEY}'
    unitysvc_service = 'b/my-alerts'

Without UnitySVC
----------------

Each of these channels needs its own account. Its token goes in the ``[notification.*]`` section, preferably as an environment variable reference, and where the user receives it (a user key or chat ID) goes on the user.

Pushover
~~~~~~~~

To enable PushOver notifications, follow these steps:

1. **Install the PushOver app** on your mobile device.
2. **Create a PushOver account** at `pushover.net <https://pushover.net>`_. After registration, you will find your **User Key** labeled as `Your User Key` — this is your `pushover_user_key`.
3. **Create a new application** (you can name it `AIMarketplaceMonitor`). After creation, you will receive an **API Token/Key**, referred to as `pushover_api_token`.

Configuration Options
^^^^^^^^^^^^^^^^^^^^^

Once you have both the user key and API token, add them to your configuration file: the API token in a notification section, the user key on the user who receives it.

.. code-block:: toml

    [notification.pushover]
    pushover_api_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

    [user.me]
    pushover_user_key = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    notify_with = 'notification.pushover'

Description Settings
^^^^^^^^^^^^^^^^^^^^

By default, notifications include the **title**, **price**, **location**, **description**, and **AI-generated comments** (if enabled). To exclude or limit the length of the **listing description**, you can add the `with_description` option to your config.

You can set `with_description` to:

- `true` — to include the **full description**.
- `false` — to exclude the description (default behavior).
- A **number** — to include only the **first N characters** of the description.

For example:

.. code-block:: toml

    [notification.pushover]
    pushover_api_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    with_description = 100

This will include up to the first 100 characters of each listing's description in your notifications.

Telegram
~~~~~~~~

To enable Telegram notifications, you'll need to create a Telegram bot and obtain a chat ID.

Step 1: Create a Telegram Bot
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

1. **Open Telegram** and search for `@BotFather` (the official bot for creating other bots).
2. **Start a conversation** with BotFather by clicking "Start" or sending `/start`.
3. **Create a new bot** by sending the command `/newbot`.
4. **Choose a bot name** when prompted (e.g., "AI Marketplace Monitor").
5. **Choose a bot username** that ends with "bot" (e.g., "my_marketplace_monitor_bot").
6. **Save your bot token** - BotFather will provide a token that looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`. **Keep this token secure and never share it publicly.**

Step 2: Get Your Chat ID
^^^^^^^^^^^^^^^^^^^^^^^^

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
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Add the bot token to a notification section, and your chat ID to the user who receives it. Environment variables keep the token out of the file:

.. code-block:: toml

    [notification.telegram]
    telegram_token = '${TELEGRAM_BOT_TOKEN}'

    [user.me]
    telegram_chat_id = '${TELEGRAM_CHAT_ID}'
    notify_with = 'notification.telegram'

Then set the environment variables:

.. code-block:: bash

    export TELEGRAM_BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    export TELEGRAM_CHAT_ID="123456789"

Telegram Troubleshooting
^^^^^^^^^^^^^^^^^^^^^^^^

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

When AI services are used, the program by default notifies you of listings with a rating of 4 (good match) or higher. You can change this behavior by setting for example:

.. code-block:: toml

    rating = 3

to also see poor matches, or ``rating = 5`` to see only great deals. Note that all listings after non-AI-based filtering will be returned if no AI service is specified or non-functional.

Seller Information
------------------

Who sells a listing matters as much as the listing: new accounts, dealers posing as private sellers, sellers with many listings but few sales, single listings at an unrealistic price, and sellers with poor ratings are often unreliable. AIMM therefore tells the AI about the seller of each listing it rates, and lets the AI judge whether the seller is legitimate.

From the listing page, AIMM reads the seller's name, the year they joined Facebook and, for sellers with ratings, their rating and number of ratings. For listings that pass your other filters, it also opens the seller's Marketplace profile, at most once a month per seller, for the number of active and sold listings, what buyers appreciate, and a few recent reviews. The AI receives a summary such as

    joined Facebook in 2024, no ratings, 20+ active listings, 1 sold listing

along with possible warning signs (a new account, a low rating, a dealer-like number of listings, few or no sales, a single listing on a new account) and the reviews, which may mention no-shows or sellers who stopped answering. The AI is told that the seller matters as much as the item, and to judge the seller from all of this together rather than from any one sign: a new account with many listings and none sold may be a moving sale, and a dealer with dozens of listings may be reputable. It rates a listing from a likely scammer no higher than 2 however well the item matches, lowers its rating for an unreliable or unverified seller, and says what it concluded about the seller in its comment. If the seller's profile could not be read, the AI is told that the seller is not verified, and the log says so.

The AI is also told to rate a listing 1 when it has a bait price: a price far below the item's market value together with "financing available", "payment plans", "no credit check", "rent to own" or "layaway", which means that the listed price is only a down payment or a monthly payment. Financing or layaway at a realistic price usually means a pawnshop or a dealer, which the AI points out and rates lower. To skip such listings without asking the AI, add the phrases to ``antikeywords``, for example ``antikeywords = ["financing available", "no credit check", "layaway"]``.

Every notification has a ``Seller`` line with what AIMM knows about the seller, when it read the seller's profile, and the warning signs, for example

    Seller: Sam Roe: joined Facebook in 2024, no ratings, 30 active listings, 0 sold listings, profile checked 2026-10-01. Warning signs: 30 active listings but none sold

It says ``not verified`` when the profile could not be read, or when there is no seller information at all (for example when AIMM is not logged in), so that a seller who was never checked is not mistaken for one who was checked and found fine.

To skip low-rated sellers altogether, set ``seller_min_rating`` in a ``marketplace`` or an ``item`` section:

.. code-block:: toml

    # skip sellers rated below 4 out of 5 by at least 3 buyers
    seller_min_rating = 4

Sellers without ratings are not skipped: most Marketplace sellers have none, and having no ratings says little on its own. The AI still sees "no ratings" in the summary, next to the account's age, listings, sales and reviews, and weighs it with them. ``exclude_sellers`` still excludes sellers by name. Seller information needs AIMM to be logged in to Facebook, which shows no seller details otherwise.

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

Matching the Title Only
-----------------------

``keywords`` and ``antikeywords`` match the title and the description, but Facebook's search
results show only the title. *AI Marketplace Monitor* therefore opens each listing to read its
description before it can apply ``keywords``. ``title_keywords`` takes the same values as
``keywords`` but matches the title only, so listings without them are skipped before they are
opened. This makes searches faster and opens fewer pages on Facebook:

.. code-block:: toml

    title_keywords = ['drone', 'DJI']
    keywords = 'drone AND (DJI OR Orqa)'

keeps listings with ``drone`` or ``DJI`` in the title, opens them, and then applies
``keywords`` to their title and description.

.. warning::
   Many sellers write very short titles, such as "Bike" or "Camera lens", and put the brand and
   model in the description only. ``title_keywords`` drops these listings without reading their
   description, so use it only for words that nearly every matching listing has in its title.

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

`search_city` takes a different value for each marketplace:

- **Facebook Marketplace**: the name, sometimes numbers, that Facebook uses for a city. To find it, search on Facebook Marketplace: it is the part after `marketplace` in the URL (e.g. `XXXXX` in `https://www.facebook.com/marketplace/XXXXX/search?query=YYYY`).
- **OfferUp**: a five-digit US ZIP code, such as `77002`, or a `"latitude,longitude"` pair, such as `"29.7604,-95.3698"`. A Facebook city code does not work for OfferUp.

To search the same place in both marketplaces, give a table of values by marketplace type, such as `search_city = { facebook = "houston", offerup = "77002" }`.

The **Assistant** (in the web UI, or ``aimm configure``) finds it for you: tell it a city, neighborhood or ZIP code (for example ``Houston, TX``, ``Los Angeles, Texas`` or ``92101``). AIMM asks Facebook Marketplace's location search, as Facebook's location dialog does, and shows the matching places with their codes (``houston``; ``487995858630733`` for Los Angeles, La Salle County, Texas; ``sandiego`` for 92101). No browser or Facebook account is involved, and nothing is changed on your account.

Multiple Cities
---------------

Multiple searches will be performed if multiple cities are provided to option `search_city`. You can also specify `seller_locations` to limit the location of sellers. These locations are names of cities as displayed on the listing pages.

.. code-block:: toml

    [item.name]
    search_city = ['city1', 'city2']
    seller_locations = ['city1', 'city2', 'city3', 'city4']

You can also change the radius of search using:

.. code-block:: toml

    [item.name]
    search_city = ['city1', 'city2']
    radius = 50

Search Radius
~~~~~~~~~~~~~

Facebook ignores a radius in the search URL and searches with the radius saved in your account's Marketplace location settings, which only its location dialog changes. When ``radius`` is set, AIMM therefore sets it in that dialog before searching a city, if the saved radius is different, and reloads the search:

- ``radius`` is in the unit Facebook shows: miles in the US, kilometers elsewhere.
- Facebook offers 1, 2, 5, 10, 20, 40, 60, 80, 100, 250 and 500, and AIMM picks the choice closest to ``radius`` (``radius = 50`` becomes 60, ``radius = 805`` becomes 500).
- The radius is saved on your Facebook account, so it also applies when you browse Marketplace yourself. Without ``radius``, AIMM searches with whatever radius the account has.
- The city comes from ``search_city`` in the URL, which Facebook does follow.

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

*AI Marketplace Monitor* does not enforce any specific currency format for price filters. It assumes that the `min_price` and `max_price` values are provided in the currency commonly used in the specified `search_city`. For example, in the configurations below:

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

and *AI Marketplace Monitor* will automatically convert `100 EUR` to `GBP` when searching United Kingdom.

.. note::
   1. The following currency codes are supported: `USD`, `JPY`, `BGN`, `CYP`, `EUR`, `CZK`, `DKK`, `EEK`, `GBP`, `HUF`, `LTL`, `LVL`, `MTL`, `PLN`, `ROL`, `RON`, `SEK`, `SIT`, `SKK`, `CHF`, `ISK`, `NOK`, `HRK`, `RUB`, `TRL`, `TRY`, `AUD`, `BRL`, `CAD`, `CNY`, `HKD`, `IDR`, `ILS`, `INR`, `KRW`, `MXN`, `MYR`, `NZD`, `PHP`, `SGD`, `THB`, `ZAR`, and `ARS`.
   2. Currency conversion only occurs if currencies are explicitly defined and differ between cities or from the currency used in `min_price`/`max_price`.
   3. Conversion rates are intended for basic filtering and may not reflect real-time market values.

Updates and Proxy
=================

Update Reminder
---------------

When the monitor starts, AIMM asks PyPI whether a newer release is out (at most once a day, so
frequent restarts do not ask again). If so, it logs a line such as::

    [UPDATE] AI Marketplace Monitor 0.11.0 is available (you have 0.10.3). Upgrade with: pip install --upgrade ai-marketplace-monitor

and the web UI shows an "AIMM 0.11.0 available" badge in its header, linking to the changelog.
The upgrade command matches how AIMM was installed (pip, pipx, ``uv tool`` or Docker). The
request sends nothing about you or your config, and a failed check is silently retried at the
next start. To check at any time, click **Check for updates** in the web UI's Settings › About,
which asks PyPI right away. To turn off the check at start, add this to your config, or set the
environment variable ``AIMM_NO_UPDATE_CHECK=1`` (the button still works):

.. code-block:: toml

    [monitor]
    check_updates = false

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



Multiple Marketplaces
=====================

AIMM supports two marketplaces, Facebook Marketplace and OfferUp, and you can create several sections of each, such as ``marketplace.city1`` and ``marketplace.city2``, with different options such as ``search_city``, ``search_region``, ``seller_locations``, and ``notify``. An item is searched in every marketplace section unless its ``marketplace`` option names the ones to use.

For example:

.. code-block:: toml

    [marketplace.facebook]
    search_city = 'houston'
    seller_locations = ['houston', 'sugarland']

    [marketplace.nationwide]
    market_type = 'facebook'
    search_region = 'usa'
    seller_locations = []
    delivery_method = 'shipping'

    [marketplace.offerup]
    search_city = '77002'   # a US ZIP code
    radius = 30

    [item.default_item]
    marketplace = 'facebook'
    search_phrases = 'local item, searched only in "facebook"'

    [item.rare_item1]
    marketplace = 'nationwide'
    search_phrases = 'rare item1'

    [item.rare_item2]
    marketplace = 'nationwide'
    search_phrases = 'rare item2'

    [item.bike]
    marketplace = ['facebook', 'offerup']
    search_phrases = 'road bike, searched around Houston in both marketplaces'

.. note::
   - An item without ``marketplace`` is searched in every marketplace section, including ones you add later. ``marketplace`` keeps it to one section, or to a list of them (``marketplace = ['facebook', 'nationwide']``).
   - An item searched in several sections uses each section's location, so it cannot set its own ``search_city``, ``search_region``, ``radius``, ``city_name`` or ``currency``.
   - A section's type comes from ``market_type``; without it, from its name if that names a marketplace (``facebook``, ``offerup``), and otherwise it is a Facebook marketplace. ``nationwide`` above is a Facebook marketplace with a different location and options.

First and Subsequent Searches
=============================

You can specify a list of two values for the options ``rating``, ``availability``, ``date_listed``, and ``delivery_method``. The first value is used for the initial search, and the second value is used for all subsequent searches. This allows different search strategies for first-time versus ongoing monitoring.

For example, to perform an initial lenient search for all listings followed by searches for only new listings:

.. code-block:: toml

    rating = [2, 4]
    availability = ["all", "in"]
    date_listed = ["all", "last 24 hours"]


Support for Non-English Languages
===================================

*AI Marketplace Monitor* relies on specific keywords from webpages to extract relevant information. For example, it looks for words following ``Condition`` to determine the condition of an item. If your Facebook account is set to a non-English language, *AI Marketplace Monitor* will be unable to extract the relevant information. If you see error messages like:

.. code-block:: text

    Failed to get details of listing https://www.facebook.com/marketplace/item/12121212121212121212
    The listing might be missing key information (e.g. seller) or not in English.
    Please add option language to your marketplace configuration is the latter is the case.
    See https://github.com/BoPeng/ai-marketplace-monitor?tab=readme-ov-file#support-for-non-english-languages for details.

you will need to check the ``Settings -> Language`` settings of your Facebook account and configure *AI Marketplace Monitor* to use the same language.

Currently, *AI Marketplace Monitor* supports the following languages:

- ``es``: Spanish
- ``zh``: Chinese

Setting Up Custom Language Support
----------------------------------

If your language is not supported, you can define your own ``translator`` section in your configuration file, following the format used by existing translators in `config.toml <https://github.com/BoPeng/ai-marketplace-monitor/blob/main/src/ai_marketplace_monitor/config.toml>`_:

1. **Add a section to your configuration file**, by copying one example from the system translators, for example:

   .. code-block:: toml

       [translator.LAN]
       locale = "Your REGION"
       "About this vehicle" = "Descripción del vendedor"
       "Seller's description" = "Información sobre este vehículo"
       "Collection of Marketplace items" = "Colección de artículos de Marketplace"
       "Condition" = "Estado"
       "Details" = "Detalles"
       "Location is approximate" = "La ubicación es aproximada"
       "Description" = "Descripción"

2. **Find example listings** (see `example <https://github.com/BoPeng/ai-marketplace-monitor/issues/29#issuecomment-2632057196>`_), locate the relevant words in your language, and update the translation section. You can switch between different languages in Facebook (Settings -> Language) to compare with the English version.

3. **Add the language setting** to your marketplace configuration:

   .. code-block:: toml

       [marketplace.facebook]
       language = "LAN"

It would be very helpful for other users of *AI Marketplace Monitor* if you could contribute your dictionary to this project by creating a pull request or simply creating a ticket with your translations.
