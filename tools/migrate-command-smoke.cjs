/* Smoke test for ~/.pi/agent/extensions/session-migrate.ts (the /migrate command). */
const path = require("path");
const os = require("os");
const fs = require("fs");
const { createRequire } = require("module");

const piRoot = "C:/Users/User/AppData/Roaming/npm/node_modules/@earendil-works/pi-coding-agent";
let failures = 0;
function check(name, cond, extra) {
	if (cond) console.log("PASS", name);
	else { failures++; console.log("FAIL", name, extra === undefined ? "" : "→ got: " + extra); }
}

(async () => {
	const piReq = createRequire(path.join(piRoot, "index.js")); // mirrors pi's loader root (aliases unused here)
	void piReq;
	const { createJiti } = require(path.join(piRoot, "node_modules", "jiti"));
	const jiti = createJiti(__filename, {});
	const extPath = path.join(os.homedir(), ".pi", "agent", "extensions", "session-migrate.ts");
	const ext = (await jiti.import(extPath)).default;

	// ---- stub ExtensionAPI: capture the /migrate command definition
	let cmdDef = null;
	ext({ registerCommand: (name, def) => { if (name === "migrate") cmdDef = def; } });
	check("registers /migrate", !!cmdDef);

	const notes = []; // [level, text]
	const ctx = { ui: { notify: (msg, level) => notes.push([level, msg]) }, mode: "tui", hasUI: false };

	// ---- pick a tiny session file as throwaway source (source is never modified by the tool)
	const sessDir = path.join(os.homedir(), ".pi", "agent", "sessions");
	let src = null;
	(function walk(d) {
		let ents; try { ents = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
		for (const e of ents.sort((a, b) => a.name.localeCompare(b.name))) {
			if (src) return;
			const p = path.join(d, e.name);
			if (e.isDirectory()) walk(p);
			else if (/\.jsonl$/.test(e.name)) {
				const sz = fs.statSync(p).size;
				// space-free path: slash args are whitespace-split, so smoke the happy path
				if (sz < 10_000 && !p.includes(" ")) { src = p; return; }
			}
		}
	})(sessDir);
	check("found tiny source session", !!src, "no space-free .jsonl under 10KB in sessions dir");

	if (!cmdDef || !src) process.exit(1);

	await cmdDef.handler(`${src} --name SMOKE-MIGRATE`, ctx);
	const info = notes.find(([lvl]) => lvl === "info")?.[1] ?? "";
	check("notify shows success", /✓ migrated as "SMOKE-MIGRATE"/.test(info), info);

	const m = info.match(/pi --session "(.*)"/);
	const newPath = m ? m[1] : "";
	check("new session file exists", !!newPath && fs.existsSync(newPath), newPath);

	// cleanup: remove exactly the file we created (never by glob)
	if (newPath && fs.existsSync(newPath)) { fs.unlinkSync(newPath); check("cleanup removed throwaway", !fs.existsSync(newPath)); }

	process.exit(failures ? 1 : 0);
})().catch((e) => { console.error("smoke crashed:", e && e.message); process.exit(2); });
