import asyncio
import websockets
import json
import urllib.request
import urllib.parse
import sys
import os
import time

OPERA_PORT = 9222
OPERA_BASE = f'http://127.0.0.1:{OPERA_PORT}'

def ensure_opera():
    """Ensure Opera is running on our port."""
    try:
        urllib.request.urlopen(f'{OPERA_BASE}/json/version')
        return
    except Exception:
        print(f'Opera not found on port {OPERA_PORT}. Launch with --remote-debugging-port={OPERA_PORT}', file=sys.stderr)
        sys.exit(1)

async def create_new_tab(url='about:blank'):
    """Create a new browser tab via Target.createTarget."""
    ensure_opera()
    
    tabs = json.loads(urllib.request.urlopen(f'{OPERA_BASE}/json').read())
    
    for tab in tabs:
        if tab.get('type') == 'page' and tab.get('url', '').startswith('http'):
            controller_ws = tab['webSocketDebuggerUrl']
            break
    else:
        raise RuntimeError('No available controller tab')
    
    # Connect and create new target
    async with websockets.connect(controller_ws) as ws:
        req = {'id': 1, 'method': 'Target.createTarget', 'params': {'url': url}}
        await ws.send(json.dumps(req))
        # Drain responses until we get the targetId
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
    
    # Find the new tab's WebSocket URL
    for _ in range(10):
        tabs = json.loads(urllib.request.urlopen(f'{OPERA_BASE}/json').read())
        for tab in tabs:
            if tab['id'] == new_tab_id:
                return tab['webSocketDebuggerUrl'], new_tab_id
        await asyncio.sleep(0.5)
    
    raise RuntimeError(f'Could not find newly created tab {new_tab_id}')

def close_tab(tab_id):
    """Close our tab."""
    try:
        urllib.request.urlopen(f'{OPERA_BASE}/json/close/{tab_id}')
    except Exception:
        pass

async def send_cmd(ws, method, params=None, timeout=15):
    """Send a CDP command and get the response."""
    req = {'id': 1, 'method': method, 'params': params or {}}
    await ws.send(json.dumps(req))
    for _ in range(int(timeout * 2)):
        try:
            resp = await asyncio.wait_for(ws.recv(), 5)
        except asyncio.TimeoutError:
            continue
        parsed = json.loads(resp)
        if parsed.get('id') == 1:
            return parsed
        await asyncio.sleep(0.1)
    raise TimeoutError(f'Timeout waiting for CDP response')

EXTRACT_JS = r"""
(() => {
    const h3s = document.querySelectorAll('h3');
    const items = [];
    for (const h3 of h3s) {
        const parent = h3.parentElement;
        if (parent?.className === 'zReHs') {
            const grandparent = parent.parentElement;
            const cite = grandparent?.querySelector('cite');
            const link = grandparent?.querySelector('a');
            items.push({
                title: h3.textContent.trim(),
                cite: cite ? cite.textContent.trim() : '',
                link: link ? link.href : '',
            });
        }
    }
    return JSON.stringify(items.slice(0, __NUM__));
})()
"""

async def search(query, num_results=10):
    """Search Google in a fresh tab."""
    print(f'Searching: {query}', file=sys.stderr)
    tab_ws, tab_id = await create_new_tab()
    
    try:
        async with websockets.connect(tab_ws) as ws:
            await send_cmd(ws, 'Page.navigate', {
                'url': f'https://www.google.com/search?q={urllib.parse.quote_plus(query)}'
            })
            await asyncio.sleep(4)
            
            resp = await send_cmd(ws, 'Runtime.evaluate', {
                'expression': EXTRACT_JS.replace('__NUM__', str(num_results))
            })
            
            result = resp['result']['result']
            if result['type'] == 'string':
                return json.loads(result['value'])
            return []
    finally:
        close_tab(tab_id)

async def extract_url(url):
    """Extract content from a URL in a fresh tab."""
    print(f'Extracting: {url}', file=sys.stderr)
    tab_ws, tab_id = await create_new_tab()
    
    try:
        async with websockets.connect(tab_ws) as ws:
            await send_cmd(ws, 'Page.navigate', {'url': url})
            await asyncio.sleep(3)
            
            resp = await send_cmd(ws, 'Runtime.evaluate', {'expression': 'document.body.innerText'})
            content = resp['result']['result']['value']
            
            resp = await send_cmd(ws, 'Runtime.evaluate', {'expression': 'document.title'})
            title = resp['result']['result']['value']
            
            return {'title': title, 'content': content[:5000]}
    finally:
        close_tab(tab_id)

async def run_async(main_func, *args, **kwargs):
    """Run async function and capture output."""
    return await main_func(*args, **kwargs)

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Web search via Opera CDP')
    parser.add_argument('action', choices=['search', 'extract'], help='Action to perform')
    parser.add_argument('target', help='Query or URL')
    parser.add_argument('--num', type=int, default=10, help='Number of results')
    
    args = parser.parse_args()
    
    tmp = os.environ.get('TEMP', 'C:\\Windows\\Temp')
    tmpfile = os.path.join(tmp, '_web_search_result.json')
    
    try:
        if args.action == 'search':
            results = asyncio.run(search(args.target, args.num))
        elif args.action == 'extract':
            results = asyncio.run(extract_url(args.target))
        
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
