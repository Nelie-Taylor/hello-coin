FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY . .
RUN uv sync --frozen

EXPOSE 8080

CMD ["uv", "run", "hello-coin", "dashboard"]
