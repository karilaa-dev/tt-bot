FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cache layer)
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# Copy application code
COPY tiktok_scrapper/ tiktok_scrapper/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "tiktok_scrapper.app:app", "--host", "0.0.0.0", "--port", "8000"]
