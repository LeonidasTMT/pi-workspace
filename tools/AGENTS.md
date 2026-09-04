# DOX — tools

- One-shot maintenance scripts for agent infrastructure (not part of any module's runtime path)

## Verification

- `node tools/test-compact-extension.cjs` — regression test for `~/.pi/agent/extensions/aggressive-compaction.ts`: phase A is an offline serializer shape matrix (incl. the 2026-09-04 string-content crash case), phase B runs the live handler end-to-end against the local LM Studio server; exit 0 = all checks pass (requires the server running)
