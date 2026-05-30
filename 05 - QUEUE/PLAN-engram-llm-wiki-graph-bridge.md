# PLAN: Engram × LLM Wiki — Living Second Brain Integration

**Status:** Ready for implementation  
**Author:** Cursor agent (2026-05-29)  
**Target executor:** Grok via `engram-mcp` on VPS  
**Prerequisite:** Read `03 - SYSTEM/BRAIN.md` first. Honor all 8-folder POS rules.

---

## 1. Executive Summary

### Vision
Combine **Engram** (agentic POS: sleep consolidation, Deep Sleep/BES, briefings, BRAIN.md governance) with **[LLM Wiki](https://github.com/nashsu/llm_wiki)** (polished desktop knowledge graph: ForceAtlas2, Louvain clustering, surprise connections) into a **loosely coupled hybrid**:

> **Engram thinks overnight; LLM Wiki lets you explore what it dreamed.**

Engram remains the **intelligence + operating backend** (MCP, N8N, vault rules, human gates).  
LLM Wiki remains the **spatial exploration frontend** (corpus graph, clustering, navigation UX).

**Do not merge codebases.** Build a **bridge layer** inside `engram-mcp` that exports structured graph overlays from sleep artifacts, plus optional vault sync metadata.

### Unique Use Case (differentiator)
Most PKM tools do **either** offline consolidation **or** beautiful graphs. This combo adds a **time dimension**:

| Layer | Tool | Question answered |
|-------|------|-------------------|
| Spatial | LLM Wiki | "What connects to what across my corpus?" |
| Temporal | Engram Sleep/BES | "What changed overnight? What priorities evolved? What surprised us?" |
| Operational | Engram POS | "What should I do today?" (briefings, QUEUE, projects) |

Combined experience: open LLM Wiki in the morning and see corpus links **plus** last night's consolidation overlays (sleep-inferred edges, BES surprise connections, priority-weighted clusters).

---

## 2. Current State Baseline (do not assume features that don't exist)

### Engram (verified in repo)
- Vault: 8 folders (`00 - CAPTURE` … `07 - ARCHIVE`), markdown-first, Obsidian-compatible wikilinks.
- `engram_trigger_sleep(n_passes=1..5, scope=nightly|manual|…)` → `04 - GENERATED/consolidated/YYYY-MM-DD-HHMM-sleep-consolidation.md`
- `engram_trigger_deep_sleep(generations=2..8, population_size=3..12, scope=deep-manual|…)` → `04 - GENERATED/consolidated/deep/deep-YYYY-MM-DD-HHMM-consolidation.md`
- Sleep v1 passes are **deterministic/heuristic** (no external LLM unless `XAI_API_KEY` future work).
- BES produces trajectories with `provenance`, `score`, evolutionary operators (crossover, translocation, combination, deletion).
- **No graph visualization** in Engram today.
- **No EFC metrics** in codebase (do not implement EFC in v1; use existing BES `score` + sleep pass metadata).
- `vault._write_to_generated()` only allows `.md` in whitelisted subs: `briefings`, `summaries`, `analyses`, `drafts`, `consolidated`, `consolidated/deep`.

### LLM Wiki (external)
- Cross-platform desktop app; ingests documents/PDFs/web clips into persistent interlinked wiki.
- v0.4.16: sigma.js + ForceAtlas2, Louvain clustering, layout caching, surprise connections, wikilinks.
- Likely ingests markdown folders natively (Obsidian-style). **Exact overlay import API unverified** — bridge must support manual/script import in Phase 1–2.

---

## 3. Architecture Principles

1. **Loose coupling** — no fork of LLM Wiki; no embedding sigma.js in engram-mcp.
2. **Engram writes; LLM Wiki reads** — primary data flow from vault → graph tool.
3. **Bidirectional optional** — LLM Wiki cluster exports can feed Deep Sleep scope (Phase 3).
4. **Never delete** — all bridge artifacts in `04 - GENERATED/`; supersede by timestamp, archive if retired.
5. **Human review gate** — graph overlays are **suggestions**, not auto-mutations of source notes.
6. **Traceability** — every node/edge cites vault source path + sleep artifact ID.
7. **Idempotent exports** — re-running export produces new timestamped files; latest pointer in manifest.

```
┌─────────────────────────────────────────────────────────────┐
│  Engram Vault (markdown, 8 folders)                         │
│  BRAIN.md · dailies · briefings · QUEUE · projects · …      │
└───────────────┬─────────────────────────────┬───────────────┘
                │                             │
                ▼                             ▼
┌───────────────────────────┐   ┌───────────────────────────┐
│  engram-mcp               │   │  LLM Wiki (desktop)       │
│  sleep / deep_sleep       │   │  folder ingest + graph UI │
│  → consolidated/*.md      │   │  Louvain · ForceAtlas2    │
│  → graph-export/*.json    │──►│  (overlay via sidecar)    │
│  N8N @ 03:00              │   │                           │
└───────────────────────────┘   └───────────────────────────┘
```

---

## 4. Deliverables by Phase

### Phase 0 — Manual validation (no code, 1 hour)
**Goal:** Confirm LLM Wiki ingest works on real vault content.

**Steps:**
1. Install LLM Wiki desktop app locally.
2. Add read-only ingest paths (user configures in LLM Wiki UI):
   - `01 - ACTIVE/` (projects, dailies)
   - `02 - REFERENCE/` or `06 - RESOURCES/` (if populated)
   - `04 - GENERATED/briefings/`
   - `04 - GENERATED/consolidated/` (optional — meta layer)
3. Exclude: `00 - CAPTURE/` (raw inbox), `07 - ARCHIVE/` (unless user wants full history).
4. Verify wikilinks resolve, graph renders, clustering works at vault scale.

**Acceptance:** User can navigate Engram vault as LLM Wiki graph without any bridge code.

---

### Phase 1 — Graph Export Sidecar (engram-mcp core)
**Goal:** After each sleep/deep_sleep run, emit machine-readable graph overlay JSON alongside existing markdown artifacts.

#### 1A. Vault layer changes (`engram-mcp/src/engram_mcp/vault.py`)

Add to `GENERATED_SUBS`:
```python
"graph-export"
```

Add new safe writer (parallel to `_write_to_generated`, JSON-only):
```python
def _write_json_to_generated(self, sub: str, filename: str, payload: dict) -> Path:
    """
    sub must be 'graph-export' only (v1).
    filename must end with .json, no path separators.
    Writes pretty-printed UTF-8 JSON with trailing newline.
    Logs to system-log.md via log_action().
    """
```

**Rules:** Same containment checks as markdown writer. Only `graph-export` sub allowed for JSON.

#### 1B. New module `engram-mcp/src/engram_mcp/graph_export.py`

Responsibilities:
- Parse sleep/deep_sleep **context dict** (already built in `collect_recent_context`) — do not re-read vault ad hoc.
- Map vault files → stable node IDs.
- Extract edges from sleep passes + BES trajectories.
- Write overlay JSON + manifest pointer.

**Node ID scheme (stable across exports):**
```
node_id = sha256(relative_vault_path)[:16]
```
Example: `01 - ACTIVE/projects/engram/overview.md` → deterministic hash.

**Node record schema (v1):**
```json
{
  "id": "a1b2c3d4e5f67890",
  "label": "Engram - Personal OS",
  "path": "01 - ACTIVE/projects/engram/overview.md",
  "folder": "01 - ACTIVE",
  "kind": "project|daily|briefing|brain|queue|consolidated|archive|other",
  "wikilink_aliases": ["Engram", "Personal OS"],
  "last_seen": "2026-05-29T03:12:00",
  "sleep_weight": 0.0,
  "tags": []
}
```

**Edge record schema (v1):**
```json
{
  "id": "edge-uuid-or-hash",
  "source": "node_id_a",
  "target": "node_id_b",
  "type": "wikilink|sleep_synthesis|bes_surprise|cross_day|priority_evolution",
  "weight": 0.72,
  "confidence": "heuristic|bes_score|human",
  "label": "Cross-day synthesis: foundation → automation",
  "provenance": {
    "artifact": "04 - GENERATED/consolidated/2026-05-29-0312-sleep-consolidation.md",
    "sleep_scope": "nightly",
    "pass": 2,
    "bes_operator": null
  },
  "created_at": "2026-05-29T03:12:00"
}
```

**Overlay bundle schema (`engram-graph-overlay-v1`):**
```json
{
  "schema_version": "engram-graph-overlay-v1",
  "generated_at": "2026-05-29T03:12:05",
  "generated_by": "engram_trigger_sleep",
  "vault_root_hint": "/path/on/vps",
  "sleep_artifact": "04 - GENERATED/consolidated/2026-05-29-0312-sleep-consolidation.md",
  "deep_sleep_artifact": null,
  "nodes": [],
  "edges": [],
  "clusters_suggested": [],
  "priority_signals": [],
  "stats": {
    "node_count": 0,
    "edge_count": 0,
    "sources_processed": 0
  }
}
```

#### 1C. Extraction logic (deterministic v1)

**Nodes — include all sources from sleep context:**
| Source key in `ctx` | `kind` | Path pattern |
|---------------------|--------|--------------|
| `brain_md` | `brain` | `03 - SYSTEM/BRAIN.md` |
| `daily_notes` | `daily` | `01 - ACTIVE/daily/{date}.md` |
| `briefings` | `briefing` | `04 - GENERATED/briefings/{date}-morning.md` |
| `queue_items` | `queue` | `05 - QUEUE/{name}` |
| `archived_samples` | `archive` | `07 - ARCHIVE/{name}` |
| `sources[]` | inferred | parse list |

**Edges — generate from:**

1. **Wikilink scan (optional v1.1):** Regex `\[\[([^\]|]+)(?:\|[^\]]+)?\]\]` on node bodies; map target to node if resolvable. Type: `wikilink`.

2. **Sleep Pass 2 connections:** When `_pass2_connect` detects patterns (e.g. "foundation+automation loop"), create edge between nodes whose paths/content match detected themes. Type: `sleep_synthesis`. Weight: 0.5 (heuristic).

3. **Cross-Day Synthesis block:** Parse consolidated markdown section `**Cross-Day Synthesis**` bullets; link daily ↔ briefing nodes from same consolidation window. Type: `cross_day`. Weight: 0.6.

4. **Priority Evolution:** Parse `**Priority Evolution**`; attach `priority_signals[]` array to overlay (not necessarily edges). Example:
   ```json
   {"phase": "Phase 2", "theme": "sleep consolidation", "affected_nodes": ["..."]}
   ```

5. **BES trajectories (deep sleep only):** For each top evolved individual in `population[:4]`:
   - Parse `provenance` list (`daily:2026-05-27`, `briefing:2026-05-21`, `crossover`, etc.)
   - If provenance spans ≥2 distinct source nodes → edge type `bes_surprise`, weight = trajectory `score`, label = first 80 chars of evolved text.
   - If `crossover|translocation|combination` in provenance → boost weight +0.1.

**Clusters suggested (heuristic v1):**
- Group nodes by top-level folder (`01 - ACTIVE`, `04 - GENERATED`, …) OR by BES shared provenance themes.
- Do not run Louvain in engram-mcp v1 (LLM Wiki owns layout/clustering).

#### 1D. Output files

After successful sleep write:
```
04 - GENERATED/graph-export/2026-05-29-0312-sleep-overlay.json
04 - GENERATED/graph-export/latest-sleep-overlay.json   # copy/symlink of latest (overwrite OK)
04 - GENERATED/graph-export/manifest.md                 # human-readable index (markdown OK)
```

After successful deep_sleep write:
```
04 - GENERATED/graph-export/2026-05-29-1430-deep-overlay.json
04 - GENERATED/graph-export/latest-deep-overlay.json
```

`manifest.md` template:
```markdown
# Engram Graph Export Manifest
**Last sleep overlay:** 2026-05-29-0312-sleep-overlay.json
**Last deep overlay:** (none)
**Nodes / edges:** 12 / 8
**For LLM Wiki:** import vault folders + apply overlay JSON via bridge script (Phase 2).
```

#### 1E. Hook into existing orchestrators (`sleep.py`)

At end of `trigger_sleep_cycle()` (after markdown artifact write, before return):
```python
from .graph_export import export_sleep_graph_overlay
overlay_path = export_sleep_graph_overlay(vault, ctx, passes, artifact_rel_path)
# Append overlay path to success return string
```

At end of `trigger_deep_sleep_cycle()`:
```python
overlay_path = export_deep_graph_overlay(vault, ctx, bes_result, artifact_rel_path)
```

**Dry-run:** Preview overlay stats in return string; do not write JSON.

**Sparse vault skip:** If sleep skips (insufficient context), do not write overlay.

#### 1F. New MCP tool (`server.py`)

```python
@mcp.tool()
def engram_export_graph_overlay(
    mode: str = "incremental",  # incremental | full
    include_archived: bool = False,
    dry_run: bool = False,
) -> str:
    """
    Standalone export: rebuild graph overlay from vault + last consolidation artifacts.
    mode=full scans all ingestible markdown under approved folders (cap 500 files).
    mode=incremental uses last sleep context only.
    Always reads BRAIN.md first.
    """
```

Use cases: manual refresh, N8N post-sleep step, debugging.

#### 1G. Tests (`engram-mcp/tests/test_graph_export.py`)

- Node ID stability (same path → same id).
- Sleep run produces JSON in `graph-export/`.
- Deep sleep adds `bes_surprise` edges when multi-provenance trajectories exist.
- Dry-run writes nothing.
- Invalid paths rejected by vault writer.
- Manifest updated.

#### 1H. Logging

Every export appends to `03 - SYSTEM/logs/system-log.md`:
```
Graph export: 04 - GENERATED/graph-export/2026-05-29-0312-sleep-overlay.json (nodes=12, edges=8, scope=nightly)
```

---

### Phase 2 — LLM Wiki Bridge Script (external to engram-mcp, in vault)
**Goal:** Apply Engram overlays inside LLM Wiki workflow (semi-automated).

#### 2A. Script location
`03 - SYSTEM/scripts/apply-engram-graph-overlay.py` (or `.sh` wrapper)

**Behavior:**
1. Read `04 - GENERATED/graph-export/latest-sleep-overlay.json` (+ optional deep).
2. Read LLM Wiki config path from env `LLM_WIKI_DATA_DIR` (user-supplied).
3. **If LLM Wiki has no overlay API:** generate companion markdown in vault:
   - `04 - GENERATED/graph-export/overlay-edges.md` — Obsidian-style note listing suggested connections:
     ```markdown
     ## Sleep-Inferred Connections (2026-05-29)
     - [[project-a]] ↔ [[project-b]] — cross_day (weight 0.6)
     - [[daily-2026-05-28]] → [[briefing-2026-05-29]] — sleep_synthesis
     ```
   - User re-ingests this file into LLM Wiki OR uses native surprise-connection UX to validate.

4. **If LLM Wiki exposes import/hooks (investigate upstream):** map overlay JSON → wiki's graph edge format.

**Do not auto-modify LLM Wiki internal DB without explicit user flag `--live`.**

#### 2B. N8N workflow extension
Extend nightly sleep workflow (after `engram_trigger_sleep`):
1. Call `engram_export_graph_overlay(mode=incremental)`.
2. Optional: notify user "Graph overlay ready" with node/edge counts.
3. Do **not** launch LLM Wiki automatically (desktop app).

---

### Phase 3 — Bidirectional Loop (advanced)
**Goal:** LLM Wiki clusters inform next Deep Sleep run.

#### 3A. Import format `engram-graph-import-v1`
User exports from LLM Wiki (manual or script) to:
```
00 - CAPTURE/llm-wiki-cluster-export-YYYY-MM-DD.json
```
or
```
04 - GENERATED/graph-export/llm-wiki-clusters-in.json
```

Schema (minimal):
```json
{
  "schema_version": "engram-graph-import-v1",
  "exported_at": "...",
  "clusters": [
    {"id": "c1", "label": "Engram Foundation", "node_paths": ["...", "..."]}
  ],
  "surprise_edges": [
    {"source_path": "...", "target_path": "...", "score": 0.9}
  ]
}
```

#### 3B. Deep Sleep scope expansion
Add optional param to `engram_trigger_deep_sleep`:
```python
cluster_focus: Optional[str] = None  # cluster id or theme from import
```
When set, `collect_recent_context` prioritizes files in that cluster + seeds BES trajectories from surprise_edges.

#### 3C. MCP tool
```python
engram_ingest_wiki_clusters(path: str, dry_run: bool = False) -> str
```

---

## 5. BRAIN.md Updates (human paste after Phase 1 ships)

Add new subsection under §9 or new §10:

```markdown
## Graph Bridge (Engram × LLM Wiki)

**Purpose:** Engram exports graph overlays after sleep/deep_sleep to `04 - GENERATED/graph-export/`. LLM Wiki ingests vault markdown + overlays for spatial exploration.

**Nightly flow:** 03:00 sleep → overlay JSON → (optional) morning LLM Wiki refresh.

**Rules:** Overlays are suggestions (NEEDS HUMAN INPUT). Never auto-edit source notes. LLM Wiki is read/explore UI; Engram remains operational backend.

**Last overlay:** see `04 - GENERATED/graph-export/manifest.md`
```

Update §8 snapshot lines for Last Sleep / Last Deep Sleep / Last Graph Export.

---

## 6. Implementation Task List (ordered)

| # | Task | File(s) | Est. |
|---|------|---------|------|
| 1 | Add `graph-export` to vault whitelist + JSON writer | `vault.py` | S |
| 2 | Implement `graph_export.py` (schemas, node/edge builders) | new | M |
| 3 | Hook sleep + deep_sleep orchestrators | `sleep.py` | S |
| 4 | Add `engram_export_graph_overlay` MCP tool | `server.py` | S |
| 5 | Unit tests | `tests/test_graph_export.py` | M |
| 6 | Update `engram_health` to report last overlay stats | `server.py` | S |
| 7 | Phase 0 manual LLM Wiki ingest (user) | — | S |
| 8 | Bridge script + manifest template | `03 - SYSTEM/scripts/` | M |
| 9 | N8N workflow step (optional) | n8n export | S |
| 10 | Phase 3 cluster import (defer) | `sleep.py`, new tool | L |

S = small (<2h), M = medium (2–6h), L = large (future sprint)

---

## 7. Acceptance Criteria (Phase 1 complete)

- [ ] `engram_trigger_sleep` writes both `.md` consolidation **and** `.json` overlay.
- [ ] `engram_trigger_deep_sleep` adds BES-derived `bes_surprise` edges when applicable.
- [ ] `engram_export_graph_overlay(dry_run=True)` returns preview without write.
- [ ] All writes go through vault safe writers; no new top-level folders.
- [ ] `manifest.md` always reflects latest overlay filenames + counts.
- [ ] Tests pass: `pytest engram-mcp/tests/test_graph_export.py -v`
- [ ] Docker rebuild + smoke: `grok mcp doctor engram-mcp` shows overlay in health (optional).
- [ ] Human can open LLM Wiki, ingest vault folders, and manually validate that overlay markdown companion lists plausible connections.

---

## 8. Non-Goals (explicit scope boundaries)

- Embedding LLM Wiki or sigma.js inside engram-mcp.
- Auto-editing `BRAIN.md` or source vault notes from graph export.
- Replacing LLM Wiki's Louvain clustering with Engram heuristics.
- EFC metrics (future research; use BES `score` for now).
- Real-time sync (batch/nightly is sufficient v1).
- Deleting or deduplicating vault files based on graph analysis.

---

## 9. Future Enhancements (post-v1)

1. **LLM-enriched passes:** When `XAI_API_KEY` set, use Grok in sleep passes to extract richer entities/edges before JSON export.
2. **EFC-style scoring:** Rename/clarify BES scores as "evolutionary fitness" in overlay UI.
3. **Obsidian plugin alternative:** Same JSON schema consumable by Obsidian graph plugins.
4. **Web dashboard:** Read-only overlay viewer (only if LLM Wiki bridge insufficient).
5. **Full vault scan mode:** `engram_export_graph_overlay(mode=full)` for initial bootstrap.

---

## 10. Grok Execution Instructions

When implementing this spec:

1. **Read `03 - SYSTEM/BRAIN.md` first** and log the read.
2. Work in `engram-mcp/` only for Phase 1 code changes.
3. Run tests before declaring done.
4. Log all automated actions to `03 - SYSTEM/logs/system-log.md`.
5. Propose BRAIN.md § updates as markdown snippet with **NEEDS HUMAN INPUT** — never auto-edit BRAIN.md.
6. After implementation, produce summary with:
   - Files changed
   - Sample overlay JSON (redacted paths OK)
   - Manual steps for user to connect LLM Wiki
7. Rebuild Docker on VPS if production deployment requested.

**Suggested first prompt to Grok:**
> Read BRAIN.md and `05 - QUEUE/PLAN-engram-llm-wiki-graph-bridge.md`. Implement Phase 1 (tasks 1–6 + tests). Do not start Phase 3. Follow all vault rules.

---

## 11. Reference Paths

| Item | Path |
|------|------|
| BRAIN | `03 - SYSTEM/BRAIN.md` |
| Sleep module | `engram-mcp/src/engram_mcp/sleep.py` |
| Vault layer | `engram-mcp/src/engram_mcp/vault.py` |
| MCP server | `engram-mcp/src/engram_mcp/server.py` |
| Consolidated output | `04 - GENERATED/consolidated/` |
| Deep consolidated | `04 - GENERATED/consolidated/deep/` |
| Graph export (new) | `04 - GENERATED/graph-export/` |
| LLM Wiki upstream | https://github.com/nashsu/llm_wiki |

---

*Generated for Engram POS — feed to Grok / engram-mcp implementation session.*
