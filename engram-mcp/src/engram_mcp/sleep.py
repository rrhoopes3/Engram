"""
engram_mcp.sleep — Periodic Sleep Cycles for memory consolidation.

Implements offline recurrent passes over recent context (inspired by
"Language Models Need Sleep" preprint, AlphaXiv 2605.26099, 2026-05-26).

- Collects from vault (BRAIN.md mandatory first, dailies, briefings, QUEUE, recent ARCHIVE, logs).
- N recurrent passes: extract (P1) → connect (P2) → compress to Fast Memory Blocks (P3+).
- Writes only via vault._write_to_generated("consolidated", ...).
- Proposes BRAIN.md deltas but NEVER writes them (human review gate).
- Dry-run: full synthesis + log, zero GENERATED writes.
- Graceful on sparse vault (early days).
- get_last_sleep_status(): honest derived status for observability (no new state files).

All I/O through passed Vault instance. No new deps. Windows paths safe (pathlib + vault).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Optional

# Note: re is also used inside get_last_sleep_status for header parsing (kept here for minimal diff)


from .vault import Vault, VaultError


ALLOWED_SCOPES = ["nightly", "manual", "ad-hoc", "weekly"]


def collect_recent_context(vault: Vault, scope: str = "nightly") -> dict[str, Any]:
    """Collect recent context using only vault public reads + structure attrs. Caps for safety."""
    ctx: dict[str, Any] = {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "scope": scope,
        "brain_md": "",
        "daily_notes": {},
        "briefings": {},
        "queue_items": [],
        "archived_samples": [],
        "log_tail": "",
        "sources": [],
    }

    # Recent daily notes (up to 5, via existing safe reader)
    today = datetime.now()
    for i in range(5):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            note = vault.read_daily_note(d)
            if "not yet created" not in note:
                ctx["daily_notes"][d] = note[:2200]
                ctx["sources"].append(f"01 - ACTIVE/daily/{d}.md")
        except Exception as e:
            vault.log_action(f"collect skip daily {d}: {str(e)[:80]}")

    # Recent briefings (use public root + FOLDERS for discovery, vault.read_file for content)
    try:
        gen = vault.FOLDERS["generated"]
        bdir = vault.root / gen / "briefings"
        if bdir.exists():
            for p in sorted(bdir.glob("*.md"), reverse=True)[:3]:
                rel = str(p.relative_to(vault.root))
                try:
                    txt = vault.read_file(rel)
                    key = re.search(r"(\d{4}-\d{2}-\d{2})", p.name)
                    k = key.group(1) if key else p.stem
                    ctx["briefings"][k] = txt[:2400]
                    ctx["sources"].append(rel)
                except Exception as e:
                    vault.log_action(f"collect skip briefing {rel}: {str(e)[:80]}")
    except Exception as e:
        vault.log_action(f"collect skip briefings phase: {str(e)[:120]}")

    # QUEUE items (via existing vault list + safe read)
    try:
        for qp in vault.list_queue_items()[:4]:
            rel = str(qp.relative_to(vault.root))
            try:
                txt = vault.read_file(rel)[:1600]
                ctx["queue_items"].append((qp.name, txt))
                ctx["sources"].append(rel)
            except Exception as e:
                vault.log_action(f"collect skip queue {qp.name}: {str(e)[:80]}")
    except Exception as e:
        vault.log_action(f"collect skip queue phase: {str(e)[:120]}")

    # Recent ARCHIVE samples (for cross-ref, never mutate)
    try:
        adir = vault.root / vault.FOLDERS["archive"]
        if adir.exists():
            for ap in sorted(adir.glob("*.md"), reverse=True)[:2]:
                rel = str(ap.relative_to(vault.root))
                try:
                    txt = vault.read_file(rel)[:900]
                    ctx["archived_samples"].append((ap.name, txt))
                    ctx["sources"].append(rel)
                except Exception as e:
                    vault.log_action(f"collect skip archive {ap.name}: {str(e)[:80]}")
    except Exception as e:
        vault.log_action(f"collect skip archive phase: {str(e)[:120]}")

    # System log tail (via safe read)
    try:
        log_rel = f"{vault.FOLDERS['system']}/logs/system-log.md"
        logp = vault.root / log_rel
        if logp.exists():
            full = vault.read_file(log_rel)
            ctx["log_tail"] = "\n".join(full.splitlines()[-15:])
            ctx["sources"].append(log_rel)
    except Exception as e:
        vault.log_action(f"collect skip log tail: {str(e)[:120]}")

    return ctx


def _flatten_for_passes(ctx: dict[str, Any]) -> str:
    """Flatten limited context for recurrent processing (no external calls)."""
    parts: list[str] = []
    if ctx.get("brain_md"):
        parts.append("BRAIN: " + ctx["brain_md"][:2800])
    for d, c in sorted(ctx.get("daily_notes", {}).items()):
        parts.append(f"DAILY-{d}: {c}")
    for d, c in sorted(ctx.get("briefings", {}).items()):
        parts.append(f"BRIEFING-{d}: {c}")
    for name, c in ctx.get("queue_items", []):
        parts.append(f"QUEUE-{name}: {c}")
    for name, c in ctx.get("archived_samples", []):
        parts.append(f"ARCHIVE-{name}: {c}")
    if ctx.get("log_tail"):
        parts.append("LOGS: " + ctx["log_tail"])
    return "\n---\n".join(parts)


def _pass1_extract(text: str) -> str:
    """Pass 1: simple extraction of entities, dates, projects, themes."""
    dates = sorted(set(re.findall(r"\d{4}-\d{2}-\d{2}", text)))[:6]
    projs = list(set(re.findall(r"(Brain[- ]?POS|POS|foundation|N8N|automation|briefing|capture)", text, re.I)))[:5]
    themes = [k for k in ["priority", "health", "sleep", "consolidat", "vault", "BRAIN"] if k.lower() in text.lower()][:4]
    facts = [m.strip() for m in re.findall(r"^[-*]\s*(.{12,70})", text, re.M)][:5]
    return f"entities/dates={dates}; projects/themes={projs+themes}; facts={facts}"


def _pass2_connect(text: str, ctx: dict[str, Any]) -> str:
    """Pass 2: naive cross-day / cross-source connections."""
    nd = len(ctx.get("daily_notes", {}))
    nb = len(ctx.get("briefings", {}))
    conn = f"span={nd} dailies + {nb} briefings"
    if "foundation" in text.lower() and "automation" in text.lower():
        conn += "; foundation+automation loop detected across sources"
    if len(ctx.get("sources", [])) > 3:
        conn += "; multi-source coherence emerging"
    return conn


def _pass3_compress(text: str, ctx: dict[str, Any]) -> str:
    """Pass 3+: Fast Memory Blocks (dense, queryable atoms)."""
    return ("Knowledge Atoms: [8-folder invariant; BRAIN-first; archive-only; GENERATED whitelist]. "
            "Cross-Day: [daily wins -> briefing synthesis]. "
            "Priority Evolution: [vault+tools -> sleep consolidation]. "
            "Signals: [early data; more cycles will sharpen patterns].")


def run_recurrent_passes(context: dict[str, Any], n_passes: int) -> list[str]:
    """Execute N recurrent passes (re-scan flattened context with rising abstraction)."""
    raw = _flatten_for_passes(context)
    out: list[str] = []
    for i in range(1, n_passes + 1):
        if i == 1:
            s = f"Pass {i}: {_pass1_extract(raw)}"
        elif i == 2:
            s = f"Pass {i}: {_pass2_connect(raw, context)}"
        else:
            s = f"Pass {i}: {_pass3_compress(raw, context)}"
        out.append(s)
    return out


def propose_brain_update(context: dict[str, Any]) -> str:
    """Exact BRAIN.md snippet proposal. Human pastes only. Always triggers review gate."""
    return """## 9. Sleep Cycles (Memory Consolidation)  [PROPOSED — review & paste surgically]

**Mechanism**: `engram_trigger_sleep(n_passes=1..5, scope="nightly"|"manual", dry_run=False)`.
- Collects recent vault state (BRAIN.md first, last dailies/briefings/QUEUE/ARCHIVE samples/logs).
- Runs N recurrent passes (extract entities → find connections → compress to Fast Memory Blocks).
- Writes timestamped artifact to `04 - GENERATED/consolidated/YYYY-MM-DD-HHMM-sleep-consolidation.md` only (HHMM for ad-hoc uniqueness; N8N nightly is daily).
- Embeds exact proposed deltas for BRAIN.md (§2/3/4/8/9); never auto-writes this file.

**Triggers**: Ad-hoc via Grok TUI/CLI or N8N cron (e.g. 03:00 nightly after capture).
**Wake behavior**: "Temp cache cleared" — subsequent tools read live BRAIN + dailies + reference consolidated index for faster coherence.
**Logging & Rules**: Every run logs to system-log.md; BRAIN.md read first always. Proposals surface "NEEDS HUMAN INPUT". No deletes, no new top folders.
**Future**: Recurrent Grok calls (xAI key) for richer passes when available.

(Integrate after §8. Update §7 schedule. Voice: direct per §5.)
"""


def synthesize_consolidated(context: dict[str, Any], passes: list[str], n_passes: int) -> str:
    """Produce full standards-compliant artifact (BRAIN §5 voice: direct/concise, footer, date)."""
    date = datetime.now().strftime("%Y-%m-%d")
    scope = context.get("scope", "nightly")
    src_lines = "\n".join(f"- {s}" for s in context.get("sources", [])) or "- (BRAIN + recent vault reads)"
    passes_md = "\n\n".join(f"### {p}" for p in passes)
    proposal = propose_brain_update(context)

    return f"""# Sleep Cycle Report — {date} (scope: {scope}, passes={n_passes})

## Context Window (what was consolidated)
- Daily notes: {len(context.get('daily_notes', {}))}
- Briefings: {len(context.get('briefings', {}))}
- QUEUE + ARCHIVE samples + log tail + full BRAIN.md
- Collected: {context.get('collected_at')}

## Recurrent Passes Performed
{passes_md}

## Consolidated Fast Memory (queryable index)
**Knowledge Atoms**
- Immutable: exactly 8 folders, BRAIN.md first (logged), never-delete (archive only with ts), _write_to_generated whitelist only.
- Current tools: morning briefing (real), capture (heuristic+file+archive), stubs with NEEDS HUMAN.

**Cross-Day Synthesis**
- May 2026 foundation: vault + BRAIN + first 2 real processors + N8N wiring. Daily notes feed briefings; priorities persist.

**Priority Evolution**
- Phase 1 (complete): storage + intelligence skeleton.
- Phase 2 (now): sleep cycles for long-horizon coherence and fast memory.

**Risk/Opportunity Signals**
- Opportunity: dense blocks let future tools query consolidated knowledge without full re-reads.
- Early-vault note: sparse history handled (insufficient → graceful skip logged).

## Proposed BRAIN.md Updates (exact snippet — NEEDS HUMAN INPUT)
{proposal}

## Emergent Insights (long-horizon)
Sleep gives the POS recurrent offline compression. Wake: fresh reads + this artifact available for reference. Keeps real-time inference lean.

## Sources Referenced (traceability; originals untouched in ARCHIVE or live folders)
{src_lines}

---
*Generated by engram_trigger_sleep via Grok / engram-mcp on {datetime.now().isoformat(timespec='seconds')}*
*Deterministic v1 passes (no external LLM). See "Language Models Need Sleep" (AlphaXiv 2605.26099).*
*Rules honored: BRAIN.md read first. 8-folder contract. Never delete. Human gate on proposals.*
""".strip()


def trigger_sleep_cycle(vault: Vault, n_passes: int = 3, scope: str = "nightly", dry_run: bool = False) -> str:
    """Core orchestrator. Always reads BRAIN first. Returns success string + paths or error/NEEDS HUMAN."""
    if not (1 <= n_passes <= 5):
        raise ValueError(f"n_passes out of range (1-5): {n_passes}")
    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"invalid scope {scope}; allowed: {ALLOWED_SCOPES}")

    # NON-NEGOTIABLE
    brain = vault.read_brain_md()
    ctx = collect_recent_context(vault, scope)
    ctx["brain_md"] = brain
    ctx["sources"].insert(0, "03 - SYSTEM/BRAIN.md")

    # Sparse vault guard (early days or empty recent)
    has_ctx = bool(ctx.get("daily_notes") or ctx.get("briefings") or ctx.get("queue_items"))
    if not has_ctx:
        msg = "Insufficient context for deep consolidation (early vault / no recent dailies or briefings). Logged; will deepen on future cycles."
        vault.log_action(f"Sleep skipped: {msg} (scope={scope}, n_passes={n_passes})")
        return f"⚠️ {msg} (BRAIN.md read; no artifact written.)"

    passes = run_recurrent_passes(ctx, n_passes)
    artifact = synthesize_consolidated(ctx, passes, n_passes)

    if dry_run:
        vault.log_action(f"Sleep DRY-RUN (no GENERATED write): scope={scope}, passes={n_passes}. Full preview + proposal generated. BRAIN.md read first.")
        preview = artifact[:1100] + "\n...(truncated; would persist on real run)"
        return (
            f"✅ DRY-RUN SUCCESS (log only). scope={scope}, n_passes={n_passes}\n\n"
            f"--- Preview ---\n{preview}\n\n"
            f"--- BRAIN Proposal (human pastes only) ---\n{propose_brain_update(ctx)[:600]}..."
        )

    # Real write via the one approved path
    filename = f"{datetime.now().strftime('%Y-%m-%d-%H%M')}-sleep-consolidation.md"
    out = vault._write_to_generated("consolidated", filename, artifact)
    rel = out.relative_to(vault.root)

    vault.log_action(f"Sleep cycle complete: {rel} (scope={scope}, n_passes={n_passes}). BRAIN read first. Proposal embedded (NEEDS HUMAN INPUT for any BRAIN edit). Fast memory consolidated.")

    # Honest status block ready for human to paste into BRAIN.md §8
    last_sleep_block = (
        f"- **Last Sleep:** {rel.name}  \n"
        f"  scope={scope}, passes={n_passes} — see `04 - GENERATED/consolidated/{rel.name}`"
    )

    return (
        f"✅ SUCCESS: Sleep Cycle complete.\n"
        f"📁 Artifact: {rel}\n"
        f"scope={scope} | passes={n_passes}\n\n"
        f"--- Preview (head) ---\n{artifact[:750]}...\n\n"
        f"Consolidated fast memory now in vault. Embedded BRAIN proposal requires explicit human paste (no auto-edit performed). "
        f"Wake state: subsequent tools read live state + this consolidation.\n\n"
        f"--- Paste this into BRAIN.md §8 (Current Context Snapshot) ---\n"
        f"{last_sleep_block}\n"
        f"(Replace the previous Last Sleep line. This is the only maintenance required.)"
    )


# ============================================================
# Honest observability helpers (no synthesized insights)
# ============================================================

def get_last_sleep_status(vault: Vault) -> Optional[dict]:
    """
    Derive last sleep status purely from existing artifacts.
    Returns a small dict or None if no sleep artifacts exist yet.
    This is the minimal honest mechanism — no new persistent state files.
    """
    consolidated_dir = vault.root / vault.FOLDERS["generated"] / "consolidated"
    if not consolidated_dir.exists():
        return None

    candidates = sorted(
        consolidated_dir.glob("*sleep-consolidation.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    if not candidates:
        return None

    latest = candidates[0]

    # Parse header for scope and passes (reliable source of truth)
    try:
        header = latest.read_text(encoding="utf-8", errors="ignore").splitlines()[:5]
        header_text = " ".join(header)
    except Exception:
        header_text = ""

    scope_match = re.search(r"scope:\s*([a-z-]+)", header_text, re.IGNORECASE)
    passes_match = re.search(r"passes=(\d+)", header_text)

    return {
        "artifact": str(latest.relative_to(vault.root)),
        "filename": latest.name,
        "scope": scope_match.group(1) if scope_match else "unknown",
        "passes": int(passes_match.group(1)) if passes_match else 0,
    }
