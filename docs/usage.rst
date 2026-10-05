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
section argument, it starts by checking existing ``[ai.*]`` sections and helping you
add or update an AI service, then asks what to configure next. ``aimm-configure ai``
is the explicit AI form: it asks which AI to use and creates or updates the section named
after it, such as ``[ai.unitysvc]``. The AI setup offers UnitySVC (recommended: one key
covers AI and email notifications), OpenAI, Anthropic, or Ollama.

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
Future configuration helpers can follow the same section-address pattern, such as
``item`` for a new item or ``item.gopro`` for an existing named item. AI-assisted
section helpers such as ``item`` require a configured and usable AI service.

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
