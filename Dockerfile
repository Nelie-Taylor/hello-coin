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
