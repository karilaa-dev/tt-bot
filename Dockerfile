FROM python:3.13-slim AS base

# Install uv by copying from official image (pin version for reproducibility)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install only dependency metadata first for better caching
COPY pyproject.toml ./

# Use a cache mount to speed up repeated builds, install deps only
RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync --no-install-project

# Now copy the rest of the project and sync fully
COPY . .

# Compile bytecode for faster startup in container
ENV UV_COMPILE_BYTECODE=1

RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync --no-editable

# Default command to run the bot
CMD ["uv", "run", "python", "main.py"]
