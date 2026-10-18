===============
Troubleshooting
===============

Common Issues and Solutions
===========================

Configuration Problems
----------------------

**Config file not found**

.. code-block:: text

    Error: Config file ~/.ai-marketplace-monitor/config.toml not found

*Solution:*
- Ensure the config file exists at ``~/.ai-marketplace-monitor/config.toml``
- Check file permissions (should be readable by your user)
- Use ``--config`` flag to specify a different location

**Invalid TOML syntax**

.. code-block:: text

    Error: Invalid TOML configuration

*Solution:*
- Validate your TOML syntax at `toml-lint.com <https://www.toml-lint.com/>`_
- Check for missing quotes around strings
- Ensure proper section headers like ``[marketplace.facebook]``

Login and Authentication Issues
------------------------------

**Facebook login failure**

.. code-block:: text

    Warning: Failed to login to Facebook

*Solution:*
- Provide username/password in config file
- Complete CAPTCHA challenges manually
- The monitor will continue with limited results if login fails

**Facebook keeps asking for a CAPTCHA**

If Facebook shows CAPTCHA after CAPTCHA and the login never finishes, turn on two-factor
authentication for your Facebook account (in Facebook's Accounts Center, under Password and
security). Facebook then asks you to confirm the login on your phone, with its app or a
code, and users found that this ends the repeated CAPTCHAs. Once you are logged in, AIMM
saves the session (see below), so it does not need to log in again when it restarts. AIMM
also suggests this in its log, and in the web UI's login banner, when a login takes long.

**Two-factor authentication required**

*Solution:*
- Complete 2FA manually in the browser window
- Consider using app passwords where supported
- AIMM saves the session after the login, so the next run does not log in again

**The saved Facebook session**

After each login, AIMM saves the browser's Facebook session (its cookies) in
``facebook-session.json`` in its data folder (``~/.ai-marketplace-monitor``, or ``/data``
in Docker), and the next run uses it instead of logging in again. Each new login can make
Facebook ask for a CAPTCHA, a security code or your approval of the login, so a restart
no longer does.

- The file gives access to your Facebook account, like your password. Only your user can
  read it; do not share it or copy it to another machine.
- AIMM checks that the session still works when it starts, and logs in again if Facebook
  has ended it. A session saved for another username is not used.
- To log in from scratch, for example if Facebook keeps showing the login page, stop AIMM,
  delete the file and start AIMM again. In Docker, delete it while the container runs,
  then restart the container::

      docker compose exec aimm rm /data/facebook-session.json
      docker compose restart aimm

  With the container stopped, delete ``facebook-session.json`` from the data folder mounted
  at ``/data`` on the host instead.

Browser and Playwright Issues
-----------------------------

**Playwright browser not installed**

.. code-block:: text

    Error: Browser executable not found

*Solution:*

.. code-block:: console

    $ playwright install

**Browser crashes or hangs**

*Solution:*
- Restart the monitor
- Check system resources (RAM, CPU)
- On a machine without a screen, run AIMM in Docker, which provides a virtual display

Notification Problems
--------------------

**PushBullet notifications not received**

*Solutions:*
- Verify API token is correct
- Check PushBullet app is installed and logged in
- Test token at `pushbullet.com <https://www.pushbullet.com/>`_

**Email notifications failing**

*Solutions:*
- Check SMTP settings (server, port, username, password)
- For Gmail, use app passwords instead of account password
- Verify firewall/antivirus isn't blocking SMTP

**Telegram bot not responding**

*Solutions:*
- Verify bot token format: ``123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11``
- Ensure you've started a conversation with the bot
- Check chat ID is correct (positive for users, negative for groups)

AI Service Issues
----------------

**OpenAI API errors**

.. code-block:: text

    Error: OpenAI API request failed

*Solutions:*
- Check API key is valid and has sufficient credits
- Verify network connectivity
- Review OpenAI status page for service issues

**AI responses seem incorrect**

*Solutions:*
- Adjust AI prompts in configuration
- Try different AI models (gpt-4, gpt-3.5-turbo, etc.)
- Check if AI service has usage limits

Search and Filtering Problems
----------------------------

**No listings found**

*Solutions:*
- Verify search city name is correct
- Check price ranges aren't too restrictive
- Review keyword filters (``keywords`` and ``antikeywords``)
- Test without AI filtering to see raw results

**Too many irrelevant results**

*Solutions:*
- Add more specific keywords
- Use ``antikeywords`` to exclude unwanted terms
- Adjust AI rating threshold higher
- Refine item descriptions for better AI filtering

**Currency conversion issues**

*Solutions:*
- Check currency codes are valid (USD, EUR, GBP, etc.)
- Ensure currency is specified for multi-region searches
- Verify exchange rate data is available

Performance Issues
-----------------

**Monitor running slowly**

*Solutions:*
- Reduce search frequency in configuration
- Clear cache: ``aimm admin --clear-cache all``
- Check system resources
- Consider using fewer simultaneous searches

**High CPU/memory usage**

*Solutions:*
- Reduce number of concurrent browser tabs
- Clear browser cache and data
- Consider running on a more powerful machine

Cache-Related Issues
-------------------

**Stale data or wrong notifications**

*Solution:*

.. code-block:: console

    $ aimm admin --clear-cache all

**Cache corruption**

.. code-block:: text

    Error: Cannot read cache data

*Solution:*
- Clear specific cache types:

.. code-block:: console

    $ aimm admin --clear-cache listing-details
    $ aimm admin --clear-cache ai-inquiries
    $ aimm admin --clear-cache user-notification

Language and Localization Issues
--------------------------------

**Non-English Facebook pages**

.. code-block:: text

    Failed to get details of listing. The listing might not be in English.

*Solutions:*
- Change Facebook language settings to English
- Add ``language`` option to marketplace configuration
- Define custom translation dictionary in config

Debug Mode and Logging
----------------------

**Enable verbose logging**

Add to your configuration:

.. code-block:: toml

    [monitor]
    log_level = "DEBUG"

**Check log files**

Logs are typically saved to:
- Console output (default)
- Log files if configured in your system

**Interactive debugging**

- Use ``aimm check URL`` to test individual listings
- Enter interactive mode by pressing any key while monitor is running. This feature requires the installation of `pynput` package.

Getting Help
============

If you're still having issues:

1. **Check GitHub Issues**: Search existing issues at `github.com/BoPeng/ai-marketplace-monitor/issues <https://github.com/BoPeng/ai-marketplace-monitor/issues>`_

2. **Community Support**: Join discussions at `github.com/BoPeng/ai-marketplace-monitor/discussions <https://github.com/BoPeng/ai-marketplace-monitor/discussions>`_

3. **Create New Issue**: If you find a bug, create a detailed issue report including:
   - Your operating system
   - Python version
   - Complete error messages
   - Configuration file (remove sensitive data)
   - Steps to reproduce the problem

4. **Sponsor Support**: Sponsors and donors receive priority email support - mention your sponsor status when contacting.

Reporting Bugs
==============

When reporting bugs, please include:

.. code-block:: text

    **Environment:**
    - OS: [e.g., Ubuntu 20.04, macOS 12.0, Windows 10]
    - Python: [e.g., 3.10.2]
    - ai-marketplace-monitor: [e.g., 0.9.6]

    **Configuration:**
    ```toml
    # Your config file with sensitive data removed
    ```

    **Error Message:**
    ```
    # Complete error message/traceback
    ```

    **Steps to Reproduce:**
    1. Step one
    2. Step two
    3. Step three

    **Expected Behavior:**
    What should have happened

    **Actual Behavior:**
    What actually happened
