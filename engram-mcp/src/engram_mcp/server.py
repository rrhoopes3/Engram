"""
engram-mcp — Grok-powered MCP server for the Engram Personal Operating System.

This server exposes high-level Engram workflow tools that N8N (or any MCP client)
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

import os
import re
from datetime import datetime
from pathlib import Path

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
# Deep Sleep (BES) is an optional higher-quality evolutionary mode.
from .sleep import (
    trigger_sleep_cycle,
    get_last_sleep_status,
    trigger_deep_sleep_cycle,
    get_last_deep_sleep_status,
)
from .graph_export import export_graph_overlay_standalone, get_last_overlay_status


# Create the MCP server using the modern FastMCP SDK (compatible with current mcp package)
if mcp is None:
    class _NoMCP:
        def tool(self):
            def deco(f):
                return f
            return deco

        def run(self, transport=None):
            """No-op fallback when FastMCP is not installed (tests/dev)."""
            pass

    mcp = _NoMCP()


CAPTURE_NAME_RE = re.compile(r"^[a-zA-Z0-9._\- ]{1,120}$")


def _ensure_tool_context(vault: Vault, tool_name: str) -> None:
    """Log resolved vault path when ENGRAM_MCP_DEBUG_VAULT=1 (startup log always on)."""
    flag = os.environ.get("ENGRAM_MCP_DEBUG_VAULT", "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return
    vault.log_action(f"tool={tool_name} vault={vault.root.resolve()}")


def _engram_first_then_context(vault: Vault, tool_name: str, *, log: bool = True) -> str:
    """Read BRAIN.md first, then optional debug vault context log."""
    brain = vault.read_brain_md(log=log)
    _ensure_tool_context(vault, tool_name)
    return brain


def _sanitize_capture_filename(name: str) -> str:
    """Normalize CAPTURE item name: basename only, charset allowlist, max length."""
    safe = Path(name).name
    if not safe or safe in (".", ".."):
        raise VaultError(f"Invalid capture item name: {name!r}")
    if not CAPTURE_NAME_RE.match(safe):
        raise VaultError(f"Invalid capture item name charset: {name!r}")
    return safe


def _is_valid_existing_briefing(content: str, target_date: str) -> bool:
    """Idempotent skip requires non-empty content with canonical heading marker."""
    stripped = content.strip()
    if not stripped:
        return False
    return f"# Morning Briefing — {target_date}" in stripped


def _coerce_bool(value, param_name: str = "value") -> bool:
    """Coerce MCP boundary values to bool (string 'false' must not be truthy)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes", "on"):
            return True
        if normalized in ("false", "0", "no", "off", ""):
            return False
    raise ValueError(f"PARAM ERROR: {param_name} must be a boolean (got {value!r})")


def _coerce_int(value, param_name: str, min_val: int, max_val: int) -> int:
    """Coerce MCP boundary values to int within range."""
    try:
        if isinstance(value, str):
            value = value.strip()
        iv = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"PARAM ERROR: {param_name} must be integer {min_val}-{max_val} (got {value!r})"
        ) from exc
    if not min_val <= iv <= max_val:
        raise ValueError(f"PARAM ERROR: {param_name} must be {min_val}-{max_val} (got {iv})")
    return iv


def _coerce_briefing_date(date: str) -> str:
    """Validate/strip briefing date; default handled by caller."""
    if not isinstance(date, str):
        raise ValueError(f"PARAM ERROR: date must be YYYY-MM-DD string (got {date!r})")
    target = date.strip()
    if not Vault.DATE_RE.match(target):
        raise ValueError(f"PARAM ERROR: date must be YYYY-MM-DD (got {date!r})")
    return target


def _configure_http_security_logging(transport_label: str) -> None:
    """Shared security + access logging for HTTP transports (streamable-http and SSE)."""
    import logging
    import sys
    import time

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"[engram-mcp] {ts} Starting {transport_label} on http://0.0.0.0:8000",
        file=sys.stderr,
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [engram-mcp-http] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("engram-mcp").setLevel(logging.INFO)
    print(
        "[engram-mcp] Structured HTTP request access logging enabled "
        "(visible via journalctl -u engram-mcp and docker logs).",
        file=sys.stderr,
    )
    sec_msg = (
        "SECURITY NOTE: Bound to 0.0.0.0 INSIDE container only. "
        "Production docker-compose.yml + engram-mcp.service publish ONLY via "
        "127.0.0.1:${MCP_PORT:-8000} on the *host* (loopback). "
        "Exposing publicly requires an auth proxy (Caddy + forward-auth, or arc-relay pattern). "
        "Never publish 8000 directly. "
        "See comments in docker-compose.yml, engram-mcp.service, AGENTS.md, and engram-mcp/README.md."
    )
    logging.warning(sec_msg)
    print("[engram-mcp] " + sec_msg, file=sys.stderr)


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


def _generate_morning_briefing_text(vault: Vault, target_date: str, brain: str) -> str:
    """
    Deterministic v1 morning briefing generator.
    Caller must read BRAIN.md first and pass content (single read per tool invocation).
    Extracts key live data (priorities, projects, daily top items, open loops)
    and produces clean, concise, standards-compliant output (<300 words target).
    No dev-time narrative, no stale tool names, timeless.
    Future versions will augment with xAI Grok calls for richer synthesis.
    """
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
def engram_generate_morning_briefing(date: str = "", force: bool = False) -> str:
    """
    Generate the daily morning briefing (<300 words target).
    Always reads BRAIN.md first, pulls yesterday's daily note + calendar,
    writes the result to 04 - GENERATED/briefings/YYYY-MM-DD-morning.md
    using the strict vault access layer (never-delete, logging, etc).

    Idempotent by default: if briefing for date already exists and force=False,
    returns success with existing path (no overwrite). Use force=True to regenerate.

    Args:
        date: YYYY-MM-DD (defaults to today)
        force: if True, overwrite existing briefing for date
    """
    try:
        vault = get_vault()
        force = _coerce_bool(force, "force")
        target_date = _coerce_briefing_date(date) if date and date.strip() else datetime.now().strftime("%Y-%m-%d")
        brain = _engram_first_then_context(vault, "engram_generate_morning_briefing")
        existing = vault.get_briefing_path(target_date)
        if existing.exists() and not force:
            existing_content = existing.read_text(encoding="utf-8")
            if _is_valid_existing_briefing(existing_content, target_date):
                rel = existing.relative_to(vault.root)
                vault.log_action(
                    f"idempotent skip: morning briefing already exists for {target_date} at {rel} (force=False)"
                )
                return (
                    f"✅ SUCCESS (idempotent skip): Morning briefing already exists for {target_date}.\n"
                    f"📁 Existing file: {rel}\n"
                    f"(No overwrite. Pass force=True to regenerate.)"
                )
        content = _generate_morning_briefing_text(vault, target_date, brain)
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
    except ValueError as e:
        return f"❌ {e}"
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
        _engram_first_then_context(vault, "engram_process_capture")
        items = vault.list_capture_items()
        if not items:
            vault.log_action("idempotent skip: engram_process_capture — 0 items in 00 - CAPTURE/ (nothing to classify)")
            return "Capture Processor: 0 items in 00 - CAPTURE/. Nothing to classify. (Drop files to test.) BRAIN.md honored."

        actions = []
        failures = []
        date = datetime.now().strftime("%Y-%m-%d")
        hhmm = datetime.now().strftime("%H%M")
        for item in items:
            safe_name = _sanitize_capture_filename(item.name)
            text = item.read_text(encoding="utf-8", errors="ignore").lower()
            name = safe_name.lower()
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
            dest_name = f"{classification}-{safe_name}" if classification in ("TASK", "IDEA") else safe_name
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
                failures.append(f"{safe_name}: {write_err}")
                actions.append(
                    f"{safe_name} → {classification} (FILING FAILED: {write_err}; original kept in CAPTURE)"
                )
                continue

            # Never-delete: archive original only after successful filing
            archived = vault.archive_file(f"00 - CAPTURE/{safe_name}", reason=f"classified-{classification.lower()}")
            actions.append(f"{safe_name} → {classification} ({filed_msg}; original archived to {archived.name})")

        # Write report via safe generated writer (HHMM suffix for same-day rerun safety)
        report = f"# Capture Report — {date}\n\nProcessed {len(items)} items from 00 - CAPTURE/.\n\n"
        report += "\n".join(f"- {a}" for a in actions) + "\n\n"
        report += "*BRAIN.md read first. Items filed to correct destinations, originals archived to 07-ARCHIVE/ (never deleted).*\n"
        report += f"*Generated by engram-mcp Capture Processor on {datetime.now().isoformat(timespec='seconds')}*"

        vault._write_to_generated("summaries", f"{date}-{hhmm}-capture-report.md", report)

        if failures:
            summary = (
                f"❌ Capture Processor: {len(failures)} item(s) failed filing "
                f"(originals kept in CAPTURE): {'; '.join(failures)}. "
                f"Partial actions: {'; '.join(actions)}."
            )
            vault.log_action(summary)
            return summary

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
        _engram_first_then_context(vault, "engram_process_queue")
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
        _engram_first_then_context(vault, "engram_run_weekly_review")
        return "Weekly Review stub executed (would analyze 7 days, propose priorities, update BRAIN.md). NEEDS HUMAN INPUT: Approve proposed priority changes before any write to BRAIN.md §4."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def engram_run_project_health_monitor() -> str:
    """Project health scoring + QUEUE REVIEW items (stub)."""
    try:
        vault = get_vault()
        _engram_first_then_context(vault, "engram_run_project_health_monitor")
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
        # Silent probe: no tool-context log, no BRAIN read log (Docker healthcheck ~2880x/day)
        _ = vault.read_brain_md(log=False)
        status = get_last_sleep_status(vault)
        deep_status = get_last_deep_sleep_status(vault)
        overlay_status = get_last_overlay_status(vault)
        base = "✅ engram-mcp healthy. BRAIN.md readable + vault layer active (8-folder, never-delete, logging). HTTP/stdio both supported."
        if status:
            base += f"\nLast sleep: {status['filename']} (scope={status['scope']}, passes={status['passes']})"
        else:
            base += "\nLast sleep: none recorded yet."
        if deep_status:
            base += f"\nLast Deep Sleep (BES): {deep_status['filename']} (scope={deep_status['scope']}, gen={deep_status['generations']}, pop={deep_status['population_size']})"
        else:
            base += "\nLast Deep Sleep (BES): none yet (optional advanced mode)."
        if overlay_status:
            base += f"\nLast graph overlay: {overlay_status['filename']} (nodes={overlay_status['node_count']}, edges={overlay_status['edge_count']})"
        else:
            base += "\nLast graph overlay: none yet (run sleep or engram_export_graph_overlay)."
        return base
    except Exception as e:
        return f"❌ engram-mcp unhealthy: {e}"


@mcp.tool()
def engram_trigger_sleep(n_passes: int = 3, scope: str = "nightly", dry_run: bool = False) -> str:
    """
    Trigger a Sleep Cycle for offline memory consolidation (recurrent passes over recent context).

    Always reads BRAIN.md first. Collects recent dailies/briefings/QUEUE/ARCHIVE/logs.
    Runs 1-5 recurrent passes.
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
        brain = _engram_first_then_context(vault, "engram_trigger_sleep")
        n_passes = _coerce_int(n_passes, "n_passes", 1, 5)
        dry_run = _coerce_bool(dry_run, "dry_run")
        scope = str(scope).strip()
        result = trigger_sleep_cycle(
            vault, n_passes=n_passes, scope=scope, dry_run=dry_run, brain_md=brain
        )
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
        brain = _engram_first_then_context(vault, "engram_trigger_deep_sleep")
        generations = _coerce_int(generations, "generations", 2, 8)
        population_size = _coerce_int(population_size, "population_size", 3, 12)
        dry_run = _coerce_bool(dry_run, "dry_run")
        scope = str(scope).strip()
        result = trigger_deep_sleep_cycle(
            vault,
            generations=generations,
            population_size=population_size,
            scope=scope,
            dry_run=dry_run,
            brain_md=brain,
        )
        return result
    except VaultError as e:
        return f"❌ VAULT RULE VIOLATION (deep sleep BES): {e}"
    except ValueError as e:
        return f"❌ DEEP SLEEP PARAM ERROR: {e} (generations 2-8; pop 3-12; valid deep scope)"
    except Exception as e:
        return f"❌ ERROR in deep sleep (BES): {e}"


@mcp.tool()
def engram_export_graph_overlay(
    mode: str = "incremental",  # incremental | full
    include_archived: bool = False,
    dry_run: bool = False,
) -> str:
    """
    Standalone graph overlay export (Phase 1 bridge).
    Rebuilds nodes/edges from recent context (or broader for mode=full, capped).
    Always reads BRAIN.md first. Writes to 04 - GENERATED/graph-export/ (JSON + manifest.md).
    Use after manual vault changes or for N8N post-sleep step. Dry-run for preview.

    The overlay JSON follows engram-graph-overlay-v1 schema (stable node IDs, sleep_synthesis
    + bes_surprise edges, folder clusters, priority signals). Intended for LLM Wiki sidecar.
    """
    try:
        vault = get_vault()
        brain = _engram_first_then_context(vault, "engram_export_graph_overlay")
        mode = str(mode).strip()
        if mode not in ("incremental", "full"):
            return "❌ PARAM ERROR: mode must be 'incremental' or 'full'"
        include_archived = _coerce_bool(include_archived, "include_archived")
        dry_run = _coerce_bool(dry_run, "dry_run")
        result = export_graph_overlay_standalone(
            vault,
            mode=mode,
            include_archived=include_archived,
            dry_run=dry_run,
            brain_md=brain,
        )
        return result
    except VaultError as e:
        return f"❌ VAULT RULE VIOLATION (graph overlay): {e}"
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ ERROR in graph overlay export: {e}"


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

    Vault is validated and logged BEFORE transport starts (stdio and HTTP are separate products).
    """
    import sys

    # Explicit transport mode from argv (Trap 3: stdio ↔ HTTP mode drift)
    transport = "stdio"
    if len(sys.argv) > 1:
        transport_arg = sys.argv[1].lower().strip()
        if transport_arg in ("http", "streamable-http"):
            transport = "streamable-http"
        elif transport_arg == "sse":
            transport = "sse"
        else:
            print(
                f"[engram-mcp] FATAL: Unknown transport '{transport_arg}'. "
                "Use: stdio (default), http, streamable-http, or sse.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Validate vault BEFORE starting transport (Trap 1 + warm-up Step 2)
    try:
        vault = get_vault()
        resolved = vault.root.resolve()
        vault.log_action(f"server startup: mode={transport} vault={resolved}")
        print(
            f"[engram-mcp] Startup validated. mode={transport} vault={resolved}",
            file=sys.stderr,
        )
    except (VaultError, OSError) as e:
        print(f"[engram-mcp] FATAL: Invalid vault or log failure — {e}", file=sys.stderr)
        sys.exit(1)

    if transport == "streamable-http":
        _configure_http_security_logging(
            "Streamable HTTP server on http://0.0.0.0:8000/mcp (for N8N / Grok CLI --url)"
        )
        mcp.run(transport="streamable-http")
        return

    if transport == "sse":
        _configure_http_security_logging("legacy SSE server on http://0.0.0.0:8000")
        mcp.run(transport="sse")
        return

    print("[engram-mcp] Starting stdio server (for Grok TUI / MCP clients)", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()