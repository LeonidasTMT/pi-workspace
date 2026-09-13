// cdp-eval.mjs — one-shot CDP: attach to an existing tab and evaluate an expression.
// Usage: node tools/cdp-eval.mjs <url-substring> <expression> [timeout-ms]
// Prints the evaluated value (returnByValue) as JSON on stdout. No navigation, no mutation
// of page state beyond what the expression itself does — keep expressions read-only unless
// you intend to mutate and restore inside the same expression.
const SUB = process.argv[2];
const EXPR = process.argv[3];
if (!SUB || !EXPR) { console.error("usage: cdp-eval.mjs <url-substring> <expression>"); process.exit(2); }

const watchdog = setTimeout(() => { console.error("TIMEOUT overall"); process.exit(3); }, 15000);

let res;
try { res = await fetch("http://127.0.0.1:9222/json"); } catch (e) {
  console.error("CDP HTTP unreachable:", e.message); process.exit(2);
}
const targets = await res.json();
const t = targets.find(x => x.type === "page" && (x.url || "").includes(SUB));
if (!t) { console.error("NO TARGET matching", SUB, "among", targets.length, "targets"); process.exit(2); }

const ws = new WebSocket(t.webSocketDebuggerUrl);
let idc = 0; const pending = {};
function send(method, params) {
  return new Promise((ok) => {
    const id = ++idc;
    pending[id] = ok;
    ws.send(JSON.stringify({ id, method, params }));
  });
}
ws.onmessage = (m) => {
  let msg; try { msg = JSON.parse(m.data.toString()); } catch { return; }
  if (msg.id && pending[msg.id]) { const p = pending[msg.id]; delete pending[msg.id]; p(msg); }
};

try {
  await new Promise((ok, err) => { ws.onopen = ok; ws.onerror = () => err(new Error("ws error")); });
  const r = await send("Runtime.evaluate", { expression: EXPR, returnByValue: true });
  if (r.result && r.result.exceptionDetails) { console.error("EVAL EXCEPTION:", JSON.stringify(r.result.exceptionDetails)); process.exit(4); }
  const out = r.result && r.result.result ? r.result.result.value : null;
  if (out === undefined || out === null) { console.error("NO VALUE", JSON.stringify(r).slice(0, 300)); process.exit(5); }
  console.log(typeof out === "string" ? out : JSON.stringify(out, null, 1));
  clearTimeout(watchdog);
  ws.close();
  process.exit(0);
} catch (e) {
  console.error("FAIL:", e.message); process.exit(1);
}
