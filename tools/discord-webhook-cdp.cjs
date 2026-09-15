#!/usr/bin/env node
// Creates pi-done-ping guild + #alerts channel + webhook by executing API calls INSIDE an already-logged-in
// discord.com tab via raw CDP WebSocket (no new tabs, no puppeteer page APIs). Prints: WEBHOOK_RESULT <json>
const http = require("http");

const GUILD_NAME = "pi-done-ping";
const CHANNEL_NAME = "alerts";
const WEBHOOK_NAME = "pi-done-ping";

function httpJson(path) {
  return new Promise((resolve, reject) => {
    const req = http.get({ host: "127.0.0.1", port: 9222, path }, (res) => {
      let d = ""; res.on("data", (c) => (d += c)); res.on("end", () => resolve(d));
    });
    req.on("error", reject); req.setTimeout(5000, () => req.destroy(new Error("timeout")));
  });
}

function fail(msg, code) { console.error(JSON.stringify({ error: msg })); process.exit(code); }

const EXPR = `(async () => {
  const j = (r) => r.json().catch(() => null);
  let me = null;
  for (let i = 0; i < 4; i++) {
    try { const r = await fetch("/api/v10/users/@me"); me = { s: r.status, b: await j(r) }; if (me.s === 200) break; } catch (e) {}
    await new Promise((r) => setTimeout(r, 2500));
  }
  if (!me || me.s !== 200) return "ERR_AUTH " + (me && me.s);

  let gid = null;
  const created = await (async () => { try { const r = await fetch("/api/v10/guilds", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: ${JSON.stringify(GUILD_NAME)} }) }); return { s: r.status, b: await j(r) }; } catch (e) { return { err: String(e) }; } })();
  if (created && created.s === 201 && created.b && created.b.id) gid = String(created.b.id);
  else {
    const list = await (async () => { try { const r = await fetch("/api/v10/users/@me/guilds"); return { s: r.status, b: await j(r) }; } catch (e) { return { err: String(e) }; } })();
    if (list && Array.isArray(list.b)) { const g = list.b.find((x) => x.name === ${JSON.stringify(GUILD_NAME)}); if (g) gid = String(g.id); }
  }
  if (!gid) return "ERR_GUILD " + JSON.stringify(created || {});

  let cid = null;
  const chans = await (async () => { try { const r = await fetch("/api/v10/guilds/" + gid + "/channels"); return { s: r.status, b: await j(r) }; } catch (e) { return { err: String(e) }; } })();
  if (chans && Array.isArray(chans.b)) { const c = chans.b.find((x) => x.type === 0); if (c) cid = String(c.id); }
  if (!cid) {
    const ch = await (async () => { try { const r = await fetch("/api/v10/guilds/" + gid + "/channels", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: ${JSON.stringify(CHANNEL_NAME)}, type: 0 }) }); return { s: r.status, b: await j(r) }; } catch (e) { return { err: String(e) }; } })();
    if (!ch || ch.s !== 201 || !ch.b || !ch.b.id) return "ERR_CHANNEL " + JSON.stringify(ch);
    cid = String(ch.b.id);
  }

  const wh = await (async () => { try { const r = await fetch("/api/v10/guilds/" + gid + "/webhooks", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ channel_id: cid, name: ${JSON.stringify(WEBHOOK_NAME)} }) }); return { s: r.status, b: await j(r) }; } catch (e) { return { err: String(e) }; } })();
  if (!wh || wh.s !== 200 || !wh.b || !wh.b.url) return "ERR_WEBHOOK " + JSON.stringify(wh);
  return JSON.stringify({ guildId: gid, channelId: cid, username: me && me.b && me.b.username, webhookUrl: wh.b.url });
})()`;

(async () => {
  const listRaw = await httpJson("/json/list").catch((e) => fail("cdp_http_failed " + e.message, 1));
  let targets; try { targets = JSON.parse(listRaw); } catch (e) { fail("cdp_json_parse_failed", 2); }
  const pageT = targets.find((t) => t.type === "page" && /^https:\/\/discord\.com\/channels\//.test(t.url || ""));
  if (!pageT) fail("no_logged_in_discord_tab — open discord.com in Chrome first", 3);

  // Raw CDP websocket to the existing tab
  const ws = new (require("C:/Users/User/.pi/agent/extensions/done-ping/node_modules/ws"))(pageT.webSocketDebuggerUrl, { perMessageDeflate: false });
  let nextId = 1;
  const pending = new Map();
  ws.on("message", (buf) => {
    let m; try { m = JSON.parse(buf.toString()); } catch (e) { return; }
    if (m.id && pending.has(m.id)) { const { resolve, reject } = pending.get(m.id); pending.delete(m.id); m.error ? reject(new Error(m.error.message || "cdp_error")) : resolve(m.result); }
  });
  const send = (method, params) => new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });

  await new Promise((r) => ws.on("open", r)).catch((e) => fail("ws_connect_failed " + e.message, 4));
  // wait for the tab to be ready (document idle-ish) then evaluate
  const t0 = Date.now();
  while (Date.now() - t0 < 20000) {
    try { await send("Runtime.evaluate", { expression: "1+1", returnByValue: true }); break; } catch (e) { await new Promise((r) => setTimeout(r, 500)); }
  }

  const res = await Promise.race([
    send("Runtime.evaluate", { expression: EXPR, awaitPromise: true, returnByValue: true, timeout: 90000 }),
    new Promise((_, rej) => setTimeout(() => rej(new Error("evaluate_timeout")), 120000)),
  ]).catch((e) => fail("cdp_evaluate_failed " + e.message, 5));

  const val = res && res.result ? res.result.value : undefined;
  if (typeof val === "string" && val.startsWith("ERR_")) { ws.close(); fail(val, 6); }
  console.log("WEBHOOK_RESULT " + val);
  ws.close(); process.exit(0);
})().catch((e) => fail("unexpected " + (e.message || String(e)), 7));
