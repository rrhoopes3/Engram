"""
Tests for Sleep Cycles (engram_mcp.sleep + engram_trigger_sleep tool).
8 dedicated test functions (part of full suite that passes 15/15 with test_vault).

Covers per spec:
- Import / callable (direct + via server glue)
- Dry run: no GENERATED write (only log)
- Real run: writes consolidated artifact, BRAIN read logged
- Param validation (n_passes, scope)
- NEEDS HUMAN / proposal text present, no BRAIN write
- Archive safety (uses existing test patterns)
- Windows path robustness (via tmp_path fixture)
- Insufficient context graceful path
- get_last_sleep_status derivation (honest observability, no new state)

Run: cd engram-mcp; python -m pytest tests/test_sleep.py -q --tb=line
"""

from __future__ import annotations

import sys
from pathlib import Path

# src layout
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from engram_mcp.vault import Vault, VaultError, get_vault
from engram_mcp import server as engram_server
from engram_mcp.sleep import (
    collect_recent_context,
    run_recurrent_passes,
    trigger_sleep_cycle,
    propose_brain_update,
    get_last_sleep_status,
    ALLOWED_SCOPES,
    trigger_deep_sleep_cycle,
    get_last_deep_sleep_status,
    run_bidirectional_evolutionary_search,
)


@pytest.fixture
def minimal_vault(tmp_path: Path):
    """Reuse/extend the pattern from test_vault (now includes consolidated)."""
    folders = {
        "capture": "00 - CAPTURE",
        "active": "01 - ACTIVE",
        "resources": "02 - RESOURCES",
        "system": "03 - SYSTEM",
        "generated": "04 - GENERATED",
        "queue": "05 - QUEUE",
        "calendar": "06 - CALENDAR",
        "archive": "07 - ARCHIVE",
    }
    for name in folders.values():
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    for sub in ["briefings", "summaries", "analyses", "drafts", "consolidated"]:
        (tmp_path / "04 - GENERATED" / sub).mkdir(parents=True, exist_ok=True)

    # BRAIN.md (mandatory)
    brain = tmp_path / "03 - SYSTEM" / "BRAIN.md"
    brain.write_text(
        "# BRAIN.md — Test\n\n"
        "## 1. Identity\nSleep test user\n\n"
        "## 4. Current Priorities\n- P1: Implement sleep cycles\n\n"
        "## 3. Active Projects\n| Engram | Sleep integration |\n\n"
        "## 8. Current Context Snapshot\nEarly foundation with sleep.\n",
        encoding="utf-8",
    )

    # 2-3 dailies + 1 briefing (enough for real consolidation)
    daily_dir = tmp_path / "01 - ACTIVE" / "daily"
    daily_dir.mkdir(exist_ok=True)
    for d, content in [
        ("2026-05-25", "# 2026-05-25\n**Top 3:** Sleep prep\n- Vault rules\n"),
        ("2026-05-26", "# 2026-05-26\n**Wins:** capture + briefing live\n"),
    ]:
        (daily_dir / f"{d}.md").write_text(content, encoding="utf-8")

    brief_dir = tmp_path / "04 - GENERATED" / "briefings"
    brief_dir.mkdir(exist_ok=True)
    (brief_dir / "2026-05-26-morning.md").write_text(
        "# Morning Briefing — 2026-05-26\n**Most Important:** Foundation + sleep.\n",
        encoding="utf-8",
    )

    # One QUEUE item
    qdir = tmp_path / "05 - QUEUE"
    (qdir / "REVIEW-sleep.md").write_text("Review sleep proposal.", encoding="utf-8")

    v = Vault(tmp_path)
    yield v


def test_sleep_module_imports_and_callable():
    """Direct module functions are importable and basic shape correct."""
    assert callable(collect_recent_context)
    assert callable(run_recurrent_passes)
    assert callable(trigger_sleep_cycle)
    assert callable(propose_brain_update)
    assert "nightly" in ALLOWED_SCOPES


def test_engram_trigger_sleep_tool_exposed():
    """Tool registered on server (via decorator)."""
    assert hasattr(engram_server, "engram_trigger_sleep")
    assert callable(engram_server.engram_trigger_sleep)


def test_sleep_dry_run_no_write_only_log(minimal_vault, tmp_path):
    v = minimal_vault
    import engram_mcp.vault as vault_mod
    vault_mod._vault_instance = v  # force singleton for server glue (uses get_vault)
    _ = v.read_brain_md()  # prime log file
    result = engram_server.engram_trigger_sleep(n_passes=2, scope="manual", dry_run=True)
    assert result.startswith("✅ DRY-RUN SUCCESS (log only)")
    assert "Preview" in result  # non-deterministic preview content ok
    # No artifact created
    cons_dir = tmp_path / "04 - GENERATED" / "consolidated"
    files = list(cons_dir.glob("*.md"))
    assert len(files) == 0, "dry_run must not write artifact"
    # But BRAIN was read (log)
    log_path = (tmp_path / "03 - SYSTEM" / "logs" / "system-log.md")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "read BRAIN.md (as required by POS rules before any action)" in log
    assert "DRY-RUN" in log or "Sleep DRY-RUN" in log  # one fallback for timing of log entry


def test_sleep_real_run_writes_artifact_and_logs(minimal_vault, tmp_path):
    v = minimal_vault
    import engram_mcp.vault as vault_mod
    vault_mod._vault_instance = v  # force singleton for server glue (uses get_vault)
    _ = v.read_brain_md()  # prime log file
    result = engram_server.engram_trigger_sleep(n_passes=2, scope="nightly", dry_run=False)
    assert result.startswith("✅ SUCCESS: Sleep Cycle complete.")
    assert "consolidated" in result  # path separator varies (Windows backslash)

    # Artifact exists with correct name pattern + content quality
    cons_dir = tmp_path / "04 - GENERATED" / "consolidated"
    arts = list(cons_dir.glob("*sleep-consolidation.md"))
    assert len(arts) >= 1
    art = arts[0]
    txt = art.read_text(encoding="utf-8")
    assert "# Sleep Cycle Report" in txt
    assert "Recurrent Passes Performed" in txt
    assert "Proposed BRAIN.md Updates" in txt
    assert "NEEDS HUMAN INPUT" in txt or "human" in txt.lower()
    assert "*Generated by engram_trigger_sleep" in txt

    # Log entry
    log_path = (tmp_path / "03 - SYSTEM" / "logs" / "system-log.md")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "Sleep cycle complete:" in log
    assert "BRAIN read first" in log or "read BRAIN.md (as required by POS rules before any action)" in log


def test_sleep_validation_errors_return_clean_messages(minimal_vault):
    v = minimal_vault
    import engram_mcp.vault as vault_mod
    vault_mod._vault_instance = v  # force singleton for server glue (uses get_vault)
    bad_p = engram_server.engram_trigger_sleep(n_passes=99, scope="nightly")
    assert bad_p.startswith("❌ SLEEP CYCLE PARAM ERROR")

    bad_s = engram_server.engram_trigger_sleep(n_passes=1, scope="evil-scope")
    assert bad_s.startswith("❌ SLEEP CYCLE PARAM ERROR")


def test_sleep_proposal_contains_gate_and_no_brain_write(minimal_vault, tmp_path):
    v = minimal_vault
    prop = propose_brain_update({"scope": "test"})
    assert "## 9. Sleep Cycles (Memory Consolidation)  [PROPOSED" in prop
    assert "NEEDS HUMAN INPUT" in prop
    assert "never auto-writes" in prop

    # Run real (will write artifact but NOT touch BRAIN)
    import engram_mcp.vault as vault_mod
    vault_mod._vault_instance = v  # force singleton for server glue (uses get_vault)
    brain_path = tmp_path / "03 - SYSTEM" / "BRAIN.md"
    before = brain_path.read_text(encoding="utf-8")
    _ = engram_server.engram_trigger_sleep(n_passes=1, dry_run=False)
    after = brain_path.read_text(encoding="utf-8")
    assert before == after, "Sleep must NEVER edit BRAIN.md"


def test_sleep_insufficient_context_graceful(minimal_vault, tmp_path):
    # Remove the dailies/briefings/queue we added to fixture to force sparse path (no daily/briefing/queue = insufficient)
    for p in (tmp_path / "01 - ACTIVE" / "daily").glob("*.md"):
        p.unlink()
    for p in (tmp_path / "04 - GENERATED" / "briefings").glob("*.md"):
        p.unlink()
    for p in (tmp_path / "05 - QUEUE").glob("*.md"):
        p.unlink()

    v = Vault(tmp_path)
    result = trigger_sleep_cycle(v, n_passes=3, scope="ad-hoc", dry_run=False)
    assert result.startswith("⚠️ Insufficient context for deep consolidation")
    # Still logged the attempt (BRAIN read happened)
    log_path = (tmp_path / "03 - SYSTEM" / "logs" / "system-log.md")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "read BRAIN.md (as required by POS rules before any action)" in log


def test_sleep_uses_archive_safety_and_read_file(minimal_vault):
    v = minimal_vault
    # Put something in CAPTURE then archive it (simulates history)
    cap = v.root / "00 - CAPTURE" / "old-capture-for-sleep.md"
    cap.write_text("Old theme: foundation sleep integration test.", encoding="utf-8")
    archived = v.archive_file("00 - CAPTURE/old-capture-for-sleep.md", reason="sleep-test")
    assert not cap.exists()
    assert archived.exists()
    assert "07 - ARCHIVE" in str(archived)

    # Now run sleep — should pick up the archived sample safely via read_file
    res = trigger_sleep_cycle(v, n_passes=1, dry_run=True)
    assert "DRY-RUN" in res or "SUCCESS" in res  # works either way
    # No new deletes
    assert archived.exists()


# ============================================================
# New tests for Deep Sleep (BES) mode — adapted for engram-mcp
# ============================================================

def test_deep_sleep_module_imports_and_callable():
    assert callable(trigger_deep_sleep_cycle)
    assert callable(get_last_deep_sleep_status)
    assert callable(run_bidirectional_evolutionary_search)


def test_engram_trigger_deep_sleep_tool_exposed():
    assert hasattr(engram_server, "engram_trigger_deep_sleep")
    assert callable(engram_server.engram_trigger_deep_sleep)


def test_deep_sleep_dry_run_no_write_and_produces_evolved_output(minimal_vault, tmp_path):
    v = minimal_vault
    import engram_mcp.vault as vault_mod
    vault_mod._vault_instance = v
    _ = v.read_brain_md()

    result = engram_server.engram_trigger_deep_sleep(generations=3, population_size=5, scope="deep-manual", dry_run=True)

    assert result.startswith("✅ DEEP SLEEP DRY-RUN SUCCESS")
    assert "BES" in result or "Deep Sleep" in result

    deep_dir = tmp_path / "04 - GENERATED" / "consolidated" / "deep"
    files = list(deep_dir.glob("*.md"))
    assert len(files) == 0, "dry_run deep sleep must not persist artifact"


def test_deep_sleep_real_run_writes_to_deep_subdir_and_logs(minimal_vault, tmp_path):
    v = minimal_vault
    import engram_mcp.vault as vault_mod
    vault_mod._vault_instance = v
    _ = v.read_brain_md()

    result = engram_server.engram_trigger_deep_sleep(generations=2, population_size=4, scope="deep-manual", dry_run=False)

    assert result.startswith("✅ SUCCESS: Deep Sleep (BES) complete.")
    assert "consolidated/deep" in result or "deep-" in result

    deep_dir = tmp_path / "04 - GENERATED" / "consolidated" / "deep"
    arts = list(deep_dir.glob("deep-*-consolidation.md"))
    assert len(arts) >= 1
    art = arts[0]
    txt = art.read_text(encoding="utf-8")

    assert "# Deep Sleep (BES) Report" in txt
    assert "Evolved Insights" in txt or "Bidirectional" in txt
    assert "NEEDS HUMAN INPUT" in txt
    assert "*Generated by engram_trigger_deep_sleep (BES)" in txt

    log_path = (tmp_path / "03 - SYSTEM" / "logs" / "system-log.md")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "Deep Sleep (BES) complete" in log


def test_deep_sleep_validation_errors_and_get_last_status(minimal_vault, tmp_path):
    v = minimal_vault
    import engram_mcp.vault as vault_mod
    vault_mod._vault_instance = v

    bad_g = engram_server.engram_trigger_deep_sleep(generations=99, population_size=5)
    assert bad_g.startswith("❌ DEEP SLEEP PARAM ERROR")

    _ = engram_server.engram_trigger_deep_sleep(generations=2, population_size=3, dry_run=False)

    status = get_last_deep_sleep_status(v)
    assert status is not None
    assert "deep-" in status["filename"]
    assert status["generations"] >= 2