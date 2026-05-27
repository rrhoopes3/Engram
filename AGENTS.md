# AGENTS.md — Engram + engram-mcp

This directory is the **Engram Personal Operating System (POS)** vault.

## Primary Intelligence Layer
- **Dedicated MCP server**: `engram-mcp` (registered via `grok mcp add`)
  - Location: `./engram-mcp/`
  - Tools: `engram_generate_morning_briefing`, `engram_process_capture`, `engram_trigger_sleep` (nightly consolidation), etc.
  - Always starts from `03 - SYSTEM/BRAIN.md`
  - Enforces strict 8-folder POS rules (never delete, archive with timestamp, etc.)
- Use `grok mcp doctor engram-mcp` and direct tool calls for automation.

## Production engram-mcp on VPS (Docker + HTTP — Recommended)
The persistent production instance runs as the `engram-mcp` Docker container (managed by systemd unit `engram-mcp.service`, Streamable HTTP on `http://localhost:8000/mcp`).

**To interact from Grok CLI / Build on the VPS (after one-time setup):**
```bash
grok mcp add engram-mcp --url http://localhost:8000/mcp --type streamable-http
grok mcp list
grok mcp doctor engram-mcp
```
- Then in any Grok session: "Call the engram_generate_morning_briefing tool (or any other) via the registered engram-mcp server. It will operate on the live vault at ${VAULT_PATH} and respect all POS rules."
- This is the live, always-running server (survives reboots). Prefer it over local stdio for day-to-day work on the VPS.
- The container uses the real vault volume + non-root user; all writes (GENERATED/, logs, archives) go through the strict Vault layer.
- 2026-05 hardening: `HEALTHCHECK` (via `engram_health`), structured HTTP request logs + strong localhost warnings in server.py, improved systemd (EnvironmentFile, signals, sleep/observability comments), + `03 - SYSTEM/scripts/backup-engram-vault.sh` for safe offsite (see Resilience subsection below + README).

See `engram-mcp/README.md` ("Production (VPS, Docker Compose + systemd — No N8N Required)") for full setup, .env, rebuild, logs (`journalctl -u engram-mcp`), smoke tests (now also `docker ps` healthy), and backup script. The systemd service + docker-compose.yml (in the engram-mcp/ dir, paired at runtime with gitignored .env) are the canonical production deployment.

## Resilience & Backups (VPS)
- Example safe offsite backup script: `03 - SYSTEM/scripts/backup-engram-vault.sh`
  - Always reads BRAIN.md first.
  - Logs every action to `03 - SYSTEM/logs/system-log.md` (exact vault convention).
  - Dry-run by default; explicit human "YES" gate for any real backup/push.
  - Supports restic (B2/S3) or simple tar+age/gpg + rclone/scp. Never deletes vault content.
  - Run: `./03\ -\ SYSTEM/scripts/backup-engram-vault.sh --help` (or --live after review).
- Wire to timer/cron only after first successful manual live test + BRAIN.md update.
- Complements the Docker HEALTHCHECK, systemd hardening, and structured HTTP logs added in 2026-05 production polish.

## Local Development / Native Fallback
- For ad-hoc Grok sessions in this vault, prefer the registered MCP tools.
- Future native Grok skills (if needed) would live under `03 - SYSTEM/skills/`.
- The MCP server is the approved Plan B path (VPS-deployable alongside N8N).
- (Fallback) Local stdio registration: `grok mcp add engram-mcp --command python --args "-m engram_mcp.server" --cwd /path/to/Engram`

## Key Rules for Any Agent / Grok Session
1. **Read BRAIN.md first** (03 - SYSTEM/BRAIN.md) — single source of truth.
2. Never delete — only archive to `07 - ARCHIVE/` with timestamp.
3. Respect the exact 8-folder structure. When in doubt: CAPTURE or GENERATED.
4. All automated changes must log to `03 - SYSTEM/logs/`.
5. Human review gate for any external comms or irreversible actions.

## Useful Commands
- `grok mcp list` / `grok mcp doctor engram-mcp`
- Invoke tools directly in prompts: "Call engram_generate_morning_briefing via the registered MCP server"
- Sleep cycle (manual): "Call engram_trigger_sleep with n_passes=2, scope=manual"
- Daily note: `01 - ACTIVE/daily/YYYY-MM-DD.md`
- First live artifact: `04 - GENERATED/briefings/2026-05-21-morning.md`
- Consolidated memory: `04 - GENERATED/consolidated/` (from nightly sleep)

*Primary runtime: dedicated grok-engram-mcp server (production HTTP on VPS). This file exists for local Grok TUI / Build compatibility and future native skill scaffolding.*
