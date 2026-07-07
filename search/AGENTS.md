# Purpose

Web search and page extraction via Opera Chrome DevTools Protocol (CDP).

## Ownership

- Owned by root project AGENTS.md
- All scripts here connect to the user's Opera GX on port 9222

## Local Contracts

- Every search/extract creates a **new tab** via `Target.createTarget`
- Created tabs are **closed immediately** after extraction
- User's existing tabs are **never** navigated, modified, or closed
- Output is routed through UTF-8 temp files + `sys.stdout.buffer` to bypass Windows cp932 encoding

## Work Guidance

- Use `asyncio` + `websockets` library for CDP connections
- `send_cmd()` sends JSON-RPC messages, waits for matching `id` response
- `search()` → Google search with `.zReHs` selector, returns `[title, cite, link]`
- `extract()` → Navigate to URL, return `document.body.innerText` + `document.title`
- CDP `Runtime.evaluate` returns `objectId` for objects — wrap in `JSON.stringify()` in JS expressions
- Opera CDP endpoints: `/json`, `/json/version`, `/json/close/{tabId}`

## Verification

- Run `python search/web_search.py search "test query" --num 3` — should return results
- Run `python search/web_search.py extract "https://example.com"` — should return page content
- Confirm user's Opera tabs are unchanged after each run
