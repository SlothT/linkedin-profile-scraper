FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --frozen --no-dev

COPY fixtures/profile_sample.json fixtures/profile_rich_sample.json ./fixtures/

ENV PATH="/app/.venv/bin:$PATH"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
