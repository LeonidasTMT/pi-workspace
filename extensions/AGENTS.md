# DOX — extensions

- Mirrors of live pi agent extensions (canonical path: `~/.pi/agent/extensions/<name>.ts`)

## Files

- `todos.ts` — mirror of `~/.pi/agent/extensions/todos.ts`: the `todo` tool + `/todos` board widget. The **live file is canonical**; sync this copy after changes there. Persistence contract: every mutation (tool action or board edit) appends a full-state custom entry (`todos-state`); reconstruction replays the current branch, last write wins — so agent-driven goals survive compaction/branching/restart. Rendering: all renderers (widget, `/todos` dialog, LLM `boardText`) collapse groups whose parent AND every child are done to a single line — display-only, state is unchanged; `clearDone` removes such items.

## Verification

- `node tools/todos-smoke.cjs` — regression test for `todos.ts`: loads it via jiti with pi's loader aliases, drives the `todo` tool + `/todos` command handler + TodoBoard keystrokes end-to-end; exit 0 = all checks pass (no server needed)
