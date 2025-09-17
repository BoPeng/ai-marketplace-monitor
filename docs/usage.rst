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
