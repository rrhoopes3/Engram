"""
engram_mcp.graph_export — Phase 1: vault JSON writer + deterministic graph overlay export.

After sleep/deep_sleep, emit engram-graph-overlay-v1 JSON sidecar in 04 - GENERATED/graph-export/
alongside the .md artifact. Enables LLM Wiki (or Obsidian plugins) to import sleep-inferred
edges, clusters, priority signals without any code merge.

- All I/O through Vault safe writers (_write_json_to_generated + _write_to_generated for manifest.md)
- Uses the *already collected* ctx from sleep (no ad-hoc full vault re-scan in hot path)
- Stable node IDs: sha256(rel_path)[:16]
- BES trajectories produce bes_surprise edges when provenance spans sources
- Dry-run + sparse-vault respected (no writes)
- Standalone MCP tool supports incremental (ctx-based) + full (broader capped)
- Logs every export to system-log.md per POS rules

BRAIN.md read first (enforced by callers). Never-delete, 8-folder, human gate.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .vault import Vault, VaultError


def _stable_node_id(rel_path: str) -> str:
    """Deterministic short ID stable across re-exports and machines."""
    return hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:16]


def _infer_kind(rel_path: str) -> str:
    p = rel_path.lower().replace("\\", "/")
    if "brain.md" in p:
        return "brain"
    if "/daily/" in p:
        return "daily"
    if "/briefings/" in p or "briefing" in p:
        return "briefing"
    if "/consolidated/" in p:
        return "consolidated"
    if "05 - queue" in p or p.startswith("05 - queue"):
        return "queue"
    if "07 - archive" in p:
        return "archive"
    if "03 - system" in p:
        return "system"
    return "other"


def _build_nodes_from_ctx(ctx: dict[str, Any], vault: Vault) -> list[dict[str, Any]]:
    """Nodes for every source present in the sleep/deep context (no extra reads)."""
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()

    # BRAIN.md (always injected by orchestrator)
    brain_rel = "03 - SYSTEM/BRAIN.md"
    bid = _stable_node_id(brain_rel)
    if bid not in seen:
        nodes.append({
            "id": bid,
            "label": "BRAIN.md",
            "path": brain_rel,
            "folder": "03 - SYSTEM",
            "kind": "brain",
            "wikilink_aliases": ["BRAIN", "Brain"],
            "last_seen": ctx.get("collected_at", datetime.now().isoformat(timespec="seconds")),
            "sleep_weight": 1.0,
            "tags": [],
        })
        seen.add(bid)

    # Daily notes
    for d in sorted(ctx.get("daily_notes", {}).keys()):
        rel = f"01 - ACTIVE/daily/{d}.md"
        nid = _stable_node_id(rel)
        if nid not in seen:
            nodes.append({
                "id": nid,
                "label": f"Daily {d}",
                "path": rel,
                "folder": "01 - ACTIVE",
                "kind": "daily",
                "wikilink_aliases": [d],
                "last_seen": ctx.get("collected_at", ""),
                "sleep_weight": 0.8,
                "tags": [],
            })
            seen.add(nid)

    # Briefings (keys are YYYY-MM-DD or stem)
    for k in sorted(ctx.get("briefings", {}).keys()):
        fname = f"{k}-morning.md" if not str(k).endswith(".md") else k
        rel = f"04 - GENERATED/briefings/{fname}"
        nid = _stable_node_id(rel)
        if nid not in seen:
            nodes.append({
                "id": nid,
                "label": f"Briefing {k}",
                "path": rel,
                "folder": "04 - GENERATED",
                "kind": "briefing",
                "wikilink_aliases": [],
                "last_seen": ctx.get("collected_at", ""),
                "sleep_weight": 0.7,
                "tags": [],
            })
            seen.add(nid)

    # QUEUE items
    for name, _ in ctx.get("queue_items", []):
        rel = f"05 - QUEUE/{name}"
        nid = _stable_node_id(rel)
        if nid not in seen:
            nodes.append({
                "id": nid,
                "label": str(name)[:60],
                "path": rel,
                "folder": "05 - QUEUE",
                "kind": "queue",
                "wikilink_aliases": [],
                "last_seen": ctx.get("collected_at", ""),
                "sleep_weight": 0.5,
                "tags": [],
            })
            seen.add(nid)

    # Archived samples (names as stored in ctx; may be ts-- prefixed)
    for name, _ in ctx.get("archived_samples", []):
        rel = f"07 - ARCHIVE/{name}"
        nid = _stable_node_id(rel)
        if nid not in seen:
            nodes.append({
                "id": nid,
                "label": str(name)[:50],
                "path": rel,
                "folder": "07 - ARCHIVE",
                "kind": "archive",
                "wikilink_aliases": [],
                "last_seen": ctx.get("collected_at", ""),
                "sleep_weight": 0.3,
                "tags": [],
            })
            seen.add(nid)

    return nodes


def _build_edges_from_ctx_and_passes(
    ctx: dict[str, Any],
    nodes: list[dict[str, Any]],
    passes: list[str],
    bes_result: Optional[dict[str, Any]] = None,
    artifact_rel_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Heuristic edges (v1). No full wikilink regex scan (deferred v1.1).
    artifact_rel_path (when provided) is written into every edge's provenance.artifact
    for full traceability back to the consolidation .md that produced the edge.
    """
    edges: list[dict[str, Any]] = []
    path_to_id = {n["path"]: n["id"] for n in nodes}
    scope = ctx.get("scope", "unknown")
    art = artifact_rel_path or ""

    # 1. Cross-day daily chains (temporal backbone)
    daily_paths = sorted(p for p in path_to_id if "/daily/" in p)
    for i in range(len(daily_paths) - 1):
        a = path_to_id[daily_paths[i]]
        b = path_to_id[daily_paths[i + 1]]
        edges.append({
            "id": f"edge-{uuid.uuid4().hex[:12]}",
            "source": a,
            "target": b,
            "type": "cross_day",
            "weight": 0.55,
            "confidence": "heuristic",
            "label": "Cross-day daily synthesis",
            "provenance": {
                "artifact": art,
                "sleep_scope": scope,
                "pass": 2,
                "bes_operator": None,
            },
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    # 2. Pass-2 synthesis signals (string match in passes output)
    p2 = " ".join(passes).lower() if passes else ""
    brain_id = path_to_id.get("03 - SYSTEM/BRAIN.md")
    if brain_id and ("foundation+automation" in p2 or "multi-source coherence" in p2):
        for p, nid in path_to_id.items():
            if "/daily/" in p or "briefing" in p:
                edges.append({
                    "id": f"edge-{uuid.uuid4().hex[:12]}",
                    "source": brain_id,
                    "target": nid,
                    "type": "sleep_synthesis",
                    "weight": 0.65,
                    "confidence": "heuristic",
                    "label": "Pass 2: foundation+automation / multi-source link",
                    "provenance": {"artifact": art, "sleep_scope": scope, "pass": 2, "bes_operator": None},
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                })
                break

    # 3. BES surprise edges (only when deep + multi-provenance trajs)
    if bes_result:
        for t in bes_result.get("population", [])[:4]:
            prov = t.get("provenance", [])
            if len([pr for pr in prov if ":" in pr]) >= 2:
                node_ids = []
                for pr in prov:
                    if pr.startswith("daily:"):
                        d = pr.split(":", 1)[1]
                        cand = f"01 - ACTIVE/daily/{d}.md"
                        if cand in path_to_id:
                            node_ids.append(path_to_id[cand])
                    elif pr.startswith("briefing:"):
                        b = pr.split(":", 1)[1]
                        cand = f"04 - GENERATED/briefings/{b}-morning.md"
                        if cand in path_to_id:
                            node_ids.append(path_to_id[cand])
                    elif pr.startswith("queue:"):
                        q = pr.split(":", 1)[1]
                        cand = f"05 - QUEUE/{q}"
                        if cand in path_to_id:
                            node_ids.append(path_to_id[cand])
                    elif pr.startswith("archive:"):
                        a = pr.split(":", 1)[1]
                        cand = f"07 - ARCHIVE/{a}"
                        if cand in path_to_id:
                            node_ids.append(path_to_id[cand])
                for ii in range(len(node_ids) - 1):
                    edges.append({
                        "id": f"edge-{uuid.uuid4().hex[:12]}",
                        "source": node_ids[ii],
                        "target": node_ids[ii + 1],
                        "type": "bes_surprise",
                        "weight": round(float(t.get("score", 0.5)) + 0.08, 2),
                        "confidence": "bes_score",
                        "label": str(t.get("text", ""))[:78],
                        "provenance": {
                            "artifact": art,
                            "sleep_scope": scope,
                            "pass": None,
                            "bes_operator": next((op for op in prov if op in ("crossover", "translocation", "combination", "deletion")), None),
                        },
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    })

    # Dedup by (src, tgt, type)
    dedup: list[dict[str, Any]] = []
    seen_e: set[tuple] = set()
    for e in edges:
        key = (e["source"], e["target"], e["type"])
        if key not in seen_e:
            seen_e.add(key)
            dedup.append(e)
    return dedup


def build_graph_overlay(
    vault: Vault,
    ctx: dict[str, Any],
    passes: Optional[list[str]] = None,
    sleep_artifact: Optional[str] = None,
    deep_artifact: Optional[str] = None,
    bes_result: Optional[dict[str, Any]] = None,
    generated_by: str = "engram_trigger_sleep",
) -> dict[str, Any]:
    """Pure builder (no I/O). Returns complete engram-graph-overlay-v1 payload."""
    nodes = _build_nodes_from_ctx(ctx, vault)
    edges = _build_edges_from_ctx_and_passes(ctx, nodes, passes or [], bes_result, sleep_artifact or deep_artifact)

    # Clusters by top-level folder (LLM Wiki will run Louvain on top)
    by_folder: dict[str, list[str]] = {}
    for n in nodes:
        by_folder.setdefault(n.get("folder", "other"), []).append(n["id"])
    clusters = [{"label": f, "node_ids": ids} for f, ids in by_folder.items()]

    # Minimal priority signals (can be enriched later from BRAIN extract)
    prio: list[dict[str, Any]] = []
    flat = str(ctx).lower()
    if "priority" in flat:
        prio.append({
            "phase": "current",
            "theme": "sleep consolidation + graph bridge",
            "affected_nodes": [nodes[0]["id"]] if nodes else [],
        })

    now = datetime.now().isoformat(timespec="seconds")
    return {
        "schema_version": "engram-graph-overlay-v1",
        "generated_at": now,
        "generated_by": generated_by,
        "vault_root_hint": str(vault.root),
        "sleep_artifact": sleep_artifact,
        "deep_sleep_artifact": deep_artifact,
        "nodes": nodes,
        "edges": edges,
        "clusters_suggested": clusters,
        "priority_signals": prio,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "sources_processed": len(ctx.get("sources", [])),
        },
    }


def _write_manifest(
    vault: Vault,
    latest_sleep: Optional[str],
    latest_deep: Optional[str],
    node_count: int,
    edge_count: int,
) -> Path:
    """Human-readable index (written via regular md writer to graph-export/).
    Robust against clobbering: always scans the graph-export dir for the most recent
    *-sleep-overlay.json and *-deep-overlay.json so that writing one type never
    erases knowledge of the other type.
    """
    gdir = vault.root / vault.FOLDERS["generated"] / "graph-export"

    def _find_latest(prefix: str) -> Optional[str]:
        if not gdir.exists():
            return None
        cands = sorted(
            [p.name for p in gdir.glob(f"*-{prefix}-overlay.json") if not p.name.startswith("latest-")],
            reverse=True,
        )
        return cands[0] if cands else None

    # Prefer the one we are writing right now; fall back to scan
    sleep_name = latest_sleep or _find_latest("sleep")
    deep_name = latest_deep or _find_latest("deep")

    md = f"""# Engram Graph Export Manifest

**Last Updated:** {datetime.now().strftime("%Y-%m-%d %H:%M")}

**Last sleep overlay:** {sleep_name or "(none)"}
**Last deep overlay:** {deep_name or "(none)"}

**Nodes / edges (latest):** {node_count} / {edge_count}

**For LLM Wiki (Phase 1/2):** Add vault folders as read-only corpus:
- 01 - ACTIVE/ (dailies + projects)
- 03 - SYSTEM/BRAIN.md
- 04 - GENERATED/briefings/ + consolidated/
- 05 - QUEUE/
Then load the latest *-overlay.json as sidecar for sleep edges + clusters.

**Rules honored:** BRAIN.md first. Never-delete. GENERATED/graph-export/ only. No auto-mutation of notes.
See 05 - QUEUE/PLAN-engram-llm-wiki-graph-bridge.md (Phase 1 complete).

---
*Generated by engram-mcp graph_export. All POS rules enforced.*
"""
    return vault._write_to_generated("graph-export", "manifest.md", md)


def export_sleep_graph_overlay(
    vault: Vault,
    ctx: dict[str, Any],
    passes: list[str],
    artifact_rel_path: str,
    dry_run: bool = False,
) -> Optional[str]:
    """Called at end of trigger_sleep_cycle (after md write)."""
    if dry_run:
        vault.log_action("Graph export: skipped (dry_run sleep)")
        return None
    has_ctx = bool(ctx.get("daily_notes") or ctx.get("briefings") or ctx.get("queue_items"))
    if not has_ctx:
        vault.log_action("Graph export: skipped (insufficient context for sleep overlay)")
        return None

    payload = build_graph_overlay(
        vault, ctx, passes=passes, sleep_artifact=artifact_rel_path, generated_by="engram_trigger_sleep"
    )  # artifact_rel_path is threaded into every edge provenance via the builder
    ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    name = f"{ts}-sleep-overlay.json"
    out = vault._write_json_to_generated("graph-export", name, payload)
    vault._write_json_to_generated("graph-export", "latest-sleep-overlay.json", payload)
    _write_manifest(vault, name, None, payload["stats"]["node_count"], payload["stats"]["edge_count"])

    rel = str(out.relative_to(vault.root))
    vault.log_action(
        f"Graph export: {rel} (nodes={payload['stats']['node_count']}, edges={payload['stats']['edge_count']}, scope={ctx.get('scope', 'nightly')})"
    )
    return rel


def export_deep_graph_overlay(
    vault: Vault,
    ctx: dict[str, Any],
    bes_result: dict[str, Any],
    artifact_rel_path: str,
    dry_run: bool = False,
) -> Optional[str]:
    """Called at end of trigger_deep_sleep_cycle."""
    if dry_run:
        vault.log_action("Graph export: skipped (dry_run deep sleep)")
        return None
    has_ctx = bool(ctx.get("daily_notes") or ctx.get("briefings") or ctx.get("queue_items"))
    if not has_ctx:
        vault.log_action("Graph export: skipped (insufficient context for deep overlay)")
        return None

    payload = build_graph_overlay(
        vault, ctx, passes=[], deep_artifact=artifact_rel_path, bes_result=bes_result, generated_by="engram_trigger_deep_sleep"
    )
    ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    name = f"{ts}-deep-overlay.json"
    out = vault._write_json_to_generated("graph-export", name, payload)
    vault._write_json_to_generated("graph-export", "latest-deep-overlay.json", payload)
    _write_manifest(vault, None, name, payload["stats"]["node_count"], payload["stats"]["edge_count"])

    rel = str(out.relative_to(vault.root))
    vault.log_action(
        f"Graph export: {rel} (nodes={payload['stats']['node_count']}, edges={payload['stats']['edge_count']}, scope=deep)"
    )
    return rel


def collect_for_full_export(vault: Vault) -> dict[str, Any]:
    """Broader collection for mode=full (still safe caps; reuses sleep collector)."""
    from .sleep import collect_recent_context

    ctx = collect_recent_context(vault, "ad-hoc")
    # full just means "use what we have + explicit note"
    ctx["scope"] = "full-export"
    return ctx


def export_graph_overlay_standalone(
    vault: Vault,
    mode: str = "incremental",
    include_archived: bool = False,
    dry_run: bool = False,
) -> str:
    """Implementation for engram_export_graph_overlay MCP tool."""
    _ = vault.read_brain_md()  # contract
    from .sleep import collect_recent_context

    if mode == "full":
        ctx = collect_for_full_export(vault)
    else:
        ctx = collect_recent_context(vault, "manual")

    ctx["brain_md"] = vault.read_brain_md()
    if "03 - SYSTEM/BRAIN.md" not in ctx.get("sources", []):
        ctx["sources"].insert(0, "03 - SYSTEM/BRAIN.md")

    payload = build_graph_overlay(vault, ctx, generated_by="engram_export_graph_overlay")  # artifact left empty for manual standalone (no consolidation .md)

    if dry_run:
        vault.log_action(f"Graph export DRY-RUN (standalone, mode={mode}): n={payload['stats']['node_count']} e={payload['stats']['edge_count']}")
        return (
            f"✅ DRY-RUN SUCCESS: engram_export_graph_overlay (mode={mode})\n"
            f"Nodes: {payload['stats']['node_count']}  Edges: {payload['stats']['edge_count']}\n"
            f"Sources processed: {payload['stats']['sources_processed']}\n"
            "No files written (preview only). Use dry_run=False to persist overlay JSON + manifest."
        )

    ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    name = f"{ts}-manual-overlay.json"
    out = vault._write_json_to_generated("graph-export", name, payload)
    vault._write_json_to_generated("graph-export", "latest-sleep-overlay.json", payload)
    _write_manifest(vault, name, None, payload["stats"]["node_count"], payload["stats"]["edge_count"])
    rel = str(out.relative_to(vault.root))
    vault.log_action(f"Graph export (standalone {mode}): {rel} (nodes={payload['stats']['node_count']}, edges={payload['stats']['edge_count']})")
    return (
        f"✅ SUCCESS: Graph overlay exported via engram_export_graph_overlay\n"
        f"📁 {rel}\n"
        f"Nodes={payload['stats']['node_count']} Edges={payload['stats']['edge_count']}\n"
        f"Manifest: 04 - GENERATED/graph-export/manifest.md\n"
        "Ready for LLM Wiki sidecar load (Phase 1 bridge complete)."
    )


def get_last_overlay_status(vault: Vault) -> Optional[dict]:
    """
    Honest observability (mirrors get_last_sleep_status / deep).
    Scans 04 - GENERATED/graph-export/ for most recent *-overlay.json (sleep/deep/manual).
    Reads stats from the JSON itself. No extra state.
    """
    gdir = vault.root / vault.FOLDERS["generated"] / "graph-export"
    if not gdir.exists():
        return None
    candidates = sorted(
        [p for p in gdir.glob("*-overlay.json") if not p.name.startswith("latest-")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    latest = candidates[0]
    try:
        data = __import__("json").loads(latest.read_text(encoding="utf-8", errors="ignore"))
        stats = data.get("stats", {})
        return {
            "artifact": str(latest.relative_to(vault.root)),
            "filename": latest.name,
            "generated_by": data.get("generated_by", "unknown"),
            "node_count": stats.get("node_count", 0),
            "edge_count": stats.get("edge_count", 0),
            "sleep_artifact": data.get("sleep_artifact"),
            "deep_sleep_artifact": data.get("deep_sleep_artifact"),
        }
    except Exception:
        return {
            "artifact": str(latest.relative_to(vault.root)),
            "filename": latest.name,
            "generated_by": "unknown",
            "node_count": 0,
            "edge_count": 0,
        }
