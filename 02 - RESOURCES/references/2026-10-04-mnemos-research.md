---
date: 2026-10-04
type: reference
topic: Mnemos (Riley Coyote) — external memory system research
source: https://github.com/Riley-Coyote/mnemos (read at commit cc3cf9b, 2026-10-04)
status: reviewed
---

# 2026-10-04 — Mnemos research: what's real, what's claimed, what to steal

**Bottom line:** Mnemos is a real, serious, heavily tested MCP memory server. Its claim to beat Claude's native memory by 2–2.5x comes from a private lab and can't be reproduced from the public repo. Its strongest idea, **memory that comes to the agent unasked**, applies directly to Engram.

## The claim (X, @RileyRalmuto, 2026-10-02 → 10-04)

| Claim | Status |
|---|---|
| "Mnemos v3.1-jev beat Claude native memory ~2.5x" | Revised down within 2 days |
| Lessons applied to new situations: 82% vs 6% | 82% appears in source (see below); 6% baseline not in repo |
| Revised: 30 model-written questions from real transcripts, 10 sealed, 240 runs, independent judge → 65% vs 33% of needed facts recalled | Self-run, not peer-reviewed, eval code private |
| Side effect: longer answers | Admitted by author |

## What the repo confirms

- **Size and activity:** ~88k lines, roughly half tests, last commit 2026-10-04 (PR #115). PyPI name `mnemos-continuity`.
- **Surface:** 11 MCP tools (`mnemos_context`, `_capture`, `_recall`, `_correct`, `_reflect`, `_handoff`, `_journal`, `_note`, ...). Local SQLite, optional local embeddings, no account needed.
- **Scope is deliberately narrow.** README: *"It is not your memory system."* It holds a small set of durable things about the human and the working relationship. It does not index documents.
- **"jev" is a component.** `mnemos/jev.py` is an optional relevance judge on a third-party paid API (`api.typesafe.ai`). It's off by default and needs a key. When on, it sends up to 1,000 characters of the message plus up to 6 memory lines per call, with a 0.4s timeout and no retry.
- **Where 82% comes from.** `mnemos/cue.py` docstring: with a notebook tool also present, the agent searched ~4×/question instead of 7, and lesson transfer **fell from 82% to 35%**. So 82% is Mnemos's own lab score, not a head-to-head.
- **The head-to-head isn't public.** Code references a private `mnemos-lab` notebook. The public `benchmarks/` folder tests only internal tuning (synthetic 224-memory graph, 10-probe packet test). Neither compares against Claude.

## Why to read the numbers carefully

- Questions were generated from the author's own transcripts.
- An LLM graded the answers.
- The metric counts **needed facts recalled**. Longer answers get more chances to hit facts, and nothing penalizes wrong or irrelevant ones.
- It's unclear which "native Claude memory" setup was the baseline.

## Mechanisms worth knowing

| Mechanism | What it does |
|---|---|
| **The cue** (`UserPromptSubmit` hook) | Each message, injects at most 3 relevant memories (one line each) before the model answers. Usually injects nothing. Never shows the same memory twice in a session. |
| **Lived-time decay** | Memories fade by days the agent was actually used, not calendar days. Absences cost nothing. |
| **Beliefs from recurrence** | An idea that returns in 3 sessions on 3 days triggers a question to the agent: "Is there something you believe here?" |
| **Authorship labels** | Every record is `agent`, `coauthored`, `system`, or `unknown`, and agent writing is signed with the model id. |
| **No model in maintenance** | Judgment work goes back to the agent via `mnemos_reflect`; Mnemos never calls an LLM to rewrite memory. |

## Engram vs Mnemos

| | Engram | Mnemos |
|---|---|---|
| Purpose | Vault-style personal OS: folders, briefings, captures, queue | Agent continuity: a few durable relationship facts |
| Storage | Markdown in 8 folders | SQLite + embeddings |
| Consolidation | Sleep passes in `engram-mcp/src/engram_mcp/sleep.py` | Decay, reconsolidation, belief proposals |
| Delivery | Agent must call tools / read files | Pushed into context every message (the cue) |
| Evaluation | Unit tests for vault rules | Behavior tests + internal benchmarks |

**Honest gap:** Engram's sleep is further along in name than in code. Pass 1 is regex matching, and **Pass 3 returns a hardcoded string** regardless of vault content (`sleep.py`, `_pass3_compress`). They're complementary, not competitors: Mnemos explicitly avoids being what Engram is.

## Candidate ideas for Engram

1. **Per-message cue.** If Grok CLI supports a per-message hook, surface ≤3 relevant vault snippets automatically. Mnemos's own data says agents under-search even when told to. *(Check Grok CLI hook support first.)*
2. **Authorship labels** on everything written to the vault (`human` / `agent` / `system`). Fits the existing logging rule.
3. **A continuity benchmark before any "it works" claim.** Seed known facts, bury them in filler at 10/50/200/500 notes, and check whether briefings and sleep output surface them. Template: Mnemos `benchmarks/continuity_eval.py`.
4. **Make sleep Pass 3 real.** Either derive it from the vault or label it as a placeholder until `XAI_API_KEY` passes land.

**NEEDS HUMAN INPUT:** pick which (if any) to queue. Suggested queue files: `05 - QUEUE/RESEARCH-grok-cli-hooks.md`, `05 - QUEUE/PLAN-continuity-benchmark.md`.

---
*Generated by Claude Code on 2026-10-04 from a direct read of the Mnemos repository and the author's public posts. Not peer-reviewed; figures are as stated by the author unless marked as verified in source.*
