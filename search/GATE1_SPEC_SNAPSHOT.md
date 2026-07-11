# Specification: snapshot() — barebrowse-style page capture

## Goal

Add a `snapshot()` function and `snapshot` CLI command to `web_search.py` that:
1. Attaches to a running Chromium browser (auto-launch if needed)
2. Opens a new tab at the target URL
3. Runs the full barebrowse pipeline: network-idle → consent dismissal → ARIA extraction → pruning
4. Returns structured JSON output (title + pruned ARIA tree text)
5. Closes only the tab, leaving the browser running

This mirrors the barebrowse API:
```js
// barebrowse (Node.js)
import { connect } from 'barebrowse';
const page = await connect({ port: 9222 });
await page.goto('https://example.com');
const snap = await page.snapshot();
await page.close(); // closes tab only
```

```python
# web_search.py (Python, ours)
from web_search import snapshot
result = await snapshot('https://example.com')
# -> {'title': '...', 'content': '...', 'mode': 'browse'}
```

## Scope

### In scope
- Add `snapshot()` async function that runs full pipeline on arbitrary URLs
- Add `snapshot` action to CLI (`python web_search.py snapshot "https://..."`)
- CLI accepts `--mode` flag: `act`, `browse`, `navigate`, `full` (default: `browse`)
- Add unit test `test_snapshot_pipeline` validating pipeline stages
- Add unit test `test_snapshot_url_validation` for unsafe URLs
- `snapshot()` calls `extract_url()` internally with mode parameter exposed

### Out of scope
- New file creation (all changes in `web_search.py` and `test_web_search.py`)
- Node.js integration or barebrowse dependency
- Headless mode or new browser management
- Changes to `search()` or existing `extract_url()` signatures (backward compatible)
- CI/CD or linting changes

## Files affected

| File | Action | Changes |
|------|--------|---------|
| `search/web_search.py` | Modify | Add `snapshot()` function, extend CLI with `snapshot` action + `--mode` flag |
| `search/test_web_search.py` | Modify | Add `test_snapshot_pipeline`, `test_snapshot_url_validation`, `test_snapshot_mode_enum` |

## Success Criteria

Each criterion is falsifiable via automated tests:

### Code-level tests (must pass)
1. **`python test_web_search.py` returns exit code 0** — all 9 existing tests still pass
2. **`test_snapshot_pipeline`**: verifies `snapshot()` calls `create_new_tab`, `wait_for_network_idle`, `dismiss_consent`, `extract_aria_tree`, `prune_aria_tree`, `aria_to_text` in order (mocked with `unittest.mock.AsyncMock`)
3. **`test_snapshot_url_validation`**: `snapshot()` rejects non-http/https URLs (e.g., `file:///etc/passwd`, `javascript:alert(1)`) — asserts `RuntimeError` or equivalent
4. **`test_snapshot_mode_enum`**: `snapshot(mode='act')` and `snapshot(mode='browse')` both call `prune_aria_tree` with correct mode string — asserts mock call args
5. **`test_snapshot_default_mode`**: `snapshot()` without mode arg defaults to `'browse'` — asserts mock call args

### CLI-level tests (manual validation)
6. **`python web_search.py snapshot "https://example.com" --mode act`** — returns valid JSON with `title` and `content` keys, non-empty content, exits 0
7. **`python web_search.py snapshot "file:///tmp/foo"`** — exits non-zero with error about unsafe URL
8. **`python web_search.py snapshot "https://example.com"`** — defaults to browse mode, returns valid JSON

### Regression tests
9. **`python web_search.py search "test" --num 2`** — existing search still works
10. **`python web_search.py extract "https://example.com"`** — existing extract still works
11. **All 9 existing unit tests still pass** — no regression

## Test Plan

### Unit tests (in test_web_search.py)
| Test | Purpose | Mock strategy | Should fail without impl |
|------|---------|--------------|--------------------------|
| `test_snapshot_pipeline` | Verify snapshot() calls pipeline in correct order | Mock `create_new_tab`, `send_cmd`, pipeline functions | ✅ fails — `snapshot` doesn't exist yet |
| `test_snapshot_url_validation` | Verify unsafe URLs rejected | Partial mock — let URL validation run | ✅ fails — validation not in snapshot yet |
| `test_snapshot_mode_enum` | Verify mode param forwarded to prune | Mock `prune_aria_tree`, check call args | ✅ fails — mode not passed yet |
| `test_snapshot_default_mode` | Verify default mode is 'browse' | Mock, inspect call args | ✅ fails — default not set |

### Implementation notes
- Use `unittest.mock.AsyncMock` for async mocking
- Tests must mock at the module level (`web_search.create_new_tab = mock`) to avoid real browser connections
- URL validation test should test actual `_is_safe_url()` logic within `snapshot()` context, not mock it away

## Validation Commands

```bash
# Run all unit tests — expect 13 passed, 0 failed
cd C:\Users\User\Documents\GitHub\pi-workspace\search
python test_web_search.py

# CLI smoke tests (requires live browser)
python web_search.py snapshot "https://example.com"
python web_search.py snapshot "https://example.com" --mode act
python web_search.py search "test" --num 2  # regression
python web_search.py extract "https://example.com"  # regression
```

## Implementation Plan

### Step 1: Add `snapshot()` function to web_search.py
```python
async def snapshot(url, mode='browse'):
    """Snapshot a page using the barebrowse pipeline.
    
    Returns: {'title': str, 'content': str, 'mode': str}
    Raises: RuntimeError if URL is unsafe
    """
    if not _is_safe_url(url):
        raise RuntimeError(f'Unsafe URL blocked: {url}')
    
    result = await extract_url(url)  # extract_url already runs full pipeline
    result['mode'] = mode
    return result
```

Wait — actually `extract_url` hardcodes `mode='browse'`. We need to refactor slightly:

**Better approach**: Extract the pipeline core into a private `_capture(url, mode)` that both `extract_url()` and `snapshot()` call.

```python
async def _capture(url: str, mode: str = 'browse') -> dict:
    """Core pipeline: navigate → network-idle → consent → ARIA → prune → text."""
    tab_ws, tab_id = await create_new_tab()
    try:
        async with websockets.connect(tab_ws) as ws:
            await send_cmd(ws, 'Page.navigate', {'url': url})
            await wait_for_network_idle(ws)
            await dismiss_consent(ws)
            
            # Title
            title_resp = await send_cmd(ws, 'Runtime.evaluate', {'expression': 'document.title'})
            title = title_resp['result']['result']['value']
            
            # ARIA pipeline
            aria_tree = await extract_aria_tree(ws)
            if aria_tree:
                pruned = await prune_aria_tree(ws, aria_tree, mode=mode)
                content = await aria_to_text(ws, pruned, max_length=5000)
                if content:
                    return {'title': title, 'content': content}
            
            # Fallback
            try:
                resp = await send_cmd(ws, 'Runtime.evaluate', {'expression': 'document.body.innerText'})
                content = resp['result']['result']['value']
            except Exception:
                content = ''
            return {'title': title, 'content': content[:5000]}
    finally:
        close_tab(tab_id)

async def extract_url(url):
    """Extract content — public API, mode=browse."""
    print(f'Extracting: {url}', file=sys.stderr)
    return await _capture(url, mode='browse')

async def snapshot(url, mode='browse'):
    """Snapshot a page using the barebrowse pipeline — same as extract_url but exposes mode."""
    if not _is_safe_url(url):
        raise RuntimeError(f'Unsafe URL blocked: {url}')
    print(f'Snapshotting: {url} (mode={mode})', file=sys.stderr)
    result = await _capture(url, mode=mode)
    result['mode'] = mode
    return result
```

### Step 2: Extend CLI
Add `snapshot` to choices, add `--mode` argument, handle in `main()`.

### Step 3: Add tests
Write 4 new tests as described above.
