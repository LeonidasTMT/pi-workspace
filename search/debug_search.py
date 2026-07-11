"""Debug web_search.search() step by step."""
import sys, json, asyncio, websockets, urllib.parse, urllib.request
sys.path.insert(0, '.')

# Patch search to add debug output
import web_search

original_search = web_search.search

async def search_debug(query, num_results=10):
    print(f'Searching: {query}', file=sys.stderr)
    tab_ws, tab_id = await web_search.create_new_tab()
    print(f"New tab WS: {tab_ws}, ID: {tab_id}", file=sys.stderr)
    try:
        async with websockets.connect(tab_ws) as ws:
            print(">>> Navigating to Google...", file=sys.stderr)
            await web_search.send_cmd(ws, 'Page.navigate', {
                'url': f'https://www.google.com/search?q={urllib.parse.quote_plus(query)}'
            })
            print(">>> Waiting for network idle...", file=sys.stderr)
            await web_search.wait_for_network_idle(ws, timeout=10)
            print(">>> Dismissing consent...", file=sys.stderr)
            await web_search.dismiss_consent(ws)

            # Get title
            resp = await web_search.send_cmd(ws, 'Runtime.evaluate', {'expression': 'document.title'})
            title = resp['result']['result']['value']
            print(f"Page title: {title}", file=sys.stderr)

            # Get innerText snippet
            resp = await web_search.send_cmd(ws, 'Runtime.evaluate', {'expression': '(document.body.innerText||"").substring(0,500)'})
            text = resp['result']['result']['value']
            print(f"innerText snippet: {text[:300]}", file=sys.stderr)

            # Check h3 elements
            resp = await web_search.send_cmd(ws, 'Runtime.evaluate', {
                'expression': """(() => {
                    const h3s = document.querySelectorAll('h3');
                    const items = [];
                    for (const h3 of h3s) {
                        items.push({
                            text: h3.textContent.substring(0, 80),
                            parentClass: h3.parentElement?.className || 'null',
                            parentTag: h3.parentElement?.tagName || 'null',
                        });
                        if (items.length >= 5) break;
                    }
                    return JSON.stringify({count: h3s.length, items: items});
                })()"""
            })
            val = resp['result']['result']
            if val['type'] == 'string':
                data = json.loads(val['value'])
                print(f"\nh3 count: {data['count']}", file=sys.stderr)
                for item in data.get('items', []):
                    print(f"  text: {item['text']}", file=sys.stderr)
                    print(f"  parentClass: {item['parentClass']}", file=sys.stderr)
            else:
                print(f"h3 check failed: {val}", file=sys.stderr)

            # Try ARIA extraction
            print("\n>>> Trying ARIA tree...", file=sys.stderr)
            aria_tree = await web_search.extract_aria_tree(ws)
            if aria_tree:
                print(f"ARIA tree: role={aria_tree.get('role')}, children={len(aria_tree.get('children', []))}", file=sys.stderr)
                pruned = await web_search.prune_aria_tree(ws, aria_tree, mode='act')
                print(f"Pruned tree nodes: {len(pruned) if pruned else 0}", file=sys.stderr)
                results = await web_search.aria_search_results(ws, pruned, num_results)
                print(f"ARIA search results: {len(results)}", file=sys.stderr)
                if results:
                    print(f"Results: {results[:3]}", file=sys.stderr)
            else:
                print("ARIA tree is None", file=sys.stderr)

    finally:
        web_search.close_tab(tab_id)

asyncio.run(search_debug('DOX agent 0', 5))
