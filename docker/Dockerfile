# Dockerfile for ai-marketplace-monitor
#
# Provides a Linux runtime that bundles:
#   - Python + aimm
#   - Playwright with Chromium
#   - Xvfb virtual display (so non-headless Chromium can run)
#   - x11vnc + websockify + noVNC for browser-based interaction (CAPTCHA / login)
#   - supervisord to manage all processes
#
# Everything runs as the unprivileged `aimm` user. The container starts as root only to give
# that user the PUID/PGID you ask for (default 1000:1000, e.g. -e PUID="$(id -u)"
# -e PGID="$(id -g)" on a Linux host) and the data folder, /data (see docker/entrypoint.sh).
#
# Build from the root of the repository, which is the build context:
#   docker build -f docker/Dockerfile -t aimm .
#
# To run aimm with Docker Compose, see docker-compose/.
#
# Run (mount a host folder for config, cache and logs):
#   docker run --rm -it \
#     -p 8467:8467 \
#     -v "$HOME/.ai-marketplace-monitor:/data" \
#     -e FACEBOOK_USERNAME -e FACEBOOK_PASSWORD \
#     -e UNITYSVC_API_KEY \
#     aimm
#
#   Web UI: http://localhost:8467
#   Click the "Browser" button in the header for the live Chromium view.

FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DISPLAY=:99 \
    SCREEN_GEOMETRY=1280x800x24 \
    VNC_PORT=5900 \
    AIMM_DOCKER=1 \
    AIMM_WEBUI_HOST=0.0.0.0 \
    AIMM_WEBUI_PORT=8467 \
    AIMM_ENABLE_VNC=1 \
    AIMM_NOVNC_DIR=/usr/share/novnc \
    AIMM_VNC_HOST=127.0.0.1 \
    AIMM_VNC_PORT=5900 \
    AIMM_HOME=/data \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

LABEL org.opencontainers.image.title="AI Marketplace Monitor" \
      org.opencontainers.image.description="Watch Facebook Marketplace for the items you want, rate listings with AI, and get notified of good deals" \
      org.opencontainers.image.url="https://github.com/BoPeng/ai-marketplace-monitor" \
      org.opencontainers.image.source="https://github.com/BoPeng/ai-marketplace-monitor" \
      org.opencontainers.image.documentation="https://ai-marketplace-monitor.readthedocs.io" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

# System packages:
#   - Xvfb + x11vnc + xauth: virtual display + VNC
#   - websockify + novnc: browser-based VNC client
#   - supervisor: process manager
#   - ca-certificates, curl, git: misc tooling
#   - fonts and libs needed by Chromium are installed by `playwright install --with-deps`
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
        xauth \
        supervisor \
        websockify \
        novnc \
        ca-certificates \
        curl \
        git \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Symlink so noVNC's web UI is reachable at /usr/share/novnc/vnc.html
RUN if [ ! -e /usr/share/novnc/vnc.html ] && [ -e /usr/share/novnc/vnc_lite.html ]; then \
        ln -s /usr/share/novnc/vnc_lite.html /usr/share/novnc/vnc.html; \
    fi

# The `aimm` user owns aimm's installation (a virtualenv) and its Chromium, so the web UI's
# Update button can install a new release in place.
RUN groupadd -g 1000 aimm \
    && useradd -u 1000 -g aimm -m -d /home/aimm -s /bin/sh aimm \
    && mkdir -p /app /opt/aimm /opt/ms-playwright /data \
    && chown aimm:aimm /app /opt/aimm /opt/ms-playwright /data \
    && mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix

WORKDIR /app

# Install aimm. Copy only metadata + source needed for a pip install.
COPY --chown=aimm:aimm pyproject.toml README.md ./
COPY --chown=aimm:aimm src ./src

USER aimm
RUN python -m venv /opt/aimm \
    && /opt/aimm/bin/pip install . \
    && /opt/aimm/bin/playwright install chromium

USER root
RUN /opt/aimm/bin/playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY docker/supervisord.conf /etc/aimm/supervisord.conf
COPY docker/entrypoint.sh /usr/local/bin/aimm-entrypoint
COPY docker/aimm-wrapper.sh /usr/local/bin/aimm
RUN ln -s aimm /usr/local/bin/ai-marketplace-monitor

EXPOSE 8467

# No VOLUME: the entrypoint tells a folder mounted at /data from one mounted at the old
# location, /root/.ai-marketplace-monitor, which an anonymous volume at /data would hide.

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${AIMM_WEBUI_PORT}/api/health" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/aimm-entrypoint"]
CMD ["/usr/bin/supervisord", "-c", "/etc/aimm/supervisord.conf", "-n"]
