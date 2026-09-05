# DOX — tools

- One-shot maintenance scripts for agent infrastructure (not part of any module's runtime path)

## Verification

- `node tools/test-compact-extension.cjs` — regression test for `~/.pi/agent/extensions/aggressive-compaction.ts`: phase A is an offline serializer shape matrix (incl. the 2026-09-04 string-content crash case), phase B runs the live handler end-to-end against the local LM Studio server; exit 0 = all checks pass (requires the server running)
- `node tools/todos-smoke.cjs` — regression test for `~/.pi/agent/extensions/todos.ts`: loads the extension via jiti with pi's loader aliases, drives the `todo` tool + `/todos` command handler end-to-end (add/sub-goal/reparent/move/remove/status/persist-reconstruct) plus interactive TodoBoard component keystrokes; exit 0 = all checks pass (no server needed)
