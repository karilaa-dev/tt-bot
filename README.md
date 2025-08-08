# tt-bot

## Running with Docker

1. Build the image:
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

## Database Migration

If your existing database still contains the old advertising columns
(`latest_ad_shown` and `latest_ad_msgs`), you can remove them by running:

```bash
python migration/remove_ad_columns.py
```
