# DOX — tools

- One-shot maintenance scripts for agent infrastructure (not part of any module's runtime path)

## Verification

- `node tools/test-compact-extension.cjs` — dry-run of the `~/.pi/agent/extensions/aggressive-compaction.ts` handler against the live local LM Studio server; exit 0 = all checks pass (requires the server running)
