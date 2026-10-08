===========
Usage Guide
===========

Basic Usage
-----------

Run the monitor with default configuration:

.. code-block:: console

    $ aimm

``aimm`` is the same as ``aimm run``. The longer ``ai-marketplace-monitor`` command provides
the same interface.

Run with a custom configuration file:

.. code-block:: console

    $ aimm run --config /path/to/your/config.toml

aimm always shows its browser window, because Facebook may ask you to complete a CAPTCHA or a
security code while logging in. To run aimm on a machine without a screen (a server or a NAS),
use the Docker image: it has a virtual display, and its web UI shows you the browser when you
need it.

Check Individual Listings
-------------------------

You can check why a listing was excluded or test a listing against your configuration:

.. code-block:: console

    $ aimm check https://facebook.com/marketplace/item/123456789

For specific item configurations:

.. code-block:: console

    $ aimm check https://facebook.com/marketplace/item/123456789 --for item_name

Cache Management
---------------

Clear different types of cache:

.. code-block:: console

    $ aimm admin --clear-cache listing-details
    $ aimm admin --clear-cache ai-inquiries
    $ aimm admin --clear-cache user-notification
    $ aimm admin --clear-cache counters
    $ aimm admin --clear-cache all

Important Notes
--------------

1. **Keep Terminal Running**: You need to keep the terminal running to allow the program to monitor continuously.

2. **Browser Interaction**: You will see a browser window open. You may need to manually:
   - Enter username/password if not specified in config
   - Complete CAPTCHA challenges
   - Click "OK" to save passwords

3. **Login Requirements**: If login fails, the monitor continues but Facebook may show limited results.

4. **Configuration Updates**: The program automatically detects config file changes and restarts searches.

Interactive Mode
---------------

While the monitor is running, you can:

- Press ``Esc`` to view current statistics
- Enter interactive mode to check individual URLs
- Type ``exit`` to leave interactive mode

* This feature requires the installation of `pynput` package, which can be installed separately or through

```bash
pip install 'ai-marketplace-monitor[pynput]'
```

You can disable this feature by define environment variable `DISABLE_PYNPUT=true` if `pynput` is already installed.

Interactive configuration
-------------------------

Run ``aimm configure`` as the primary interactive configuration command. It uses your
default AI service (the first ``[ai.*]`` section) to help you: tell it what you want in your
own words, for example "limit my Houston search to 20 miles", and it finds the section,
drafts the change and asks you to confirm before writing. If you have no usable AI service
yet, it starts with the AI setup, ``aimm configure ai``, which works without AI.

aimm uses the **first** ``[ai.*]`` section as your default AI, and the others only if it
fails. So the AI setup checks only the default and lists the others, then offers to keep or
update it (or fix it if the check failed), to make one of the other sections the default
(which moves it to the top of the file), or to create a new AI section, which becomes the
default. With no AI section yet, it goes straight to choosing a provider: UnitySVC
(recommended: one key covers AI and email notifications), OpenAI, Anthropic, or Ollama.
For UnitySVC and Ollama it also asks for the base URL (UnitySVC's default is
``https://api.svcpass.com/p/llm``; an alias such as ``https://api.svcpass.com/a/myllm`` works
too). Whenever the provider can list its models (the key is set), you choose the model from
that list.

When your default AI works, ``aimm configure ai`` lets that AI help instead: tell it what you
want ("use a cheaper model", "add Claude as a backup", "make the backup the default") and it does
what the menus above do, with the same checks. It tries a section before saving, offers the
models the provider lists, and writes a new section first (the new default) unless you want it as
a backup. A section only becomes the default if it works. The session keeps using the AI it
started with; changes take effect the next time aimm starts. The key's
environment variable must be set before an AI section is saved, because aimm cannot start with an
unset AI key. Without a working AI, ``aimm configure ai`` runs the menus.

Use ``aimm configure ai.NAME`` to work on one section. A section named after a provider
uses that provider, so ``aimm configure ai.openai`` sets up ``[ai.openai]`` without asking
which AI; an existing section keeps its own provider. To use two keys for the same
provider, give the second section another name, such as ``aimm configure ai.openai2``,
which asks for the provider once and writes it as ``provider = "openai"``.

For hosted providers, the command writes the API key as an environment-variable
reference such as ``${UNITYSVC_API_KEY}``; the key itself is never written to the config
file. Every write shows the proposed TOML first, asks for confirmation, and keeps a
backup in ``~/.ai-marketplace-monitor/backups/``.

Use ``--config`` or ``--config-file`` to read and update a specific config file.

Marketplaces
~~~~~~~~~~~~

``aimm configure marketplace`` sets up where and how to search Facebook Marketplace with
the help of your default AI service (the AI setup runs first if it cannot be used). It lists your
existing marketplaces, each with its ``request`` (a short summary of what you asked for)
and its settings, and asks whether to update one or create a new one;
``aimm configure marketplace.NAME`` goes straight to one section.

The AI then leads a short conversation. You answer in your own words, for example:

.. code-block:: text

    I'm in Austin, Texas and will drive about 30 miles. Only local pickup, used things in
    good condition or better. Checking every hour is fine.

It works out what is still needed (a location is required), asks about what is likely
to matter to you, fills in the section, and decides from your answers when you are done.
The AI acts only through tools that aimm provides: it can read and draft this one section,
and ask you questions; aimm checks every value, and nothing is written until you confirm
the change to your config file. Type ``/show`` to see the drafts so far, or ``/quit`` to
stop without writing.

Marketplace values are defaults for all items of that marketplace: items without their own
value use them, and items with their own value keep it. This command never changes items.

Only the ``[marketplace.NAME]`` section is written, in place in the file that defines it:
comments and all other sections stay as they are. If nothing changed, nothing is written.

The AI follows a playbook for each section, which describes the goal, how to work out
each part, and when the section is complete. You can add your own rules for a section in
``~/.ai-marketplace-monitor/playbooks/marketplace.md``; they are appended to the bundled
playbook.

Items
~~~~~

``aimm configure item`` adds or updates what to search for. It lists your existing items
and asks whether to update one or add a new one; ``aimm configure item.NAME`` goes straight
to one item. Describe what you want, for example:

.. code-block:: text

    Search for an action camera within $200 and within 20 miles. Skip anything that needs
    repair.

The AI fills in the search phrases, a ``description`` of what you want (which the AI that
rates listings reads), the price range, and any extra requests in ``extra_prompt``, in your
own words. You can refine it afterwards in the same conversation: "make the max price
$300".

An item uses its marketplace's values (location, distance, schedule, notifications) unless
it sets its own, and the AI sees what the item inherits, so it sets a value on the item only
when this item should differ. If the marketplace does not exist yet, or has no location,
the same conversation creates it or adds the location, tells you so, and saves both
sections after one confirmation. No other section is changed.

Notifications and users
~~~~~~~~~~~~~~~~~~~~~~~

``aimm configure notification`` (or ``aimm configure user``) sets up how and to whom aimm sends
notifications. Users and notifications are set up together: a ``[notification.NAME]`` section is
one channel with its servers and credentials, and a ``[user.NAME]`` section says where a person
receives it (email address, chat ID, ...) and which notifications they get (``notify_with``). If
you have no user yet, notifications go to a new ``[user.me]``, so you only need to say how you
want to be notified:

.. code-block:: text

    Notify me through email.

The AI offers the options that fit: email through UnitySVC (``smtp.svcpass.com`` with your
UnitySVC key, sent to your UnitySVC-registered address) or Gmail (which needs an app password),
UnitySVC notifications, Pushbullet, Pushover, ntfy or Telegram. Passwords, tokens and keys are
written only as environment-variable references such as ``${GMAIL_APP_PASSWORD}``; you never type
them in the chat. After saving, aimm lists any variable that is not set yet, with the ``export``
line to add to your shell profile. ``aimm configure user.NAME`` and
``aimm configure notification.NAME`` start at that section; the session may still change any user
or notification, and nothing else.

Proxy, regions and translations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Three smaller section types have their own commands:

- ``aimm configure monitor`` sets up the proxy aimm's browser uses (``[monitor]``). The proxy
  account's user name and password are written as environment-variable references.
- ``aimm configure region`` (or ``region.NAME``) adds a region of your own, or changes a built-in
  one such as ``usa`` ("search the USA within 300 miles" sets only its radius). Each city is a
  Facebook location code taken from a Marketplace URL you paste, as for marketplaces. Use a region
  with ``search_region`` on a marketplace or item.
- ``aimm configure translation`` (or ``translation.NAME``) is for a Facebook in another language:
  the AI drafts the page labels aimm looks for ("Condition", "Description", ...) in your language,
  and you check them against a Facebook listing before saving, because they must match the page
  exactly. Use it with ``language`` on a marketplace.

In ``aimm configure`` the AI has the tools of every section type it can configure
(AI services, marketplaces, items, users, notifications, regions, translations and the monitor
settings). It sees only the section names and their
``request`` summaries until it opens a section, and it changes only the sections you asked
about; several drafted sections are saved together after one confirmation.

The command is a terminal front end over a reusable async setup flow. Web UI code can
drive the same flow through JSON prompt/answer messages over a websocket instead of
shelling out to the command.

Cost Considerations
------------------

**Free Components:**
- The software itself (AGPL license)

**Usage-Based Costs:**
- Notification services (PushBullet, SMTP, etc.)
- AI platforms (OpenAI, DeepSeek, etc.)

**Infrastructure:**
- 24/7 operation requires a PC, server, or cloud hosting
- Example: AWS t3.micro (~$10/month for continuous operation)
