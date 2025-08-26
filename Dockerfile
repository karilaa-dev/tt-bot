# Base image with Python 3.13 and uv pre-installed on Debian Trixie slim
FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim

WORKDIR /app

# Leverage build cache: copy project metadata and lockfile first
COPY pyproject.toml uv.lock ./

# Install only dependencies into a project-managed virtualenv (.venv)
RUN uv sync --locked --no-install-project

# Copy the rest of the application source
COPY . .

# Install the project itself (editable by default)
RUN uv sync --locked

# Ensure the project venv executables are on PATH and unbuffer Python output
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Run the bot
CMD ["uv", "run", "main.py"]
