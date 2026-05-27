# SKILL.md — Engram (Native Skill Scaffolding)

**Note:** The approved architecture for the Engram intelligence layer is the dedicated `engram-mcp` MCP server (Plan B — VPS + N8N). This file provides minimal scaffolding for local Grok native skill / agent fallback and development consistency.

## When to Use Native vs MCP
- **Primary (always-on automation):** `engram-mcp` tools called by N8N or Grok TUI (`engram_generate_morning_briefing` etc.)
- **Ad-hoc / local Grok sessions:** This vault root + registered MCP or direct file ops.
- Native skills (if implemented later) would expose similar high-level workflows as MCP tools.

## Current Native Entry Points (MCP-backed)
- Use the registered `engram-mcp` server for all POS workflows.
- See `engram-mcp/src/engram_mcp/server.py` and `vault.py` for implementation.
- BRAIN.md is always the first read.

## Future Native Skill Structure (Placeholder)
If a pure-native Grok skill is added:
- `03 - SYSTEM/skills/brain_pos.py` (or similar)
- Would re-use `engram_mcp/vault.py` for all I/O to guarantee rule compliance.
- Expose the same 5 workflows + any helpers.

## References
- `03 - SYSTEM/BRAIN.md` (law)
- `engram-mcp/README.md`
- `README.md` (vault overview)

*This SKILL.md ensures Phase 1 scaffolding completeness even under the dedicated-MCP path. No native code is active today.*
