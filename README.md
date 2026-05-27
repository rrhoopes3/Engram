# 🧠 Engram

> **A personal OS that sleeps to remember.**

An open architecture for a self-maintaining productivity OS — Obsidian vault + dedicated MCP server (`engram-mcp`) + N8N automation, with nightly memory consolidation passes inspired by *"Language Models Need Sleep"* (AlphaXiv 2605.26099).

The system operates whether or not you touch it. Three layers — Storage, Intelligence, Automation. Remove any one and you have a tool, not an OS.

---

## What makes it different

- **Eight folders. Forever.** No sprawl, no taxonomy debates, no "where does this go?"
- **Sleep cycles.** Nightly recurrent passes compress recent context into dense Fast Memory Blocks — the LLM equivalent of memory consolidation during sleep.
- **BRAIN.md as the brain stem.** Every workflow, every tool call, every session starts by reading one file. One edit propagates intelligence everywhere.
- **Never delete.** Everything moves to `07 - ARCHIVE/` with timestamps. Recovery is always possible.
- **Survives bad days.** Anti-overwhelm flow is built in. The OS keeps running when you can't.

---

## Vault Structure (strict — no exceptions)

| Folder            | Purpose                                      | Notes |
|-------------------|----------------------------------------------|-------|
| `00 - CAPTURE/`   | Everything unprocessed (true inbox)          | Zero decisions here |
| `01 - ACTIVE/`    | Only what is alive *right now*               | `projects/`, `areas/`, `daily/` |
| `02 - RESOURCES/` | Reference only (never action)                | research, references, templates |
| `03 - SYSTEM/`    | The OS itself                                | **BRAIN.md** (read first), workflows, logs |
| `04 - GENERATED/` | engram-mcp / LLM outputs only                | briefings, summaries, analyses, consolidated |
| `05 - QUEUE/`     | Tasks for engram-mcp to process              | `VERB-topic.md` naming (e.g. `RESEARCH-foo.md`) |
| `06 - CALENDAR/`  | Time-based items                             | events, reviews |
| `07 - ARCHIVE/`   | Completed or outdated (never delete)         | Timestamped moves only |

**Rule:** Every piece of content lives in exactly one place. When in doubt → `CAPTURE` or `GENERATED`.

---

## The Six Autonomous Workflows

Ready-to-import N8N JSON workflows live at `03 - SYSTEM/workflows/n8n/`. All run on schedule via N8N's built-in MCP Client node against the `engram-mcp` HTTP server. Output to `GENERATED/`. Every action logged via the vault layer.

| # | Workflow                  | Schedule         | What it does |
|---|---------------------------|------------------|--------------|
| 1 | Daily Morning Briefing    | 6:00 AM          | BRAIN.md + yesterday's daily + calendar → "Most Important Today" (<300 words) |
| 2 | Capture Processor         | 8:00 PM          | Empties `CAPTURE/`, classifies, files, archives originals |
| 3 | Weekly Review Generator   | Sun 7:00 PM      | 7-day synthesis → Wins, Stalls, Patterns, next 3 priorities |
| 4 | Queue Processor           | Every 2 hours    | Processes `VERB-topic.md` items in `QUEUE/`, archives when done |
| 5 | Project Health Monitor    | Mon 7:00 AM      | Scores active projects, creates `REVIEW-*.md` for stalled work |
| 6 | Nightly Sleep Cycle       | 3:00 AM          | Recurrent passes compress recent context → Fast Memory Blocks in `consolidated/` |

---

## Quick Start

1. **Clone and open as Obsidian vault.**
   ```bash
   git clone https://github.com/rrhoopes3/Engram.git
   ```
2. **Customize `03 - SYSTEM/BRAIN.md`** — fill in identity, life areas, active projects, top 3 priorities (5 minutes).
3. **Install engram-mcp** — see [`engram-mcp/README.md`](engram-mcp/README.md) for Docker + systemd production setup, or local Python install for dev:
   ```bash
   cd engram-mcp && pip install -e .
   ```
4. **Register with your LLM client** (Grok TUI, Claude Desktop, any MCP-aware tool):
   ```bash
   grok mcp add engram-mcp --command python --args "-m engram_mcp.server"
   ```
5. **First tool call:**
   ```
   Call engram_generate_morning_briefing — it will read BRAIN.md and write to 04 - GENERATED/briefings/.
   ```
6. **(Optional) Wire N8N** to automate the six workflows on schedule. See [`03 - SYSTEM/workflows/n8n/README.md`](03%20-%20SYSTEM/workflows/n8n/README.md).

---

## Architecture

```
┌─────────────────────────────────────────────┐
│            03 - SYSTEM/BRAIN.md             │  ← read first by every operation
└────────────────────┬────────────────────────┘
                     │
       ┌─────────────┴─────────────┐
       ▼                           ▼
  ┌──────────┐              ┌─────────────┐
  │  Vault   │◄────────────►│ engram-mcp  │  ← MCP server (Python, FastMCP)
  │ (8 dirs) │   strict     │   tools     │     enforces all POS rules
  └────┬─────┘   rules      └──────┬──────┘
       │                           │
       │                           ▼
       │                    ┌─────────────┐
       └───────────────────►│     N8N     │  ← 6 scheduled workflows
                            └─────────────┘
```

- **Storage:** Obsidian-compatible Markdown vault, git-versioned.
- **Intelligence:** [`engram-mcp`](engram-mcp/) — an MCP server that exposes high-level tools (`engram_generate_morning_briefing`, `engram_trigger_sleep`, etc.) any MCP client can call.
- **Automation:** N8N (self-hostable on a $5 VPS via Docker) — calls the MCP server on schedule.

---

## Sleep Cycles — the distinctive feature

Inspired by the "Language Models Need Sleep" preprint, `engram_trigger_sleep` runs nightly:

1. **Collect** recent context — last N daily notes, recent briefings, QUEUE items, ARCHIVE samples, system log tail, full BRAIN.md.
2. **N recurrent passes:**
   - *Pass 1:* Extract entities, dates, projects, themes, facts.
   - *Pass 2:* Cross-source connections and patterns.
   - *Pass 3+:* Compress into dense Fast Memory Blocks (Knowledge Atoms, Cross-Day Synthesis, Priority Evolution, Signals).
3. **Write** a single timestamped artifact to `04 - GENERATED/consolidated/`.
4. **Propose** exact BRAIN.md deltas — but **never auto-write** to BRAIN.md (human review gate).

Subsequent tool calls "wake up" — they read fresh live state plus the consolidated index, keeping real-time inference lean.

The v1 passes are deterministic (no LLM call required). When `XAI_API_KEY` is configured, passes upgrade to true recurrent Grok calls for richer abstraction.

---

## Operating Rules (Non-Negotiable)

- **Never Delete** — everything moves to `07 - ARCHIVE/` with timestamps.
- **BRAIN.md is Law** — read first, always. One file drives everything.
- **Capture Safety Net** — zero decisions at capture time. Drop and forget.
- **Human Review Gate** — engram-mcp never sends external comms or makes irreversible changes without a `NEEDS HUMAN INPUT` flag.
- **8 folders forever** — no new top-level folders, ever.
- **Everything logged** — every automated action appends to `03 - SYSTEM/logs/system-log.md`.

Full rules in [`03 - SYSTEM/BRAIN.md`](03%20-%20SYSTEM/BRAIN.md) §6.

---

## Repo Layout

```
Engram/
├── 00 - CAPTURE/  …  07 - ARCHIVE/      ← the vault (your data)
├── engram-mcp/                          ← the MCP server (Python)
│   ├── src/engram_mcp/                  ← server.py, vault.py, sleep.py
│   ├── tests/                           ← pytest suite
│   ├── docker-compose.example.yml       ← production HTTP deployment
│   ├── Dockerfile + healthcheck.py
│   └── README.md                        ← full deployment guide
├── 03 - SYSTEM/
│   ├── BRAIN.md                         ← the brain stem
│   ├── workflows/n8n/                   ← 7 importable N8N workflows
│   └── scripts/backup-engram-vault.sh   ← restic-based offsite backup
├── AGENTS.md                            ← instructions for LLM agents
└── README.md                            ← you are here
```

---

## Status

v1.0 — vault contract finalized, engram-mcp shipping (production Docker + systemd + Streamable HTTP), all 7 N8N workflows importable, Sleep Cycles implemented.

Three of the six workflow tools are full implementations (morning briefing, capture processor, sleep cycle); the other three (weekly review, queue processor, project health monitor) are stubs with vault-enforced guardrails — replace heuristics with richer LLM calls as needed.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgements

- *"Language Models Need Sleep"* (AlphaXiv 2605.26099) — the sleep-cycle architecture.
- [Anthropic's MCP](https://modelcontextprotocol.io/) — the protocol that makes engram-mcp portable across LLM clients.
- The PARA method (Tiago Forte) and the broader PKM community — folder-discipline ideas distilled into the 8-folder contract.
