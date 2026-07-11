# -*- coding: utf-8 -*-
import asyncio
import websockets
import json
import urllib.request
import urllib.parse
import sys
import os
import time
import subprocess
import shutil
import signal

# ── Browser config (Chromium-based) ──────────────────────────
# Supports Opera, Chrome, Edge, Chromium — auto-detects & launches
CDP_PORT = int(os.environ.get('CDP_PORT', '9222'))
CDP_BASE = f'http://127.0.0.1:{CDP_PORT}'

# Browser priority order — first found wins
BROWSER_PATHS = [
    # Opera GX
    os.path.expandvars(r'%PROGRAMFILES%\Opera GX\opera.exe'),
    os.path.expandvars(r'%PROGRAMFILES(X86)%\Opera GX\opera.exe'),
    os.path.expandvars(r'%PROGRAMFILES%\Opera\opera.exe'),
    os.path.expandvars(r'%PROGRAMFILES(X86)%\Opera\opera.exe'),
    # Google Chrome
    os.path.expandvars(r'%PROGRAMFILES%\Google\Chrome\Application\chrome.exe'),
    os.path.expandvars(r'%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe'),
    # Microsoft Edge
    os.path.expandvars(r'%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe'),
    os.path.expandvars(r'%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe'),
    # Chromium
    os.path.expandvars(r'%PROGRAMFILES%\Chromium\Application\chrome.exe'),
]

def find_browser():
    """Find the first available Chromium-based browser executable."""
    for path in BROWSER_PATHS:
        path_expanded = os.path.expandvars(path)
        if os.path.isfile(path_expanded):
            return path_expanded
    # Fallback: search PATH
    for name in ['opera.exe', 'chrome.exe', 'msedge.exe']:
            exe = shutil.which(name)
            if exe:
                return exe
    return None

def _is_cdp_listening():
    """Check if a browser is already listening on the CDP port."""
    try:
        resp = urllib.request.urlopen(f'{CDP_BASE}/json/version', timeout=2)
        data = json.loads(resp.read())
        return data
    except Exception:
        return None

def _is_port_in_use():
    """Check if anything is listening on the CDP port (even if not CDP)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(('127.0.0.1', CDP_PORT))
        s.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False

def launch_browser():
    """Launch a Chromium-based browser with --remote-debugging-port."""
    # If port is occupied but not serving CDP, give a clear error
    if _is_port_in_use():
        raise RuntimeError(
            f'Port {CDP_PORT} is in use but not serving CDP. ' +
            'Something (likely Opera) is running without --remote-debugging-port. ' +
            'Close it and restart with: opera.exe --remote-debugging-port=' + str(CDP_PORT)
        )
    browser_exe = find_browser()
    if not browser_exe:
        raise RuntimeError(
            'No Chromium-based browser found. '
            'Install Opera, Chrome, or Edge, or start one manually with '
            f'--remote-debugging-port={CDP_PORT}'
        )

    # Build launch args
    args = [
        browser_exe,
        f'--remote-debugging-port={CDP_PORT}',
        '--no-first-run',
        '--no-default-browser-check',
    ]

    # If this is Chrome/Edge (not Opera), set a unique user data dir to avoid conflicts
    browser_name = os.path.basename(browser_exe).lower()
    if browser_name != 'opera.exe':
        user_data_dir = os.path.join(
            os.environ.get('TEMP', 'C:\\Windows\\Temp'),
            f'.cdp_browser_user_data_{CDP_PORT}'
        )
        args.append(f'--user-data-dir={user_data_dir}')

    print(f'Launching browser: {browser_exe}', file=sys.stderr)
    try:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        raise RuntimeError(f'Failed to launch browser: {e}') from e

    # Wait for CDP port to become available
    for _ in range(20):  # max 10 seconds
        time.sleep(0.5)
        info = _is_cdp_listening()
        if info:
            browser_name = os.path.basename(browser_exe)
            print(f'Browser ready: {browser_name} on port {CDP_PORT}', file=sys.stderr)
            return info, proc

    raise RuntimeError(
        f'Browser failed to start on port {CDP_PORT}. '
        f'Is port in use? Try: taskkill /F /IM chrome.exe'
    )


def ensure_browser():
    """Ensure a browser is available. Returns CDP info dict."""
    info = _is_cdp_listening()
    if info:
        # Browser already running — try to identify it
        product = info.get('product', '')
        browser_name = 'unknown'
        if 'opera' in product.lower():
            browser_name = 'Opera'
        elif 'chrome' in product.lower():
            browser_name = 'Chrome'
        elif 'edge' in product.lower():
            browser_name = 'Edge'
        print(f'Browser connected: {browser_name} on port {CDP_PORT}', file=sys.stderr)
        return info
    else:
        # Launch browser
        info, proc = launch_browser()
        return info


def ensure_opera():  # Backward compat alias
    return ensure_browser()

# ╔══════════════════════════════════════════════════════════╗
# ║  CDP COMMAND WHITELIST — DOX ENFORCEMENT                 ║
# ║  Only these methods are allowed. Everything else blocked. ║
# ╚══════════════════════════════════════════════════════════╝
ALLOWED_CDP_METHODS = {
    'Target.createTarget',
    'Target.getTargetInfo',
    'Target.getTargets',
    'Page.navigate',            # restricted to http/https only
    'Page.reload',
    'Page.getNavigationHistory',
    'Runtime.evaluate',
    'Runtime.enable',
    'DOM.getDocument',
    'DOM.enable',
    'CSS.enable',
    'Network.enable',
    'Page.enable',
    'Browser.getVersion',
    # ── barebrowse additions ──
    'Input.dispatchMouseEvent',
    'Accessibility.enable',
    'Accessibility.getFullAXTree',
}

def _is_safe_url(url):
    lower = url.lower().split('?')[0].split('#')[0].rstrip('/')
    return lower.startswith('http://') or lower.startswith('https://')

def _is_safe_expression(expression):
    expr_lower = expression.lower()
    for pattern in ['localstorage', 'sessionstorage', 'document.cookie',
                    'navigator.cookieenabled', 'indexeddb', 'opendatabase',
                    'clearcookies', 'deletecookies']:
        if pattern in expr_lower:
            return False
    return True

def check_cdp_cmd(method, params=None):
    params = params or {}
    if method not in ALLOWED_CDP_METHODS:
        return f'CDP method not allowed: {method}'
    if method == 'Page.navigate':
        url = params.get('url', '')
        if not _is_safe_url(url):
            return f'Navigation blocked (unsafe URL): {url}'
    if method == 'Runtime.evaluate':
        expr = params.get('expression', '')
        if not _is_safe_expression(expr):
            return 'Runtime.evaluate blocked: storage/cookie access not allowed'
    return None  # allowed


# ═══════════════════════════════════════════════════════════════
#  JS PAYLOADS — injected via Runtime.evaluate
# ═══════════════════════════════════════════════════════════════

NETWORK_IDLE_INJECT_JS = r"""
(function() {
  if (window.__netPending) return;
  window.__netPending = 0;
  window.__netIdleSince = null;
  function bump() { window.__netPending++; window.__netIdleSince = null; }
  function settle() { window.__netPending--; if (window.__netPending <= 0) { window.__netPending = 0; window.__netIdleSince = Date.now(); } }
  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function() { bump(); this.addEventListener('load', settle); this.addEventListener('error', settle); this.addEventListener('abort', settle); return origOpen.apply(this, arguments); };
  const origFetch = window.fetch;
  window.fetch = function() { bump(); return origFetch.apply(this, arguments).then(r => { settle(); return r; }, e => { settle(); throw e; }); };
})();
"""

NETWORK_IDLE_POLL_JS = r"""
(() => {
  if (window.__netPending !== undefined) {
    if (window.__netPending === 0 && window.__netIdleSince) {
      return (Date.now() - window.__netIdleSince) >= (arguments[0] || 500);
    }
    if (window.__netPending === 0 && !window.__netIdleSince) return true;
  }
  return false;
})()
"""

CONSENT_DETECT_JS = r"""
(() => {
  const acceptTexts = ['accept all','allow all','agree to all','yes, i agree','i agree','accept cookies','allow cookies','got it','alle accepteren','akkoord','alle akzeptieren','allem zustimmen','tout accepter','accepter tout','aceptar todo','accetta tutto','aceitar tudo','zaakceptuj wszystko','akceptuj wszystko'];
  const consentKws = ['cookie','consent','privacy'];
  const bodyText = (document.body.textContent||'').toLowerCase();
  if (!consentKws.some(k => bodyText.includes(k))) return null;
  const dialogs = document.querySelectorAll('[role="dialog"],[role="alertdialog"],dialog');
  for (const d of dialogs) {
    const dt = (d.textContent||'').toLowerCase();
    if (!consentKws.some(k=>dt.includes(k))) continue;
    const btns = d.querySelectorAll('button,[role="button"]');
    for (const b of btns) {
      const t = (b.textContent||'').trim().toLowerCase();
      for (const p of acceptTexts) { if (t.includes(p)) { b.click(); return 'clicked'; } }
    }
  }
  const allBtns = document.querySelectorAll('button,[role="button"]');
  for (const b of allBtns) {
    const t = (b.textContent||'').trim().toLowerCase();
    for (const p of acceptTexts) { if (t===p) { b.click(); return 'clicked'; } }
  }
  return null;
})()
"""

# Prune JS — port of barebrowse/prune.js, injected via Runtime.evaluate
PRUNE_JS = r"""
(function(tree, mode) {
  mode = mode || 'browse';
  const LANDMARKS = new Set(['banner','main','contentinfo','navigation','complementary','search','form','region']);
  const INTERACTIVE = new Set(['button','link','textbox','searchbox','checkbox','radio','combobox','listbox','menuitem','menuitemcheckbox','menuitemradio','option','slider','spinbutton','switch','tab','treeitem']);
  const GROUPS = new Set(['radiogroup','tablist','menu','menubar','toolbar','listbox','tree','treegrid','grid']);
  const STRUCTURAL = new Set(['generic','group','list','table','row','rowgroup','cell','directory','document','application','presentation','none','separator','LayoutTable','LayoutTableRow','LayoutTableCell']);
  const SKIP = new Set(['InlineTextBox','LineBreak','superscript']);
  const MODE_R = { act: new Set(['main']), browse: new Set(['main']), navigate: new Set(['main','banner','navigation','search']), full: new Set(['main','banner','navigation','contentinfo','complementary','search']) };
  const allowed = MODE_R[mode] || MODE_R.act;
  const isB = mode === 'browse';
  function hasI(n){return INTERACTIVE.has(n.role)||GROUPS.has(n.role)||n.children?.some(c=>hasI(c))||false;}
  function hasH(n){return n.role==='heading'||n.children?.some(c=>hasH(c))||false;}
  function er(nodes){
    if(nodes.length===1&&(nodes[0].role==='RootWebArea'||nodes[0].role==='WebArea'))nodes=nodes[0].children||[];
    const hl=nodes.some(n=>LANDMARKS.has(n.role)),mn=nodes.find(n=>n.role==='main'),hm=mn?(hasI(mn)||hasH(mn)):false,r=[];
    for(const n of nodes){
      if(LANDMARKS.has(n.role)){if(allowed.has(n.role))r.push(n);}
      else if(hl&&hm){if(allowed.has('navigation'))r.push(n);}
      else if(hl&&!hm){if(hasI(n)||hasH(n))r.push(n);}
      else r.push(n);
    }
    return r;
  }
  function pn(node,ctx){
    if(!node||SKIP.has(node.role))return null;
    if(ctx.m==='act'&&node.role==='link'&&ctx.p==='paragraph')return null;
    if(node.role==='paragraph'){return ctx.m==='act'?null:{...node,children:pC(node.children,ctx)};}
    if(isB&&node.role==='navigation')return null;
    if(node.role==='code')return node;
    if(INTERACTIVE.has(node.role))return{...node,children:pC(node.children,ctx)};
    if(GROUPS.has(node.role)&&node.name)return{...node,children:pC(node.children,ctx)};
    if(node.role==='group'&&node.name)return{...node,children:pC(node.children,ctx)};
    if(node.role==='heading')return{...node,children:[]};
    if(node.role==='StaticText'){const t=node.name||'';if(!t)return null;if(isB&&t.length>0)return node;if(!isB&&t.length<30)return node;return null;}
    if(node.role==='img'||node.role==='image'){if(isB&&node.name)return{...node,children:[]};return null;}
    if(node.role==='separator')return null;
    const childCtx={m:ctx.m,parent:node.role},kept=pC(node.children,childCtx);
    if(kept.length>0)return{...node,children:kept};return null;
  }  function pC(ch,ctx){if(!ch)return[];return ch.map(c=>pn(c,ctx)).filter(Boolean);}
  function collapse(node){
    if(!node)return null;
    node={...node,children:node.children.map(c=>collapse(c)).filter(Boolean)};
    if((STRUCTURAL.has(node.role)&&!node.name)||/^LayoutTable/.test(node.role)||['row','cell','rowgroup'].includes(node.role)){
      if(node.children.length===1)return node.children[0];
      if(node.children.length>0)return{...node,role:'_promote',children:node.children};return null;
    }
    return node;
  }
  let r=er([tree]).map(n=>pn(n,{m:mode,parent:null})).filter(Boolean).map(n=>collapse(n)).filter(Boolean);
  if(r.length===0)return null;if(r.length===1)return r[0];
  return{nodeId:'',role:'root',name:'',properties:{},ignored:false,children:r};
})
"""

# Flatten: pruned tree -> readable text
FLATTEN_JS = r"""
(function(node){
  const parts=[];
  function fmt(n){
    if(!n||n.ignored||n.role==='InlineTextBox'||n.role==='LineBreak'){for(const c of(n.children||[]))fmt(c);return;}
    let line=n.role||'none';if(n.name)line+=' "'+n.name+'"';if(n.properties?.level)line+=' [level='+n.properties.level+']';
    parts.push(line);for(const c of(n.children||[]))fmt(c);
  }
  fmt(node);return parts.join('\n');
})
"""

# Search result extraction from ARIA tree
SEARCH_TREE_JS = r"""
(function(root,num){
  num=num||10;const r=[];
  function walk(node,pLink){
    if(!node)return;
    if(node.role==='link'){for(const c of(node.children||[]))walk(c,node);return;}
    if(node.role==='heading'&&node.name)r.push({title:node.name,link:pLink?.name||'',snippet:''});
    if(node.role==='StaticText'&&node.name&&r.length>0&&!r[r.length-1].snippet)r[r.length-1].snippet=node.name;
    for(const c of(node.children||[]))walk(c,pLink);
  }
  walk(root);return r.slice(0,num);
})
"""


# ═══════════════════════════════════════════════════════════════
#  Helper functions
# ═══════════════════════════════════════════════════════════════

async def create_new_tab(url='about:blank'):
    ensure_browser()  # auto-launches if not already running
    tabs = json.loads(urllib.request.urlopen(f'{CDP_BASE}/json').read())
    for tab in tabs:
        if tab.get('type') == 'page' and tab.get('url', '').startswith('http'):
            controller_ws = tab['webSocketDebuggerUrl']
            break
    else:
        raise RuntimeError('No available controller tab')
    async with websockets.connect(controller_ws) as ws:
        req = {'id': 1, 'method': 'Target.createTarget', 'params': {'url': url}}
        await ws.send(json.dumps(req))
        for _ in range(5):
            try:
                resp = await asyncio.wait_for(ws.recv(), 3)
                data = json.loads(resp)
                if isinstance(data, dict) and 'result' in data and 'targetId' in data['result']:
                    new_tab_id = data['result']['targetId']
                    break
            except asyncio.TimeoutError:
                continue
        else:
            raise RuntimeError('Did not get targetId from Target.createTarget')
    for _ in range(10):
        tabs = json.loads(urllib.request.urlopen(f'{CDP_BASE}/json').read())
        for tab in tabs:
            if tab['id'] == new_tab_id:
                return tab['webSocketDebuggerUrl'], new_tab_id
        await asyncio.sleep(0.5)
    raise RuntimeError(f'Could not find newly created tab {new_tab_id}')

def close_tab(tab_id):
    try:
        urllib.request.urlopen(f'{CDP_BASE}/json/close/{tab_id}')
    except Exception:
        pass

_CMD_SEQ = 0  # global counter — unique id per command across the process

def _next_id():
    global _CMD_SEQ
    _CMD_SEQ += 1
    return _CMD_SEQ

async def send_cmd(ws, method, params=None, timeout=15):
    err = check_cdp_cmd(method, params)
    if err:
        raise RuntimeError(f'CDP BLOCKED — {err}')
    rid = _next_id()
    req = {'id': rid, 'method': method, 'params': params or {}}
    await ws.send(json.dumps(req))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = await asyncio.wait_for(ws.recv(), min(2, deadline - time.time()))
        except asyncio.TimeoutError:
            continue
        parsed = json.loads(resp)
        if parsed.get('id') == rid:
            return parsed
        # Skip CDP events (they have no 'id' or different 'id')
    raise TimeoutError(f'Timeout waiting for CDP response id={rid}')

# ── Network Idle ─────────────────────────────────────────────
async def wait_for_network_idle(ws, timeout=10, idle_ms=500):
    """Wait until page network is idle. Falls back to sleep(timeout/2) on failure."""
    try:
        await send_cmd(ws, 'Network.enable')
    except Exception:
        pass  # best effort
    try:
        await send_cmd(ws, 'Runtime.evaluate', {'expression': NETWORK_IDLE_INJECT_JS})
    except Exception:
        pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = await send_cmd(ws, 'Runtime.evaluate', {'expression': NETWORK_IDLE_POLL_JS})
            if resp.get('result', {}).get('result', {}).get('value') is True:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.25)
    # Fallback: just sleep a bit
    await asyncio.sleep(3)

# ── Consent Dismissal ────────────────────────────────────────
async def dismiss_consent(ws, timeout=5):
    """Auto-dismiss cookie consent dialogs. Idempotent (safe when no consent)."""
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = await send_cmd(ws, 'Runtime.evaluate', {'expression': CONSENT_DETECT_JS})
            val = resp.get('result', {}).get('result', {}).get('value')
            if val == 'clicked':
                await asyncio.sleep(0.5)
                return True
            elif val is None:
                return False
        return False
    except Exception:
        return False  # idempotent failure

# ── ARIA Tree Extraction ─────────────────────────────────────
async def extract_aria_tree(ws):
    """Get ARIA tree via CDP Accessibility.getFullAXTree."""
    try:
        await send_cmd(ws, 'Accessibility.enable')
        resp = await send_cmd(ws, 'Accessibility.getFullAXTree')
        flat_nodes = resp.get('result', {}).get('nodes', [])
        # Build nested tree from flat list
        tree = build_aria_tree(flat_nodes)
        return tree
    except Exception:
        return None

def _ax_value(val):
    """Extract string value from AXNode wrapper (Opera/new CDP format) or pass through."""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return val.get('value', '')
    return str(val) if val is not None else ''

def _normalize_ax_node(n):
    """Normalize an AX node to use plain string values (handles both old/new CDP formats)."""
    return {
        'nodeId': _ax_value(n.get('nodeId', '')),
        'role': _ax_value(n.get('role', '')),
        'name': _ax_value(n.get('name', '')),
        'parentId': _ax_value(n.get('parentId', '')),
        'ignored': n.get('ignored', False),
        'properties': n.get('properties', {}),
    }

def build_aria_tree(flat_nodes):
    """Build nested tree from flat CDP AX nodes."""
    if not flat_nodes:
        return None
    # Normalize nodes (handle Opera's wrapped AXNode values)
    normed = [_normalize_ax_node(n) for n in flat_nodes]
    ignored = set()
    for n in normed:
        if n.get('ignored', False):
            ignored.add(n['nodeId'])
    ignored_roles = {'InlineTextBox', 'LineBreak', 'superscript'}
    # Filter out ignored nodes and noise roles
    clean = [n for n in normed if n['nodeId'] not in ignored and n.get('role', '') not in ignored_roles]
    # Build map
    node_map = {}
    for n in clean:
        node_map[n['nodeId']] = {
            'nodeId': n['nodeId'],
            'role': n.get('role', ''),
            'name': n.get('name', ''),
            'properties': {},
            'children': []
        }
    # Link children
    roots = []
    for n in clean:
        node = node_map[n['nodeId']]
        pid = n.get('parentId', '')
        if pid and pid in node_map:
            node_map[pid]['children'].append(node)
        else:
            roots.append(node)
    if len(roots) == 1:
        return roots[0]
    elif len(roots) > 1:
        return {'nodeId': '', 'role': 'RootWebArea', 'name': '', 'properties': {}, 'children': roots}
    return None

# ── Prune ARIA Tree ──────────────────────────────────────────
async def prune_aria_tree(ws, tree, mode='browse'):
    """Prune ARIA tree via injected JS. Returns pruned tree dict."""
    try:
        tree_str = json.dumps(tree)
        expr = f'({PRUNE_JS})({tree_str}, "{mode}")'
        resp = await send_cmd(ws, 'Runtime.evaluate', {'expression': expr})
        val = resp.get('result', {}).get('result', {}).get('value')
        if val:
            return json.loads(val)
        return None
    except Exception:
        return tree  # fallback: return raw tree

# ── Flatten ARIA Tree to Text ────────────────────────────────
async def aria_to_text(ws, tree, max_length=5000):
    """Flatten pruned ARIA tree to readable text."""
    try:
        tree_str = json.dumps(tree)
        expr = f'({FLATTEN_JS})({tree_str})'
        resp = await send_cmd(ws, 'Runtime.evaluate', {'expression': expr})
        val = resp.get('result', {}).get('result', {}).get('value', '')
        if val:
            return json.loads(val)[:max_length]
        return ''
    except Exception:
        return str(tree)[:max_length]

# ── Search Results from ARIA Tree ────────────────────────────
async def aria_search_results(ws, tree, num=10):
    """Extract search results from ARIA tree."""
    try:
        tree_str = json.dumps(tree)
        expr = f'({SEARCH_TREE_JS})({tree_str}, {num})'
        resp = await send_cmd(ws, 'Runtime.evaluate', {'expression': expr})
        val = resp.get('result', {}).get('result', {}).get('value')
        if val:
            return json.loads(val)
        return []
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
#  Main functions (enhanced with barebrowse pipeline)
# ═══════════════════════════════════════════════════════════════

EXTRACT_JS = r"""
(() => {
    const results = document.querySelectorAll('.kb0PBd.A9Y9g');
    const items = [];
    for (const el of results) {
        const linkEl = el.querySelector('a.zReHs');
        if (!linkEl) continue;
        const titleEl = el.querySelector('h3');
        const container = el.closest('.N54PNb') || el.parentElement;
        const snippetEls = container.querySelectorAll('.kb0PBd.A9Y9g:not(.jGGQ5e)');
        let snippet = '';
        for (const s of snippetEls) {
            const t = (s.textContent || '').trim();
            if (t.length > 10) { snippet = t; break; }
        }
        items.push({
            title: titleEl?.textContent.trim() || linkEl.textContent.trim(),
            snippet,
            link: linkEl.href,
            cite: el.querySelector('.B6fmyf')?.textContent.trim() || '',
        });
    }
    return JSON.stringify(items.slice(0, __NUM__));
})()
"""

async def search(query, num_results=10):
    """Search Google in a fresh tab using ARIA/prune pipeline."""
    print(f'Searching: {query}', file=sys.stderr)
    tab_ws, tab_id = await create_new_tab()
    try:
        async with websockets.connect(tab_ws) as ws:
            await send_cmd(ws, 'Page.navigate', {
                'url': f'https://www.google.com/search?q={urllib.parse.quote_plus(query)}'
            })
            # barebrowse pipeline: network-idle + consent + ARIA extraction
            await wait_for_network_idle(ws, timeout=10)
            await dismiss_consent(ws)

            # Google renders results asynchronously; poll until they appear (up to 15s)
            for attempt in range(15):
                await asyncio.sleep(1)
                resp = await send_cmd(ws, 'Runtime.evaluate', {
                    'expression': EXTRACT_JS.replace('__NUM__', str(num_results))
                })
                result = resp['result']['result']
                if result['type'] == 'string':
                    results = json.loads(result['value'])
                    if results:
                        print(f'Google search complete in {attempt+1}s', file=sys.stderr)
                        return results

            return []  # no results found
    finally:
        close_tab(tab_id)

# ── Core capture pipeline ───────────────────────────────────

async def _capture(url, mode='browse'):
    """Core pipeline: create tab -> navigate -> network-idle -> consent -> ARIA -> prune -> text.
    
    Returns: {'title': str, 'content': str}
    """
    tab_ws, tab_id = await create_new_tab()
    try:
        async with websockets.connect(tab_ws) as ws:
            await send_cmd(ws, 'Page.navigate', {'url': url})
            # barebrowse pipeline
            await wait_for_network_idle(ws, timeout=10)
            await dismiss_consent(ws)

            # Get page title (always needed)
            try:
                title_resp = await send_cmd(ws, 'Runtime.evaluate', {'expression': 'document.title'})
                title = title_resp['result']['result']['value']
            except Exception:
                title = url

            # Try ARIA tree extraction first
            aria_tree = await extract_aria_tree(ws)
            if aria_tree:
                pruned = await prune_aria_tree(ws, aria_tree, mode=mode)
                content = await aria_to_text(ws, pruned, max_length=5000)
                if content:
                    return {'title': title, 'content': content}

            # Fallback: original innerText
            try:
                resp = await send_cmd(ws, 'Runtime.evaluate', {'expression': 'document.body.innerText'})
                content = resp['result']['result']['value']
            except Exception:
                content = ''
            return {'title': title, 'content': content[:5000]}
    finally:
        close_tab(tab_id)


async def extract_url(url):
    """Extract content from a URL using ARIA/prune pipeline (browse mode)."""
    print(f'Extracting: {url}', file=sys.stderr)
    return await _capture(url, mode='browse')


# ── Snapshot (barebrowse-style) ──────────────────────────────

VALID_MODES = {'act', 'browse', 'navigate', 'full'}

async def snapshot(url, mode='browse'):
    """Snapshot a page using the barebrowse pipeline.
    
    Returns: {'title': str, 'content': str, 'mode': str}
    Raises: RuntimeError if URL is unsafe or mode is invalid
    """
    if not _is_safe_url(url):
        raise RuntimeError(f'Unsafe URL blocked: {url}')
    if mode not in VALID_MODES:
        raise RuntimeError(f'Invalid mode: {mode!r}. Must be one of: {", ".join(sorted(VALID_MODES))}')
    print(f'Snapshotting: {url} (mode={mode})', file=sys.stderr)
    result = await _capture(url, mode=mode)
    result['mode'] = mode
    return result

async def run_async(main_func, *args, **kwargs):
    return await main_func(*args, **kwargs)

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Web search via Opera CDP')
    parser.add_argument('action', choices=['search', 'extract', 'snapshot'], help='Action to perform')
    parser.add_argument('target', help='Query or URL')
    parser.add_argument('--num', type=int, default=10, help='Number of results')
    parser.add_argument('--mode', choices=['act', 'browse', 'navigate', 'full'], default='browse', help='Snapshot mode (default: browse)')
    args = parser.parse_args()
    tmp = os.environ.get('TEMP', 'C:\Windows\Temp')
    tmpfile = os.path.join(tmp, '_web_search_result.json')
    try:
        if args.action == 'search':
            results = asyncio.run(search(args.target, args.num))
        elif args.action == 'extract':
            results = asyncio.run(extract_url(args.target))
        elif args.action == 'snapshot':
            results = asyncio.run(snapshot(args.target, mode=args.mode))
        with open(tmpfile, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        with open(tmpfile, 'r', encoding='utf-8') as f:
            content = f.read()
        sys.stdout.buffer.write(content.encode('utf-8'))
        sys.stdout.buffer.write(b'\n')
    finally:
        os.remove(tmpfile) if os.path.exists(tmpfile) else None

if __name__ == '__main__':
    main()
