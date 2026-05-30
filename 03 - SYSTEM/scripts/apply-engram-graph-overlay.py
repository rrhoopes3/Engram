#!/usr/bin/env python3
"""
apply-engram-graph-overlay.py

Phase 2 bridge script for Engram × LLM Wiki.

Reads the latest engram-graph-overlay-v1 JSON(s) produced by sleep/deep_sleep
and turns them into human-readable, Obsidian-style markdown notes containing
wikilinks for the inferred connections.

These notes can be dropped into (or re-ingested by) LLM Wiki so the
"temporal dreams" (sleep synthesis, BES surprise edges, cross-day links)
become visible in the spatial graph.

Usage:
    python "03 - SYSTEM/scripts/apply-engram-graph-overlay.py"          # dry-run (default, safe)
    python "03 - SYSTEM/scripts/apply-engram-graph-overlay.py" --write  # actually write the files

Environment:
    BRAIN_VAULT_PATH (optional) — defaults to discovery from this script.

Safety:
- Never modifies anything outside 04 - GENERATED/graph-export/
- Never touches LLM Wiki's internal data
- --write is required to persist files
- Always logs actions via the vault layer

See: 05 - QUEUE/PLAN-engram-llm-wiki-graph-bridge.md (Phase 2)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Make engram_mcp importable when run from vault root
SCRIPT_DIR = Path(__file__).resolve().parent
VAULT_ROOT = SCRIPT_DIR.parent.parent  # 03 - SYSTEM/scripts/ -> vault root
sys.path.insert(0, str(VAULT_ROOT / "engram-mcp" / "src"))

from engram_mcp.vault import Vault, VaultError


def load_latest_overlay(vault: Vault, kind: str = "sleep") -> Optional[dict[str, Any]]:
    """Load latest-sleep-overlay.json or latest-deep-overlay.json if present."""
    overlay_dir = vault.root / "04 - GENERATED" / "graph-export"
    pointer = overlay_dir / f"latest-{kind}-overlay.json"
    if not pointer.exists():
        return None
    try:
        return json.loads(pointer.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warning: Could not parse {pointer.name}: {e}")
        return None


def node_label(node: dict[str, Any]) -> str:
    """Return a nice label suitable for wikilinks."""
    label = node.get("label", "")
    if not label:
        label = Path(node.get("path", "")).stem
    # Make daily notes more wikilink-friendly
    if node.get("kind") == "daily":
        label = label.replace("Daily ", "")
    return label.strip()


def build_edges_markdown(overlay: dict[str, Any], source_name: str) -> str:
    """Turn one overlay's edges into clean, grouped markdown."""
    edges = overlay.get("edges", [])
    if not edges:
        return f"_(No edges in {source_name})_\n"

    # Group by type for readability
    by_type: dict[str, list[dict]] = {}
    for e in edges:
        t = e.get("type", "unknown")
        by_type.setdefault(t, []).append(e)

    lines: list[str] = []
    lines.append(f"## {source_name}")
    lines.append(f"Generated from: `{overlay.get('sleep_artifact') or overlay.get('deep_sleep_artifact') or 'overlay JSON'}`")
    lines.append(f"Nodes: {overlay['stats']['node_count']} | Edges: {overlay['stats']['edge_count']}")
    lines.append("")

    type_order = ["bes_surprise", "sleep_synthesis", "cross_day", "wikilink"]
    type_titles = {
        "bes_surprise": "BES Surprise Connections (evolved trajectories)",
        "sleep_synthesis": "Sleep Synthesis (recurrent passes)",
        "cross_day": "Cross-Day Links",
        "wikilink": "Wikilink-based",
    }

    for t in type_order + [k for k in by_type if k not in type_order]:
        group = by_type.get(t, [])
        if not group:
            continue

        # Sort strongest first
        group.sort(key=lambda x: x.get("weight", 0), reverse=True)

        lines.append(f"### {type_titles.get(t, t.title())}")
        for e in group[:25]:  # cap for sanity
            src = e.get("source_label") or ""
            tgt = e.get("target_label") or ""
            # Fallback: we don't store labels in the current schema, so resolve from nodes
            # (we'll enrich below)
            w = e.get("weight", 0)
            conf = e.get("confidence", "")
            label = e.get("label", "")[:70]

            prov = e.get("provenance", {})
            art = prov.get("artifact", "")
            art_short = Path(art).name if art else ""

            line = f"- [[{src}]] → [[{tgt}]] — **{t}** (w={w:.2f}"
            if conf:
                line += f", {conf}"
            line += ")"
            if label:
                line += f"  \n  *{label}*"
            if art_short:
                line += f"  \n  (from {art_short})"
            lines.append(line)
        lines.append("")

    return "\n".join(lines)


def enrich_edge_labels(overlay: dict[str, Any]) -> None:
    """Attach source_label / target_label to edges for nice wikilinks (in-memory only)."""
    id_to_label = {n["id"]: node_label(n) for n in overlay.get("nodes", [])}
    for e in overlay.get("edges", []):
        e["source_label"] = id_to_label.get(e.get("source"), e.get("source", "???"))
        e["target_label"] = id_to_label.get(e.get("target"), e.get("target", "???"))


def generate_companion_markdown(vault: Vault, write: bool = False) -> str:
    """Main logic. Returns the markdown content (and writes if requested)."""
    sleep_ov = load_latest_overlay(vault, "sleep")
    deep_ov = load_latest_overlay(vault, "deep")

    if not sleep_ov and not deep_ov:
        return "No overlay JSONs found in 04 - GENERATED/graph-export/. Run a sleep cycle first."

    date = datetime.now().strftime("%Y-%m-%d")
    sections: list[str] = []

    header = f"""# Sleep-Inferred Connections — {date}

**Purpose**: These are suggestions from Engram's overnight consolidation (sleep + optional Deep Sleep BES).  
They are **not** facts. Review before using them to connect notes in LLM Wiki or Obsidian.

**How to use**:
- Re-ingest this file (or copy interesting lines) into LLM Wiki
- Or manually create the surprise connections using LLM Wiki's native tools
- Stronger weights (≥ 0.7) and BES surprise edges are usually the most interesting

**Source overlays**:
"""

    sections.append(header.strip())

    if sleep_ov:
        enrich_edge_labels(sleep_ov)
        sections.append(build_edges_markdown(sleep_ov, "Regular Sleep Overlay"))

    if deep_ov:
        enrich_edge_labels(deep_ov)
        sections.append(build_edges_markdown(deep_ov, "Deep Sleep (BES) Overlay"))

    footer = f"""
---

*Generated by apply-engram-graph-overlay.py (Phase 2 bridge) on {datetime.now().isoformat(timespec='seconds')}*
*Rules: BRAIN.md first. All writes go through GENERATED/graph-export/. Suggestions only — NEEDS HUMAN INPUT.*
*See 05 - QUEUE/PLAN-engram-llm-wiki-graph-bridge.md*
"""
    full = "\n\n".join(sections) + "\n" + footer.strip()

    if write:
        # Use the safe generated writer so it gets logged properly
        ts = datetime.now().strftime("%Y-%m-%d-%H%M")
        filename = f"{ts}-overlay-edges.md"
        target = vault._write_to_generated("graph-export", filename, full)

        # Also maintain a stable "latest" pointer (overwrite is intentional and safe here)
        vault._write_to_generated("graph-export", "overlay-edges.md", full)

        vault.log_action(
            f"Phase 2 bridge: wrote companion edges markdown → {target.relative_to(vault.root)} "
            f"(from sleep={bool(sleep_ov)}, deep={bool(deep_ov)})"
        )
        return f"Wrote:\n  {target.relative_to(vault.root)}\n  04 - GENERATED/graph-export/overlay-edges.md (latest pointer)"

    return full


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Turn Engram sleep graph overlays into LLM Wiki / Obsidian friendly wikilink notes."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually write the companion markdown file(s). Default is dry-run (preview only).",
    )
    args = parser.parse_args()

    try:
        vault = Vault()
        _ = vault.read_brain_md()  # mandatory

        result = generate_companion_markdown(vault, write=args.write)

        if args.write:
            print("SUCCESS")
            print(result)
        else:
            print("=== DRY RUN (no files written) ===")
            print(result)
            print("\nRe-run with --write to persist the companion note.")

        return 0

    except VaultError as e:
        print(f"VAULT RULE VIOLATION: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
