"""
engram-mcp — Grok-powered MCP server for the Engram Personal Operating System.

This server exposes high-level Brain workflow tools that N8N (or any MCP client)
can call on schedule. It is designed to run on a VPS alongside N8N.

Supports two modes:
- stdio (default): for Grok TUI / local clients
- HTTP (python -m engram_mcp.server http): Streamable HTTP for production (Docker on VPS, Grok CLI --url registration, N8N)

When a workflow tool is invoked, the server always starts from BRAIN.md and
strictly enforces the 8-folder POS rules (via the Vault layer). v1 uses
deterministic generation from vault state; future iterations can integrate
xAI Grok API calls for richer synthesis.

Key tools:
- engram_generate_morning_briefing: daily briefing from BRAIN.md + daily note + calendar.
- engram_process_capture: classify + file + archive (never-delete) from 00-CAPTURE/.
- engram_health: lightweight readiness probe (BRAIN.md read + vault status + last sleep + last *deep* sleep).
- engram_trigger_sleep(...): fast recurrent consolidation (default nightly).
- engram_trigger_deep_sleep(generations=4, population_size=6, scope="deep-manual", dry_run=False):
  Optional Bidirectional Evolutionary Search (BES) mode for richer trajectory recombination.
  Writes to 04 - GENERATED/consolidated/deep/. Still full rule compliance + human gate on BRAIN proposals.
- Stubs: engram_process_queue, engram_run_weekly_review, engram_run_project_health_monitor (emit NEEDS HUMAN INPUT).

All production deploys use the hardened Docker + systemd setup (localhost-only :8000 in compose).
"""

from __future__ import annotations

from datetime import datetime

try:
    from mcp.server.fastmcp import FastMCP
    # Host 0.0.0.0 + port 8000 for production HTTP exposure; ignored for stdio.
    # streamable_http_path matches the /mcp endpoint used by clients and N8N.
    mcp = FastMCP("engram-mcp", host="0.0.0.0", port=8000, streamable_http_path="/mcp")
except ImportError:
    mcp = None

# Real vault layer (strict POS rules — always BRAIN.md first, archive-only, 8-folder enforcement)
from .vault import Vault, VaultError, get_vault

# Sleep Cycles (memory consolidation via recurrent passes — "Language Models Need Sleep")
# + Deep Sleep (BES) — optional higher-quality evolutionary mode
from .sleep import (
    trigger_sleep_cycle,
    get_last_sleep_status,
    trigger_deep_sleep_cycle,
    get_last_deep_sleep_status,
)


# Create the MCP server using the modern FastMCP SDK (compatible with current mcp package)
if mcp is None:
    class _NoMCP:
        def tool(self):
            def deco(f):
                return f
            return deco
    mcp = _NoMCP()


def _extract_section(text: str, heading: str) -> str:
    """
    Improved section extractor. Looks for markdown headings containing the key phrase.
    Captures until next heading. Truncates long sections for briefing.
    """
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if heading.lower() in stripped.lower() and (stripped.startswith(('#', '##', '###', '**', '|', '-')) or stripped.startswith('##')):
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    out_lines = []
    for line in lines[start_idx:]:
        s = line.strip()
        if s.startswith(('#', '##', '###')) and out_lines:
            break
        out_lines.append(line)
    result = "\n".join(out_lines).strip()
    # Truncate sensibly for briefing context
    if len(result) > 600:
        result = result[:600].rsplit('\n', 1)[0] + "\n..."
    return result


def _generate_morning_briefing_text(vault: Vault, target_date: str) -> str:
    """
    Deterministic v1 morning briefing generator.
    Always starts by reading BRAIN.md (enforced by Vault layer).
    Extracts key live data (priorities, projects, daily top items, open loops)
    and produces clean, concise, standards-compliant output (<300 words target).
    No dev-time narrative, no stale tool names, timeless.
    Future versions will augment with xAI Grok calls for richer synthesis.
    """
    brain = vault.read_brain_md()  # NON-NEGOTIABLE — enforced + logged
    yesterday = vault.get_yesterday_date()
    daily = vault.read_daily_note(yesterday)
    cal = vault.read_calendar_for_date(target_date)

    # Live extracts (improved extractor)
    priorities = _extract_section(brain, "Current Priorities") or _extract_section(brain, "Priorities")
    active_projects = _extract_section(brain, "Active Projects")
    life_areas = _extract_section(brain, "Life Areas")
    daily_top3 = _extract_section(daily, "Top 3 Today") or _extract_section(daily, "**Top 3")
    daily_open = _extract_section(daily, "Open Loops") or _extract_section(daily, "Capture")

    # Clean, professional briefing per BRAIN.md §5 (voice, structure, no fluff)
    briefing = f"""# Morning Briefing — {target_date}

**Most Important Today**  
{daily_top3 or "Review BRAIN.md priorities and advance the top active project task. Zero decisions in CAPTURE; focus on scheduled work."}

**Schedule & Context**  
- Yesterday: {yesterday} daily reviewed  
- Today focus: BRAIN.md priorities + any CALENDAR items  
{cal if cal and "No calendar" not in cal else "- No specific calendar events for today."}

**Open Loops & Capture**  
{daily_open or "- No open items reported in yesterday's daily. Drop new items into 00 - CAPTURE/ or 05 - QUEUE/ at any time."}

**Project Pulse** (from BRAIN.md)  
{active_projects[:450] or "See full table in BRAIN.md §3. Only projects with clear next actions remain in ACTIVE."}

**Life Areas Snapshot**  
{life_areas[:350] or "Health / Finances / Relationships / Learning / Career — update during Monday review."}

**Weekly Priorities Reminder** (BRAIN.md §4)  
{priorities[:550] or "Update every Monday. Current top items drive all automation."}

---
**Rules honored this run:** BRAIN.md read first. Never-delete (archive only). Strict 8-folder contract. All actions logged to SYSTEM/logs/. Human review gate respected for external actions.

*Generated via engram-mcp (Grok layer) • Full file: 04 - GENERATED/briefings/{target_date}-morning.md*
"""

    return briefing.strip()



# ============================================================
# Tool Implementations (FastMCP style — modern SDK)
# ============================================================

@mcp.tool()
def engram_generate_morning_briefing(date: str = "") -> str:
    """
    Generate the daily morning briefing (<300 words target).
    Always reads BRAIN.md first, pulls yesterday's daily note + calendar,
    writes the result to 04 - GENERATED/briefings/YYYY-MM-DD-morning.md
    using the strict vault access layer (never-delete, logging, etc).

    Args:
        date: YYYY-MM-DD (defaults to today)
    """
    try:
        vault = get_vault()
        target_date = date or datetime.now().strftime("%Y-%m-%d")
        content = _generate_morning_briefing_text(vault, target_date)
        out_path = vault.write_briefing(target_date, content)
        rel = out_path.relative_to(vault.root)
        preview = content[:900] + "..." if len(content) > 900 else content
        return (
            f"✅ SUCCESS: Morning briefing generated and persisted to vault.\n"
            f"📁 Written to: {rel}\n\n"
            f"--- Content Preview ---\n{preview}\n\n"
            f"(Full file is in the vault and ready for N8N / human review. "
            f"BRAIN.md was read first per POS contract. All rules enforced.)"
        )
    except VaultError as e:
        return f"❌ VAULT RULE VIOLATION (never-delete / 8-folder / BRAIN-first): {e}"
    except Exception as e:
        return f"❌ ERROR during morning briefing: {e}"


@mcp.tool()
def engram_process_capture() -> str:
    """
    Capture Processor (v1 with real filing).
    - Always reads BRAIN.md first (enforced by vault).
    - Lists items in 00 - CAPTURE/.
    - Basic keyword heuristic classification (TASK/IDEA/REFERENCE/NOTE/EVENT).
    - **Real filing**: writes classified content to the correct destination folder
      (05-QUEUE/ for TASK/IDEA as TASK-*/IDEA-* , 02-RESOURCES/references/ for ref/note,
       06-CALENDAR/events/ for events) using vault.write_file.
    - Then archives the *original* from CAPTURE (never delete).
    - Writes timestamped report to 04 - GENERATED/summaries/.
    - Logs every action.
    Future: replace heuristic with LLM via Grok; same filing + archive contract.
    """
    try:
        vault = get_vault()
        _ = vault.read_brain_md()
        items = vault.list_capture_items()
        if not items:
            return "Capture Processor: 0 items in 00 - CAPTURE/. Nothing to classify. (Drop files to test.) BRAIN.md honored."

        actions = []
        date = datetime.now().strftime("%Y-%m-%d")
        for item in items:
            text = item.read_text(encoding="utf-8", errors="ignore").lower()
            name = item.name.lower()
            original_content = item.read_text(encoding="utf-8", errors="ignore")

            # Simple heuristic (expandable; future: call Grok for classification)
            if any(k in text or k in name for k in ["task:", "todo", "action:"]):
                classification = "TASK"
                dest_folder = "05 - QUEUE"
            elif any(k in text or k in name for k in ["idea:", "idea", "brainstorm"]):
                classification = "IDEA"
                dest_folder = "05 - QUEUE"
            elif any(k in text or k in name for k in ["ref:", "reference", "link:", "bookmark"]):
                classification = "REFERENCE"
                dest_folder = "02 - RESOURCES/references"
            elif any(k in text or k in name for k in ["event:", "calendar", "meeting"]):
                classification = "EVENT"
                dest_folder = "06 - CALENDAR/events"
            else:
                classification = "NOTE"
                dest_folder = "02 - RESOURCES/references"

            # Real filing before archive (the v1 fix)
            dest_name = f"{classification}-{item.name}" if classification in ("TASK", "IDEA") else item.name
            if not any(dest_name.lower().endswith(ext) for ext in (".md", ".txt", ".markdown")):
                dest_name += ".md"
            dest_rel = f"{dest_folder}/{dest_name}"
            try:
                filed_content = (
                    original_content.rstrip()
                    + f"\n\n---\n*Classified as {classification} and filed by engram_process_capture on {datetime.now().isoformat(timespec='seconds')}*"
                )
                vault.write_file(dest_rel, filed_content, reason=f"classified-as-{classification.lower()}")
                filed_msg = f"filed to {dest_rel}"
            except Exception as write_err:
                filed_msg = f"filing failed ({write_err}); only archived"

            # Never-delete: always archive original after (or instead of) filing
            archived = vault.archive_file(f"00 - CAPTURE/{item.name}", reason=f"classified-{classification.lower()}")
            actions.append(f"{item.name} → {classification} ({filed_msg}; original archived to {archived.name})")

        # Write report via safe generated writer
        report = f"# Capture Report — {date}\n\nProcessed {len(items)} items from 00 - CAPTURE/.\n\n"
        report += "\n".join(f"- {a}" for a in actions) + "\n\n"
        report += "*BRAIN.md read first. Items filed to correct destinations, originals archived to 07-ARCHIVE/ (never deleted).*\n"
        report += f"*Generated by engram-mcp Capture Processor on {datetime.now().isoformat(timespec='seconds')}*"

        vault._write_to_generated("summaries", f"{date}-capture-report.md", report)

        summary = f"Capture Processor: processed {len(items)} items. Actions: {'; '.join(actions)}. Report written to GENERATED/summaries/."
        vault.log_action(summary)
        return summary

    except Exception as e:
        return f"Error in Capture Processor: {e}"


@mcp.tool()
def engram_process_queue() -> str:
    """Process QUEUE/ items (stub)."""
    try:
        vault = get_vault()
        _ = vault.read_brain_md()
        items = vault.list_queue_items()
        if items:
            return f"Queue Processor stub. {len(items)} VERB-*.md files ready for processing. NEEDS HUMAN INPUT: Review and implement full Queue Processor logic (or drop REVIEW- items for manual triage)."
        return "Queue Processor stub. 0 items in 05 - QUEUE/."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def engram_run_weekly_review() -> str:
    """Weekly review + BRAIN.md update (stub)."""
    try:
        vault = get_vault()
        _ = vault.read_brain_md()
        return "Weekly Review stub executed (would analyze 7 days, propose priorities, update BRAIN.md). NEEDS HUMAN INPUT: Approve proposed priority changes before any write to BRAIN.md §4."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def engram_run_project_health_monitor() -> str:
    """Project health scoring + QUEUE REVIEW items (stub)."""
    try:
        vault = get_vault()
        _ = vault.read_brain_md()
        projects = vault.list_active_projects()
        base = f"Project Health Monitor stub. Active projects: {projects or ['(none)']}. Would create REVIEW-* for stalled ones."
        if projects:
            base += " NEEDS HUMAN INPUT: Review any new REVIEW-*.md items created in 05-QUEUE/ for stalled projects."
        return base
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def engram_health() -> str:
    """Lightweight health/readiness probe for N8N monitoring, Docker healthchecks, or manual verification.
    Always reads BRAIN.md first per POS contract.
    Reports last regular sleep + last Deep Sleep (BES) for honest observability + compute monitoring.
    """
    try:
        vault = get_vault()
        _ = vault.read_brain_md()
        status = get_last_sleep_status(vault)
        deep_status = get_last_deep_sleep_status(vault)
        base = "✅ engram-mcp healthy. BRAIN.md readable + vault layer active (8-folder, never-delete, logging). HTTP/stdio both supported."
        if status:
            base += f"\nLast sleep: {status['filename']} (scope={status['scope']}, passes={status['passes']})"
        else:
            base += "\nLast sleep: none recorded yet."
        if deep_status:
            base += f"\nLast Deep Sleep (BES): {deep_status['filename']} (scope={deep_status['scope']}, gen={deep_status['generations']}, pop={deep_status['population_size']})"
        else:
            base += "\nLast Deep Sleep (BES): none yet (optional advanced mode)."
        return base
    except Exception as e:
        return f"❌ engram-mcp unhealthy: {e}"


@mcp.tool()
def engram_trigger_sleep(n_passes: int = 3, scope: str = "nightly", dry_run: bool = False) -> str:
    """
    Trigger a Sleep Cycle for offline memory consolidation (recurrent passes over recent context).

    Always reads BRAIN.md first. Collects recent dailies/briefings/QUEUE/ARCHIVE/logs.
    Runs 1-5 deterministic recurrent passes (extract → connect → Fast Memory Blocks).
    Writes artifact to 04 - GENERATED/consolidated/ (or dry-run preview only).
    Embeds exact BRAIN.md proposal (human pastes; never auto-edits BRAIN).
    Follows all POS rules: logging, never-delete, 8-folder, human gate.

    Args:
        n_passes: 1-5 (default 3). Higher = deeper abstraction.
        scope: "nightly" | "manual" | "ad-hoc" | "weekly"
        dry_run: if True, synthesize + log only (no write to GENERATED)
    """
    try:
        vault = get_vault()
        # trigger_sleep_cycle does the mandatory BRAIN read + collection + synthesis + (conditional) write
        result = trigger_sleep_cycle(vault, n_passes=n_passes, scope=scope, dry_run=dry_run)
        return result
    except VaultError as e:
        return f"❌ VAULT RULE VIOLATION (sleep cycle): {e}"
    except ValueError as e:
        return f"❌ SLEEP CYCLE PARAM ERROR: {e} (n_passes 1-5; scope in nightly/manual/ad-hoc/weekly)"
    except Exception as e:
        return f"❌ ERROR in sleep cycle: {e}"


@mcp.tool()
def engram_trigger_deep_sleep(
    generations: int = 4,
    population_size: int = 6,
    scope: str = "deep-manual",
    dry_run: bool = False,
) -> str:
    """
    Trigger Deep Sleep powered by Bidirectional Evolutionary Search (BES).

    Forward evolutionary recombination (crossover, translocation, combination, deletion)
    of daily trajectories + backward subgoal decomposition for dense partial-progress scoring.
    Produces higher-quality consolidated artifacts than regular sleep.

    Always reads BRAIN.md first. Full POS rule compliance (vault layer, never-delete,
    proposals only for BRAIN.md, logging). Writes to 04 - GENERATED/consolidated/deep/.

    More compute-heavy — intended for manual trigger or weekend scheduled runs.
    Default nightly remains the fast engram_trigger_sleep.

    Args:
        generations: 2-8 (default 4). More = deeper evolution.
        population_size: 3-12 (default 6). Larger explores more combinations.
        scope: "deep-manual" | "deep-weekend" | "deep-adhoc" | "deep-scheduled"
        dry_run: if True, full synthesis + log only (no artifact written)
    """
    try:
        vault = get_vault()
        result = trigger_deep_sleep_cycle(
            vault,
            generations=generations,
            population_size=population_size,
            scope=scope,
            dry_run=dry_run,
        )
        return result
    except VaultError as e:
        return f"❌ VAULT RULE VIOLATION (deep sleep BES): {e}"
    except ValueError as e:
        return f"❌ DEEP SLEEP PARAM ERROR: {e} (generations 2-8; pop 3-12; valid deep scope)"
    except Exception as e:
        return f"❌ ERROR in deep sleep (BES): {e}"


# ============================================================
# Entry point (matches pyproject console script + FastMCP)
# ============================================================

def main():
    """Run the engram-mcp server.

    - No args (default): stdio transport — for local Grok TUI, `grok mcp`, and N8N stdio MCP nodes.
    - `http` or `streamable-http`: Streamable HTTP transport on 0.0.0.0:8000/mcp — recommended for production (Docker on VPS, Grok CLI via --url).
    - `sse`: legacy SSE transport (for older clients).

    Example production:
      python -m engram_mcp.server http

    The HTTP mode allows Grok CLI (grok mcp add --url http://... --type streamable-http) and N8N
    to call tools reliably at http://localhost:8000/mcp (or http://engram-mcp:8000/mcp inside Docker net).
    """
    import sys
    if len(sys.argv) > 1:
        transport_arg = sys.argv[1].lower().strip()
        if transport_arg in ("http", "streamable-http"):
            import time
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[engram-mcp] {ts} Starting Streamable HTTP server on http://0.0.0.0:8000/mcp (for N8N / Grok CLI --url / future)")
            # Basic structured request logging (FastMCP uses uvicorn under the hood for streamable-http).
            # Ensures access logs (method, path, status, time) appear in systemd journal + `docker compose logs`.
            # No new dependencies; uvicorn access logger is enabled at INFO.
            import logging
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [engram-mcp-http] %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
                # Ensure output goes to stderr (captured by systemd journal + docker logs even if stdout is redirected in some entrypoints)
                stream=sys.stderr
            )
            logging.getLogger("uvicorn").setLevel(logging.INFO)
            logging.getLogger("uvicorn.access").setLevel(logging.INFO)
            logging.getLogger("engram-mcp").setLevel(logging.INFO)
            print("[engram-mcp] Structured HTTP request access logging enabled (visible via journalctl -u engram-mcp and docker logs).")

            # Strong explicit warning for production reality (matches compose + service + AGENTS.md contract).
            # Also emitted via logging so it appears as structured event in journal.
            sec_msg = ("SECURITY NOTE: Bound to 0.0.0.0 INSIDE container only. "
                       "Production docker-compose.yml + engram-mcp.service publish ONLY via 127.0.0.1:${MCP_PORT:-8000} on the *host* (loopback). "
                       "Exposing publicly requires an auth proxy (Caddy + forward-auth, or arc-relay pattern). Never publish 8000 directly. "
                       "See comments in docker-compose.yml, engram-mcp.service, AGENTS.md, and engram-mcp/README.md.")
            logging.warning(sec_msg)
            print("[engram-mcp] " + sec_msg)  # Also plain for immediate docker run visibility
            mcp.run(transport="streamable-http")
            return
        if transport_arg == "sse":
            print("[engram-mcp] Starting legacy SSE server on http://0.0.0.0:8000")
            mcp.run(transport="sse")
            return
        print(f"[engram-mcp] Unknown transport '{transport_arg}', falling back to stdio.")

    # Default: stdio (used by Grok TUI and local development)
    print("[engram-mcp] Starting stdio server (for Grok TUI / MCP clients)")
    mcp.run()


if __name__ == "__main__":
    main()