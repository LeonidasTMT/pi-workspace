# Purpose

Web search and page extraction via Chromium-based browser CDP (Opera, Chrome, Edge).

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

## Work Guidance

- Use `asyncio` + `websockets` library for CDP connections
- `send_cmd()` sends JSON-RPC messages, waits for matching `id` response
- `ensure_browser()` → auto-detects & launches browser with `--remote-debugging-port`
- `find_browser()` → scans `BROWSER_PATHS` in priority order (Opera → Chrome → Edge)
- `create_new_tab()` → calls `ensure_browser()` then creates tab via CDP
- `search()` → Google search with ARIA tree pipeline, returns `[title, cite, link]`
- `extract_url()` → Navigate to URL, return ARIA-pruned content + title
- CDP `Runtime.evaluate` returns `objectId` for objects — wrap in `JSON.stringify()` in JS expressions
- Opera/Chrome CDP endpoints: `/json`, `/json/version`, `/json/close/{tabId}`

## Verification

- Run `python search/web_search.py search "test query" --num 3` — should return results
- Run `python search/web_search.py extract "https://example.com"` — should return page content
- Confirm user's Opera tabs are unchanged after each run
