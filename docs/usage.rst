===========
Usage Guide
===========

Basic Usage
-----------

Run the monitor with default configuration:

.. code-block:: console

    $ ai-marketplace-monitor

Run with a custom configuration file:

.. code-block:: console

    $ ai-marketplace-monitor --config /path/to/your/config.toml

Run in headless mode (without browser window):

.. code-block:: console

    $ ai-marketplace-monitor --headless

Check Individual Listings
-------------------------

You can check why a listing was excluded or test a listing against your configuration:

.. code-block:: console

    $ ai-marketplace-monitor --check https://facebook.com/marketplace/item/123456789

For specific item configurations:

.. code-block:: console

    $ ai-marketplace-monitor --check https://facebook.com/marketplace/item/123456789 --for item_name

Cache Management
---------------

Clear different types of cache:

.. code-block:: console

    $ ai-marketplace-monitor --clear-cache listing-details
    $ ai-marketplace-monitor --clear-cache ai-inquiries
    $ ai-marketplace-monitor --clear-cache user-notification
    $ ai-marketplace-monitor --clear-cache counters
    $ ai-marketplace-monitor --clear-cache all

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

Run ``aimm-configure`` as the primary interactive configuration command. With no
section argument, it starts with your AI service, then asks what to configure next.
``aimm-configure ai`` is the explicit AI form.

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

Use ``aimm-configure ai.NAME`` to work on one section. A section named after a provider
uses that provider, so ``aimm-configure ai.openai`` sets up ``[ai.openai]`` without asking
which AI; an existing section keeps its own provider. To use two keys for the same
provider, give the second section another name, such as ``aimm-configure ai.openai2``,
which asks for the provider once and writes it as ``provider = "openai"``.

For hosted providers, the command writes the API key as an environment-variable
reference such as ``${UNITYSVC_API_KEY}``; the key itself is never written to the config
file. Every write shows the proposed TOML first, asks for confirmation, and keeps a
backup in ``~/.ai-marketplace-monitor/backups/``.

Use ``--config`` or ``--config-file`` to read and update a specific config file.

Marketplaces
~~~~~~~~~~~~

``aimm-configure marketplace`` sets up where and how to search Facebook Marketplace with
the help of your AI service, so it needs a working ``[ai.*]`` section first. It lists your
existing marketplaces, each with its ``request`` (a short summary of what you asked for)
and its settings, and asks whether to update one or create a new one;
``aimm-configure marketplace.NAME`` goes straight to one section.

The AI then leads a short conversation. You answer in your own words, for example:

.. code-block:: text

    I'm in Austin, Texas and will drive about 30 miles. Only local pickup, used things in
    good condition or better. Checking every hour is fine.

It works out what is still needed (a location is required), asks about what is likely
to matter to you, fills in the section, and decides from your answers when you are done:
to save the section, keep it unchanged, or stop. aimm checks every value and that nothing
required is missing; before saving it shows the section and the change to your config file
and asks you to confirm. Type ``/show`` to see the section so far, or ``/quit`` to stop
without writing.

Marketplace values are defaults for all items of that marketplace. When you change one,
items without their own value use the new value and items with their own value keep it,
unless you ask for every item to use the marketplace's value.

Only the ``[marketplace.NAME]`` section is written, in place in the file that defines it:
comments and all other sections stay as they are (items change only when you ask for a
value to apply to every item). If nothing changed, nothing is written.

The AI follows a playbook for each section, which describes the goal, how to work out
each part, and when the section is complete. You can add your own rules for a section in
``~/.ai-marketplace-monitor/playbooks/marketplace.md``; they are appended to the bundled
playbook.

Configuring items (``aimm-configure item``) will follow the same pattern.

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
