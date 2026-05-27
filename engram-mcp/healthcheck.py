"""
engram-mcp dedicated Docker / compose healthcheck probe.

Purpose: Single source of truth for container health (used by Dockerfile HEALTHCHECK
and docker-compose healthcheck: blocks). Solves prior duplication + fragile substring
predicate bug ("healthy" appears inside error strings containing "unhealthy").

- Reuses the existing engram_health() tool (mandatory BRAIN.md read + vault rules + sleep status).
- Robust success test: startswith("✅")  (all real success paths use this; errors use "❌").
- Exits 0 (healthy) / 1 (unhealthy) for Docker.
- Minimal, no new runtime deps. Runs as the non-root user inside the image.

This is the canonical probe for `docker ps`, `docker compose ps`, and systemd monitoring.
"""

import os
import sys

# Match the exact environment the container and smoke tests use
sys.path.insert(0, "/app/src")
os.environ.setdefault("BRAIN_VAULT_PATH", "/vault")

from engram_mcp.server import engram_health

h = engram_health()
print(h)

# Robust predicate (replaces the previous fragile 'healthy' in lower() test)
sys.exit(0 if h.startswith("✅") else 1)
