# GitHub Actions Docker Build to GHCR — Design

Date: 2026-09-01
Status: approved by owner ("làm tiếp plan github action build image đi"; registry choice GHCR
confirmed earlier the same day)

## Goal

Every push to `main`/`master` (and every `v*` tag) builds the Docker image in CI and pushes it
to GitHub Container Registry, so the machine running the dashboard can `docker compose pull`
instead of building locally.

## Design

**New file `.github/workflows/docker-build.yml`:**

- Triggers: push to `main` and `master` (the repo's default branch is `main` but day-to-day
  work lands on local `master`), tags `v*`, and `workflow_dispatch`.
- Permissions: `contents: read`, `packages: write` — auth via the built-in `GITHUB_TOKEN`,
  no secrets to configure.
- Steps: checkout → setup-buildx → login to `ghcr.io` → `docker/metadata-action` →
  `docker/build-push-action`.
- Image: `ghcr.io/nelie-taylor/hello-coin` (owner name already lowercase, as GHCR requires).
- Tags: branch name, short SHA, semver from `v*` tags, and `latest` on pushes to `main` or
  `master` (explicit expression rather than `{{is_default_branch}}`, because work lands on
  `master` while the GitHub default branch is `main`).
- Layer cache: `type=gha` (`mode=max`), which only pays off together with the Dockerfile
  split below.
- Platform: `linux/amd64` only (multi-arch roughly doubles build time; add later if needed).

**Dockerfile layer split (same file, no new stage):**

- Copy `pyproject.toml` + `uv.lock` first and run
  `uv sync --frozen --no-install-project --no-dev` so the dependency layer caches
  independently of source changes; then `COPY . .` and `uv sync --frozen --no-dev` to install
  the project itself.
- `--no-dev` drops pytest/ruff/respx from the image.
- CMD becomes `uv run --no-sync hello-coin dashboard` — without `--no-sync`, `uv run` would
  re-sync at container start and reinstall the dev group.

**docker-compose.yml:** add `image: ghcr.io/nelie-taylor/hello-coin:latest` alongside
`build: .` — local `docker compose build` keeps working and names the image so
`docker compose pull` fetches the CI-built one.

## Verification

- Local: `docker compose build` succeeds with the reworked Dockerfile; container starts and
  the dashboard answers 200 on :8080.
- CI: the workflow itself can only run on GitHub — pushing is left to the owner (the push is
  outward-facing and publishes the day's commits).

## Out of scope

- Running tests in the workflow before building (owner chose the minimal build-only variant).
- Multi-arch images, release automation, deploy steps.
