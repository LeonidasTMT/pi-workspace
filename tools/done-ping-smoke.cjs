/* Smoke test for ~/.pi/agent/extensions/done-ping/index.ts (offline: no real alerts fired) */
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

const extPath = path.join(os.homedir(), ".pi", "agent", "extensions", "done-ping", "index.ts");
const stateFile = path.join(os.homedir(), ".pi", "agent", "extensions", "done-ping.json");

(async () => {
	const piReq = createRequire(path.join(piRoot, "index.js"));
	const nm = (p) => path.join(piRoot, "node_modules", p);
	const alias = {
		typebox: piReq.resolve("typebox"),
		"typebox/compile": piReq.resolve("typebox/compile"),
		"typebox/value": piReq.resolve("typebox/value"),
		"@earendil-works/pi-tui": require.resolve(nm("@earendil-works/pi-tui")),
		"@earendil-works/pi-ai": path.join(nm("@earendil-works/pi-ai/dist/compat.js")),
	};
	const { createJiti } = require(path.join(piRoot, "node_modules", "jiti"));
	const jiti = createJiti(__filename, { alias });

	let ext;
	try { ext = (await jiti.import(extPath)).default; } catch (e) { console.log("FAIL extension loads →", e.message); process.exit(1); }
	check("extension module loads", typeof ext === "function");

	// preserve + disable real state so no actual alerts fire during the test
	const hadState = fs.existsSync(stateFile);
	const prevState = hadState ? JSON.parse(fs.readFileSync(stateFile, "utf8")) : null;
	fs.writeFileSync(stateFile, JSON.stringify({ enabled: false }, null, 2));

	try {
		const listeners = {};
		let commandDef = null;
		ext({ on: (ev, fn) => { (listeners[ev] ||= []).push(fn); }, registerCommand: (_n, def) => { commandDef = def; } });
		check("agent_start listener", Array.isArray(listeners["agent_start"]) && listeners["agent_start"].length > 0);
		check("agent_settled listener", Array.isArray(listeners["agent_settled"]) && listeners["agent_settled"].length > 0);
		check("command registered", commandDef !== null);

		const notified = [];
		const ctxStub = { cwd: "C:\\Users\\User\\Documents\\GitHub\\pi-workspace", ui: { notify: (m, k) => notified.push([k, m]) } };

		let threw = false;
		try { await listeners["agent_start"][0]({}, ctxStub); await listeners["agent_settled"][0]({}, ctxStub); } catch (e) { threw = true; console.log("threw:", e.message); }
		check("disabled start→settled does not throw", !threw);

		notified.length = 0;
		await commandDef.handler("", ctxStub);
		const statusMsg = notified.map((n) => n[1]).join("\n");
		check("status says OFF (test state)", /done-ping: OFF/.test(statusMsg), statusMsg);
		check("status shows channel line", /kde=.*· toast=powershell · discord=/.test(statusMsg), statusMsg);

		notified.length = 0;
		await commandDef.handler("on", ctxStub);
		check("on toggles", /done-ping: ON/.test(notified.map((n) => n[1]).join("\n")));
		notified.length = 0;
		await commandDef.handler("off", ctxStub);
		check("off toggles back", /done-ping: OFF/.test(notified.map((n) => n[1]).join("\n")));

		notified.length = 0;
		await commandDef.handler("discord not-a-url", ctxStub);
		check("discord rejects bad url", /not a valid/i.test(notified.map((n) => n[1]).join("\n")));
	} finally {
		if (hadState && prevState) fs.writeFileSync(stateFile, JSON.stringify(prevState, null, 2));
		else if (!hadState) try { fs.unlinkSync(stateFile); } catch { /* ignore */ }
	}

	console.log(failures === 0 ? "ALL PASS" : `${failures} FAILURES`);
	process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error("smoke crashed:", e); process.exit(1); });
