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

## Troubleshooting

- If you encounter permission issues, ensure `$HOME/.local/bin` is in your PATH
- If playwright browsers fail to install, you may need to install additional system dependencies with `sudo apt install libnss3-dev libatk-bridge2.0-dev libdrm2-dev`
