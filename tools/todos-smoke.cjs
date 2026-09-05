/* Smoke test for ~/.pi/agent/extensions/todos.ts */
const path = require("path");
const os = require("os");
const { createRequire } = require("module");

const piRoot = "C:/Users/User/AppData/Roaming/npm/node_modules/@earendil-works/pi-coding-agent";
let failures = 0;
function check(name, cond, extra) {
	if (cond) console.log("PASS", name);
	else { failures++; console.log("FAIL", name, extra === undefined ? "" : "→ got: " + extra); }
}

const extPath = path.join(os.homedir(), ".pi", "agent", "extensions", "todos.ts");

(async () => {
	// ---- mirror pi's loader alias map (dist/core/extensions/loader.js getAliases) ----
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
	const ext = (await jiti.import(extPath)).default;

	// ---- stub ExtensionAPI ----
	const entries = []; // pi.appendEntry log
	let toolDef = null;
	let commandDef = null;
	const listeners = {};
	const stubPi = {
		registerTool: (t) => { toolDef = t; },
		registerCommand: (_name, def) => { commandDef = def; },
		on: (ev, fn) => { (listeners[ev] ||= []).push(fn); },
		appendEntry: (customType, data) => entries.push({ customType, data }),
	};

	ext(stubPi);
	check("tool registered", toolDef && toolDef.name === "todo");
	check("command registered", commandDef !== null);
	check("session_start listener present", Array.isArray(listeners["session_start"]) && listeners["session_start"].length > 0);

	const run = (params) =>
		toolDef.execute("call-1", params, new AbortController().signal, () => {}, {});

	// 1. plan: top-level + sub-goals
	if (process.env.DEBUG) console.log("dbg first add:");
	let r = await run({ action: "add", text: "Implement feature X" });
	check("add top-level #1", /added #1/.test(r.content[0].text));
	r = await run({ action: "add", text: "design API", parentId: 1 });
	check("add sub under #1 → #2", /added #2 under #1/.test(r.content[0].text));
	await run({ action: "add", text: "implement endpoints", parentId: 1 }); // #3
	await run({ action: "add", text: "write tests", parentId: 1 });         // #4
	r = await run({ action: "add", text: "Ship release" });                 // #5 top-level

	check("details snapshot has items+nextId", Array.isArray(r.details.items) && r.details.nextId === 6);
	const order = r.details.items.map((g) => g.id).join(",");
	check("children glued after parent (1,2,3,4,5)", order === "1,2,3,4,5", `order=${order} text=${r.content[0].text.replace(/\n/g, " | ")}`);

	// 2. status + single-doing enforcement
	await run({ action: "update", id: 2, status: "doing" });
	r = await run({ action: "update", id: 3, status: "doing" });
	const s2 = r.details.items.find((g) => g.id === 2).status;
	const s3 = r.details.items.find((g) => g.id === 3).status;
	check("single-doing: #2 back to todo", s2 === "todo");
	check("single-doing: #3 is doing", s3 === "doing");

	// 3. reprioritize within level (siblings)
	r = await run({ action: "move", id: 4, dir: "up" }); // one up → position 2
	check("sibling move msg", /moved #4 to priority 2\/3/.test(r.content[0].text), r.content[0].text.split("\n")[0]);
	const idsNow = r.details.items.map((g) => g.id).join(",");
	check("sibling order swapped (1,2,4,3,5)", idsNow === "1,2,4,3,5");

	// 4. top-level move with children glued (the old bug)
	r = await run({ action: "move", id: 5, dir: "top" }); // Ship release first
	const afterTopMove = r.details.items.map((g) => g.id).join(",");
	check("top-level move keeps children glued (5,1,2,4,3)", afterTopMove === "5,1,2,4,3");

	// 5. list renders board text
	r = await run({ action: "list" });
	check("list shows both goals", /Implement feature X/.test(r.content[0].text) && /Ship release/.test(r.content[0].text));

	// 6. remove sub-goal, then top-level cascades to children
	await run({ action: "remove", id: 2 }); // design API (child of #1)
	r = await run({ action: "remove", id: 1 }); // removes #1 + remaining children (#4,#3)
	check("cascade remove msg", /removed #1 \+ 2 sub-goal\(s\)/.test(r.content[0].text));
	const idsNow2 = r.details.items.map((g) => g.id).join(",");
	check("only #5 remains", idsNow2 === "5");

	// 7. nextId continues after removes (no reuse)
	await run({ action: "add", text: "Docs site" }); // consumes #6
	const rAdd = await run({ action: "list" });
	check("nextId continues after removes (→7)", rAdd.details.nextId === 7);

	// 8. command handler quick-adds (ui.notify stub, no board)
	const themeStub = { fg: (_c, s) => s, bold: (s) => s };
	const notices = [];
	const fakeCtx = {
		mode: "tui", hasUI: true,
		ui: {
			notify: (m, kind) => notices.push([kind, m]),
			setWidget: () => {}, setStatus: () => {},
			custom: async () => { throw new Error("board should not open with args"); },
			theme: themeStub,
		},
		sessionManager: { getBranch: () => [] },
	};
	await commandDef.handler("add Quick task", fakeCtx); // #7
	check("/todos add works + notifies", /added #7/.test(notices.at(-1)[1]));

	// 8b. demote/promote keeps children glued (off-by-one regression)
	let rp = await run({ action: "add", text: "child C", parentId: 5 }); // #8 under #5
	check("new child glues after parent (5,8,6,7)", rp.details.items.map((g) => g.id).join(",") === "5,8,6,7");
	rp = await run({ action: "reparent", id: 8 }); // promote to top-level → end
	check("promote lands after last block (5,6,7,8)", rp.details.items.map((g) => g.id).join(",") === "5,6,7,8");
	rp = await run({ action: "reparent", id: 8, parentId: 5 }); // demote back under #5
	check("demote glues right after parent (5,8,6,7)", rp.details.items.map((g) => g.id).join(",") === "5,8,6,7");

	// 9. reconstruction via session_start: last write wins (tool details then custom entries)
	const snapA = rAdd.details; // snapshot before diverging
	await commandDef.handler("add Later task", fakeCtx);   // #8, persisted as custom entry
	const ctx2 = {
		hasUI: true,
		ui: { notify: () => {}, setWidget: () => {}, setStatus: () => {}, theme: themeStub },
		sessionManager: {
			getBranch: () => [
				{ type: "message", message: { role: "toolResult", toolName: "todo", details: snapA } },
				...entries.map((e) => ({ type: "custom", customType: e.customType, data: e.data })),
			],
		},
	};
	await listeners["session_start"][0]({ reason: "resume" }, ctx2);
	const snapB = (await run({ action: "list" })).details;
	check("reconstruct last-write-wins", JSON.stringify(snapB) === JSON.stringify(entries.at(-1).data));

	// 11. interactive board component: render + keystrokes end-to-end
	let comp = null;
	let closed = false;
	const fakeTui = { requestRender: () => {} };
	const ctxBoard = {
		mode: "tui", hasUI: true,
		ui: {
			notify: (m, k) => notices.push([k, m]),
			setWidget: () => {}, setStatus: () => {},
			theme: themeStub,
			custom: async (factory) => {
				comp = factory(fakeTui, themeStub, null, () => { closed = true; });
			},
		},
		sessionManager: { getBranch: () => [] },
	};
	await commandDef.handler("", ctxBoard); // no args → opens board
	check("board component created", comp !== null && typeof comp.render === "function");
	let lines = comp.render(80);
	check("board renders lines", Array.isArray(lines) && lines.length >= 2, `lines=${JSON.stringify(lines?.length)}`);
	const beforeCount = (await run({ action: "list" })).details.items.length;
	// type a new goal on the empty-selection row: 'a' then text then Enter
	comp.handleInput("a");
	for (const ch of ["U", "I", "-", "g", "o", "a", "l"]) comp.handleInput(ch);
	lines = comp.render(80); // input mode shows buffer
	check("input mode renders buffer", lines.some((l) => l.includes("UI-goal") || l.includes("U")));
	comp.handleInput("\r"); // Enter commits
	const afterCount = (await run({ action: "list" })).details.items.length;
	check("board add via keystrokes", afterCount === beforeCount + 1, `before=${beforeCount} after=${afterCount}`);
	lines = comp.render(80);
	check("flash shows added msg", lines.some((l) => l.includes("added")));
	// move selection down a couple rows and quit
	comp.handleInput("j");
	comp.handleInput("j");
	comp.handleInput("q");
	check("board closes on q", closed === true);

	console.log(failures ? `\n${failures} FAILURES` : "\nALL PASS");
	process.exit(failures ? 1 : 0);
})().catch((e) => { console.error("HARNESS ERROR", e); process.exit(2); });
