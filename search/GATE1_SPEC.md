# Gate 1: Specification — barebrowse-Style Enhancements for web_search.py

## 1. Problem Statement

The current `web_search.py` has critical weaknesses compared to `barebrowse`:

| Issue | Current | Target |
|-------|---------|--------|
| **Page readiness** | Blind `await asyncio.sleep(4/3)` | CDP `network-idle` detection (all requests done) |
| **Content extraction** | Raw `document.body.innerText` (huge, noisy) | ARIA tree → pruned, structured output |
| **Cookie consent** | No handling — may block page | Auto-dismiss via ARIA dialog/button detection |
| **Search parsing** | Fragile CSS selector (`zReHs`) | ARIA tree → structural/link extraction |
| **Token efficiency** | ~5KB raw text dump | Pruned ARIA tree (10-100x smaller) |

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────┐
│  web_search.py (enhanced)                       │
│                                                 │
│  search() / extract_url()                       │
│    ├── create_new_tab()  [existing]             │
│    ├── navigate()        [existing]             │
│    ├── wait_for_network_idle()  [NEW]           │
│    ├── dismiss_consent()      [NEW]             │
│    ├── extract_aria_tree()    [NEW]             │
│    └── prune_aria_tree()      [NEW]             │
└─────────────────────────────────────────────────┘

JS payloads (injected via Runtime.evaluate):
  ├── network_idle.js   → resolves when requests finish
  ├── aria_extract.js   → walks accessibility node tree
  ├── consent.js        → finds & clicks consent accept
  └── aria_flatten.js   → converts tree to flat text
```

## 3. Detailed Requirements

### 3.1 Network Idle Detection (`wait_for_network_idle`)

**Reference**: `barebrowse/src/network-idle.js`

**Implementation**: Inject JS via `Runtime.evaluate` that:
1. Intercepts `fetch`/`XMLHttpRequest`/`navigator.sendBeacon`
2. Listens to CDP `Network.requestWillBeSent` & `Network.loadingFinished`
3. Resolves when no pending requests for 500ms (configurable)

**Requirements**:
- Must NOT block forever: hard timeout of 15s, then return anyway
- Must handle SPA single-page loads (may have 0 network requests after DOM ready)
- Must work with Google Search results (multiple parallel requests)

**Success criteria**: Replaces `await asyncio.sleep(4)` with `await wait_for_network_idle(ws, timeout=10)`

### 3.2 Consent Auto-Dismissal (`dismiss_consent`)

**Reference**: `barebrowse/src/consent.js`, `consent-patterns.js`

**Implementation**: Inject JS via `Runtime.evaluate` that:
1. Queries ARIA tree via `Accessibility.getFullAXTree` CDP command
2. Finds nodes with `role="dialog"` or `role="alertdialog"`
3. Checks if node name matches consent hints (cookie, privacy, consent, etc.)
4. Finds child button matching accept patterns (Accept All, Agree, OK, etc.)
5. Performs CDP `Input.dispatchMouseEvent` click on the button

**Requirements**:
- Must handle multilingual consent buttons (20+ languages from patterns)
- Must NOT dismiss non-consent dialogs
- Must be idempotent (safe to call when no consent present)
- Must include timeout: max 5s total

**CDP Extension**: Add to whitelist:
```python
'Input.dispatchMouseEvent',  # needed for consent click
'Accessibility.getFullAXTree',
```

### 3.3 ARIA Tree Extraction (`extract_aria_tree`)

**Reference**: `barebrowse/src/aria.js`

**Implementation**:
1. Send CDP `Accessibility.getFullAXTree` → raw AX tree
2. Build tree from flat list (each node has `ignored` flag)
3. Filter out ignored nodes
4. Return nested `{nodeId, role, name, properties, children}` structure

**Requirements**:
- Must handle large pages (10,000+ nodes)
- Must return tree as JSON-serializable structure
- Must be called BEFORE pruning

### 3.4 ARIA Tree Pruning (`prune_aria_tree`)

**Reference**: `barebrowse/src/prune.js`

**Implementation**: Port `prune.js` logic to Python (or keep as JS injected via `Runtime.evaluate`).

**Decision**: Keep as **JS payload** executed via `Runtime.evaluate` for best performance and maintainability. Python version would need complex data structure handling.

**JS payload** implements the 9-step pipeline:
1. Extract landmark regions (main, banner, navigation, etc.)
2. Prune nodes by role taxonomy (interactive, structural, text, etc.)
3. Collapse structural wrappers (LayoutTable, group, etc.)
4. Post-clean (combobox trim, orphaned headings)
5-8. E-commerce noise removal (links dedup, footer, etc.)

**Modes**:
- `'browse'` / `'read'`: Keep paragraphs, emphasis, figures → for `extract_url()`
- `'act'`: Compact, interactive elements → for `search()`

**Requirements**:
- Output must be ≤ 5KB for typical pages
- Must preserve links, headings, key text content
- Must handle Google Search results specifically

### 3.5 Search Results Extraction (ARIA-based)

**Reference**: Google Search uses semantic HTML → ARIA tree should have:
- `<h3>` headings → role="heading", properties={level: 3}
- Links → role="link"
- URL snippets → role="StaticText" or inside "link"

**Implementation**: After pruning, traverse ARIA tree to extract:
```python
{
  'title': heading.name,
  'link': link.href (from child link node),
  'snippet': static_text.name (from sibling/child text nodes),
}
```

## 4. File Modifications

### `web_search.py` — Changes

#### New constants/imports:
```python
# ARIA/Network/Consent JS payloads (as multiline strings)
NETWORK_IDLE_JS = r"""..."""
ARIA_EXTRACT_JS = r"""..."""  # or use CDP directly
CONSENT_JS = r"""..."""
ARIA_PRUNE_JS = r"""..."""
ARIA_FLATTEN_JS = r"""..."""

# Extended CDP whitelist
'Input.dispatchMouseEvent',
'Accessibility.getFullAXTree',
'Network.enable',  # for network-idle
'Network.requestWillBeSent',
'Network.loadingFinished',
'Network.loadingFailed',
'Page.domContentEventFired',
'Page.loadEventFired',
```

#### New async functions:
```python
async def wait_for_network_idle(ws, timeout=10, idle_ms=500):
    """Wait until page network is idle, with fallback timeout."""

async def dismiss_consent(ws, timeout=5):
    """Auto-dismiss cookie consent dialogs. Idempotent."""

async def extract_aria_tree(ws):
    """Get ARIA tree via CDP, return as dict."""

async def prune_aria_tree(tree, mode='browse'):
    """Prune ARIA tree for agent consumption. Returns pruned tree."""

async def aria_to_text(tree, max_length=5000):
    """Flatten pruned ARIA tree to readable text."""
```

#### Modified functions:
```python
async def search(query, num_results=10):
    # Replace: await asyncio.sleep(4)
    await wait_for_network_idle(ws, timeout=10)
    await dismiss_consent(ws)

    # Replace: EXTRACT_JS (CSS selectors)
    tree = await extract_aria_tree(ws)
    pruned = await prune_aria_tree(tree, mode='act')
    return parse_search_results(pruned, num_results)

async def extract_url(url):
    # Replace: await asyncio.sleep(3)
    await wait_for_network_idle(ws, timeout=10)
    await dismiss_consent(ws)

    # Replace: document.body.innerText
    tree = await extract_aria_tree(ws)
    pruned = await prune_aria_tree(tree, mode='browse')
    text = await aria_to_text(pruned)
    return {'title': page_title, 'content': text[:5000]}
```

## 5. Success Criteria

### Unit Tests (must pass):
- [x] `test_network_idle_resolves`: Injects JS, simulates requests, verifies resolution
- [x] `test_consent_detection`: Mock ARIA tree with consent dialog → detects accept button
- [x] `test_aria_tree_extraction`: Mock CDP response → correct nested structure
- [x] `test_prune_preserves_links`: Input tree with links → all links in output
- [x] `test_prune_reduces_size`: Large input → output ≤ 20% of input size
- [x] `test_search_returns_results`: Mock Google page → extracts titles/links/snippets

### Integration Tests (require Opera):
- [x] `test_search_real_google`: Search "hello world" → returns ≥ 1 result with title/link
- [x] `test_extract_real_page`: Extract known URL → returns structured content < 5KB
- [x] `test_consent_on_page_with_consent`: Hit a page known to have consent → auto-dismissed

### Non-Functional:
- Response time ≤ 15s per operation (vs current ~8s with sleep)
- Output size ≤ 5KB for typical pages (vs current ~5KB raw but unstructured)
- Zero crashes on pages without consent (idempotent consent handling)

## 6. Exit Criteria for Gate 1

- [x] All requirements clearly stated ✓
- [x] File modifications specified ✓
- [x] Success criteria defined ✓
- [x] Test cases enumerated ✓
- [ ] **APPROVAL**: Stakeholder sign-off

---

## Appendix: Porting Notes

### barebrowse → web_search.py Mapping

| barebrowse module | web_search.py equivalent |
|---|---|
| `cdp.js` | `send_cmd()`, `create_new_tab()` (already exist) |
| `network-idle.js` | NEW `wait_for_network_idle()` |
| `consent.js` | NEW `dismiss_consent()` |
| `aria.js` | NEW `extract_aria_tree()` |
| `prune.js` | JS payload for `prune_aria_tree()` |
| `readable.js` | `aria_to_text()` |

### Key Differences from barebrowse
1. **barebrowse** is Node.js CLI; **web_search.py** is Python CDP client
2. We inject JS payloads via `Runtime.evaluate` rather than running JS natively
3. We use `websockets` library; barebrowse uses native `ws`
4. We keep the existing Opera tab isolation model
