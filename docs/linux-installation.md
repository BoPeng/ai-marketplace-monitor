If you're using Ubuntu Linux and prefer not to use package managers like conda/mamba or virtual environments, you can install `ai-marketplace-monitor` as a system-wide command using `pipx`.

## Prerequisites

If you haven't used `pipx` before or don't have `$HOME/.local/bin` in your `$PATH`:

```bash
sudo apt update
sudo apt install pipx
pipx ensurepath
source ~/.bashrc
```

**Note:** You may need to restart your terminal or run `exec bash` instead of `source ~/.bashrc` for the PATH changes to take effect.

## Installation

```bash
# Install the main package
pipx install ai-marketplace-monitor

# Install playwright in the same virtual environment
pipx inject ai-marketplace-monitor playwright

# Install playwright browsers
playwright install
```

If prompted to install playwright system dependencies, run:

```bash
sudo /home/YOURUSER/.local/bin/playwright install-deps
```

## Configuration

Edit your configuration file using your preferred text editor:

```bash
# Using nano
nano ~/.ai-marketplace-monitor/config.toml

# Using vim
vim ~/.ai-marketplace-monitor/config.toml

# Or install a code editor via snap (recommended method for VS Code)
sudo snap install code --classic
```

## Verification

To verify the installation was successful:

```bash
ai-marketplace-monitor --version
```

## Running as a systemd service

On a Linux workstation or server it is convenient to run the monitor in the
background so that it is automatically restarted if the Playwright browser
crashes or the process exits unexpectedly. `ai-marketplace-monitor` ships with
built-in helpers that install a `systemd --user` unit for you.

### Prerequisites

- A systemd-based distribution (Ubuntu, Debian, Fedora, Arch, etc.).
- `ai-marketplace-monitor` installed for the current user (e.g. via `pipx`),
  so the executable is on `$PATH`.
- A working configuration at `~/.ai-marketplace-monitor/config.toml`.
- Facebook credentials saved in the config file. The service runs headless
  and cannot complete an interactive login. Set `username` and `password`
  under the `[marketplace.facebook]` section, and consider setting a small
  `login_wait_time` so the service does not idle on the login page.
- If the user account is not normally logged into a graphical session, run
  `sudo loginctl enable-linger $USER` so that user units keep running after
  you log out.

### Install the service

```bash
ai-marketplace-monitor --install-service
```

This writes `~/.config/systemd/user/ai-marketplace-monitor.service`, reloads
the user unit cache, and runs `systemctl --user enable --now` so the monitor
starts immediately and on every subsequent login. The generated unit passes
`--headless` to the CLI and sets `Restart=on-failure` with a 30 second delay,
so a crashed monitor is automatically restarted without any manual
intervention.

### Inspect the service

```bash
# One-shot status via the built-in helper:
ai-marketplace-monitor --service-status

# Live log tail via journald:
journalctl --user -u ai-marketplace-monitor.service -f
```

### Remove the service

```bash
ai-marketplace-monitor --uninstall-service
```

This stops the unit, disables it, and deletes the unit file.

### A note about Playwright and headless mode

The monitor drives Facebook Marketplace through a Playwright-controlled
browser. Running it as a service is only viable in **headless** mode, because
a systemd user unit has no attached display. The login flow therefore needs
to be fully automated using the credentials in the config file. If Facebook
challenges the session with a 2FA prompt or a CAPTCHA, the service will not
be able to resolve it on its own — in that case, stop the service, run the
monitor interactively once to complete the challenge, and then start the
service again.

## Troubleshooting

- If you encounter permission issues, ensure `$HOME/.local/bin` is in your PATH
- If playwright browsers fail to install, you may need to install additional system dependencies with `sudo apt install libnss3-dev libatk-bridge2.0-dev libdrm2-dev`
