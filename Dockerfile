# syntax=docker/dockerfile:1

# --- Claude Code CLI: powers the AI features with a Claude Pro/Max subscription.
# The npm package ships a native binary, so the final image needs no Node.js.
FROM node:25-slim AS claude-code
RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

# --- nightcrawler -------------------------------------------------------------
FROM python:3.12-slim

LABEL org.opencontainers.image.title="nightcrawler" \
      org.opencontainers.image.description="Self-hosted crawler for new & used products with Geizhals-style filters and Claude-powered AI" \
      org.opencontainers.image.source="https://github.com/hoody424/nightcrawler" \
      org.opencontainers.image.licenses="GPL-3.0-only"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NIGHTCRAWLER_DB=/data/nightcrawler.db \
    NIGHTCRAWLER_CONFIG=/config/config.yaml \
    CLAUDE_CONFIG_DIR=/data/claude \
    DISABLE_AUTOUPDATER=1 \
    PORT=8080

COPY --from=claude-code /usr/local/lib/node_modules/@anthropic-ai/claude-code /opt/claude-code
RUN /opt/claude-code/bin/claude.exe --version

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY nightcrawler ./nightcrawler
COPY config.example.yaml /config/config.yaml

# The container starts as root only to apply PUID/PGID and fix /data ownership
# (bind mounts on NAS systems such as Unraid), then runs as the crawler user.
RUN useradd --create-home --uid 10001 crawler \
    && mkdir -p /data/claude \
    && chown -R crawler:crawler /data
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --chmod=755 docker-claude.sh /usr/local/bin/claude
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8080\")}/health', timeout=4)"

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve"]
