# syntax=docker/dockerfile:1

# --- Claude Code CLI: powers the AI features with a Claude Pro/Max subscription.
# The npm package ships a native binary, so the final image needs no Node.js.
FROM node:22-slim AS claude-code
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
RUN ln -s /opt/claude-code/bin/claude.exe /usr/local/bin/claude && claude --version

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY nightcrawler ./nightcrawler
COPY config.example.yaml /config/config.yaml

RUN useradd --create-home --uid 10001 crawler \
    && mkdir -p /data/claude \
    && chown -R crawler:crawler /data
USER crawler
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8080\")}/health', timeout=4)"

ENTRYPOINT ["python", "-m", "nightcrawler"]
CMD ["serve"]
