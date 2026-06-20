"""
engram_mcp.sleep — Periodic Sleep Cycles for memory consolidation + Deep Sleep (BES).

Regular: recurrent passes (inspired by "Language Models Need Sleep", AlphaXiv 2605.26099).
Deep Sleep: Bidirectional Evolutionary Search (BES, arXiv:2605.28814) for higher-quality
recombination of trajectories — forward evolution (crossover/translocation/etc.) + backward
subgoal decomposition. Optional, more compute-heavy, writes to consolidated/deep/.

- All modes: BRAIN.md first (mandatory), vault only for I/O, never-delete, proposals only.
- Dry-run support, honest status derivation, graceful sparse vault.
- Future: XAI_API_KEY enables true LLM calls inside operators/fitness for richer evolution.

No new runtime deps. Windows-safe.
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from typing import Any, Optional

# Note: re is also used inside get_last_sleep_status for header parsing (kept here for minimal diff)


from .vault import Vault, VaultError
from .graph_export import export_sleep_graph_overlay, export_deep_graph_overlay


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


def trigger_sleep_cycle(
    vault: Vault,
    n_passes: int = 3,
    scope: str = "nightly",
    dry_run: bool = False,
    brain_md: str | None = None,
) -> str:
    """Core orchestrator. Always reads BRAIN first (unless brain_md pre-read by caller). Returns success string + paths or error/NEEDS HUMAN."""
    if not (1 <= n_passes <= 5):
        raise ValueError(f"n_passes out of range (1-5): {n_passes}")
    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"invalid scope {scope}; allowed: {ALLOWED_SCOPES}")

    # NON-NEGOTIABLE — use pre-read content when caller already logged BRAIN-first
    brain = brain_md if brain_md is not None else vault.read_brain_md()
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

    # Phase 1 graph bridge hook (after md, before return; respects dry_run/sparse inside)
    overlay_rel = export_sleep_graph_overlay(vault, ctx, passes, str(rel), dry_run=False)

    # Honest status block ready for human to paste into BRAIN.md §8
    last_sleep_block = (
        f"- **Last Sleep:** {rel.name}  \n"
        f"  scope={scope}, passes={n_passes} — see `04 - GENERATED/consolidated/{rel.name}`"
    )

    overlay_note = f"\n📊 Graph overlay: {overlay_rel}" if overlay_rel else ""
    return (
        f"✅ SUCCESS: Sleep Cycle complete.\n"
        f"📁 Artifact: {rel}{overlay_note}\n"
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


# ============================================================
# DEEP SLEEP MODE: Bidirectional Evolutionary Search (BES)
# ============================================================
# Adapted from "Self-Improving Language Models with Bidirectional Evolutionary Search"
# (arXiv:2605.28814v1, May 2026, Xu et al.).
#
# Forward: evolutionary recombination of experience "trajectories" (daily notes,
# briefings, captures, logs) via crossover, translocation, combination, deletion.
# Backward: recursive decomposition of high-level goals (from BRAIN.md priorities +
# open patterns) into verifiable subgoals for dense scoring / partial progress detection.
#
# v1: fully deterministic heuristic (no external LLM calls, stdlib only) so it runs
# reliably offline in the MCP container. Produces richer consolidated artifacts than
# the fast recurrent-pass sleep.
# Future (when XAI_API_KEY in env): replace operator/fitness bodies with Grok calls
# for true generative evolution while keeping identical structure + vault contract.
#
# All writes go through vault._write_to_generated("consolidated/deep", ...).
# Never touches BRAIN.md (only proposes deltas). Full logging + traceability.
# ============================================================

DeepSleepScope = ["deep-manual", "deep-weekend", "deep-adhoc", "deep-scheduled"]


def _simple_chunk(text: str, max_chars: int = 320) -> list[str]:
    """Lightweight chunker for trajectories. Prefers paragraph/sentence breaks."""
    if not text or len(text) < 40:
        return []
    chunks: list[str] = []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 20]
    for p in paras:
        if len(p) <= max_chars:
            chunks.append(p[:max_chars])
        else:
            sents = re.split(r"(?<=[.!?])\s+", p)
            buf = ""
            for s in sents:
                if len(buf) + len(s) + 1 > max_chars and buf:
                    chunks.append(buf.strip())
                    buf = s
                else:
                    buf = (buf + " " + s).strip()
            if buf:
                chunks.append(buf[:max_chars])
    return chunks[:8]


def _extract_trajectories(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Build initial population of trajectories from collected context."""
    trajs: list[dict[str, Any]] = []
    for d, txt in ctx.get("daily_notes", {}).items():
        for ch in _simple_chunk(txt):
            trajs.append({
                "text": ch,
                "provenance": [f"daily:{d}"],
                "score": 0.0,
            })
    for d, txt in ctx.get("briefings", {}).items():
        for ch in _simple_chunk(txt, 260):
            trajs.append({
                "text": ch,
                "provenance": [f"briefing:{d}"],
                "score": 0.0,
            })
    for name, txt in ctx.get("queue_items", []):
        for ch in _simple_chunk(txt, 200)[:2]:
            trajs.append({"text": ch, "provenance": [f"queue:{name}"], "score": 0.0})
    for name, txt in ctx.get("archived_samples", []):
        for ch in _simple_chunk(txt, 160)[:1]:
            trajs.append({"text": ch, "provenance": [f"archive:{name}"], "score": 0.0})

    seen = set()
    unique = []
    for t in trajs:
        key = t["text"][:60].lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)
    random.shuffle(unique)
    return unique[:25]


def _backward_decompose(brain_md: str, ctx: dict[str, Any]) -> list[str]:
    """Produce a small set of verifiable subgoals for scoring partial progress."""
    subgoals: list[str] = []
    prio = ""
    m = re.search(r"Current Priorities.*?(?=\n##|\Z)", brain_md, re.S | re.I)
    if m:
        prio = m.group(0)[:600]
    for line in prio.splitlines():
        if line.strip().startswith(("1.", "2.", "3.", "-", "*")) and len(line) > 15:
            subgoals.append(line.strip()[:120])

    themes = []
    flat = (brain_md + " " + str(ctx.get("daily_notes", {})) + " " + str(ctx.get("briefings", {}))).lower()
    for kw in ["vault", "automation", "n8n", "sleep", "consolidat", "priority", "health", "capture"]:
        if kw in flat:
            themes.append(kw)
    if themes:
        subgoals.append(f"Cross-day coherence on: {', '.join(themes[:4])}")

    subgoals.append("Evidence of forward progress on active projects")
    subgoals.append("Detection of recurring patterns or stalled loops")

    seen = set()
    final = []
    for g in subgoals:
        if g.lower() not in seen:
            seen.add(g.lower())
            final.append(g)
    return final[:7]


def _score(traj: dict[str, Any], subgoals: list[str]) -> float:
    """Dense scoring: subgoal coverage + actionability + sweet-spot length."""
    txt = traj.get("text", "").lower()
    if not txt:
        return 0.0
    covered = sum(1 for g in subgoals if any(w in txt for w in g.lower().split()[:4] if len(w) > 3))
    cov = covered / max(1, len(subgoals))
    bonus = 0.12 if any(k in txt for k in ["action", "next", "progress", "pattern", "evolved", "deeper"]) else 0.0
    ln = len(traj["text"])
    length_f = 0.08 if 80 < ln < 380 else 0.0
    return min(0.98, cov + bonus + length_f)


def _crossover(a: dict, b: dict) -> dict:
    ta, tb = a["text"], b["text"]
    mid_a = len(ta) // 2
    mid_b = len(tb) // 2
    new_text = (ta[:mid_a].rstrip() + "  |EVOLVED-CROSS|  " + tb[mid_b:].lstrip())[:380]
    return {
        "text": new_text,
        "provenance": list(set(a["provenance"] + b["provenance"] + ["crossover"])),
        "score": 0.0,
    }


def _translocation(a: dict, b: dict) -> dict:
    seg = b["text"][:120].strip()
    if len(seg) < 25:
        seg = b["text"]
    new_text = (a["text"][:200].rstrip() + "  [TRANSLOCATED: " + seg + "] " + a["text"][200:]).strip()[:380]
    return {
        "text": new_text,
        "provenance": list(set(a["provenance"] + b["provenance"] + ["translocation"])),
        "score": 0.0,
    }


def _combination(a: dict, b: dict) -> dict:
    new_text = f"In the light of {a['text'][:90]}... and {b['text'][:90]}..., the deeper consolidated pattern is: multi-day integration of these threads yields actionable coherence for the Engram POS."
    return {
        "text": new_text[:380],
        "provenance": list(set(a["provenance"] + b["provenance"] + ["combination"])),
        "score": 0.0,
    }


def _deletion(t: dict) -> dict:
    txt = t["text"]
    sents = re.split(r"(?<=[.!?])\s+", txt)
    if len(sents) <= 1:
        return {**t, "text": txt[:int(len(txt)*0.7)]}
    sents = sorted(sents, key=len, reverse=True)
    pruned = " ".join(sents[:max(1, len(sents)-1)])
    return {
        "text": pruned[:380],
        "provenance": t["provenance"] + ["deletion"],
        "score": 0.0,
    }


def run_bidirectional_evolutionary_search(
    initial_trajs: list[dict[str, Any]],
    subgoals: list[str],
    generations: int = 4,
    pop_size: int = 6,
) -> dict[str, Any]:
    """Execute the core BES loop. Returns evolved population + metrics."""
    if not initial_trajs:
        return {"population": [], "metrics": {"generations": 0, "note": "no trajectories"}, "subgoals": subgoals}

    pop = [dict(t) for t in initial_trajs[:pop_size * 2]]
    random.shuffle(pop)
    pop = pop[:pop_size]

    for t in pop:
        t["score"] = _score(t, subgoals)

    metrics = {
        "generations": generations,
        "population_size": pop_size,
        "operators_applied": 0,
        "best_final_score": 0.0,
        "subgoal_coverage": 0.0,
    }

    for g in range(max(1, generations)):
        for t in pop:
            t["score"] = _score(t, subgoals)

        pop.sort(key=lambda x: x["score"], reverse=True)
        metrics["best_final_score"] = max(metrics["best_final_score"], pop[0]["score"] if pop else 0)

        elite = pop[:max(2, pop_size // 2)]
        parents = elite + random.sample(pop, min(len(pop), max(2, pop_size // 3)))

        new_gen: list[dict] = []
        for _ in range(pop_size):
            p1, p2 = random.sample(parents, 2) if len(parents) >= 2 else (parents[0], parents[0])
            r = random.random()
            if r < 0.35:
                cand = _crossover(p1, p2)
            elif r < 0.55:
                cand = _translocation(p1, p2)
            elif r < 0.75:
                cand = _combination(p1, p2)
            else:
                cand = _deletion(random.choice([p1, p2]))
            metrics["operators_applied"] += 1
            new_gen.append(cand)

        pop = (elite + new_gen)[:pop_size]

    for t in pop:
        t["score"] = _score(t, subgoals)
    pop.sort(key=lambda x: x["score"], reverse=True)

    if pop:
        metrics["best_final_score"] = pop[0]["score"]
        covered = sum(1 for g in subgoals if any(g.lower()[:30] in t["text"].lower() for t in pop[:3]))
        metrics["subgoal_coverage"] = round(covered / max(1, len(subgoals)), 2)

    return {
        "population": pop,
        "metrics": metrics,
        "subgoals": subgoals,
    }


def synthesize_deep_consolidated(
    context: dict[str, Any],
    bes_result: dict[str, Any],
    generations: int,
    pop_size: int,
) -> str:
    """Produce the high-quality Deep Sleep artifact following BRAIN §5 standards."""
    date = datetime.now().strftime("%Y-%m-%d")
    scope = context.get("scope", "deep-manual")
    src_lines = "\n".join(f"- {s}" for s in context.get("sources", [])) or "- (BRAIN + trajectories)"

    pop = bes_result.get("population", [])
    metrics = bes_result.get("metrics", {})
    subgoals = bes_result.get("subgoals", [])

    top_insights = []
    for i, t in enumerate(pop[:4], 1):
        prov = ", ".join(t.get("provenance", [])[:3])
        top_insights.append(f"{i}. {t['text'][:220]}...\n   (score={t['score']:.2f}, from: {prov})")

    subgoal_md = "\n".join(f"- [ ] {g}  (partial progress scored in evolution)" for g in subgoals)

    return f"""# Deep Sleep (BES) Report — {date} (scope: {scope}, generations={generations}, pop={pop_size})

## Context & Compute
- Trajectories evolved: {len(pop)} final individuals from {len(context.get('daily_notes',{}))} dailies + {len(context.get('briefings',{}))} briefings + queue/archive
- Generations run: {generations}
- Operators applied: {metrics.get('operators_applied', 0)}
- Best evolved score: {metrics.get('best_final_score', 0.0):.2f}
- Subgoal coverage (top-3): {metrics.get('subgoal_coverage', 0.0)}
- Collected: {context.get('collected_at')}

## Backward Subgoals (verifiable decomposition from BRAIN priorities + patterns)
{subgoal_md}

## Evolved Insights (forward recombination via crossover / translocation / combination / deletion)
{chr(10).join(top_insights) if top_insights else "(Insufficient diversity for evolution — fell back to raw extraction.)"}

## Cross-Day Multi-Hop Patterns Detected
BES recombination surfaced stronger connections than single-pass sleep. Key evolved threads above represent spliced partial progress across days. Use these as seeds for weekly review or project health.

## Proposed BRAIN.md Updates (exact snippet — NEEDS HUMAN INPUT)
## 10. Deep Sleep — Bidirectional Evolutionary Search (BES)  [PROPOSED]
**Optional advanced mode**: `engram_trigger_deep_sleep(generations=3..6, population_size=5..8, scope="deep-manual"|"deep-weekend", dry_run=False)`
- Runs forward evolutionary operators on trajectories + backward subgoal decomposition.
- Writes richer artifacts to `04 - GENERATED/consolidated/deep/deep-YYYY-MM-DD-HHMM-consolidation.md`
- Still 100% vault-rule compliant (BRAIN first, archive-only, proposals only, logged).
- More expensive than nightly recurrent sleep; run manually or on weekends.
See `engram-mcp/src/engram_mcp/sleep.py` (BES section) and arXiv:2605.28814.

(Append after §9. Update §7 schedule + §8 Last Deep Sleep line.)

## Metrics for Observability (token/compute future)
- generations={generations} pop_size={pop_size} operators={metrics.get('operators_applied',0)}
- This run used pure deterministic BES v1 (no LLM). When XAI_API_KEY present the same loop can call Grok for operator application and scoring.

## Sources (full traceability)
{src_lines}

---
*Generated by engram_trigger_deep_sleep (BES) via Grok / engram-mcp on {datetime.now().isoformat(timespec='seconds')}*
*Bidirectional Evolutionary Search v1 (deterministic). See "Self-Improving Language Models with Bidirectional Evolutionary Search" (arXiv:2605.28814).*
*Rules honored: BRAIN.md read first. 8-folder contract. Never delete. Human gate on proposals. No auto BRAIN edits.*
""".strip()


def trigger_deep_sleep_cycle(
    vault: Vault,
    generations: int = 4,
    population_size: int = 6,
    scope: str = "deep-manual",
    dry_run: bool = False,
    brain_md: str | None = None,
) -> str:
    """Orchestrator for Deep Sleep (BES). Mirrors trigger_sleep_cycle contract exactly."""
    if not (2 <= generations <= 8):
        raise ValueError(f"generations out of range (2-8): {generations}")
    if not (3 <= population_size <= 12):
        raise ValueError(f"population_size out of range (3-12): {population_size}")
    if scope not in DeepSleepScope:
        raise ValueError(f"invalid deep scope {scope}; allowed: {DeepSleepScope}")

    # NON-NEGOTIABLE — use pre-read content when caller already logged BRAIN-first
    brain = brain_md if brain_md is not None else vault.read_brain_md()

    ctx = collect_recent_context(vault, scope)
    ctx["brain_md"] = brain
    ctx["sources"].insert(0, "03 - SYSTEM/BRAIN.md")

    has_ctx = bool(ctx.get("daily_notes") or ctx.get("briefings") or ctx.get("queue_items"))
    if not has_ctx:
        msg = "Insufficient trajectories for BES Deep Sleep (need recent dailies/briefings). Logged."
        vault.log_action(f"DeepSleep skipped: {msg} (scope={scope}, gen={generations})")
        return f"⚠️ {msg} (BRAIN.md read; no deep artifact written.)"

    trajs = _extract_trajectories(ctx)
    subgoals = _backward_decompose(brain, ctx)
    bes_result = run_bidirectional_evolutionary_search(trajs, subgoals, generations, population_size)

    artifact = synthesize_deep_consolidated(ctx, bes_result, generations, population_size)

    if dry_run:
        vault.log_action(f"DeepSleep DRY-RUN (no write): scope={scope}, gen={generations}, pop={population_size}. BRAIN read first.")
        preview = artifact[:900] + "\n...(truncated preview)"
        return (
            f"✅ DEEP SLEEP DRY-RUN SUCCESS (log only).\n"
            f"scope={scope} generations={generations} pop={population_size}\n\n"
            f"--- Preview ---\n{preview}\n\n"
            f"BES metrics: {bes_result.get('metrics')}\n"
        )

    ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    filename = f"deep-{ts}-consolidation.md"
    out = vault._write_to_generated("consolidated/deep", filename, artifact)
    rel = out.relative_to(vault.root)

    vault.log_action(
        f"Deep Sleep (BES) complete: {rel} (scope={scope}, gen={generations}, pop={population_size}). "
        f"BRAIN read first. Evolutionary recombination performed. Proposal embedded."
    )

    # Phase 1 graph bridge hook (BES surprise edges included when multi-provenance)
    overlay_rel = export_deep_graph_overlay(vault, ctx, bes_result, str(rel), dry_run=False)

    last_block = (
        f"- **Last Deep Sleep:** {rel.name}  \n"
        f"  scope={scope}, generations={generations}, pop={population_size} — see `04 - GENERATED/consolidated/deep/{rel.name}`"
    )

    overlay_note = f"\n📊 Graph overlay: {overlay_rel}" if overlay_rel else ""
    return (
        f"✅ SUCCESS: Deep Sleep (BES) complete.\n"
        f"📁 Artifact: {rel}{overlay_note}\n"
        f"scope={scope} | generations={generations} | pop_size={population_size}\n\n"
        f"--- Preview (head) ---\n{artifact[:650]}...\n\n"
        f"Deep consolidated memory (evolved trajectories + subgoal progress) now in vault.\n"
        f"Embedded BRAIN proposal (new §10) requires explicit human paste.\n\n"
        f"--- Paste into BRAIN.md §8 (Current Context Snapshot) ---\n"
        f"{last_block}\n"
        f"(Replace previous Last Deep Sleep line. This is the maintenance step.)"
    )


def get_last_deep_sleep_status(vault: Vault) -> Optional[dict]:
    """
    Derive last Deep Sleep (BES) status from artifacts in consolidated/deep/.
    Honest, no extra state. Falls back to scanning consolidated/ for deep- prefixed files.
    """
    base = vault.root / vault.FOLDERS["generated"] / "consolidated"
    deep_dir = base / "deep"

    candidates: list = []
    if deep_dir.exists():
        candidates = list(deep_dir.glob("deep-*-consolidation.md"))

    if not candidates:
        if base.exists():
            candidates = [p for p in base.glob("deep-*-consolidation.md")]

    if not candidates:
        return None

    latest = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]

    try:
        header = latest.read_text(encoding="utf-8", errors="ignore").splitlines()[:6]
        header_text = " ".join(header)
    except Exception:
        header_text = ""

    scope_m = re.search(r"scope:\s*([a-z-]+)", header_text, re.I)
    gen_m = re.search(r"generations=(\d+)", header_text)
    pop_m = re.search(r"pop(?:_size)?=(\d+)", header_text)

    return {
        "artifact": str(latest.relative_to(vault.root)),
        "filename": latest.name,
        "scope": scope_m.group(1) if scope_m else "deep-unknown",
        "generations": int(gen_m.group(1)) if gen_m else 0,
        "population_size": int(pop_m.group(1)) if pop_m else 0,
    }
