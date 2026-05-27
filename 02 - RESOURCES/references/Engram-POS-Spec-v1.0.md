Personal Operating System (POS) Specification
Obsidian + Grok (via dedicated engram-mcp MCP server) + N8N
Version 1.0 | Concise Build Spec (original Claude path evolved to Plan B: grok-engram-mcp dedicated server)
Source: @cyrilXBT thread (May 2026); updated for Grok implementation 2026-05-21
1. Purpose & Design Goals
Build a self-maintaining productivity operating system that:

Survives bad days (no guilt, no backlog panic)
Eliminates manual maintenance burden
Keeps complexity fixed (8 folders, no sprawl)
Adds intelligence (Claude reasons over your life data)
Runs autonomously via automation

Core Principle: The system operates whether or not you touch it.
2. Three-Layer Architecture

























LayerComponentRole1. StorageObsidian vault (plain Markdown)Permanent, human + machine-readable data layer2. IntelligenceGrok via dedicated engram-mcp (VPS MCP server, Plan B)Reads vault (always BRAIN.md first), generates via workflows, updates files per rules3. AutomationN8N (self-hosted on $5 VPS)Cron schedules, triggers, engram-mcp tool calls, file movement — zero manual intervention
Remove any layer → you get a tool, not an OS.
3. Vault Structure (Strict — Every Note in Exactly One Folder)
text00 - CAPTURE/          ← Everything unprocessed (inbox)
01 - ACTIVE/           ← Only what is alive *now*
   projects/[name]/    (overview.md + tasks/ + notes/ + outputs/)
   areas/              (health | finances | relationships | learning | career)
   daily/[YYYY-MM-DD].md
02 - RESOURCES/        ← Reference only (research/ | references/ | templates/ | bookmarks/)
03 - SYSTEM/           ← OS itself (BRAIN.md + skills/ + workflows/ + logs/)
04 - GENERATED/        ← engram-mcp / Grok outputs only (briefings/ | summaries/ | analyses/ | drafts/)
05 - QUEUE/            ← Tasks for engram-mcp (name: VERB-topic.md e.g. RESEARCH-xxx.md)
06 - CALENDAR/         ← Time-based (events/ | reviews/)
07 - ARCHIVE/          ← Completed/outdated (never delete)
Rule: No overlaps. No optional folders. When in doubt → CAPTURE or GENERATED.
4. BRAIN.md — Single Source of Truth (formerly CLAUDE.md)
One file. Update Mondays (5 min). Every workflow / engram-mcp tool reads it first.
Required Sections:

Identity (Name, Role, Location)
Life Areas & Current Status (Health / Finances / Relationships / Learning / Career)
Active Projects (Name | 1-sentence desc | Status | Next Action)
Current Priorities (Top 3 this week — update every Monday)
Standards for Generated Content (Voice, Format prefs, What to avoid)
Operating Rules (Never delete — archive with timestamp; Never send comms without human review; Always date-stamp YYYY-MM-DD; Log to SYSTEM/logs/)
Update Schedule

5. The Five Automated Workflows (N8N + engram-mcp / Grok)
All run on schedule. Output to GENERATED/. Log actions. (Originally designed for Claude; now implemented in dedicated engram-mcp server)

Daily Morning Briefing (6:00 AM)
Reads BRAIN.md + yesterday’s daily note + calendar.
Generates: Most Important Today | Schedule | Open Loops | Project Pulse | Weekly Focus (Mondays).
< 300 words. Saves: GENERATED/briefings/[DATE]-morning.md
Capture Processor (8:00 PM daily)
Empties 00 - CAPTURE/. Classifies each item (TASK / IDEA / REFERENCE / NOTE / EVENT). Files correctly. Moves original to ARCHIVE. Logs to SYSTEM/logs/capture-log.md
Weekly Review Generator (Sunday 7:00 PM)
Analyzes 7 days of daily notes + modified projects + BRAIN.md.
Produces: Wins | Stalls + reasons | Pattern/Insight | Next Week’s 3 Priorities | One Open Decision.
Auto-updates BRAIN.md priorities. Saves: GENERATED/summaries/[DATE]-weekly-review.md
Queue Processor (every 2 hours)
Processes any file in 05 - QUEUE/. Uses filename verb + content. Leverages SYSTEM/skills/ if available. Outputs to GENERATED/. Archives queue file. Flags “NEEDS HUMAN INPUT” when required.
Project Health Monitor (Monday 7:00 AM)
Scores every active project (On Track / At Risk / Stalled / Blocked) with evidence. Flags >7 days no activity → creates REVIEW-[project].md in QUEUE. Saves health report to GENERATED/briefings/.

6. Anti-Breakdown Mechanisms (Why It Never Dies)

Capture Safety Net — Zero decisions at capture time.
Never-Delete Rule — Everything moves to ARCHIVE. Storage is infinite; daily operation never touches it.
BRAIN.md Single Source — One update propagates to every workflow automatically.

7. One-Weekend Build Order



































Day/TimeTaskTimeSaturday AMCreate 8 folders + populate BRAIN.md + 1 project overview.md2 hSaturday PMGrok + engram-mcp skeleton + local TUI test + first workflow impl1 hSaturday EveDrop 1 real task in QUEUE → review output30 minSunday AMInstall N8N → build & schedule Morning Briefing workflow2 hSunday PMAdd remaining 4 workflows2 h
Total: ~7.5 hours → fully operational Sunday evening.
8. Tech Stack & Prerequisites

Obsidian (free, local)
Grok (via dedicated engram-mcp MCP server on VPS or local TUI for dev; replaces original Claude Desktop path)
N8N (self-hosted on $5/mo VPS recommended for reliable cron)
Git (optional but recommended for vault versioning)

9. Success Metrics (After 90 Days)

Morning briefing arrives before you open laptop
CAPTURE folder empties every evening automatically
Weekly review appears Sunday night with next priorities already in BRAIN.md
Stalled projects flagged before they become crises
System ran through vacations, sickness, and chaos without manual intervention

Build the foundation this weekend. The OS runs from the first morning it is live.

File saved to: /home/workdir/artifacts/POS-Spec-v1.0.md (full Markdown version with exact prompts ready for copy-paste into N8N/Claude).
Ready to implement? Drop the first file in QUEUE tonight.what’s N8N?N8N (pronounced “n-eight-n”) is an open-source workflow automation platform — think of it as a self-hosted, more powerful, and developer-friendly alternative to Zapier or Make.com.
What it does
You build visual workflows (called “workflows” in n8n) by connecting nodes. Each node performs an action:

Trigger a workflow on a schedule (cron)
Call an API (like Claude)
Read/write files
Move or rename files in your Obsidian vault
Send emails, Slack messages, etc.
Run custom JavaScript or Python code

It has 400+ native integrations and excellent support for AI/LLM nodes (perfect for calling Claude via API).
Why it’s used in the Personal OS spec
In the Obsidian + Claude system I described earlier, N8N is the Automation Layer. It runs all five workflows on autopilot:

6:00 AM → Daily Morning Briefing
8:00 PM → Capture Processor
Every 2 hours → Queue Processor
Sunday 7:00 PM → Weekly Review
Monday 7:00 AM → Project Health Monitor

It handles the scheduling, calls Claude with the right prompts, reads/writes files in your vault via the Filesystem MCP, and moves things between folders — all without you lifting a finger.
Key advantages for this use case

Self-hostable on a cheap $5/month VPS (or even locally)
Fair-code / open source (you own your data and workflows)
Cron + webhook triggers built-in
AI-native — easy to plug in Claude, OpenAI, etc.
File system nodes — perfect for manipulating your Obsidian vault
Visual editor + code when you need it

Quick start options

Easiest for the spec: Sign up at n8n.cloud (free tier available, paid plans start low)
Recommended for full control: Self-host on a $5 DigitalOcean / Hetzner / Railway VPS using Docker (takes ~10 minutes)