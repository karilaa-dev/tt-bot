FROM oven/bun:1.3.13-alpine

WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY tsconfig.json ./
COPY migrations ./migrations
COPY locales ./locales
COPY src ./src
COPY scripts ./scripts
COPY tests ./tests

USER bun
CMD ["bun", "run", "src/main.ts"]
