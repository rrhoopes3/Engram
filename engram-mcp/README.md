# engram-mcp

Grok-powered Model Context Protocol (MCP) server for the **Engram Personal Operating System**.

This is the intelligence layer of the Engram POS. It's a dedicated MCP server that any MCP-aware LLM client (Grok TUI, Claude Desktop, N8N's MCP node) can call on schedule or ad-hoc to operate on the vault under strict POS rules.

## Design Goals

- Runs on the same VPS as N8N (Docker recommended)
- Always starts from `BRAIN.md` (the single source of truth)
- Strictly enforces the 8-folder vault contract
- Implements the six autonomous workflows from the POS spec (morning briefing, capture, queue, weekly review, project health, nightly sleep)
- Human review gates for any external actions
- Full audit logging

## Tools Exposed

| Tool                              | Description                                      | Schedule (from spec)     |
|-----------------------------------|--------------------------------------------------|--------------------------|
| `engram_generate_morning_briefing` | Daily briefing (<300 words). **Idempotent:** skips if `{date}-morning.md` exists (non-empty); pass `force=true` to regenerate. | 6:00 AM daily            |
| `engram_process_capture`           | Empty 00-CAPTURE/, classify & file everything    | 8:00 PM daily            |
| `engram_process_queue`             | Handle VERB-*.md items in 05-QUEUE/              | Every 2 hours            |
| `engram_run_weekly_review`         | Sunday review + auto-update priorities           | Sunday 7:00 PM           |
| `engram_run_project_health_monitor`| Score projects, flag stalled work                | Monday 7:00 AM           |
| `engram_trigger_sleep`             | Recurrent offline passes → consolidated fast memory in GENERATED/consolidated/ | 03:00 AM nightly (or manual) |
| `engram_trigger_deep_sleep`        | **Optional** Bidirectional Evolutionary Search (BES) for higher-quality trajectory recombination + subgoal progress. Writes to consolidated/deep/. | Manual / weekends (advanced) |

## Development (local)

```bash
cd engram-mcp
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e .
engram-mcp                     # runs the stdio server
```

In another terminal you can test with the Grok TUI after registering it locally:

```bash
grok mcp add engram-mcp --command python --args "-m engram_mcp.server" --cwd /path/to/Engram
```

## Production (VPS, Docker Compose + systemd — No N8N Required)

This is the recommended path for a persistent, production-grade `engram-mcp` on your VPS. It runs the Streamable HTTP server (port 8000) against the real vault, fully usable by the Grok CLI (via `grok mcp add --url`) and ready for N8N later. No N8N installation needed.

**One-time VPS setup:**

1. Ensure Docker + Docker Compose plugin are installed (`docker --version` and `docker compose version`).

2. In the cloned repo:
   ```bash
   cd ${VAULT_PATH}/engram-mcp
   cp .env.example .env
   # .env already pre-populated for the canonical path ${VAULT_PATH} + PUID=1000
   # (edit only if your host UID differs: `id -u`)
   ```

3. Start the stack (builds image with non-root user, mounts vault, starts HTTP server):
   ```bash
   docker compose up -d --build
   docker compose ps
   docker compose logs --tail=20
   ```

4. Verify the HTTP endpoint is reachable:
   ```bash
   curl -I http://localhost:8000/mcp || true
   ss -tlnp | grep 8000
   ```

5. Install the systemd unit for boot persistence + easy ops:
   ```bash
   sudo cp engram-mcp.service /etc/systemd/system/engram-mcp.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now engram-mcp
   systemctl status engram-mcp
   journalctl -u engram-mcp -f   # follow logs
   ```

6. (Optional but recommended) Register the production HTTP server with the local Grok CLI (replaces or augments stdio registration):
   ```bash
   grok mcp add engram-mcp --url http://localhost:8000/mcp --type streamable-http
   grok mcp doctor engram-mcp
   ```
   Now Grok Build sessions on the VPS will call the real vault via the persistent server.

**Daily operations (systemctl or docker):**
- `sudo systemctl restart engram-mcp` (or `stop` / `start`)
- `journalctl -u engram-mcp -n 100 --no-pager`
- `docker compose -f ${VAULT_PATH}/engram-mcp/docker-compose.yml --env-file .env logs -f engram-mcp`
- After `git pull` or code edit in `engram-mcp/`:
  ```bash
  docker compose build
  sudo systemctl restart engram-mcp
  ```
- The service survives VPS reboot (enabled in systemd).

**Resilience & Backups (VPS production)**
- Example script: `03 - SYSTEM/scripts/backup-engram-vault.sh` (in the Engram vault root, not inside engram-mcp/).
  - BRAIN.md read first (POS contract). Exhaustive logging to `system-log.md`.
  - Dry-run default + interactive human "YES" gate before any real backup or offsite push.
  - restic (preferred: encrypted, deduped, to Backblaze B2 or S3) or tar + age/gpg example.
  - Never mutates the live vault (reads only; respects never-delete / archive-only).
  - Usage: `cd ${VAULT_PATH}; 03\ -\ SYSTEM/scripts/backup-engram-vault.sh --help`
  - Run manually first; only later consider systemd timer (after explicit approval + test live run + log review).
- This complements the Dockerfile `HEALTHCHECK` (powered by `engram_health()`), docker-compose healthcheck blocks, improved startup + uvicorn request logging in server.py, and systemd unit polish (all added 2026-05).

**Configuration (via `.env` — never hardcode vault path):**
- `BRAIN_VAULT_PATH` — host path to Engram vault root (mounted at `/vault` inside container)
- `PUID` / `PGID` — for the non-root container user (ensures writes succeed on volume)
- `MCP_PORT` — host port for the `/mcp` endpoint
- The `docker-compose.yml` in this directory is the committed lean production template (always used with the gitignored `.env` created from `.env.example`). The `engram-mcp.service` unit references the same pair. See comments in both files.

**Health & smoke tests (run after `docker compose up`):**
```bash
# Basic reachability + listening
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/mcp || echo " (GET may 405; connection proves server up)"

# Real tool smoke test inside the running container (uses real vault, enforces all POS rules)
docker compose exec -T engram-mcp python -c '
import os, sys
sys.path.insert(0, "/app/src")
os.environ["BRAIN_VAULT_PATH"] = "/vault"
from engram_mcp.server import engram_health, engram_generate_morning_briefing
print("=== engram_health ===")
print(engram_health())
print("\n=== engram_generate_morning_briefing (real vault interaction) ===")
print(engram_generate_morning_briefing()[:1200])
'
```
Expected: ✅ healthy (now also includes "Last sleep: ..." status), briefing generated to `04 - GENERATED/briefings/`, BRAIN.md read first, action logged to `03 - SYSTEM/logs/system-log.md`, no deletions.

**Morning briefing idempotency (N8N / cron):** `engram_generate_morning_briefing` skips when `04 - GENERATED/briefings/YYYY-MM-DD-morning.md` already exists, is non-empty, and contains the `# Morning Briefing — {date}` heading (`force=false` default). Re-running the 6:00 AM workflow is safe — you get a success message with the existing path. To regenerate after vault edits or a corrupt/empty/malformed file, call with `force=true`.

**Capture processor (N8N / cron):** `engram_process_capture` is idempotent on empty inbox — 0 items logs an explicit skip and writes no report. Items are filed via `vault.write_file()` then archived only on **successful** filing (originals stay in `00 - CAPTURE/` if filing fails). Reports use collision-safe `{date}-{HHMM}-capture-report.md` naming in `04 - GENERATED/summaries/` for same-day reruns.

**Healthcheck log discipline:** `engram_health` (Docker probe) reads BRAIN.md silently — no per-probe `read BRAIN.md` log lines. Per-tool vault path logging requires `ENGRAM_MCP_DEBUG_VAULT=1`; server startup always logs vault path once.

# Docker-native health (new in 2026-05 hardening)
docker ps --filter name=engram-mcp   # look for "healthy" in STATUS (powered by same engram_health + HEALTHCHECK in Dockerfile/compose)
docker compose ps
# Programmatic assert example in scripts/CI:
# docker compose ps --format json | jq -e '.[] | select(.Service=="engram-mcp" and .Health=="healthy")'
# Also visible in `systemctl status engram-mcp` (cross-check with journal for uvicorn access logs + startup messages)

# Manual verification of the centralized healthcheck.py probe (success + forced error):
# docker compose exec -T engram-mcp python /app/healthcheck.py   # should exit 0 + print ✅
# (To force unhealthy for testing: temporarily break the vault mount or BRAIN.md read inside a test container; the probe will exit 1 and Docker will report unhealthy.)
```

Also run the backup example (dry-run always safe):
```bash
03\ -\ SYSTEM/scripts/backup-engram-vault.sh --help
03\ -\ SYSTEM/scripts/backup-engram-vault.sh     # BRAIN.md first, logs, full plan, zero side effects
```

**Local / dev (stdio mode) still supported:**
- `cd engram-mcp && python -m engram_mcp.server` (or `pip install -e . && engram-mcp`)
- Register locally if needed: `grok mcp add engram-mcp --command python --args "-m engram_mcp.server" --cwd /path/to/Engram`
- Use for TUI/dev before switching to the HTTP production instance.

The HTTP production server is the primary runtime for all automation and Grok CLI work on the VPS. N8N can be layered on later using the same `http://engram-mcp:8000/mcp` (or localhost:8000 from host).

## Relationship to the Vault

The server expects to be pointed at an Engram vault root (the directory containing `00 - CAPTURE/`, `01 - ACTIVE/`, ..., `03 - SYSTEM/BRAIN.md`, etc.).

It never deletes — only moves to `07 - ARCHIVE/` with timestamps.

## Status

- **6 tools**: 3 full implementations (`engram_generate_morning_briefing`, `engram_process_capture`, `engram_trigger_sleep`) + 3 vault-enforced stubs (`engram_process_queue`, `engram_run_weekly_review`, `engram_run_project_health_monitor`) that emit `NEEDS HUMAN INPUT` until enriched.
- **Two transports**: stdio (local dev / Grok TUI) and Streamable HTTP on `:8000/mcp` (production, N8N-callable).
- **Hardened**: non-root Docker, Dockerfile `HEALTHCHECK` (powered by `engram_health()`), structured logging, systemd unit, example backup script.

See the parent [README](../README.md) and [BRAIN.md](../03%20-%20SYSTEM/BRAIN.md) for the full POS specification.