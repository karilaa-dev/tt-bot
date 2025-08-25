FROM python:3.13-slim AS base

# Install uv by copying from official image (pin version for reproducibility)
# Consider pinning to a specific tag or digest for fully reproducible builds, e.g.:
# COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /uvx /bin/
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install only dependency metadata first for better caching
# Include the lockfile so dependency layer rebuilds only when deps change
COPY pyproject.toml uv.lock ./

# Use copy link mode to improve caching when using a cache mount
ENV UV_LINK_MODE=copy
ENV UV_SYSTEM_PYTHON=1
ENV PYTHONDONTWRITEBYTECODE=1

# Use a cache mount to speed up repeated builds, install deps only
RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync --locked --no-install-project

# Now copy the rest of the project and sync fully
COPY . .

# Sync the full project (non-editable), then remove uv to slim the image
RUN --mount=type=cache,target=/root/.cache/uv \
	uv sync --locked --no-editable && \
	rm -f /bin/uv /bin/uvx

# Default command to run the bot
CMD ["python", "main.py"]
