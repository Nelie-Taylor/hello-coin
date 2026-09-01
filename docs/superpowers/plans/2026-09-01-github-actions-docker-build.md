# GitHub Actions Docker Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CI builds the Docker image on every push to main/master (and v* tags) and pushes it to `ghcr.io/nelie-taylor/hello-coin`.

**Architecture:** One workflow file using the official Docker actions with GHA layer cache, plus a Dockerfile layer split so the cache actually helps, plus an `image:` name in docker-compose so `docker compose pull` works.

**Tech Stack:** GitHub Actions, docker/build-push-action@v6, GHCR, uv.

Spec: `docs/superpowers/specs/2026-09-01-github-actions-docker-build-design.md`

---

### Task 1: Dockerfile layer split + no dev deps

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1:** Replace `Dockerfile` with:

```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependency layer: only invalidated when the lockfile or project metadata changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8080

CMD ["uv", "run", "--no-sync", "hello-coin", "dashboard"]
```

- [ ] **Step 2:** In `docker-compose.yml`, add `image: ghcr.io/nelie-taylor/hello-coin:latest` under the `dashboard` service (keep `build: .`).
- [ ] **Step 3:** Verify: `docker compose build` succeeds; `docker compose up -d`; `Invoke-WebRequest http://localhost:8080/` returns 200.
- [ ] **Step 4:** Commit: `build: split Docker layers, drop dev deps, name image for GHCR pulls`

### Task 2: The workflow

**Files:**
- Create: `.github/workflows/docker-build.yml`

- [ ] **Step 1:** Create the file:

```yaml
name: docker-build

on:
  push:
    branches: [main, master]
    tags: ["v*"]
  workflow_dispatch:

permissions:
  contents: read
  packages: write

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: docker/setup-buildx-action@v3

      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/nelie-taylor/hello-coin
          tags: |
            type=ref,event=branch
            type=semver,pattern={{version}}
            type=sha
            type=raw,value=latest,enable=${{ github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master' }}

      - uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 2:** Commit: `ci: build and push Docker image to GHCR on push`
- [ ] **Step 3:** Hand off to the owner: pushing to GitHub triggers the first run (not done automatically — outward-facing).
