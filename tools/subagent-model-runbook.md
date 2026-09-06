# Subagent model failure runbook (pi-subagents + LM Studio)

Instructions for any agent that hits a subagent dispatch failure of the form:

```text
Requested subagent model 'lmstudio/<id>' is excluded and cannot be replaced by a fallback
(reason: Model "lmstudio/<id>" not found. Use --list-models to see available models.; expires: <ISO>)
```

or any child spawn that dies with `Model "<provider>/<id>" not found`. Do **not** retry the
dispatch blindly — repeated failures each record a fresh ~24h exclusion, which is exactly why
the failure "keeps" happening even after LM Studio comes back up.

> **Local patch (2026-09-06):** on this machine, explicit-model exclusions no longer hard-block
dispatches. The installed pi-subagents was patched (`src/runs/shared/model-fallback.ts` →
`throwForExplicitModelExclusion`, `LOCAL-PATCH 2026-09-06` marker): a cached exclusion now only
warns and the dispatch proceeds. The store is still recorded (~24h TTL) as diagnostics, so this
runbook remains valid for pre-patch processes, inherited/fallback filtering, and root-causing any
"not found" failure. Re-apply the patch after upgrading pi-subagents (procedure below).

## Step 1 — run the doctor (one command)

```bash
node tools/subagent-model-doctor.cjs            # from pi-workspace root; add --model <id> if not qwen3.8-27b
```

Exit codes: `0` healthy · `2` server down · `3` model missing/not loaded · `4` stale exclusion active.

## Step 2 — act on the verdict

| Verdict | Meaning | Action |
|---|---|---|
| `SERVER_DOWN` (2) | LM Studio process unreachable at all | Start the LM Studio server (default `http://127.0.0.1:1234`). Then re-run doctor. |
| `MODEL_MISSING` (3) | Server up, model not in memory | Load `<id>` in LM Studio (`/api/v0/models` lists only models currently loaded). pi registers exactly those keys as `lmstudio/<key>`. Re-run doctor. |
| `STALE_EXCLUSION_ACTIVE` (4) | Model is fine; a recorded failure is blocking explicit requests for up to 24h per attempt | Confirm the doctor's step [1/3] shows the model loaded, then: `node tools/subagent-model-doctor.cjs --clear`. Then retry the dispatch. |
| `HEALTHY` (0) | Environment fine | The failure was transient or belongs to another process; retry once. If it still fails, see "Process-level staleness" below. |

## Why this happens (root-cause chain)

1. A pi process that starts while LM Studio is down (or before the model is loaded) has **no
   `lmstudio` provider in its ModelRuntime**. The pi-lmstudio extension only re-syncs providers
   on each assistant `message_end` — a headless run or a session whose first action dispatches
   subagents may never get that sync, so every lookup fails with "not found".
2. Every failed attempt records the model in the pi-subagents exclusion store for ~24h:
   `%TEMP%\pi-subagents-<scope>\model-exclusions.json` (this machine: `C:\Users\User\AppData\Local\Temp\pi-subagents-user-User\model-exclusions.json`).
3. **Explicit** model requests (`model: "lmstudio/<id>"` in a dispatch/mission) hard-failed
   against that store until the TTL expired — even when the server and model were back up.
   Inherited or fallback models are only *filtered* (they self-heal on the next attempt). That
   asymmetry is why pinned-model pipelines looked "permanently" broken while inherited ones
   recovered. Since 2026-09-06 the explicit hard-fail is disabled by a local patch (warn-only);
   inherited/fallback candidate filtering still applies, and any pre-patch process keeps both
   behaviors until reloaded or restarted.

## Process-level staleness

If doctor says HEALTHY but a long-lived session still fails: that process started before the
server/model was available and never hit an assistant `message_end` since (headless runs, or
sessions whose turns are only tool calls). Fix = start a fresh pi process/run after the server
is up; you cannot hot-register providers into an already-running ModelRuntime.

## Prevention rules for dispatching agents

- Check LM Studio before long missions: `node tools/subagent-model-doctor.cjs` (must exit 0).
- Start order: LM Studio up + model loaded **before** launching pi sessions that use it.
- Pinned explicit models are unblocked again (local patch makes exclusions warn-only), but a
  pinned request still fails with "not found" when the child's ModelRuntime never synced —
  prefer `model: "inherit"` where the parent's model is acceptable, since inherited requests
  degrade gracefully on transient outages.
- On any exclusion error: doctor first, then `--clear` only after step [1/3] proves the model
  is resolvable. Never hand-edit the store while a failure is still reproducible — you will just
  get re-recorded.

## Local patch — explicit exclusions are warn-only (re-apply after upgrades)

Applied 2026-09-06 to `~/.pi/agent/npm/node_modules/pi-subagents/src/runs/shared/model-fallback.ts`:

- `throwForExplicitModelExclusion(model)` no longer throws; it logs
  `[pi-subagents local-patch] requested model '...' has a cached exclusion (...); continuing dispatch without it.`
  and returns. Marked with a `LOCAL-PATCH 2026-09-06` comment directly above the function.

Notes:

- Effective from when pi loads the extension (new process, or after `/reload`). A running session
  keeps both its pre-patch module cache **and** any exclusions already loaded into memory — for a
  live session: doctor `--clear`, then `/reload` (or start a fresh session).
- Failure recording (`recordModelFailure`) is unchanged: exclusions are still written to the
  store as diagnostics; they just no longer block. Inherited/fallback candidate filtering still
  drops excluded models (with launch warnings).
- A pi-subagents upgrade restores the upstream hard throw. After upgrading, grep for `LOCAL-PATCH`
  in that file and re-apply if it is gone — replace the `throw new Error(...)` line with:

```ts
console.warn(`[pi-subagents local-patch] requested model '${model}' has a cached exclusion (reason: ${reason}${expiry}); continuing dispatch without it.`);
```

## Related environment fix (sibling issue)

Background/detached children also need the pi peer packages installed globally next to pi:
`npm i -g @earendil-works/pi-server@<piVer> @earendil-works/pi-client@<piVer>` (same prefix as
the global `pi`). Without them every detached spawn fails with "does not provide
@earendil-works/pi-server" before model resolution is even reached. See
`~/.pi/agent/AGENTS.md` → "pi-subagents background children".
