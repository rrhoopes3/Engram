# Brain - Personal Operating System (POS) — Project Overview

**Status:** Active — Foundation Phase  
**Started:** 2026-05-21  
**Last Updated:** 2026-05-21  
**Owner:** [You]  
**Next Action:** Complete N8N workflow deployment and first live morning briefing

---

## One-Sentence Description

Build and perpetually operate a self-maintaining Personal Operating System (Obsidian vault + Grok via dedicated `engram-mcp` server on VPS + N8N automation) that eliminates manual maintenance, survives bad days without guilt or backlog panic, and keeps complexity permanently fixed at 8 folders while adding autonomous intelligence over your life data.

---

## Goals & Success Metrics (90 Days)

- Morning briefing arrives automatically before you open your laptop every day.
- `00 - CAPTURE/` empties itself every evening with zero manual effort.
- Weekly review generates itself Sunday night and auto-updates priorities in BRAIN.md.
- Stalled projects are flagged proactively (Project Health Monitor) before they become crises.
- The entire system continues running through vacations, sickness, travel, and chaos with zero manual intervention.
- You feel zero "backlog anxiety" because the OS is trusted and always current.

---

## Current Phase: One-Weekend Build (Target: Fully Operational Sunday Evening)

| Day          | Focus                              | Key Deliverables                                      | Status    |
|--------------|------------------------------------|-------------------------------------------------------|-----------|
| Saturday AM  | Vault + BRAIN.md + first project  | 8 folders + BRAIN.md v1 + Engram overview.md     | Complete  |
| Saturday PM  | Grok + engram-mcp dev test          | Local MCP server skeleton + vault layer + morning briefing impl + TUI test       | In Progress |
| Saturday Eve | First real QUEUE task              | Drop 1 authentic task into QUEUE; review output       | Pending   |
| Sunday AM    | N8N setup + Morning Briefing       | N8N installed/self-hosted; first cron workflow live   | Pending   |
| Sunday PM    | Remaining 4 workflows              | Capture, Weekly Review, Queue, Project Health Monitor scheduled | Pending   |

**Total effort target:** ~7.5 hours → live system Sunday evening.

---

## Architecture (Three Layers — Remove Any = Just a Tool, Not an OS)

1. **Storage Layer** — Obsidian vault (plain Markdown files, git-versioned). Human + machine readable. This repo.
2. **Intelligence Layer** — Grok via dedicated `engram-mcp` MCP server (Plan B: standalone deployable on VPS) that reads the entire vault (always starting from BRAIN.md), reasons, generates outputs via workflows, and safely updates files per strict POS rules.
3. **Automation Layer** — N8N (self-hosted on cheap VPS or local) running 5 scheduled workflows that call engram-mcp tools (via stdio/MCP), read/write the vault, move items between folders, and log everything.

---

## Key Constraints (The "Never Dies" Rules)

- Strict 8-folder structure. No sprawl. When in doubt: CAPTURE or GENERATED.
- Never delete — archive only.
- BRAIN.md is the single source of truth read by every workflow / engram-mcp tool.
- Zero decisions at capture time.
- All automation logs to `03 - SYSTEM/logs/`.
- Human approval gate for any external action.

---

## Subsystems & Locations

- **Daily Notes:** `01 - ACTIVE/daily/YYYY-MM-DD.md`
- **Areas (ongoing responsibility):** `01 - ACTIVE/areas/{health,finances,relationships,learning,career}/`
- **Reference Material:** `02 - RESOURCES/`
- **System / OS itself:** `03 - SYSTEM/` (this overview lives under the Engram project, BRAIN.md lives in SYSTEM)
- **Grok / engram-mcp Outputs:** `04 - GENERATED/{briefings,summaries,analyses,drafts}/`
- **Grok / engram-mcp Work Items:** `05 - QUEUE/VERB-topic.md`
- **Time-based:** `06 - CALENDAR/`
- **Everything Historical:** `07 - ARCHIVE/`

---

## Immediate Next Steps (This Week)

1. Implement vault.py layer + first real `engram_generate_morning_briefing` in engram-mcp; register & test end-to-end from local Grok TUI (writes real briefing to vault).
2. Drop a real "RESEARCH-..." or "PLAN-..." item into QUEUE tonight.
3. Provision N8N (n8n.cloud trial or $5 VPS Docker) and wire the Morning Briefing workflow to call engram-mcp first.
4. Implement the other four workflows in engram-mcp.
5. Add a `.gitignore` and initial commit of the vault foundation to GitHub (already done for early files).
6. Create first real daily note for today (done).

---

## Risks & Mitigations

- **N8N reliability / cron on local machine:** → Prefer cheap VPS ($5 Hetzner/Railway/DO) with Docker for always-on.
- **MCP / server path / permissions:** → Use explicit BRAIN_VAULT_PATH env or parent-dir detection. Test small first. Keep manual override.
- **Scope creep / folder explosion:** → Ruthless adherence to the 8-folder rule. Any new category must map into existing.
- **Context / token limits on large vault:** → Workflows use targeted reads (BRAIN.md + recent dailies + specific project) not full vault dump.
- **Motivation drop:** → The system itself is designed to carry you on bad days. Trust the automation.

---

**This project is the meta-project: building the OS that will manage all other projects.**

*Next review: During first Weekly Review workflow (Sunday 7 PM target).*

---
*Updated as part of Grok + engram-mcp implementation phase — 2026-05-21*