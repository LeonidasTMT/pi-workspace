# DOX — tools

- One-shot maintenance scripts for agent infrastructure (not part of any module's runtime path)

## Scripts

- `migrate-session.cjs` — move an old pi conversation into a new chat file so it can be continued in a FRESH process, where extension tools (todo board etc.) bind at start. Clones the source session verbatim (all entries + custom state, e.g. todos-state), writes a fresh header (new uuid/timestamp; `parentSession` = source path for provenance), appends a `session_info` label plus a displayed `custom_message` handoff marker (`customType: "session-migrate"`); the source file is never modified. Flags: `--out-dir DIR`, `--name TEXT` (session_info label only — filename is always `<timestamp>_<uuid>.jsonl`, so the source can never be clobbered), `--handoff FILE|-` (extra text prepended to auto-generated provenance facts), `--dry-run`. Prints the open command (`pi --session <new>`) plus a one-line headless verify that proves the clone loads in a fresh process.

## Verification

- `node tools/test-compact-extension.cjs` — regression test for `~/.pi/agent/extensions/aggressive-compaction.ts`: phase A is an offline serializer shape matrix (incl. the 2026-09-04 string-content crash case), phase B runs the live handler end-to-end against the local LM Studio server; exit 0 = all checks pass (requires the server running)
- `node tools/migrate-command-smoke.cjs` — loads `~/.pi/agent/extensions/session-migrate.ts` via jiti, drives the `/migrate` handler end-to-end against a tiny throwaway session (source never modified; created file removed by exact name); exit 0 = all checks pass
- `node tools/todos-smoke.cjs` — regression test for `~/.pi/agent/extensions/todos.ts`: loads the extension via jiti with pi's loader aliases, drives the `todo` tool + `/todos` command handler end-to-end (add/sub-goal/reparent/move/remove/status/persist-reconstruct) plus interactive TodoBoard component keystrokes; exit 0 = all checks pass (no server needed)
