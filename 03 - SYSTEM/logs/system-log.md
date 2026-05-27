# Engram — System Log

All significant automated and manual system events are appended here by the engram-mcp `vault.log_action()` helper, plus any manual operational notes.

Format: `YYYY-MM-DD HH:MM — [EVENT] — details`

---

## Initial install

- This log is append-only. The engram-mcp vault layer writes here on every BRAIN.md read, every GENERATED write, every archive move, and every notable action.
- N8N workflow runs append their results here too.
- Reset this file safely by deleting it — it will be recreated on the next `vault.log_action()` call.

*Your real log entries will start appearing below the moment you run your first tool.*
