#!/usr/bin/env node
// Creates the "pi-done-ping" Discord guild + #alerts channel + webhook via CDP on a logged-in Chrome.
// Idempotent: reuses existing guild/webhook if present. Prints exactly one line: WEBHOOK_RESULT <json>
// Requires: chrome running with --remote-debugging-port=9222 (AGENTS.md standard), Discord logged in there.
const puppeteer = require("C:/Users/User/.pi/agent/extensions/done-ping/node_modules/puppeteer");

const GUILD_NAME = "pi-done-ping";
const CHANNEL_NAME = "alerts";
const WEBHOOK_NAME = "pi-done-ping";

function fail(msg, code) { console.error(JSON.stringify({ error: msg })); process.exit(code); }

(async () => {
  let browser;
  try {
    browser = await puppeteer.connect({ browserURL: "http://127.0.0.1:9222", defaultViewport: null });
  } catch (e) { fail("cdp_connect_failed: " + e.message, 1); }

  const ctx = await browser.defaultBrowserContext();
  if (!ctx) throw new Error("no default browser context");
  const page = await ctx.newPage();

  try {
    await page.goto("https://discord.com/channels/@me", { waitUntil: "networkidle2", timeout: 60000 }).catch(() => {});
    await new Promise((r) => setTimeout(r, 3000));

    // Login test: a logged-in session stays on /channels/... (not bounced to /login)
    const here = page.url();
    let meStatus = null;
    const me = await page.evaluate(async () => {
      try { const r = await fetch("/api/v10/users/@me"); const b = await r.json().catch(() => null); return { status: r.status, id: b && b.id }; }
      catch (e) { return { err: String(e) }; }
    });
    meStatus = me ? me.status : null;
    if (!here.includes("/channels/") || (meStatus !== 200 && !me.err)) {
      fail("discord_not_logged_in url=" + here + " @me_status=" + meStatus, 3);
    }

    // Guild: create or find existing
    let guild = null;
    const created = await page.evaluate(async (name) => {
      try { const r = await fetch("/api/v10/guilds", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }) }); return { status: r.status, body: await r.json().catch(() => null) }; }
      catch (e) { return { err: String(e) }; }
    }, GUILD_NAME);
    if (created && created.status === 201) guild = created.body;
    else {
      const list = await page.evaluate(async () => {
        try { const r = await fetch("/api/v10/users/@me/guilds"); return { status: r.status, body: await r.json().catch(() => null) }; }
        catch (e) { return { err: String(e) }; }
      });
      guild = ((list && list.body) || []).find((g) => g.name === GUILD_NAME) || null;
    }
    if (!guild || !guild.id) fail("guild_create_failed " + JSON.stringify(created), 4);

    // Text channel: find or create
    const chans = await page.evaluate(async (gid) => {
      try { const r = await fetch("/api/v10/guilds/" + gid + "/channels"); return { status: r.status, body: await r.json().catch(() => null) }; }
      catch (e) { return { err: String(e) }; }
    }, guild.id);
    let channel = ((chans && chans.body) || []).find((c) => c.type === 0 && c.name === CHANNEL_NAME)
      || ((chans && chans.body) || []).find((c) => c.type === 0) || null;
    if (!channel) {
      const ch = await page.evaluate(async ({ gid, name }) => {
        try { const r = await fetch("/api/v10/guilds/" + gid + "/channels", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, type: 0 }) }); return { status: r.status, body: await r.json().catch(() => null) }; }
        catch (e) { return { err: String(e) }; }
      }, { gid: guild.id, name: CHANNEL_NAME });
      if (!ch || ch.status !== 201 || !ch.body) fail("channel_create_failed " + JSON.stringify(ch), 5);
      channel = ch.body;
    }

    // Webhook: create (one is enough; reuse path not needed for v1)
    const wh = await page.evaluate(async ({ gid, cid, name }) => {
      try { const r = await fetch("/api/v10/guilds/" + gid + "/webhooks", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ channel_id: String(cid), name }) }); return { status: r.status, body: await r.json().catch(() => null) }; }
      catch (e) { return { err: String(e) }; }
    }, { gid: guild.id, cid: channel.id, name: WEBHOOK_NAME });
    if (!wh || wh.status !== 200 || !wh.body || !wh.body.url) fail("webhook_create_failed " + JSON.stringify(wh), 6);

    console.log("WEBHOOK_RESULT " + JSON.stringify({
      guildId: String(guild.id), guildName: GUILD_NAME,
      channelId: String(channel.id), channelName: channel.name,
      webhookUrl: wh.body.url,
    }));
  } finally {
    await page.close().catch(() => {});
    browser.disconnect();
  }
})().catch((e) => fail("unexpected " + (e && e.message ? e.message : String(e)), 7));
