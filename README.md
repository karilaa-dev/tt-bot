# tt-bot

## Running with Docker

1. Build the image (uses uv for dependency management):
   ```bash
   docker build -t tt-bot .
   ```
2. Create a `.env` file based on `.env.example` and fill in the required settings.
3. Run the container with the environment file:
   ```bash
   docker run --rm --env-file .env tt-bot
   ```

## Docker Compose

To run the bot and an optional PostgreSQL database with Docker Compose:

```bash
docker compose up
```

Only the bot service will start if you specify it explicitly:

```bash
docker compose up bot
```

The Compose file also defines a PostgreSQL service. You can override its
default credentials by setting `POSTGRES_USER`, `POSTGRES_PASSWORD`, and
`POSTGRES_DB` in your `.env` file or in the environment when launching
Compose.

## Local development with uv

This project uses uv for dependency management. To run locally without Docker:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Ensure ~/.local/bin is on your PATH, then:
uv sync
uv run python main.py
```
