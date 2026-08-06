FROM oven/bun:1.3.14-alpine

WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --production

COPY tsconfig.json ./
COPY migrations ./migrations
COPY locales ./locales
COPY src ./src

USER bun
CMD ["bun", "run", "src/main.ts"]
