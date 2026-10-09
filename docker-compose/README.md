# Docker Compose

Run AI Marketplace Monitor with Docker Compose:

- `docker-compose.yml`: aimm, its web UI on port 8467, and its data in `./data`. Use it as is.
- `.env.example`: copy it to `.env` and fill in your credentials and settings.
- `docker-compose.traefik.yml`: save it as `docker-compose.override.yml` to serve aimm through Traefik.

```bash
cp .env.example .env && chmod 600 .env   # then edit .env
docker compose up -d
```

See the [Docker Compose installation guide](../docs/docker-installation.md) for the first run, updates and troubleshooting.
