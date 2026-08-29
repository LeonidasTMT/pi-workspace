# Purpose

Web search and page extraction via Chromium-based browser CDP (Opera, Chrome, Edge), plus the resident CDP bridge daemon (`cdp_bridge.py`) for long automation sessions.

## Ownership

- Owned by root project AGENTS.md
- All scripts connect to a Chromium-based browser on port 9222 via CDP
- Auto-launches browser if not already running (Opera → Chrome → Edge priority)

## Local Contracts

- Every search/extract creates a **new tab** via `Target.createTarget`
- Created tabs are **closed immediately** after extraction
- User's existing tabs are **never** navigated, modified, or closed
- Output is routed through UTF-8 temp files + `sys.stdout.buffer` to bypass Windows cp932 encoding
- **Browser auto-launch**: if no browser is listening on CDP port, `ensure_browser()` launches Opera → Chrome → Edge (first found)
- **Browser priority**: Opera → Chrome → Edge — configurable via `BROWSER_PATHS` list
- **User data isolation**: Chrome/Edge use isolated `--user-data-dir` to avoid profile conflicts
- **One CDP connection at a time**: while `cdp_bridge.py` runs, it is the ONLY client allowed on port 9222 — other CDP tools must go through its HTTP API or be paused (parallel connections re-trigger Opera approval prompts and can tear down the shared session)
- **Bridge tab hygiene**: `/close` only for targetIds this automation opened; never close user tabs

## Work Guidance

- Use `asyncio` + `websockets` library for CDP connections
- `send_cmd()` sends JSON-RPC messages, waits for matching `id` response
- `ensure_browser()` → auto-detects & launches browser with `--remote-debugging-port`
- `find_browser()` → scans `BROWSER_PATHS` in priority order (Opera → Chrome → Edge)
- `create_new_tab()` → calls `ensure_browser()` then creates tab via CDP
- `search()` → Google search with ARIA tree pipeline, returns `[title, cite, link]`
- `extract_url()` → Navigate to URL, return ARIA-pruned content + title
- CDP `Runtime.evaluate` returns `objectId` for objects — wrap in `JSON.stringify()` in JS expressions
- Opera/Chrome CDP endpoints: `/json`, `/json/version`, `/json/close/{tabId}
- `cdp_bridge.py`: resident daemon holding ONE raw-WebSocket CDP connection (no Origin header) so the approval prompt appears once; HTTP API on 127.0.0.1:9333 — `GET /targets`, `POST /eval {match|targetId, expr}`, `POST /navigate`, `POST /close`; start/stop/status via its own subcommands (pid file in cwd)
- Target IDs are stable across in-tab navigations — pin the id up front, don't re-match by URL after navigating

## Verification

- Run `python search/cdp_bridge.py status` while it runs — should print running + target counts; after `stop`, port 9333 is closed again
- Bridge smoke test: launch detached, wait for approval prompt (one), then `curl http://127.0.0.1:9333/healthz` → `{"ok": true}` and `/targets` lists the user's open tabs
- Run `python search/web_search.py search "test query" --num 3` — should return results
- Run `python search/web_search.py extract "https://example.com"` — should return page content
- Confirm user's Opera tabs are unchanged after each run

## Child DOX Index

No child DOX files.
