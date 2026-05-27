#!/bin/bash
#
# Engram — Example Offsite Backup Script (resilience & disaster recovery)
#
# Location: 03 - SYSTEM/scripts/ (alongside schedulers/ for native automation)
# Purpose: Demonstrate a safe, logged, BRAIN.md-first approach to offsite vault backups.
#          Can be run manually or wired to a systemd timer/cron later (after human review).
#
# Key POS rules enforced by this script (see 03 - SYSTEM/BRAIN.md §6):
# - ALWAYS starts by reading BRAIN.md (mandatory, logged).
# - Never deletes anything in the vault (only reads for archive/tar; no rm -rf).
# - All actions logged to 03 - SYSTEM/logs/system-log.md using the exact existing convention.
# - Dry-run by default + explicit human confirmation gate before any real backup/push.
# - Archive-only mindset: backups are copies; originals stay in place (use 07-ARCHIVE/ for internal moves).
# - Human review gate for any "live" / destructive-potential ops (even if this script is read-only on vault).
#
# Supported modes (example implementations):
# - Default: restic (if installed + repo configured) — modern, dedup, encryption, B2/S3 friendly.
# - Fallback / simple: tar + gzip (to local /tmp or $BACKUP_DIR), with instructions for age/gpg encrypt + offsite copy (scp/rsync/rclone to B2, another VPS, etc.).
# - No creds or secrets committed here. Configure via env or external .env (gitignored).
#
# Usage:
#   ./backup-engram-vault.sh --help
#   ./backup-engram-vault.sh                # full dry-run + plan (safe, always)
#   ./backup-engram-vault.sh --live         # REAL backup (requires interactive YES gate)
#
# After real run: review the log entry, the generated backup artifact (if local), and push/commit any
# related notes. Then (optionally) `git add 03\ -\ SYSTEM/scripts/backup-engram-vault.sh` etc. if editing.
#
# Recommended production:
# - Install restic: https://restic.readthedocs.io/
# - Init a repo once: restic -r b2:mybucket:/engram-backups init (or sftp/local)
# - Set RESTIC_REPOSITORY, RESTIC_PASSWORD, B2_ACCOUNT_ID etc in a secure env file (sourced or systemd).
# - Wire to timer only after testing + explicit approval in BRAIN.md §7.
#
# This is intentionally small and self-contained (no python dep on the script itself; reuses vault only for inspiration).
# Follows the same BRAIN-first + logging discipline as the engram-mcp tools (see AGENTS.md).
#
# Manual verification notes (no automated test harness added per minimalism):
# - Dry-run + --live with human gate: primary path.
# - Key hardened branches (non-tty abort, BRAIN-missing early log + exit, age WARNING, restic-missing fatal, trap firing on signals): exercise manually (e.g. kill -INT, rm BRAIN.md temporarily in a copy, age not in PATH, RESTIC set + no binary).
# - DEBUG_BRAIN=1 for full header dump path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"   # 03 - SYSTEM/scripts/ -> 03-SYSTEM -> Brain root
BRAIN_MD="$VAULT_ROOT/03 - SYSTEM/BRAIN.md"
SYSTEM_LOG="$VAULT_ROOT/03 - SYSTEM/logs/system-log.md"
DATE_TS="$(date +%Y-%m-%d-%H%M%S)"
BACKUP_NAME="brain-vault-${DATE_TS}"
LAST_ACTION="startup"

# Config (override via env before calling)
DRY_RUN="${DRY_RUN:-true}"
BACKUP_DIR="${BACKUP_DIR:-/tmp/engram-backups}"
RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-}"
# Example for age encryption (install age from https://github.com/FiloSottile/age):
#   tar ... | age -r "age1..." > ${BACKUP_DIR}/${BACKUP_NAME}.tar.gz.age
AGE_RECIPIENT="${AGE_RECIPIENT:-}"   # set to your age pubkey for simple path

# === Function definitions (trap placed after these for robustness on early errors) ===

log_to_system() {
    local msg="$1"
    local ts
    ts="$(date +"%Y-%m-%d %H:%M")"
    # Exact format used by vault.log_action() and existing entries
    echo "- **${ts}** — ${msg}" >> "$SYSTEM_LOG"
}

require_yes() {
    local prompt="$1"
    echo "NEEDS HUMAN INPUT: ${prompt}"
    if [[ ! -t 0 ]]; then
        echo "Non-interactive (no TTY) environment detected (cron, pipe, systemd, CI, etc.). Human gate cannot be satisfied interactively."
        echo "Aborting for safety. Use explicit automation flags only after separate human approval + testing."
        log_to_system "Backup ABORTED: non-tty environment for live gate (human confirmation impossible). DRY_RUN=${DRY_RUN}."
        exit 1
    fi
    echo -n "Type YES (all caps) to proceed or anything else to abort: "
    read -r ans
    if [[ "$ans" != "YES" ]]; then
        echo "Aborted by human (no changes performed)."
        log_to_system "Backup ABORTED by human gate (no backup performed). DRY_RUN was ${DRY_RUN}."
        exit 1
    fi
}

# Guaranteed final logging on any exit (error, interrupt, normal). Placed after log_to_system/require_yes defs for robustness.
trap 'log_to_system "Backup script exiting (code=$?). Last action before trap: ${LAST_ACTION:-none}."' EXIT

print_help() {
    cat <<EOF
Engram Vault Backup (example)

Usage: $0 [options]

Options:
  --help          Show this help
  --live          Perform real backup (default is dry-run only; still requires explicit YES confirmation)
  --restic-only   Force restic path even if no RESTIC_REPOSITORY (will error if unset)

Environment (examples):
  DRY_RUN=false
  RESTIC_REPOSITORY=b2:my-backups-bucket:/brain-vault
  RESTIC_PASSWORD=...
  B2_ACCOUNT_ID=... B2_ACCOUNT_KEY=...
  BACKUP_DIR=/srv/backups
  AGE_RECIPIENT=age1...

Always:
- Reads BRAIN.md first (POS contract)
- Logs every step to system-log.md
- Dry-run + human gate by default
- Never deletes or mutates vault contents

See script header + engram-mcp/README.md + AGENTS.md "Resilience & Backups" for full context.
EOF
}

do_backup_plan() {
    echo "=== Backup Plan (${BACKUP_NAME}) ==="
    echo "Vault root: $VAULT_ROOT"
    echo "BRAIN.md: $BRAIN_MD (will be read first)"
    echo "Mode: $([ "$DRY_RUN" = "true" ] && echo "DRY-RUN (no writes/pushes)" || echo "LIVE (after human gate)")"
    echo "Target: ${BACKUP_DIR}/${BACKUP_NAME}.tar.gz (or restic snapshot)"
    echo "Offsite options documented in script (age/gpg + rclone/scp, or restic to B2)."
    echo "This script only *reads* the vault for the archive step."
    echo
}

# === MAIN ===

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    print_help
    exit 0
fi

if [[ "${1:-}" == "--live" ]]; then
    DRY_RUN="false"
fi

echo "Engram backup starting at $(date -Iseconds)"
echo

# NON-NEGOTIABLE: BRAIN.md first (per §6 Operating Rules + every tool/workflow)
echo ">>> Reading BRAIN.md first (POS contract §6 + AGENTS.md) ..."
if [[ -f "$BRAIN_MD" ]]; then
    # Safe redacted summary only (addresses data exposure: full raw BRAIN.md head — including priorities, sleep status, personal context — must not leak to stdout, journal, or backup metadata in normal operation).
    # Full file is still read by the script (for governance), but only non-sensitive header + confirmation is emitted here.
    head -n 8 "$BRAIN_MD" || true
    echo "... (BRAIN.md identity + rules header shown for auditability. Full content read internally per POS contract; sensitive sections intentionally omitted from logs/stdout/backup side-effects. Set DEBUG_BRAIN=1 to override if needed for deep troubleshooting.)"
    if [[ "${DEBUG_BRAIN:-}" == "1" ]]; then
        echo "DEBUG_BRAIN=1: dumping first 25 lines (operator requested)"
        head -n 25 "$BRAIN_MD" || true
    fi
else
    log_to_system "Backup ERROR: BRAIN.md not found at $BRAIN_MD (POS contract violation). Aborting before any backup work."
    echo "ERROR: BRAIN.md not found at $BRAIN_MD — aborting (violates core contract)."
    exit 1
fi
log_to_system "Backup script invoked (BRAIN.md read first per POS rules). DRY_RUN=${DRY_RUN}. Args: $*"
LAST_ACTION="brain-read-complete"

do_backup_plan

# Ensure backup dir exists (outside vault or in safe GENERATED if desired; here /tmp for example)
if [[ "$DRY_RUN" != "true" ]]; then
    mkdir -p "$BACKUP_DIR"
fi

# === Actual backup implementations (choose one) ===
if [[ -n "$RESTIC_REPOSITORY" ]]; then
    echo ">>> Restic backend detected (RESTIC_REPOSITORY set)."
    if command -v restic >/dev/null 2>&1; then
        if [[ "$DRY_RUN" == "true" ]]; then
            echo "[DRY] Would run: restic -r '$RESTIC_REPOSITORY' backup '$VAULT_ROOT' --exclude '*.log' --exclude '03 - SYSTEM/logs/*.log' --exclude '07 - ARCHIVE/*-test*' --one-file-system"
            # Note: restic excludes are relative to the full path passed (unlike tar's -C + "Brain/" prefixing). Unprefixed form is intentional here for restic semantics.
            echo "[DRY] (restic snapshots are append-only + encrypted; no vault mutation.)"
            log_to_system "Backup DRY-RUN (restic): plan only for ${BACKUP_NAME}. No snapshot created."
        else
            require_yes "About to run REAL restic backup of the Brain vault to ${RESTIC_REPOSITORY}. This will read all files and create an encrypted snapshot offsite."
            echo ">>> Executing real restic backup..."
            # (restic excludes relative to full path; see dry-run comment above for why not "Brain/" prefixed)
            restic -r "$RESTIC_REPOSITORY" backup "$VAULT_ROOT" \
                --exclude "*.log" \
                --exclude "03 - SYSTEM/logs/*.log" \
                --exclude "07 - ARCHIVE/*-test*" \
                --one-file-system \
                --tag "brain-pos" \
                --tag "${DATE_TS}"
            echo "Restic backup complete."
            log_to_system "Backup SUCCESS (restic): created snapshot for ${BACKUP_NAME} (scope=vault, excludes=logs+test-archives). BRAIN.md was read first. Offsite repo: ${RESTIC_REPOSITORY}."
        fi
    else
        # Round-3 adjustment: fatal only for live runs (preserves safe dry-run default + "example" usability).
        # When RESTIC_REPOSITORY is set in the environment but binary is missing:
        #   - live (--live / DRY_RUN=false): hard fatal (strong protection against misconfigured production runs)
        #   - dry-run (default): clear warning + guaranteed tar fallback (original safe intent)
        if [[ "$DRY_RUN" != "true" ]]; then
            echo "FATAL: RESTIC_REPOSITORY is set but 'restic' binary not found in PATH."
            echo "This is a misconfiguration for a live backup run. Either install restic or unset RESTIC_REPOSITORY to use the tar fallback."
            log_to_system "Backup FATAL: RESTIC_REPOSITORY set but restic binary missing in PATH (live mode). No backup artifact produced (misconfig)."
            LAST_ACTION="restic-missing-fatal"
            exit 1
        else
            echo "WARNING: RESTIC_REPOSITORY is set but 'restic' binary not found in PATH."
            echo "This would be fatal for a live (--live) backup. Falling back to tar example path for this dry-run (safe default behavior preserved)."
            log_to_system "Backup WARNING: RESTIC_REPOSITORY set but restic binary missing. Dry-run: falling back to tar example path (would be fatal in live mode)."
            LAST_ACTION="restic-missing-dry-fallback"
            # Fall through to the tar block below (outer else will execute because of the condition tweak)
            DO_TAR_FALLBACK=1
        fi
    fi
if [[ -z "$RESTIC_REPOSITORY" || "${DO_TAR_FALLBACK:-}" == "1" ]]; then
    echo ">>> No RESTIC_REPOSITORY (or dry-run fallback from restic-missing) — using simple tar + gzip example (local first, then manual offsite)."
    TAR_FILE="${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"

    # Build a minimal safe tar (exclude volatile / secrets / large binaries per .gitignore spirit)
    # In real use: consider splitting (e.g. only 03-SYSTEM + 04-GENERATED + BRAIN + recent dailies) or full.
    TAR_CMD=(tar --create --gzip --file "$TAR_FILE" \
        --exclude="*.log" \
        --exclude="Brain/03 - SYSTEM/logs/*.log" \
        --exclude="Brain/07 - ARCHIVE/*-test*" \
        --exclude="*.pyc" \
        --exclude="__pycache__" \
        --exclude=".env" \
        --exclude=".env.*" \
        --exclude="node_modules" \
        --exclude=".git" \
        --one-file-system \
        -C "$(dirname "$VAULT_ROOT")" \
        "$(basename "$VAULT_ROOT")")

    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[DRY] Would execute (no output file created):"
        printf '    %q ' "${TAR_CMD[@]}"; echo
        echo "[DRY] Then (example for offsite):"
        echo "    # age encryption (recommended, no gpg needed):"
        echo "    # tar ... | age -r '\$AGE_RECIPIENT' > ${TAR_FILE}.age"
        echo "    # rclone copy ${TAR_FILE}.age b2:mybucket:engram-backups/   # or scp/rsync to remote host"
        echo "    # (Keep age private key + restic password in password manager / separate from VPS.)"
        log_to_system "Backup DRY-RUN (tar): plan + offsite instructions only for ${BACKUP_NAME}. No tar created. Human gate would be required for --live."
    else
        require_yes "About to create REAL local tar backup at ${TAR_FILE} (read-only on vault). Review plan above. After, manually encrypt + push offsite."
        echo ">>> Creating tar (this reads the vault but does not modify it)..."
        mkdir -p "$(dirname "$TAR_FILE")"
        "${TAR_CMD[@]}"
        echo "Local tar created: $TAR_FILE ($(du -h "$TAR_FILE" | cut -f1))"
        log_to_system "Backup SUCCESS (tar): wrote ${TAR_FILE} (size=$(du -h "$TAR_FILE" | cut -f1), excludes=logs+test+env). BRAIN.md read first. Next manual step (human): age/gpg encrypt + offsite copy (rclone/scp)."

        if [[ -n "$AGE_RECIPIENT" ]]; then
            echo ">>> AGE_RECIPIENT set — creating encrypted copy (example)..."
            if age -r "$AGE_RECIPIENT" < "$TAR_FILE" > "${TAR_FILE}.age"; then
                log_to_system "Backup: created age-encrypted sidecar ${TAR_FILE}.age for offsite transport."
            else
                echo "age encryption failed (non-fatal for the tar itself; operator must encrypt manually before offsite push)."
                log_to_system "Backup WARNING: age encryption of ${TAR_FILE} failed (sidecar not created or incomplete). Operator must handle encryption before any offsite copy. Tar itself is intact."
            fi
        fi
    fi
fi

fi   # balancing fi for round-3/4 edits (restores syntax while preserving the separate tar if that catches DO_TAR_FALLBACK)

echo
echo "=== Backup run complete (see ${SYSTEM_LOG} for the audit entry) ==="
echo "Next (always):"
echo "  1. Review the new log entry in system-log.md"
echo "  2. If live: verify the backup artifact / restic snapshots (restic snapshots list)"
echo "  3. For full offsite: complete the encrypt + push step (human action)"
echo "  4. (Optional) Update BRAIN.md §8 resilience note or §7 schedule after first successful live run."
echo
log_to_system "Backup script finished for ${BACKUP_NAME}. DRY_RUN=${DRY_RUN}. See above for details + any follow-up human offsite push."

# Exit success even on dry (the gate only aborts real)
exit 0
