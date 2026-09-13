// cdp-reload.mjs — one-shot CDP: force a fresh navigation of an existing tab and fingerprint its DOM.
// Usage: node tools/cdp-reload.mjs [url-substring]   (default: review.html)
// Requires Chrome with remote debugging on 127.0.0.1:9222 (/json endpoint).
// Single clean attempt by design (repeated failed CDP attach can wedge a target).
const SUB = process.argv[2] || "review.html";

const watchdog = setTimeout(() => { console.error("TIMEOUT overall"); process.exit(3); }, 25000);

let res;
try { res = await fetch("http://127.0.0.1:9222/json"); } catch (e) {
  console.error("CDP HTTP unreachable:", e.message); process.exit(2);
}
const targets = await res.json();
const t = targets.find(x => x.type === "page" && (x.url || "").includes(SUB));
if (!t) { console.error("NO TARGET matching", SUB, "among", targets.length, "targets"); process.exit(2); }

const ws = new WebSocket(t.webSocketDebuggerUrl);
let idc = 0; const pending = {}; let loaded = false; let loadTimer = null;
function send(method, params) {
  return new Promise((ok, err) => {
    const id = ++idc;
    pending[id] = ok;
    ws.send(JSON.stringify(params ? { id, method, params } : { id, method }));
  });
}
ws.onmessage = (m) => {
  let msg; try { msg = JSON.parse(m.data.toString()); } catch { return; }
  if (msg.id && pending[msg.id]) { const p = pending[msg.id]; delete pending[msg.id]; p(msg); return; }
  if (msg.method === "Page.loadEventFired") loaded = true;
};

try {
  await new Promise((ok, err) => { ws.onopen = ok; ws.onerror = () => err(new Error("ws error")); });
  const waitLoaded = (ms) => new Promise(r => { loadTimer = setTimeout(() => r(false), ms); const iv = setInterval(() => { if (loaded) { clearInterval(iv); clearTimeout(loadTimer); r(true); } }, 100); });

  await send("Network.enable");
  await send("Page.enable");
  await send("Page.navigate", { url: t.url });
  const gotLoad = await waitLoaded(8000);
  if (!gotLoad) console.error("(warn) no Page.loadEventFired within 8s — continuing");
  await new Promise(r => setTimeout(r, 400));

  if (process.argv[3]) {
    const pre = await send("Runtime.evaluate", { expression: process.argv[3], returnByValue: true });
    if (pre.result && pre.result.exceptionDetails) console.error("(warn) pre-eval exception:", JSON.stringify(pre.result.exceptionDetails));
  }

  const FINGERPRINT = "JSON.stringify({t:document.title,h:location.href," +
    "cols:Array.prototype.map.call(document.querySelectorAll('#cols .bcol .grp'),function(e){return e.textContent})," +
    "nitems:document.querySelectorAll('.item').length,nscenes:(typeof DATA!=='undefined')?DATA.length:-1})";
  const r = await send("Runtime.evaluate", { expression: FINGERPRINT, returnByValue: true });
  if (r.result && r.result.exceptionDetails) { console.error("EVAL EXCEPTION:", JSON.stringify(r.result.exceptionDetails)); process.exit(4); }
  const out = r.result && r.result.result ? r.result.result.value : null;
  if (!out) { console.error("NO VALUE", JSON.stringify(r).slice(0, 300)); process.exit(5); }
  const fp = JSON.parse(out);
  console.log(JSON.stringify(fp, null, 1));
  clearTimeout(watchdog);
  ws.close();
  process.exit(fp.cols && fp.cols.length ? 0 : 6);
} catch (e) {
  console.error("FAIL:", e.message); process.exit(1);
}
