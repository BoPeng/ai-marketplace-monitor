# CLAUDE.md

Notes for Claude Code working in this repository.

## Releases

A release is prepared in a pull request and published from GitHub:

1. Bump `version` in `pyproject.toml` and turn `## [Unreleased]` in `CHANGELOG.md` into a dated `## [X.Y.Z] - YYYY-MM-DD` section, with the `[Unreleased]` and `[X.Y.Z]` compare links at the end of the file. Feature PRs do not edit `CHANGELOG.md`; the release PR writes it.
2. Do not list changes to the app-store templates in `deploy/` in `CHANGELOG.md`; they are deployment files, not changes to aimm.
3. After the PR is merged and the `tests`, `docker` and `CodeQL` workflows pass on `main`, create the GitHub release `vX.Y.Z` on that commit (its full SHA), with the version's `CHANGELOG.md` section as the notes. The `release` workflow publishes to PyPI, and the `vX.Y.Z` tag makes the `docker` workflow push `ghcr.io/bopeng/ai-marketplace-monitor:X.Y.Z` (and `latest`).

### Update the app-store templates

The templates in `deploy/` that pin a version must be bumped to each release, in a pull request after the release, once the image is pushed. Get the image's multi-arch digest with:

```bash
docker buildx imagetools inspect ghcr.io/bopeng/ai-marketplace-monitor:X.Y.Z
```

and use the `Digest:` of the index (not one of the per-platform manifests).

| File | Update |
| --- | --- |
| `deploy/casaos/AIMarketplaceMonitor/docker-compose.yml` | `image: ghcr.io/bopeng/ai-marketplace-monitor:X.Y.Z`, and `version` in `x-casaos` |
| `deploy/runtipi/ai-marketplace-monitor/docker-compose.json` | `"image"` tag `X.Y.Z` |
| `deploy/runtipi/ai-marketplace-monitor/config.json` | `"version": "X.Y.Z"`, `"tipi_version"` + 1, `"updated_at"` (now, in milliseconds) |
| `deploy/umbrel/ai-marketplace-monitor/docker-compose.yml` | `image: ghcr.io/bopeng/ai-marketplace-monitor:X.Y.Z@sha256:<digest>` |
| `deploy/umbrel/ai-marketplace-monitor/umbrel-app.yml` | `version: "X.Y.Z"`, and `releaseNotes` (a short summary, or the link to the GitHub release) |
| `deploy/truenas/ai-marketplace-monitor/ix_values.yaml` | `tag: "X.Y.Z@sha256:<digest>"` |
| `deploy/truenas/ai-marketplace-monitor/app.yaml` | `app_version: X.Y.Z`, and `version` (the app's own version: bump its patch number) |

The Unraid, Portainer and Cosmos templates use `latest` and need no change. Check that nothing still names the previous version with `grep -rn "<previous version>" deploy`.

For a store that already lists aimm, the same bump goes to the store in a pull request to its repository; [#417](https://github.com/BoPeng/ai-marketplace-monitor/issues/417) tracks which stores list it.
