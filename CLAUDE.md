# CLAUDE.md

Notes for Claude Code working in this repository.

## Releases

A release is prepared in a pull request and published from GitHub:

1. Bump `version` in `pyproject.toml` and turn `## [Unreleased]` in `CHANGELOG.md` into a dated `## [X.Y.Z] - YYYY-MM-DD` section, with the `[Unreleased]` and `[X.Y.Z]` compare links at the end of the file. Feature PRs do not edit `CHANGELOG.md`; the release PR writes it.
2. Do not list changes to the app-store templates in `deploy/` in `CHANGELOG.md`; they are deployment files, not changes to aimm.
3. After the PR is merged and the `tests`, `docker` and `CodeQL` workflows pass on `main`, create the GitHub release `vX.Y.Z` on that commit (its full SHA), with the version's `CHANGELOG.md` section as the notes. The `release` workflow publishes to PyPI, and the `vX.Y.Z` tag makes the `docker` workflow push `ghcr.io/bopeng/ai-marketplace-monitor:X.Y.Z` (and `latest`).

### Update the app-store templates

The templates in `deploy/` that pin a version are bumped to each release automatically: after the `docker` workflow pushes the image of a `vX.Y.Z` tag, its `bump-deploy` job reads the image's index digest from the registry, runs `python scripts/bump_deploy_versions.py X.Y.Z sha256:<digest>`, checks the result, and opens or updates a pull request titled "Pin the app-store templates to X.Y.Z" on `codex/bump-deploy-X.Y.Z`. Merge that PR after its required checks pass. The digest is the image's (not the PyPI package's), so it exists only once the image is pushed. Edit Umbrel's `releaseNotes` afterwards if a summary is wanted instead of the link the job writes.

Configure the repository Actions secret `DEPLOY_PR_TOKEN` before using this job: use a fine-grained personal access token scoped to this repository with **Contents: read/write** and **Pull requests: read/write** permissions. The token owner must be allowed to push a branch and open a PR. The job fails with a setup message if the secret is missing. It deliberately uses this token instead of `GITHUB_TOKEN` so the generated PR triggers the required tests and CodeQL workflows; no branch-protection bypass is needed.

If the job did not run or failed, run it again with **Actions › docker › Run workflow** and a `version` (it then only bumps, without building), or run the script locally. To find the digest by hand:

```bash
docker buildx imagetools inspect ghcr.io/bopeng/ai-marketplace-monitor:X.Y.Z
```

and use the `Digest:` of the index (not one of the per-platform manifests). The script makes these changes:

| File | Update |
| --- | --- |
| `deploy/casaos/AIMarketplaceMonitor/docker-compose.yml` | `image: ghcr.io/bopeng/ai-marketplace-monitor:X.Y.Z`, and `version` in `x-casaos` |
| `deploy/runtipi/ai-marketplace-monitor/docker-compose.json` | `"image"` tag `X.Y.Z` |
| `deploy/runtipi/ai-marketplace-monitor/config.json` | `"version": "X.Y.Z"`, `"tipi_version"` + 1, `"updated_at"` (now, in milliseconds) |
| `deploy/umbrel/ai-marketplace-monitor/docker-compose.yml` | `image: ghcr.io/bopeng/ai-marketplace-monitor:X.Y.Z@sha256:<digest>` |
| `deploy/umbrel/ai-marketplace-monitor/umbrel-app.yml` | `version: "X.Y.Z"`, and `releaseNotes` (a short summary, or the link to the GitHub release) |
| `deploy/truenas/ai-marketplace-monitor/ix_values.yaml` | `tag: "X.Y.Z@sha256:<digest>"` |
| `deploy/truenas/ai-marketplace-monitor/app.yaml` | `app_version: X.Y.Z`, and `version` (the app's own version: bump its patch number) |

The Unraid, Portainer and Cosmos templates use `latest` and need no change.

The `deploy-versions` workflow enforces this on every pull request and push to `main`: `python scripts/check_deploy_versions.py` requires every pin above to name the version in `pyproject.toml` once it is released (the tag `vX.Y.Z` exists), or the latest release while the release PR is open, and checks the Umbrel and TrueNAS digests against the registry. So if the automatic bump did not happen, pull requests fail until the template-update PR is merged. Run it locally before pushing; `--offline` skips the registry.

For a store that already lists aimm, the same bump goes to the store in a pull request to its repository; [#417](https://github.com/BoPeng/ai-marketplace-monitor/issues/417) tracks which stores list it.
