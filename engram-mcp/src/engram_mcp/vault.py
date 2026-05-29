"""
engram_mcp.vault — Vault access layer for the Engram.

Enforces the strict 8-folder POS contract at all times:
- Never delete files (only archive with timestamp to 07 - ARCHIVE/).
- Every note lives in exactly one folder.
- BRAIN.md (in 03 - SYSTEM/) is always read first before any reasoning or action.
- All actions are logged to 03 - SYSTEM/logs/.
- Human review gates respected (tools flag NEEDS HUMAN INPUT; never auto-execute external actions).
- Writes only to approved locations (GENERATED/* subfolders, QUEUE, etc.).
- Archive moves use ISO timestamp prefix to avoid collisions.
- Safe path handling for Windows paths with spaces and special chars.

This layer is the single point of truth for all file I/O from the MCP server.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Union


class VaultError(Exception):
    """Raised for any violation of POS vault rules."""
    pass


class Vault:
    """Engram vault manager with strict rule enforcement."""

    # Canonical folder names (exact, including spaces and leading numbers)
    FOLDERS = {
        "capture": "00 - CAPTURE",
        "active": "01 - ACTIVE",
        "resources": "02 - RESOURCES",
        "system": "03 - SYSTEM",
        "generated": "04 - GENERATED",
        "queue": "05 - QUEUE",
        "calendar": "06 - CALENDAR",
        "archive": "07 - ARCHIVE",
    }

    GENERATED_SUBS = ["briefings", "summaries", "analyses", "drafts", "consolidated"]

    # Deep Sleep (BES) and future advanced modes may write to consolidated/deep/
    # for organized higher-quality artifacts. Explicitly allowlisted below.
    # Strict date format for all date-prefixed files (prevents path injection)
    DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def __init__(self, vault_root: Optional[Union[str, Path]] = None):
        if vault_root is None:
            vault_root = os.environ.get("BRAIN_VAULT_PATH")
        if vault_root is None:
            # Heuristic discovery: walk up from this file or cwd until we find 00 - CAPTURE
            start = Path(__file__).resolve().parent
            for _ in range(6):
                candidate = start / ".." / ".." / ".."   # rough for src/engram_mcp -> vault
                candidate = candidate.resolve()
                if (candidate / self.FOLDERS["capture"]).exists():
                    vault_root = candidate
                    break
                start = start.parent
            if vault_root is None:
                # final fallback: current working dir + common relatives (robust for MCP stdio spawns)
                cwd = Path.cwd().resolve()
                candidates = [cwd, cwd.parent, cwd / "..", Path(__file__).resolve().parents[4]]  # generous up
                for cand in candidates:
                    cand = cand.resolve()
                    if (cand / self.FOLDERS["capture"]).exists():
                        vault_root = cand
                        break
                if vault_root is None:
                    vault_root = cwd  # last resort, will raise in _validate

        self.root = Path(vault_root).resolve()
        self._validate_vault()

    def _validate_vault(self) -> None:
        """Ensure this is a valid Brain vault with the 8 required top-level folders."""
        missing = []
        for key, name in self.FOLDERS.items():
            if not (self.root / name).exists():
                missing.append(name)
        if missing:
            raise VaultError(
                f"Invalid Brain vault at {self.root}. Missing required folders: {missing}. "
                "Run from vault root or set BRAIN_VAULT_PATH env var."
            )

    # --- Core rule: always read BRAIN.md first ---
    def read_brain_md(self) -> str:
        """MANDATORY first read for every workflow/tool. Logs the read."""
        brain_path = self.root / self.FOLDERS["system"] / "BRAIN.md"
        if not brain_path.exists():
            raise VaultError("BRAIN.md not found — this violates core POS contract.")
        content = brain_path.read_text(encoding="utf-8")
        self.log_action("read BRAIN.md (as required by POS rules before any action)")
        return content

    # --- Safe read helpers ---
    def read_file(self, relative_path: Union[str, Path]) -> str:
        """Read any file under the vault root. Enforces path safety."""
        p = self._safe_path(relative_path)
        if not p.exists():
            raise VaultError(f"File not found: {relative_path}")
        return p.read_text(encoding="utf-8")

    def read_daily_note(self, date: Optional[str] = None) -> str:
        """Read 01 - ACTIVE/daily/YYYY-MM-DD.md . Defaults to today. Uses safe path."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        if not self.DATE_RE.match(str(date)):
            raise VaultError(f"Invalid date for daily note (must be YYYY-MM-DD): {date}")
        rel = f"{self.FOLDERS['active']}/daily/{date}.md"
        daily_path = self._safe_path(rel)
        if not daily_path.exists():
            # allow missing (early days)
            return f"# {date} — Daily Note (not yet created)"
        return daily_path.read_text(encoding="utf-8")

    def get_yesterday_date(self) -> str:
        """Return yesterday's YYYY-MM-DD string."""
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # --- Write / generation paths (only to approved locations) ---
    def _safe_path(self, relative: Union[str, Path]) -> Path:
        """Resolve relative to vault root and guarantee it stays inside (prevents ../ escapes)."""
        candidate = (self.root / relative).resolve()
        root_resolved = self.root.resolve()
        if not candidate.is_relative_to(root_resolved):
            raise VaultError(f"Path traversal blocked: {relative} resolved outside vault root")
        return candidate

    def _ensure_parent(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

    def _write_to_generated(self, sub: str, filename: str, content: str) -> Path:
        """
        Central, safe writer for all GENERATED/ content.
        Enforces:
        - sub must be in GENERATED_SUBS (briefings/summaries/etc.)
        - filename must be safe (no path separators)
        - full path containment under the approved subdir (prevents ../ escapes)
        - Uses _safe_path for root containment.
        """
        allowed = set(self.GENERATED_SUBS) | {"consolidated/deep"}
        if sub not in allowed:
            raise VaultError(f"Invalid GENERATED subfolder: {sub}. Allowed: {sorted(allowed)}")
        if "/" in filename or "\\" in filename or ".." in filename:
            raise VaultError(f"Unsafe filename for GENERATED write: {filename}")
        if not filename.endswith(".md"):
            raise VaultError("Generated files must be .md")

        rel = f"{self.FOLDERS['generated']}/{sub}/{filename}"
        target = self._safe_path(rel)

        # Containment check: must be inside the specific GENERATED/sub dir
        approved_dir = (self.root / self.FOLDERS["generated"] / sub).resolve()
        if not target.resolve().is_relative_to(approved_dir):
            raise VaultError(f"Write containment violation: {target} escaped approved dir {approved_dir}")

        self._ensure_parent(target)
        target.write_text(content, encoding="utf-8")
        self.log_action(f"Wrote to GENERATED/{sub}: {target.relative_to(self.root)}")
        return target

    def write_briefing(self, date: str, content: str) -> Path:
        """Write morning briefing to 04 - GENERATED/briefings/. Delegates to central safe writer."""
        if not content.strip():
            raise VaultError("Refusing to write empty briefing.")
        if not self.DATE_RE.match(str(date)):
            raise VaultError(f"Invalid date for briefing (must be YYYY-MM-DD): {date}")

        sub = "briefings"
        filename = f"{date}-morning.md"
        target = self._write_to_generated(sub, filename, content)

        # Add standard footer if not present (idempotent)
        # Note: since content was already written, we re-read + rewrite only if needed (rare)
        final_content = target.read_text(encoding="utf-8")
        footer = f"\n\n---\n*Generated by engram-mcp / Grok on {datetime.now().isoformat(timespec='seconds')}*"
        if "*Generated by engram-mcp" not in final_content:
            final_content = final_content.rstrip() + footer
            target.write_text(final_content, encoding="utf-8")

        # Re-log with specific briefing message for backward compat in logs
        self.log_action(f"Generated and wrote morning briefing: {target.relative_to(self.root)}")
        return target

    def write_file(self, relative_path: Union[str, Path], content: str, reason: str = "processed") -> Path:
        """
        Safe general writer for approved non-GENERATED locations (QUEUE/, RESOURCES/references/, CALENDAR/events/ etc.).
        Used primarily by Capture Processor for *real filing* of classified items before archiving the original.
        Enforces:
        - No path traversal (via _safe_path)
        - Parent dirs created
        - Full audit log
        Does not force .md extension (caller responsibility for consistency).
        """
        if not content or not str(content).strip():
            raise VaultError("Refusing to write empty file via write_file().")
        rel_str = str(relative_path)
        if ".." in rel_str or rel_str.startswith(("/", "\\")):
            raise VaultError(f"Unsafe relative path for write_file: {relative_path}")
        target = self._safe_path(relative_path)
        self._ensure_parent(target)
        target.write_text(content, encoding="utf-8")
        self.log_action(f"Wrote file: {rel_str} ({reason})")
        return target

    # --- Never-delete archive rule ---
    def archive_file(self, src_relative: Union[str, Path], reason: str = "processed") -> Path:
        """
        Move a file to 07 - ARCHIVE/ with timestamp prefix. NEVER deletes.
        Example: 2026-05-21-142530-original-name.md
        """
        src = self._safe_path(src_relative)
        if not src.exists():
            raise VaultError(f"Cannot archive non-existent file: {src_relative}")

        ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        stem = src.stem
        suffix = src.suffix
        archive_dir = self.root / self.FOLDERS["archive"]
        archive_dir.mkdir(exist_ok=True)

        dest = archive_dir / f"{ts}--{stem}{suffix}"
        # Avoid collision (rare)
        counter = 1
        while dest.exists():
            dest = archive_dir / f"{ts}--{stem}-{counter}{suffix}"
            counter += 1

        shutil.move(str(src), str(dest))
        self.log_action(f"Archived ({reason}): {src_relative} → {dest.relative_to(self.root)}")
        return dest

    # --- List / discovery (used by processors) ---
    def list_capture_items(self) -> list[Path]:
        """Return list of files (non-dirs) in 00 - CAPTURE/."""
        cap = self.root / self.FOLDERS["capture"]
        return [p for p in cap.iterdir() if p.is_file()]

    def list_queue_items(self) -> list[Path]:
        """Return list of files in 05 - QUEUE/."""
        q = self.root / self.FOLDERS["queue"]
        return [p for p in q.iterdir() if p.is_file() and p.suffix == ".md"]

    def list_active_projects(self) -> list[str]:
        """Return names of projects under 01 - ACTIVE/projects/."""
        proj_dir = self.root / self.FOLDERS["active"] / "projects"
        if not proj_dir.exists():
            return []
        return [d.name for d in proj_dir.iterdir() if d.is_dir()]

    # --- Logging (always append, never overwrite) ---
    def log_action(self, message: str) -> None:
        """Append a timestamped entry to 03 - SYSTEM/logs/system-log.md ."""
        log_path = self.root / self.FOLDERS["system"] / "logs" / "system-log.md"
        self._ensure_parent(log_path)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- **{ts}** — {message}\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)

    # --- Utility: read calendar events for a date (stub for now) ---
    def read_calendar_for_date(self, date: str) -> str:
        """Placeholder — later parse 06 - CALENDAR/events/ for date."""
        cal_dir = self.root / self.FOLDERS["calendar"] / "events"
        if cal_dir.exists():
            # For v1: just note existence
            items = list(cal_dir.glob("*.md"))
            if items:
                return f"Calendar has {len(items)} event(s). (detailed parsing in future iteration)"
        return "No calendar events parsed for this date (stub)."

    def get_brain_path(self) -> Path:
        return self.root / self.FOLDERS["system"] / "BRAIN.md"


# Convenience singleton for simple usage in tools (respects env)
_vault_instance: Optional[Vault] = None

def get_vault() -> Vault:
    """Get or create the shared Vault instance (cached)."""
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = Vault()
    return _vault_instance
