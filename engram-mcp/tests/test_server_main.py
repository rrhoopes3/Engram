"""
Tests for server.main() vault validation and briefing idempotency (warm-up traps 1/3/5).

Run: cd engram-mcp && python -m pytest tests/test_server_main.py -q --tb=line
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from engram_mcp import server as engram_server
from engram_mcp.vault import Vault, VaultError


def _valid_briefing_content(date: str, body: str = "Content here.") -> str:
    return f"# Morning Briefing — {date}\n\n{body}\n"


# Tools that must log tool= when ENGRAM_MCP_DEBUG_VAULT=1 (engram_health excluded)
TOOLS_WITH_CONTEXT = [
    ("engram_generate_morning_briefing", lambda: engram_server.engram_generate_morning_briefing(date="2026-06-20", force=True)),
    ("engram_process_capture", lambda: engram_server.engram_process_capture()),
    ("engram_process_queue", lambda: engram_server.engram_process_queue()),
    ("engram_run_weekly_review", lambda: engram_server.engram_run_weekly_review()),
    ("engram_run_project_health_monitor", lambda: engram_server.engram_run_project_health_monitor()),
    ("engram_trigger_sleep", lambda: engram_server.engram_trigger_sleep(n_passes=1, scope="manual", dry_run=True)),
    ("engram_trigger_deep_sleep", lambda: engram_server.engram_trigger_deep_sleep(generations=2, population_size=3, scope="deep-manual", dry_run=True)),
    ("engram_export_graph_overlay", lambda: engram_server.engram_export_graph_overlay(mode="incremental", dry_run=True)),
]


@pytest.fixture
def debug_vault_env(monkeypatch):
    monkeypatch.setenv("ENGRAM_MCP_DEBUG_VAULT", "1")


@pytest.fixture
def minimal_vault(tmp_path: Path):
    folders = [
        "00 - CAPTURE",
        "01 - ACTIVE",
        "02 - RESOURCES",
        "03 - SYSTEM",
        "04 - GENERATED",
        "05 - QUEUE",
        "06 - CALENDAR",
        "07 - ARCHIVE",
    ]
    for name in folders:
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    for sub in ["briefings", "summaries", "analyses", "drafts", "consolidated", "graph-export"]:
        (tmp_path / "04 - GENERATED" / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / "04 - GENERATED" / "consolidated" / "deep").mkdir(parents=True, exist_ok=True)
    (tmp_path / "02 - RESOURCES" / "references").mkdir(parents=True, exist_ok=True)
    (tmp_path / "05 - QUEUE").mkdir(parents=True, exist_ok=True)
    (tmp_path / "03 - SYSTEM" / "BRAIN.md").write_text(
        "# BRAIN.md — Test\n\n## 4. Current Priorities\n- P1\n",
        encoding="utf-8",
    )
    daily_dir = tmp_path / "01 - ACTIVE" / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    (daily_dir / "2026-05-20.md").write_text("# Daily\n", encoding="utf-8")
    return Vault(tmp_path)


def _log_text(vault: Vault) -> str:
    log_path = vault.root / "03 - SYSTEM" / "logs" / "system-log.md"
    return log_path.read_text(encoding="utf-8") if log_path.exists() else ""


def _brain_read_count(log: str) -> int:
    return log.count("read BRAIN.md (as required by POS rules")


def test_main_validates_vault_before_stdio(minimal_vault, capsys):
    mock_run = MagicMock()
    with patch.object(engram_server, "get_vault", return_value=minimal_vault), patch.object(
        engram_server.mcp, "run", mock_run
    ):
        with patch.object(sys, "argv", ["engram_mcp.server"]):
            engram_server.main()
    mock_run.assert_called_once_with()
    err = capsys.readouterr().err
    assert "Startup validated" in err
    assert "mode=stdio" in err
    assert str(minimal_vault.root.resolve()) in err


def test_main_validates_vault_before_http(minimal_vault, capsys):
    mock_run = MagicMock()
    with patch.object(engram_server, "get_vault", return_value=minimal_vault), patch.object(
        engram_server.mcp, "run", mock_run
    ):
        with patch.object(sys, "argv", ["engram_mcp.server", "http"]):
            engram_server.main()
    mock_run.assert_called_once_with(transport="streamable-http")
    err = capsys.readouterr().err
    assert "mode=streamable-http" in err or "Streamable HTTP" in err


def test_main_validates_vault_before_sse(minimal_vault, capsys):
    mock_run = MagicMock()
    with patch.object(engram_server, "get_vault", return_value=minimal_vault), patch.object(
        engram_server.mcp, "run", mock_run
    ):
        with patch.object(sys, "argv", ["engram_mcp.server", "sse"]):
            engram_server.main()
    mock_run.assert_called_once_with(transport="sse")
    err = capsys.readouterr().err
    assert "SSE" in err or "sse" in err.lower()


def test_main_exits_on_invalid_vault(capsys):
    mock_run = MagicMock()
    with patch.object(
        engram_server,
        "get_vault",
        side_effect=VaultError("Invalid Engram vault at /bad"),
    ), patch.object(engram_server.mcp, "run", mock_run):
        with patch.object(sys, "argv", ["engram_mcp.server"]):
            with pytest.raises(SystemExit) as exc:
                engram_server.main()
    assert exc.value.code == 1
    mock_run.assert_not_called()
    err = capsys.readouterr().err
    assert "FATAL" in err


def test_main_exits_on_invalid_vault_http(capsys):
    mock_run = MagicMock()
    with patch.object(
        engram_server,
        "get_vault",
        side_effect=VaultError("Invalid Engram vault at /bad"),
    ), patch.object(engram_server.mcp, "run", mock_run):
        with patch.object(sys, "argv", ["engram_mcp.server", "http"]):
            with pytest.raises(SystemExit) as exc:
                engram_server.main()
    assert exc.value.code == 1
    mock_run.assert_not_called()


def test_main_exits_on_oserror_during_startup_log(minimal_vault, capsys):
    mock_run = MagicMock()
    with patch.object(engram_server, "get_vault", return_value=minimal_vault), patch.object(
        minimal_vault, "log_action", side_effect=OSError("disk full")
    ), patch.object(engram_server.mcp, "run", mock_run):
        with patch.object(sys, "argv", ["engram_mcp.server"]):
            with pytest.raises(SystemExit) as exc:
                engram_server.main()
    assert exc.value.code == 1
    mock_run.assert_not_called()
    assert "FATAL" in capsys.readouterr().err


def test_main_exits_on_unknown_transport(capsys):
    mock_run = MagicMock()
    with patch.object(engram_server, "get_vault") as mock_get, patch.object(
        engram_server.mcp, "run", mock_run
    ):
        with patch.object(sys, "argv", ["engram_mcp.server", "websocket"]):
            with pytest.raises(SystemExit) as exc:
                engram_server.main()
    assert exc.value.code == 1
    mock_get.assert_not_called()
    mock_run.assert_not_called()
    err = capsys.readouterr().err
    assert "Unknown transport" in err


def test_main_startup_logged_to_system_log(minimal_vault):
    with patch.object(engram_server, "get_vault", return_value=minimal_vault), patch.object(
        engram_server.mcp, "run", MagicMock()
    ):
        with patch.object(sys, "argv", ["engram_mcp.server"]):
            engram_server.main()
    log = _log_text(minimal_vault)
    assert "server startup: mode=stdio" in log
    assert f"vault={minimal_vault.root.resolve()}" in log


def test_briefing_idempotency_skip(minimal_vault, debug_vault_env):
    date = "2026-06-20"
    briefing = minimal_vault.get_briefing_path(date)
    briefing.write_text(_valid_briefing_content(date), encoding="utf-8")
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_generate_morning_briefing(date=date, force=False)
    assert "idempotent skip" in result
    assert briefing.read_text(encoding="utf-8") == _valid_briefing_content(date)
    log = _log_text(minimal_vault)
    assert "idempotent skip" in log
    assert _brain_read_count(log) == 1


def test_briefing_idempotency_reads_brain_before_context(minimal_vault, debug_vault_env):
    date = "2026-06-22"
    briefing = minimal_vault.get_briefing_path(date)
    briefing.write_text(_valid_briefing_content(date), encoding="utf-8")
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        engram_server.engram_generate_morning_briefing(date=date, force=False)
    log = _log_text(minimal_vault)
    brain_idx = log.find("read BRAIN.md")
    tool_idx = log.find("tool=engram_generate_morning_briefing")
    assert brain_idx != -1 and tool_idx != -1
    assert brain_idx < tool_idx


def test_briefing_invalid_heading_regenerates(minimal_vault, debug_vault_env):
    date = "2026-06-27"
    briefing = minimal_vault.get_briefing_path(date)
    briefing.write_text("# Wrong heading\n\nSome content.\n", encoding="utf-8")
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_generate_morning_briefing(date=date, force=False)
    assert "idempotent skip" not in result
    assert f"# Morning Briefing — {date}" in briefing.read_text(encoding="utf-8")


def test_briefing_wrong_date_heading_regenerates(minimal_vault, debug_vault_env):
    date = "2026-06-29"
    briefing = minimal_vault.get_briefing_path(date)
    briefing.write_text(_valid_briefing_content("2026-06-28"), encoding="utf-8")
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_generate_morning_briefing(date=date, force=False)
    assert "idempotent skip" not in result
    assert f"# Morning Briefing — {date}" in briefing.read_text(encoding="utf-8")


def test_briefing_empty_file_regenerates(minimal_vault, debug_vault_env):
    date = "2026-06-23"
    briefing = minimal_vault.get_briefing_path(date)
    briefing.write_text("", encoding="utf-8")
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_generate_morning_briefing(date=date, force=False)
    assert "idempotent skip" not in result
    assert "SUCCESS" in result
    assert f"# Morning Briefing — {date}" in briefing.read_text(encoding="utf-8")


def test_briefing_generate_single_brain_read(minimal_vault, debug_vault_env):
    date = "2026-06-28"
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        engram_server.engram_generate_morning_briefing(date=date, force=False)
    log = _log_text(minimal_vault)
    assert _brain_read_count(log) == 1


def test_briefing_first_run_creates_file(minimal_vault, debug_vault_env):
    date = "2026-06-24"
    briefing = minimal_vault.get_briefing_path(date)
    assert not briefing.exists()
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_generate_morning_briefing(date=date, force=False)
    assert "SUCCESS" in result
    assert briefing.exists()
    assert f"# Morning Briefing — {date}" in briefing.read_text(encoding="utf-8")


def test_briefing_double_call_idempotent(minimal_vault, debug_vault_env):
    date = "2026-06-25"
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        first = engram_server.engram_generate_morning_briefing(date=date, force=False)
        content_after_first = minimal_vault.get_briefing_path(date).read_text(encoding="utf-8")
        second = engram_server.engram_generate_morning_briefing(date=date, force=False)
    assert "SUCCESS" in first
    assert "idempotent skip" in second
    assert minimal_vault.get_briefing_path(date).read_text(encoding="utf-8") == content_after_first


def test_briefing_force_regenerates(minimal_vault, debug_vault_env):
    date = "2026-06-21"
    briefing = minimal_vault.get_briefing_path(date)
    briefing.write_text(_valid_briefing_content(date, "Stale."), encoding="utf-8")
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_generate_morning_briefing(date=date, force=True)
    assert "SUCCESS" in result
    assert "idempotent skip" not in result
    assert "Stale." not in briefing.read_text(encoding="utf-8")


def test_briefing_force_string_false_not_truthy(minimal_vault, debug_vault_env):
    date = "2026-06-26"
    briefing = minimal_vault.get_briefing_path(date)
    briefing.write_text(_valid_briefing_content(date), encoding="utf-8")
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_generate_morning_briefing(date=date, force="false")
    assert "idempotent skip" in result


def test_tool_context_gated_without_debug_env(minimal_vault, monkeypatch):
    monkeypatch.delenv("ENGRAM_MCP_DEBUG_VAULT", raising=False)
    engram_server._engram_first_then_context(minimal_vault, "test_tool_gated")
    log = _log_text(minimal_vault)
    assert "tool=test_tool_gated" not in log
    assert "read BRAIN.md" in log


def test_real_tool_suppresses_debug_vault_log_without_env(minimal_vault, monkeypatch):
    monkeypatch.delenv("ENGRAM_MCP_DEBUG_VAULT", raising=False)
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        engram_server.engram_process_queue()
    log = _log_text(minimal_vault)
    assert "tool=engram_process_queue" not in log
    assert "read BRAIN.md" in log


def test_ensure_tool_context_logs_when_debug_env(minimal_vault, debug_vault_env):
    minimal_vault.read_brain_md()
    engram_server._ensure_tool_context(minimal_vault, "test_tool")
    log = _log_text(minimal_vault)
    assert "tool=test_tool" in log
    assert f"vault={minimal_vault.root.resolve()}" in log


@pytest.mark.parametrize("tool_name,tool_fn", TOOLS_WITH_CONTEXT)
def test_tools_log_context_on_entry(minimal_vault, debug_vault_env, tool_name, tool_fn):
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        tool_fn()
    log = _log_text(minimal_vault)
    assert f"tool={tool_name}" in log
    brain_idx = log.find("read BRAIN.md")
    tool_idx = log.find(f"tool={tool_name}")
    assert brain_idx != -1 and tool_idx != -1
    assert brain_idx < tool_idx


def test_engram_health_silent_no_logs(minimal_vault):
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_health()
    assert result.startswith("✅")
    log = _log_text(minimal_vault)
    assert "tool=engram_health" not in log
    assert "read BRAIN.md" not in log


def test_healthcheck_exit_code_predicate_healthy(minimal_vault):
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_health()
    assert (0 if result.startswith("✅") else 1) == 0


def test_healthcheck_exit_code_predicate_unhealthy():
    with patch.object(engram_server, "get_vault", side_effect=VaultError("broken vault")):
        result = engram_server.engram_health()
    assert result.startswith("❌")
    assert (0 if result.startswith("✅") else 1) == 1


def test_sleep_tool_single_brain_read(minimal_vault, debug_vault_env):
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        engram_server.engram_trigger_sleep(n_passes=1, scope="manual", dry_run=True)
    log = _log_text(minimal_vault)
    assert _brain_read_count(log) == 1


def test_deep_sleep_tool_single_brain_read(minimal_vault, debug_vault_env):
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        engram_server.engram_trigger_deep_sleep(
            generations=2, population_size=3, scope="deep-manual", dry_run=True
        )
    log = _log_text(minimal_vault)
    assert _brain_read_count(log) == 1


def test_graph_overlay_tool_single_brain_read(minimal_vault, debug_vault_env):
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        engram_server.engram_export_graph_overlay(mode="incremental", dry_run=True)
    log = _log_text(minimal_vault)
    assert _brain_read_count(log) == 1


def test_mcps_briefing_json_has_force():
    repo_root = Path(__file__).parent.parent.parent
    schema_path = repo_root / "mcps" / "engram-mcp" / "tools" / "engram_generate_morning_briefing.json"
    assert schema_path.exists(), f"MCP schema missing at {schema_path}"
    data = json.loads(schema_path.read_text(encoding="utf-8"))
    props = data["inputSchema"]["properties"]
    assert "force" in props
    assert props["force"]["type"] == "boolean"
    assert props["force"]["default"] is False
    assert "idempotent" in data["description"].lower() or "force" in data["description"].lower()


def test_capture_empty_idempotent_skip_no_report(minimal_vault, debug_vault_env):
    summaries = minimal_vault.root / "04 - GENERATED" / "summaries"
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_process_capture()
    assert "0 items" in result
    assert list(summaries.glob("*-capture-report.md")) == []
    log = _log_text(minimal_vault)
    assert "idempotent skip: engram_process_capture" in log


def test_capture_happy_path_filing_and_archive(minimal_vault, debug_vault_env):
    cap = minimal_vault.root / "00 - CAPTURE" / "task-item.md"
    cap.write_text("task: do something important", encoding="utf-8")
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_process_capture()
    assert "processed 1 items" in result
    assert not cap.exists()
    filed = minimal_vault.root / "05 - QUEUE" / "TASK-task-item.md"
    assert filed.exists()
    archive_items = list((minimal_vault.root / "07 - ARCHIVE").iterdir())
    assert len(archive_items) == 1
    reports = list((minimal_vault.root / "04 - GENERATED" / "summaries").glob("*-capture-report.md"))
    assert len(reports) == 1
    assert reports[0].name.count("-") >= 3  # YYYY-MM-DD-HHMM-capture-report.md


def test_capture_report_hhmm_collision_safe(minimal_vault, debug_vault_env):
    times = [
        datetime(2026, 6, 20, 10, 15),
        datetime(2026, 6, 20, 10, 45),
    ]
    cap = minimal_vault.root / "00 - CAPTURE" / "solo.md"
    fake_dt = MagicMock()
    # Each capture run calls now() for date, hhmm, filed isoformat, report isoformat (4x per run)
    fake_dt.now.side_effect = [
        times[0], times[0], times[0], times[0],
        times[1], times[1], times[1], times[1],
    ]
    fake_dt.strftime = datetime.strftime
    with patch.object(engram_server, "get_vault", return_value=minimal_vault), patch.object(
        engram_server, "datetime", fake_dt
    ):
        cap.write_text("note one", encoding="utf-8")
        engram_server.engram_process_capture()
        cap.write_text("note two", encoding="utf-8")
        engram_server.engram_process_capture()
    reports = sorted((minimal_vault.root / "04 - GENERATED" / "summaries").glob("2026-06-20-*-capture-report.md"))
    assert len(reports) == 2
    assert reports[0].name == "2026-06-20-1015-capture-report.md"
    assert reports[1].name == "2026-06-20-1045-capture-report.md"


def test_capture_archive_only_after_successful_filing(minimal_vault, debug_vault_env):
    cap = minimal_vault.root / "00 - CAPTURE" / "task-item.md"
    cap.write_text("task: do something", encoding="utf-8")
    with patch.object(minimal_vault, "write_file", side_effect=VaultError("blocked")), patch.object(
        engram_server, "get_vault", return_value=minimal_vault
    ):
        result = engram_server.engram_process_capture()
    assert "FILING FAILED" in result
    assert cap.exists(), "Original must remain in CAPTURE when filing fails"


def test_capture_rejects_unsafe_filename(minimal_vault, debug_vault_env):
    cap = minimal_vault.root / "00 - CAPTURE" / "bad!name.md"
    cap.write_text("task: bad name", encoding="utf-8")
    with patch.object(engram_server, "get_vault", return_value=minimal_vault):
        result = engram_server.engram_process_capture()
    assert "Invalid capture item name charset" in result
    assert cap.exists()


def test_main_vault_validated_before_mcp_run_order(minimal_vault):
    call_order = []
    mock_run = MagicMock(side_effect=lambda **kw: call_order.append("mcp.run"))
    with patch.object(
        engram_server,
        "get_vault",
        side_effect=lambda: (call_order.append("get_vault") or minimal_vault),
    ), patch.object(engram_server.mcp, "run", mock_run):
        with patch.object(sys, "argv", ["engram_mcp.server"]):
            engram_server.main()
    assert call_order == ["get_vault", "mcp.run"]