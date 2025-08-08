==========
Quickstart
==========

This guide will get you up and running with AI Marketplace Monitor in under 10 minutes.

.. warning::
   **Important Legal Notice**: Facebook's EULA prohibits automated data collection without authorization. This tool was developed for personal, hobbyist use only. You are solely responsible for ensuring compliance with platform terms and applicable laws. For commercial use, obtain explicit permission from Meta first.

Step 1: Installation
--------------------

Install AI Marketplace Monitor:

.. code-block:: console

    $ pip install ai-marketplace-monitor

Install Playwright browser:

.. code-block:: console

    $ playwright install

Step 2: Set Up Notifications (Optional)
---------------------------------------

Choose one notification method:

**PushBullet** (Recommended for beginners):
1. Sign up at `pushbullet.com <https://www.pushbullet.com/>`_
2. Install the app on your phone
3. Get your API token from the website

**Email**:
1. Use your existing email account
2. Get SMTP settings from your email provider
3. For Gmail, create an app password

Step 3: Create Configuration
---------------------------

Create the configuration directory:

.. code-block:: console

    $ mkdir -p ~/.ai-marketplace-monitor

Create a minimal configuration file at ``~/.ai-marketplace-monitor/config.toml``:

.. code-block:: toml

    [marketplace.facebook]
    search_city = 'houston'  # Replace with your city

    [item.gopro]
    search_phrases = 'Go Pro Hero 11'
    min_price = 100
    max_price = 300

    [user.me]
    pushbullet_token = 'your_pushbullet_token_here'

.. note::
   Replace ``'houston'`` with your city name and ``'your_pushbullet_token_here'`` with your actual PushBullet token.

Step 4: Add AI Service (Optional but Recommended)
------------------------------------------------

Sign up for an AI service like `OpenAI <https://openai.com/>`_ or `DeepSeek <https://www.deepseek.com/>`_ and add to your config:

.. code-block:: toml

    [ai.openai]
    api_key = 'your_openai_api_key'

    # ... rest of your config

Step 5: Run the Monitor
----------------------

Start monitoring:

.. code-block:: console

    $ ai-marketplace-monitor

What happens next:

1. **Browser Opens**: A browser window will appear
2. **Login Prompt**: Enter Facebook credentials if prompted
3. **CAPTCHA**: Complete any CAPTCHA challenges
4. **Monitoring Starts**: The program begins searching automatically
5. **Notifications**: You'll receive notifications when matches are found

Step 6: Test Your Setup
-----------------------

To verify everything works, check a specific listing:

.. code-block:: console

    $ ai-marketplace-monitor --check https://facebook.com/marketplace/item/123456789

Example Output
-------------

When the monitor finds a matching item, you'll see console output like:

.. code-block:: text

    [2025-01-08 10:30:15] Found 1 new gopro from facebook
    [Great deal (5)] Go Pro Hero 12
    $250, Houston, TX
    https://facebook.com/marketplace/item/1234567890
    AI: Excellent condition camera with original accessories - great value!

And receive a notification on your phone via PushBullet.

Next Steps
----------

- :doc:`configuration` - Learn about advanced configuration options
- :doc:`features` - Explore all available features
- :doc:`usage` - Master command-line options and interactive mode
- `GitHub Issues <https://github.com/BoPeng/ai-marketplace-monitor/issues>`_ - Get help or report problems

Common Issues
-------------

**"Config file not found"**
   Make sure the file is at ``~/.ai-marketplace-monitor/config.toml``

**"Cannot login to Facebook"**
   The monitor will still work but with limited results. Try providing username/password in config.

**"No notifications received"**
   Check your PushBullet token and ensure the app is installed on your phone.

**Browser doesn't open**
   Try running without ``--headless`` flag to see the browser window.
