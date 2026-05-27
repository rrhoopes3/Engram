FROM python:3.12-slim

# Build args for non-root user (defaults to 1000:1000 to match typical host user like 'support' on VPS
# for seamless read/write on the mounted Brain vault volume without permission fixes).
ARG PUID=1000
ARG PGID=1000

WORKDIR /app

COPY README.md pyproject.toml .
COPY src/ ./src/
COPY healthcheck.py /app/healthcheck.py

RUN pip install --no-cache-dir .

# Create non-root user and fix ownership of app files (vault mount at runtime will match host UID/GID).
RUN set -eux; \
    groupadd -r -g ${PGID} brain || true; \
    useradd -r -u ${PUID} -g brain -d /app -s /bin/false brain || true; \
    chown -R ${PUID}:${PGID} /app || true

# Run as non-root (overridable via build args or runtime user in compose if needed)
USER ${PUID}:${PGID}

# Default: stdio (Grok TUI/local). Production (compose): override with `python -m engram_mcp.server http` for Streamable HTTP.
# Healthcheck: reuses the exact lightweight python -c + engram_health() pattern from README smoke tests.
# Calls the real tool (which does mandatory BRAIN.md read + vault rules + sleep status).
# "healthy" or ✅ in output => healthy container. Runs inside image (no host net needed).
# Healthcheck: dedicated probe (healthcheck.py) for correctness + single source of truth.
# Uses robust startswith("✅") (all success paths; avoids "healthy" substring in error strings like "unhealthy").
# Exec form (no shell). Reuses engram_health() (BRAIN.md first + sleep status). Centralizes logic.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]

CMD ["python", "-m", "engram_mcp.server"]