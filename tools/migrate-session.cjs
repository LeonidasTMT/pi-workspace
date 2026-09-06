#!/usr/bin/env node
/**
 * migrate-session.cjs — move an old pi conversation into a new chat.
 *
 * Why: extension tools (todo board etc.) bind at process start; an already-running or
 * older conversation cannot have newly-added tools hot-bound in place, and injected
 * messages are model text, not command dispatch. The working path is to migrate the
 * conversation into a NEW session file and open that in a FRESH pi process — where every
 * extension/tool present on disk at start binds normally, and AGENTS.md Plan Mode resume
 * rules apply to carried-over pending instructions.
 *
 * What it does (source file is NEVER modified):
 *   1. Clones the source session byte-for-byte: full entry tree + all custom state
 *      (extension entries such as todos-state ride along untouched).
 *   2. Writes a fresh header: new uuid/timestamp, original cwd, parentSession = source path
 *      (same provenance field pi itself writes for /fork and /clone).
 *   3. Appends two tail entries chained off the old leaf:
 *        - session_info      → display name in the /resume picker
 *        - custom_message    → handoff marker, customType "session-migrate", display:true;
 *                               participates in LLM context so future-me sees it as part of
 *                               the conversation.
 *   4. Prints the exact open command: `pi --session <new file>` (fresh process = fresh tools),
 *      plus a ready-to-run verify line — one cheap headless turn that proves the new
 *      session loads in a fresh process. The tool itself spawns nothing; pure file ops.
 *
 * Usage:
 *   node migrate-session.cjs <old.jsonl | partial-id> [--out-dir DIR] [--name TEXT]
 *                            [--handoff FILE|-] [--dry-run]
 *
 * Notes:
 *   - Legacy v1 sessions (no id/parentId) are refused: open them once in current pi so it
 *     auto-migrates to v3, then migrate. (v2/v3 clone fine.)
 *   - --out-dir defaults to the source file's directory (normal session dir layout).
 */
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");

function fail(msg) {
	console.error("migrate-session: " + msg);
	process.exit(1);
}

/* ------------------------------ args */

const argv = process.argv.slice(2);
let target = null, outDir = null, name = null, handoffFile = null;
let dry = false;
for (let i = 0; i < argv.length; i++) {
	const a = argv[i];
	if (a === "--out-dir") outDir = argv[++i];
	else if (a === "--name") name = argv[++i];
	else if (a === "--handoff") handoffFile = argv[++i];
	else if (a === "--dry-run") dry = true;
	else if (a.startsWith("--")) fail("unknown flag " + a);
	else if (!target) target = a;
	else fail("unexpected argument: " + a);
}
if (!target)
	fail(
		'usage: node migrate-session.cjs <old.jsonl|partial-id> [--out-dir DIR] [--name TEXT]\n' +
			"       [--handoff FILE|-] [--dry-run]"
	);

/* ------------------------------ resolve source */

let oldPath = target;
if (!fs.existsSync(oldPath)) {
	const root = path.join(os.homedir(), ".pi", "agent", "sessions");
	const matches = [];
	(function walk(d) {
		let ents;
		try { ents = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
		for (const e of ents) {
			const p = path.join(d, e.name);
			if (e.isDirectory()) walk(p);
			else if (/\.jsonl$/.test(e.name)) matches.push(p);
		}
	})(root);
	const sub = target.toLowerCase();
	const hit = matches.filter((p) => p.toLowerCase().replace(/\\/g, "/").includes(sub));
	if (hit.length === 1) oldPath = hit[0];
	else fail(`target "${target}" matched ${hit.length} sessions; give a unique partial id or full path`);
}
if (!fs.existsSync(oldPath)) fail("session file not found: " + oldPath);
oldPath = path.resolve(oldPath);

/* ------------------------------ parse (bytes preserved) */

const rawLines = fs.readFileSync(oldPath, "utf8").split("\n");
const lines = rawLines.filter((l) => l.trim() !== "");
if (!lines.length) fail("empty session file: " + oldPath);

let header;
try { header = JSON.parse(lines[0]); } catch (e) { fail("line 1 is not valid JSON: " + e.message); }
if (header.type !== "session") fail("first entry is not a session header — not a pi session file");

const entries = lines.slice(1); // raw strings, re-serialized verbatim below
let leafId = null;
let msgCount = 0, model = null, firstTs = null, lastTs = null;
let todosInfo = "none";
for (const l of entries) {
	let e;
	try { e = JSON.parse(l); } catch { continue; } // never corrupt on odd line: clone verbatim anyway
	if (e.id) leafId = e.id;
	if (e.timestamp) { if (!firstTs) firstTs = e.timestamp; lastTs = e.timestamp; }
	if (e.type === "message") {
		msgCount++;
		const m = e.message || {};
		if (m.role === "assistant" && m.model) model = m.model;
	}
	if (e.type === "custom" && e.customType === "todos-state" && e.data) {
		const items = Array.isArray(e.data.items) ? e.data.items : [];
		const done = items.filter((g) => g && g.status === "done").length;
		const doing = items.filter((g) => g && g.status === "doing").length;
		todosInfo = `${items.length} item(s): ${done} done, ${doing} doing`;
	}
}
if (!leafId)
	fail(
		"no id-bearing entries found (legacy v1 session). Open it once in current pi to auto-migrate to v3, then re-run."
	);

/* ------------------------------ build new file */

const now = new Date().toISOString();
const uuid = crypto.randomUUID();
const id8 = () => crypto.randomBytes(4).toString("hex");
const fileBase = `${now.replace(/:/g, "-").replace(".", "-")}_${uuid}.jsonl`;
const dir = outDir ? path.resolve(outDir) : path.dirname(oldPath);
const newPath = path.join(dir, fileBase);

const label = name || `Migrated ${path.basename(oldPath)}`;

let facts = [
	`source session: ${oldPath}`,
	`source session id: ${header.id ?? "?"}`,
	`entries cloned: ${entries.length} (${msgCount} messages)` + (model ? `, last model: ${model}` : ""),
	`span: ${firstTs || "?"} → ${lastTs || "?"}`,
	`cwd: ${header.cwd !== undefined ? header.cwd : "?"}`,
	`carried extension state — todos-state (last entry): ${todosInfo}`,
	"NOTE: tools/extensions available in the process opening this chat were NOT bound in the source conversation. Carried-over context is authoritative; pending instructions carried over now take effect (see AGENTS.md Plan Mode).",
].join("\n");

let handoff = facts;
if (handoffFile) {
	let h;
	try {
		h = handoffFile === "-" ? fs.readFileSync(0, "utf8") : fs.readFileSync(path.resolve(handoffFile), "utf8").trim();
	} catch (e) { fail("cannot read --handoff: " + e.message); }
	if (h) handoff = h + "\n\n" + facts;
}

const infoId = id8(), msgId = id8();
const newHeader = { type: "session", version: 3, id: uuid, timestamp: now };
if (header.cwd !== undefined) newHeader.cwd = header.cwd;
newHeader.parentSession = oldPath; // provenance, same field pi writes for /fork and /clone

const infoLine = JSON.stringify({ type: "session_info", id: infoId, parentId: leafId, timestamp: now, name: label });
const msgLine = JSON.stringify({
	type: "custom_message", id: msgId, parentId: infoId, timestamp: now,
	customType: "session-migrate", content: handoff, display: true,
});

const out = [JSON.stringify(newHeader), ...entries, infoLine, msgLine].join("\n") + "\n";

/* ------------------------------ write / report */

if (dry) {
	console.log(`[dry-run] would create: ${newPath}`);
	console.log("[dry-run] tail entries that would be appended:");
	console.log("  " + infoLine.slice(0, 160) + " …");
	console.log("  " + msgLine.slice(0, 160) + " …");
	process.exit(0);
}

fs.mkdirSync(dir, { recursive: true });
if (fs.existsSync(newPath)) fail("refusing to overwrite existing file: " + newPath);
fs.writeFileSync(newPath, out, "utf8");

console.log(`✓ migrated → ${newPath}`);
console.log(`  source untouched: ${oldPath}`);
console.log(`  label: "${label}"`);
console.log("");
console.log("Open in a FRESH process (extensions/tools bind at start):");
console.log(`  pi --session "${newPath}"`);

console.log("\nVerify it loads in a fresh process (one cheap headless turn):");
console.log(`  pi -p --session "${newPath}" "Reply with exactly MIGRATE_VERIFY_OK and nothing else."`);
