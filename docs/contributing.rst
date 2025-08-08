============
Contributing
============

We welcome contributions to AI Marketplace Monitor! Here's how you can help make this project better.

Ways to Contribute
==================

🐛 **Report Bugs and Issues**
   - Search existing issues first
   - Provide detailed reproduction steps
   - Include system information and error messages

💡 **Suggest New Features**
   - Open a feature request issue
   - Explain the use case and expected behavior
   - Discuss implementation approaches

🔧 **Submit Pull Requests**
   - Fix bugs or implement new features
   - Follow our coding standards
   - Add tests for new functionality

📚 **Improve Documentation**
   - Fix typos and unclear sections
   - Add examples and tutorials
   - Translate documentation

🏪 **Add Marketplace Support**
   - Implement new marketplace backends
   - Extend the marketplace abstraction
   - Add region and currency support

🌍 **Internationalization**
   - Add support for new languages
   - Create translation dictionaries
   - Test non-English Facebook pages

🤖 **AI Provider Integration**
   - Add new AI service providers
   - Improve prompt engineering
   - Test different AI models

📱 **Notification Methods**
   - Implement new notification backends
   - Improve existing notification features
   - Add notification customization

Development Setup
=================

Prerequisites
-------------

- Python 3.10 or higher
- Git
- `uv` package manager (recommended) or pip

Clone and Setup
---------------

.. code-block:: console

    $ git clone https://github.com/BoPeng/ai-marketplace-monitor.git
    $ cd ai-marketplace-monitor
    $ uv sync --extra dev
    $ playwright install
    $ uv run invoke install-hooks

This installs:
- All dependencies including development tools
- Playwright browsers for testing
- Pre-commit hooks for code quality

Development Workflow
===================

Code Quality
-----------

Run all quality checks:

.. code-block:: console

    $ uv run invoke lint        # Run linting and formatting checks
    $ uv run invoke mypy        # Type checking
    $ uv run invoke security    # Security vulnerability scan

Auto-format code:

.. code-block:: console

    $ uv run invoke format      # Format with black and isort

Testing
-------

Run the test suite:

.. code-block:: console

    $ uv run invoke tests       # Run pytest with coverage
    $ uv run pytest tests/     # Run specific tests
    $ nox                      # Test across Python versions

Add tests for new features:
- Unit tests in ``tests/test_*.py``
- Mock external services (Facebook, AI APIs)
- Use fixtures for common test data

Documentation
------------

Build documentation locally:

.. code-block:: console

    $ uv run invoke docs        # Build Sphinx documentation
    $ uv run invoke docs --serve --open-browser  # Live preview

Documentation files:
- ``docs/*.rst`` - Main documentation pages
- ``README.md`` - Project overview
- ``CHANGELOG.md`` - Version history
- Docstrings in code for API documentation

Coding Standards
===============

Style Guidelines
---------------

- **Line length**: 99 characters maximum
- **Formatting**: Use black and isort (automated by pre-commit)
- **Linting**: Follow ruff recommendations
- **Type hints**: Required for all public functions

Code Organization
----------------

- ``src/ai_marketplace_monitor/`` - Main package
- ``tests/`` - Test files matching ``test_*.py``
- ``docs/`` - Sphinx documentation
- ``noxfile.py`` - Multi-environment testing
- ``tasks.py`` - Development tasks (invoke)

Architecture Patterns
---------------------

- **Abstract base classes** for marketplaces and AI backends
- **Configuration inheritance** from marketplace to item level
- **Plugin architecture** for extensible components
- **Caching strategy** to minimize external API calls

Commit Guidelines
================

Commit Message Format
--------------------

.. code-block:: text

    type(scope): brief description

    Longer explanation of the change if needed.

    Closes #123

Types:
- ``feat``: New feature
- ``fix``: Bug fix
- ``docs``: Documentation changes
- ``style``: Code formatting
- ``refactor``: Code restructuring
- ``test``: Adding tests
- ``chore``: Maintenance tasks

Examples:

.. code-block:: text

    feat(telegram): add support for group chat notifications

    fix(facebook): handle new marketplace layout changes

    docs: add troubleshooting section for AI service errors

Pull Request Process
===================

Before Submitting
----------------

1. **Create an issue** first to discuss major changes
2. **Fork the repository** and create a feature branch
3. **Write tests** for new functionality
4. **Update documentation** as needed
5. **Run all checks** locally

.. code-block:: console

    $ uv run invoke lint
    $ uv run invoke tests
    $ uv run invoke mypy

Pull Request Checklist
---------------------

- [ ] Tests pass locally
- [ ] Code follows style guidelines
- [ ] Documentation updated
- [ ] CHANGELOG.md updated (for significant changes)
- [ ] Commit messages are clear
- [ ] PR description explains the change

Review Process
-------------

1. **Automated checks** must pass (CI/CD)
2. **Code review** by maintainers
3. **Testing** on different environments
4. **Documentation review** if applicable
5. **Merge** when approved

Community Guidelines
===================

Code of Conduct
---------------

This project follows the `Contributor Covenant Code of Conduct <https://www.contributor-covenant.org/version/2/1/code_of_conduct/>`_.

Key principles:
- Be respectful and inclusive
- Focus on what's best for the community
- Accept constructive criticism gracefully
- Help newcomers get involved

Communication Channels
---------------------

- **GitHub Issues**: Bug reports and feature requests
- **GitHub Discussions**: Questions and community chat
- **Pull Requests**: Code changes and reviews

Support for Contributors
========================

Getting Help
-----------

- **Documentation**: Start with this guide and the main docs
- **Issues**: Search existing issues for similar problems
- **Discussions**: Ask questions in GitHub Discussions
- **Code**: Read existing code for patterns and examples

Recognition
----------

Contributors are recognized in:
- ``CONTRIBUTORS.md`` file
- GitHub contributor graphs
- Release notes for significant contributions
- Special thanks in documentation

Getting Started with Your First Contribution
===========================================

Good First Issues
----------------

Look for issues labeled:
- ``good first issue`` - Simple changes perfect for newcomers
- ``documentation`` - Documentation improvements
- ``help wanted`` - Community input needed

Simple Contributions
-------------------

1. **Fix typos** in documentation
2. **Add examples** to configuration reference
3. **Improve error messages** for better user experience
4. **Add tests** for existing functionality
5. **Translate** interface messages

Example First Contribution
--------------------------

1. Find a typo in documentation
2. Fork the repository
3. Fix the typo in your fork
4. Submit a pull request
5. Celebrate your contribution! 🎉

Thank you for contributing to AI Marketplace Monitor!
