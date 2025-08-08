.. highlight:: shell

============
Installation
============

Prerequisites
-------------

- Python 3.10 or higher
- Internet connection

Quick Installation
------------------

Install the program:

.. code-block:: console

    $ pip install ai-marketplace-monitor

Install a browser for Playwright:

.. code-block:: console

    $ playwright install

For community-contributed instructions, see:

- `Community installation instructions #234 <https://github.com/BoPeng/ai-marketplace-monitor/issues/234>`_

Linux Installation (using pipx)
--------------------------------

.. include:: linux-installation.md
   :parser: myst_parser.sphinx_

Development Installation
------------------------

If you want to contribute to the project:

.. code-block:: console

    $ git clone https://github.com/BoPeng/ai-marketplace-monitor.git
    $ cd ai-marketplace-monitor
    $ uv sync --extra dev
    $ playwright install

This will install the project with development dependencies using `uv`.
