#!/usr/bin/env node
/* subagent-model-doctor.cjs - one-shot diagnostic/remediation for pi-subagents model failures.
 *
 * Fixes the "Requested subagent model 'X' is excluded and cannot be replaced by a fallback"
 * failure loop on this machine (LM Studio + pi-subagents). Checks, in order:
 *   1) LM Studio server reachable (default http://127.0.0.1:1234, or ~/.pi/agent/lmstudio.json)
 *   2) target model present AND loaded per GET <server>/api/v0/models (fallback /v1/models)
 *   3) stale pi-subagents model exclusions in %TEMP%/pi-subagents-<scope>/model-exclusions.json
 *
 * Usage: node subagent-model-doctor.cjs [--clear] [--model ID] [--server URL] [--temp-root DIR] [--all]
 *   --clear         remove live+expired lmstudio/* exclusion entries (atomic write, other providers kept)
 *   --model ID      model to check (default qwen3.8-27b; "provider/id" accepted, prefix stripped)
 *   --server URL    override LM Studio base URL (else ~/.pi/agent/lmstudio.json, else http://127.0.0.1:1234)
 *   --temp-root DIR override temp root for exclusion stores (mirrors PI_SUBAGENTS_TEMP_ROOT)
 *   --all           report every exclusion entry, not just lmstudio/*
 *
 * Exit codes: 0 healthy | 2 server down | 3 model missing/not loaded | 4 stale exclusion active
 */
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");

// --------------------------------------------------------------------------- args
let clearMode = false;
let targetModel = "qwen3.8-27b";
let serverUrl = null;
let tempRootOverride = process.env.PI_SUBAGENTS_TEMP_ROOT || null;
let showAll = false;
for (let i = 0; i < process.argv.length; i++) {
	const a = process.argv[i];
	if (a === "--clear") clearMode = true;
	else if (a === "--all") showAll = true;
	else if (a === "--model" && process.argv[i + 1]) targetModel = process.argv[++i];
	else if (a === "--server" && process.argv[i + 1]) serverUrl = process.argv[++i];
	else if (a === "--temp-root" && process.argv[i + 1]) tempRootOverride = process.argv[++i];
}

// provider-prefixed input ("lmstudio/qwen3.8-27b") -> bare id for the LM Studio check
const bareModel = String(targetModel).includes("/") ? targetModel.split("/").slice(1).join("/") : targetModel;

function fail(code, msg) {
	console.log(msg);
	console.log("VERDICT: FAIL (" + code + ")");
	process.exit(code);
}

// --------------------------------------------------------------------------- server url
function resolveServerUrl() {
	if (serverUrl) return serverUrl.replace(/\/+$/, "");
	try {
		const cfgPath = path.join(os.homedir(), ".pi", "agent", "lmstudio.json");
		const cfg = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
		let url;
		if (Array.isArray(cfg.urls) && cfg.urls.length > 0) url = String(cfg.urls[0]);
		else if (typeof cfg.url === "string" && cfg.url.length > 0) url = cfg.url;
		if (!url) {
			const entries = Object.entries(cfg.providers || {});
			if (entries.length > 0) url = String(entries[0][1].baseUrl);
		}
		if (url) return url.replace(/\/+$/, "");
	} catch { /* not configured -> default */ }
	return "http://127.0.0.1:1234";
}

// --------------------------------------------------------------------------- lm studio
async function fetchModels(url) {
	// native endpoint first (has loaded state), then OpenAI-compat fallback.
	// LM Studio builds differ: older ones return {models:[...]}, newer ones
	// return OpenAI-style {data:[...]} on BOTH /api/v0/models and /v1/models.
	for (const p of ["/api/v0/models", "/v1/models"]) {
		try {
			const res = await fetch(url + p, { signal: AbortSignal.timeout(8000) });
			if (!res.ok) continue;
			const data = await res.json();
			const list = Array.isArray(data.models) ? data.models : Array.isArray(data.data) ? data.data : [];
			return list.map((m) => ({
				id: typeof m.id === "string" && m.id.length > 0 ? m.id : String(m.key || ""),
				state: typeof m.state === "string" ? m.state : null,
			}));
		} catch { /* try next path */ }
	}
	throw new Error("server unreachable or no /models endpoint at " + url);
}

// --------------------------------------------------------------------------- exclusion stores
function findStoreFiles() {
	const files = [];
	if (process.env.PI_MODEL_EXCLUSIONS_PATH) files.push(process.env.PI_MODEL_EXCLUSIONS_PATH);
	const root = tempRootOverride || os.tmpdir();
	let entries = [];
	try { entries = fs.readdirSync(root, { withFileTypes: true }); } catch { return dedupe(files); }
	for (const e of entries) {
		if (!e.isDirectory() || !e.name.startsWith("pi-subagents-")) continue;
		const f = path.join(root, e.name, "model-exclusions.json");
		if (fs.existsSync(f)) files.push(f);
	}
	return dedupe(files.filter((f) => fs.existsSync(f)));
}

function dedupe(arr) { return [...new Set(arr)]; }

function parseStore(file) {
	try {
		const raw = JSON.parse(fs.readFileSync(file, "utf8"));
		let entriesArr = Array.isArray(raw.exclusions) ? raw.exclusions : [];
		if (entriesArr.length === 0 && raw.exclusions && typeof raw.exclusions === "object") {
			// legacy object-map shape: { "<id>": { model, reason, expiresAt } }
			entriesArr = Object.entries(raw.exclusions).map(([k, v]) => ({ id: k, ...v }));
		}
		return entriesArr.filter((e) => e && typeof e === "object").map((e) => {
			// Current store schema is { modelId, provider, reason, recordedAt, expiresAt }; legacy entries used `model`.
			const model = String(e.model || ((e.provider ? e.provider + "/" : "") + (e.modelId || "")));
			// expiresAt is epoch-ms numeric in the current schema, ISO string in legacy entries.
			const exp = typeof e.expiresAt === "number" && Number.isFinite(e.expiresAt)
				? e.expiresAt
				: (Date.parse(e.expiresAt || "") || 0);
			return { id: String(e.id || ""), model, reason: String(e.reason || "").slice(0, 120), expiresAt: exp, raw: e };
		});
	} catch { return []; }
}

function relevant(entry) {
	const m = entry.model;
	return showAll || m === "lmstudio/" + bareModel || m.includes("/" + bareModel);
}

function clearEntries(files) {
	let removedTotal = 0;
	for (const file of files) {
		let all;
		try { all = parseStore(file); } catch { continue; }
		if (!all.length) continue;
		const keep = [];
		const removed = [];
		for (const e of all) {
			// --clear is only reached when the server was verified up, so every
			// lmstudio/* entry (live or expired) is stale by definition.
			if (e.model.startsWith("lmstudio/")) { removed.push(e); } else keep.push(e);
		}
		if (!removed.length) continue;
		// atomic write: tmp file + rename (same pattern as pi-subagents ModelExclusionStore.flush)
		const dir = path.dirname(file);
		const tmp = path.join(dir, "model-exclusions-" + process.pid + ".tmp.json");
		// Lossless pass-through of kept entries (current and legacy schemas preserved verbatim).
		fs.writeFileSync(tmp, JSON.stringify({ version: 1, exclusions: keep.map((e) => e.raw) }, null, 2));
		try { fs.renameSync(tmp, file); } finally { try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch {} }
		removedTotal += removed.length;
		for (const e of removed) console.log("  cleared exclusion: " + e.model + " (was expires " + new Date(e.expiresAt).toISOString() + ") in " + file);
	}
	return removedTotal;
}

// --------------------------------------------------------------------------- main
(async () => {
	const url = resolveServerUrl();
	console.log("[1/3] LM Studio server: " + url);
	let models;
	try {
		models = await fetchModels(url);
	} catch (err) {
		console.log("  DOWN - " + String(err.message || err));
		fail(2, "VERDICT: SERVER_DOWN");
	}

	const hit = models.find((m) => m.id === bareModel);
	if (!hit) {
		console.log("  UP - serving " + models.length + " model(s): " + (models.map((m) => m.id).join(", ") || "(none)"));
		fail(3, "VERDICT: MODEL_MISSING (" + bareModel + " not in /api/v0/models; load it in LM Studio first - pi registers exactly these keys as lmstudio/<key>)");
	}
	console.log("  UP - '" + hit.id + "' present (state: " + (hit.state || "n/a") + ")");

	console.log("[2/3] Exclusion stores under temp root:");
	const files = findStoreFiles();
	if (!files.length) {
		console.log("  none found (nothing recorded yet - nothing to clear)");
	}
	const liveRelevant = [];
	for (const file of files) {
		const entries = parseStore(file).filter(relevant);
		for (const e of entries) if ((e.expiresAt || 0) > Date.now()) liveRelevant.push({ ...e, file });
		if (entries.length) console.log("  " + file + " -> " + entries.length + " relevant entr" + (entries.length === 1 ? "y" : "ies"));
	}

	console.log("[3/3] Verdict for model '" + targetModel + "':");
	if (clearMode && liveRelevant.length) {
		clearEntries(files);
		const stillLive = findStoreFiles().flatMap((f) => parseStore(f)).filter((e) => relevant(e) && e.expiresAt > Date.now());
		if (stillLive.length) fail(4, "VERDICT: STALE_EXCLUSION (entries survived clear - inspect manually: " + files.join(" ") + ")");
		console.log("  cleared. server up + model loaded -> healthy.");
		console.log("VERDICT: HEALTHY_AFTER_CLEAR");
		process.exit(0);
	}
	if (liveRelevant.length) {
		for (const e of liveRelevant) console.log("  ACTIVE exclusion on " + e.model + ": " + e.reason + " | expires " + new Date(e.expiresAt).toISOString() + " | store: " + e.file);
		console.log("  fix: node tools/subagent-model-doctor.cjs --clear   (only after confirming the model is resolvable, as above)");
		fail(4, "VERDICT: STALE_EXCLUSION_ACTIVE");
	}
	console.log("  no live exclusions for this model.");
	console.log("VERDICT: HEALTHY");
	process.exit(0);
})().catch((err) => {
	console.log("unexpected error: " + (err && err.stack ? err.stack : String(err)));
	process.exit(1);
});
