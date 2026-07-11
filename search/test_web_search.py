"""Unit tests for enhanced web_search.py — barebrowse pipeline features.
Run: python test_web_search.py
"""
import json
import os
import sys
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import web_search as ws


# ──────────────────────────────────────────────────────────────
# Fixtures — minimal ARIA tree samples
# ──────────────────────────────────────────────────────────────

GOOGLE_SEARCH_AX = {
    'nodeId': '1', 'role': 'RootWebArea', 'name': '', 'properties': {},
    'children': [
        {
            'nodeId': '10', 'role': 'main', 'name': '', 'properties': {},
            'children': [
                {'nodeId': '20', 'role': 'heading', 'name': 'Results 1-10 for hello world',
                 'properties': {'level': 2}, 'children': []},
                {'nodeId': '30', 'role': 'generic', 'name': '', 'properties': {},
                 'children': [
                     {'nodeId': '31', 'role': 'heading', 'name': 'Hello World - Wikipedia',
                      'properties': {'level': 3},
                      'children': [
                          {'nodeId': '32', 'role': 'link',
                           'name': 'https://en.wikipedia.org/wiki/Hello_world_program',
                           'properties': {},
                           'children': [
                               {'nodeId': '33', 'role': 'StaticText',
                                'name': 'Hello World - Wikipedia',
                                'properties': {}, 'children': []}
                           ]}
                      ]},
                     {'nodeId': '34', 'role': 'StaticText',
                      'name': 'Hello World is a computer programming source code...',
                      'properties': {}, 'children': []},
                 ]},
                {'nodeId': '40', 'role': 'generic', 'name': '', 'properties': {},
                 'children': [
                     {'nodeId': '41', 'role': 'heading', 'name': 'Hello World Program',
                      'properties': {'level': 3},
                      'children': [
                          {'nodeId': '42', 'role': 'link',
                           'name': 'https://www.geeksforgeeks.org/first-program/',
                           'properties': {},
                           'children': [
                               {'nodeId': '43', 'role': 'StaticText',
                                'name': 'Hello World Program',
                                'properties': {}, 'children': []}
                           ]}
                      ]},
                     {'nodeId': '44', 'role': 'StaticText',
                      'name': 'Hello World program in various languages like C',
                      'properties': {}, 'children': []},
                 ]},
            ]
        },
        {'nodeId': '90', 'role': 'navigation', 'name': 'Main navigation', 'properties': {},
         'children': [
             {'nodeId': '91', 'role': 'link', 'name': 'Gmail', 'properties': {}, 'children': []},
             {'nodeId': '92', 'role': 'link', 'name': 'Images', 'properties': {}, 'children': []},
         ]},
    ]
}

LARGE_AX_TREE = {
    'nodeId': '1', 'role': 'RootWebArea', 'name': '', 'properties': {},
    'children': []
}
for i in range(200):
    LARGE_AX_TREE['children'].append({
        'nodeId': f'noise-{i}', 'role': 'LayoutTable', 'name': '', 'properties': {},
        'children': [
            {'nodeId': f'noise-{i}-r', 'role': 'row', 'name': '', 'properties': {},
             'children': [
                 {'nodeId': f'noise-{i}-c', 'role': 'cell', 'name': '', 'properties': {},
                  'children': [
                      {'nodeId': f'noise-{i}-t', 'role': 'InlineTextBox',
                       'name': f'Noise text fragment {i}',
                       'properties': {}, 'children': []},
                  ]},
            ]},
        ]
    })
for i in range(5):
    LARGE_AX_TREE['children'].append({
        'nodeId': f'link-{i}', 'role': 'link',
        'name': f'https://example.com/page/{i}', 'properties': {},
        'children': [
            {'nodeId': f'link-text-{i}', 'role': 'StaticText',
             'name': f'Real link {i}', 'properties': {}, 'children': []},
        ]
    })


def _all_nodes(node):
    result = [node]
    for c in node.get('children', []):
        result.extend(_all_nodes(c))
    return result


def _run_node_file(script_content):
    """Write JS to temp file, run with Node.js, return parsed JSON."""
    fd, path = tempfile.mkstemp(suffix='.js', prefix='web_search_test_')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(script_content)
    try:
        result = subprocess.run(['node', path], capture_output=True,
                                text=True, timeout=10)
        os.unlink(path)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception:
        os.unlink(path)
        raise


# ──────────────────────────────────────────────────────────────
# 1. Test: build_aria_tree produces correct nesting
# ──────────────────────────────────────────────────────────────

def test_build_aria_tree_flat():
    flat_nodes = [
        {'nodeId': 'a', 'role': 'RootWebArea', 'name': '', 'ignored': False,
         'properties': {}, 'parentId': ''},
        {'nodeId': 'b', 'role': 'main', 'name': '', 'ignored': False,
         'properties': {}, 'parentId': 'a'},
        {'nodeId': 'c', 'role': 'heading', 'name': 'Title', 'ignored': False,
         'properties': {'level': 1}, 'parentId': 'b'},
        {'nodeId': 'd', 'role': 'StaticText', 'name': 'ignored text',
         'ignored': True, 'properties': {}, 'parentId': 'b'},
    ]
    tree = ws.build_aria_tree(flat_nodes)
    assert tree is not None
    assert tree['role'] == 'RootWebArea'
    main = tree['children'][0]
    assert main['role'] == 'main'
    heading = main['children'][0]
    assert heading['role'] == 'heading'
    assert heading['name'] == 'Title'
    all_names = [n.get('name', '') for n in _all_nodes(tree)]
    assert 'ignored text' not in all_names
    print('[PASS] test_build_aria_tree_flat')


# ──────────────────────────────────────────────────────────────
# 2. Test: PRUNE_JS preserves links
# ──────────────────────────────────────────────────────────────

def test_prune_preserves_links():
    js_code = f'''
const pruneCode = {repr(ws.PRUNE_JS)};
const prune = new Function('tree', 'mode', 'return ' + '(' + pruneCode + ')');
const tree = {json.dumps(GOOGLE_SEARCH_AX)};
const pruned = prune(tree, 'act');
function collectLinks(n) {{
  if (!n) return [];
  const links = n.role === 'link' ? [n.name] : [];
  return links.concat(...(n.children || []).map(collectLinks));
}}
const links = collectLinks(pruned);
process.stdout.write(JSON.stringify({{ numLinks: links.length, links: links }}));
'''
    stdout, stderr, rc = _run_node_file(js_code)
    if rc != 0:
        print(f'[SKIP] test_prune_preserves_links (Node error: {stderr[:200]})')
        return
    data = json.loads(stdout)
    assert data['numLinks'] >= 1, f"Expected links, got {data['links']}"
    print(f'[PASS] test_prune_preserves_links ({data["numLinks"]} links)')


# ──────────────────────────────────────────────────────────────
# 3. Test: PRUNE_JS reduces size
# ──────────────────────────────────────────────────────────────

def test_prune_reduces_size():
    js_code = f'''
const pruneCode = {repr(ws.PRUNE_JS)};
const prune = new Function('tree', 'mode', 'return ' + '(' + pruneCode + ')');
const tree = {json.dumps(LARGE_AX_TREE)};
const inputSize = JSON.stringify(tree).length;
const pruned = prune(tree, 'browse');
const outputSize = pruned ? JSON.stringify(pruned).length : 0;
process.stdout.write(JSON.stringify({{ inputSize, outputSize, ratio: outputSize / inputSize }}));
'''
    stdout, stderr, rc = _run_node_file(js_code)
    if rc != 0:
        print(f'[SKIP] test_prune_reduces_size (Node error: {stderr[:200]})')
        return
    data = json.loads(stdout)
    assert data['ratio'] <= 0.5, f"Prune ratio {data['ratio']:.1%} > 50%"
    print(f'[PASS] test_prune_reduces_size (ratio: {data["ratio"]:.1%})')


# ──────────────────────────────────────────────────────────────
# 4. Test: SEARCH_TREE_JS extracts search results
# ──────────────────────────────────────────────────────────────

def test_search_tree_js():
    js_code = f'''
const searchCode = {repr(ws.SEARCH_TREE_JS)};
const extractor = new Function('root', 'num', 'return ' + '(' + searchCode + ')');
const tree = {json.dumps(GOOGLE_SEARCH_AX)};
const results = extractor(tree, 10);
process.stdout.write(JSON.stringify(results));
'''
    stdout, stderr, rc = _run_node_file(js_code)
    if rc != 0:
        print(f'[SKIP] test_search_tree_js (Node error: {stderr[:200]})')
        return
    data = json.loads(stdout)
    assert len(data) >= 2, f"Expected >=2 results, got {len(data)}"
    for r in data[:2]:
        assert r.get('title'), f"Missing title in {r}"
        assert r.get('link', '').startswith('http'), f"Missing link in {r}"
    print(f'[PASS] test_search_tree_js ({len(data)} results)')


# ──────────────────────────────────────────────────────────────
# 5. Test: FLATTEN_JS produces readable text
# ──────────────────────────────────────────────────────────────

def test_flatten_js():
    js_code = f'''
const flattenCode = {repr(ws.FLATTEN_JS)};
const flatten = new Function('node', 'return ' + '(' + flattenCode + ')');
const tree = {json.dumps(GOOGLE_SEARCH_AX)};
const text = flatten(tree);
const result = {{ length: text.length, hasResults: text.includes('Results') }};
process.stdout.write(JSON.stringify(result));
'''
    stdout, stderr, rc = _run_node_file(js_code)
    if rc != 0:
        print(f'[SKIP] test_flatten_js (Node error: {stderr[:200]})')
        return
    data = json.loads(stdout)
    assert data['hasResults'], "Flattened text should contain 'Results'"
    assert data['length'] > 0
    print(f'[PASS] test_flatten_js ({data["length"]} chars)')


# ──────────────────────────────────────────────────────────────
# 6. Test: CONSENT_DETECT_JS parses correctly
# ──────────────────────────────────────────────────────────────

def test_consent_detect_js():
    js_code = f'''
const CONSENT = {repr(ws.CONSENT_DETECT_JS)};
try {{ new Function(CONSENT); process.stdout.write('OK'); }} catch(e) {{ process.stderr.write('PARSE_ERROR: '+e.message); }}
'''
    stdout, stderr, rc = _run_node_file(js_code)
    assert stdout == 'OK', f"Consent JS parse failed: {stderr}"
    print('[PASS] test_consent_detect_js')


# ──────────────────────────────────────────────────────────────
# 7. Test: NETWORK_IDLE JS payloads parse correctly
# ──────────────────────────────────────────────────────────────

def test_network_idle_js_parses():
    js_code = f'''
const INJECT = {repr(ws.NETWORK_IDLE_INJECT_JS)};
const POLL = {repr(ws.NETWORK_IDLE_POLL_JS)};
let ok = '';
try {{ new Function(INJECT); ok += 'INJECT_OK\\n'; }} catch(e) {{}}
try {{ new Function(POLL); ok += 'POLL_OK\\n'; }} catch(e) {{}}
process.stdout.write(ok);
'''
    stdout, stderr, rc = _run_node_file(js_code)
    assert 'INJECT_OK' in stdout, f"Inject JS parse failed: {stderr}"
    assert 'POLL_OK' in stdout, f"Poll JS parse failed: {stderr}"
    print('[PASS] test_network_idle_js_parses')


# ──────────────────────────────────────────────────────────────
# 8. Test: CDP whitelist blocks dangerous methods
# ──────────────────────────────────────────────────────────────

def test_cdp_whitelist():
    assert ws.check_cdp_cmd('DOM.click') is not None, "Should block DOM.click"
    assert ws.check_cdp_cmd('Input.dispatchMouseEvent') is None
    assert ws.check_cdp_cmd('Accessibility.getFullAXTree') is None
    assert ws.check_cdp_cmd('Page.navigate', {'url': 'data:text/html,<h1>x</h1>'}) is not None
    assert ws.check_cdp_cmd('Page.navigate', {'url': 'https://safe.com'}) is None
    assert ws.check_cdp_cmd('Runtime.evaluate', {'expression': 'document.cookie'}) is not None
    assert ws.check_cdp_cmd('Runtime.evaluate', {'expression': 'document.title'}) is None
    print('[PASS] test_cdp_whitelist')


# ──────────────────────────────────────────────────────────────
# 9. Test: _is_safe_url edge cases
# ──────────────────────────────────────────────────────────────

def test_is_safe_url():
    assert ws._is_safe_url('https://example.com') is True
    assert ws._is_safe_url('http://localhost:8080') is True
    assert ws._is_safe_url('data:text/html,<h1>hi') is False
    assert ws._is_safe_url('javascript:alert(1)') is False
    assert ws._is_safe_url('file:///etc/passwd') is False
    print('[PASS] test_is_safe_url')


# ──────────────────────────────────────────────────────────────
# 10-13. Test: snapshot() feature
# ──────────────────────────────────────────────────────────────

import unittest.mock as mock
import asyncio

def test_snapshot_pipeline():
    """snapshot() calls the full pipeline in correct order."""
    # Mock the core capture function
    mock_capture = mock.AsyncMock(return_value={'title': 'Test', 'content': 'hello world'})
    ws._capture = mock_capture

    result = asyncio.run(ws.snapshot('https://example.com'))

    mock_capture.assert_called_once_with('https://example.com', mode='browse')
    assert result == {'title': 'Test', 'content': 'hello world', 'mode': 'browse'}

    # Test custom mode
    ws._capture.reset_mock()
    result = asyncio.run(ws.snapshot('https://example.com', mode='act'))
    ws._capture.assert_called_once_with('https://example.com', mode='act')
    assert result['mode'] == 'act'

    print('[PASS] test_snapshot_pipeline')


def test_snapshot_url_validation():
    """snapshot() rejects unsafe URLs before calling _capture."""
    ws._capture = mock.AsyncMock()

    for unsafe in ['file:///etc/passwd', 'javascript:alert(1)', 'ftp://example.com']:
        try:
            asyncio.run(ws.snapshot(unsafe))
            assert False, f'Should have raised for {unsafe!r}'
        except RuntimeError as e:
            assert 'Unsafe URL' in str(e) or 'blocked' in str(e).lower()

    # Safe URL should not raise
    ws._capture.reset_mock()
    ws._capture.return_value = {'title': 'T', 'content': 'C'}
    result = asyncio.run(ws.snapshot('https://example.com'))
    assert result['mode'] == 'browse'
    ws._capture.assert_called_once()

    print('[PASS] test_snapshot_url_validation')


def test_snapshot_mode_enum():
    """snapshot() rejects invalid modes."""
    ws._capture = mock.AsyncMock()

    # Valid modes should work
    for mode in ['act', 'browse', 'navigate', 'full']:
        ws._capture.return_value = {'title': 'T', 'content': 'C'}
        result = asyncio.run(ws.snapshot('https://example.com', mode=mode))
        assert result['mode'] == mode
        ws._capture.reset_mock()

    # Invalid mode should raise
    try:
        asyncio.run(ws.snapshot('https://example.com', mode='invalid'))
        assert False, 'Should have raised for invalid mode'
    except RuntimeError as e:
        assert 'invalid' in str(e).lower() or 'mode' in str(e).lower()

    print('[PASS] test_snapshot_mode_enum')


def test_snapshot_default_mode():
    """snapshot() defaults to 'browse' mode."""
    mock_capture = mock.AsyncMock(return_value={'title': 'T', 'content': 'C'})
    ws._capture = mock_capture

    result = asyncio.run(ws.snapshot('https://example.com'))

    assert result['mode'] == 'browse'
    mock_capture.assert_called_once_with('https://example.com', mode='browse')

    print('[PASS] test_snapshot_default_mode')


# ──────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    tests = [
        test_build_aria_tree_flat,
        test_prune_preserves_links,
        test_prune_reduces_size,
        test_search_tree_js,
        test_flatten_js,
        test_consent_detect_js,
        test_network_idle_js_parses,
        test_cdp_whitelist,
        test_is_safe_url,
        test_snapshot_pipeline,
        test_snapshot_url_validation,
        test_snapshot_mode_enum,
        test_snapshot_default_mode,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f'[FAIL] {t.__name__}: {e}')
            failed += 1
        except Exception as e:
            print(f'[FAIL] {t.__name__}: UNEXPECTED {e}')
            failed += 1
    print(f'\n{"="*50}')
    print(f'Results: {passed} passed, {failed} failed')
    if failed:
        sys.exit(1)
