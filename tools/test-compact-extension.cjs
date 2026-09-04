/* Dry-run of aggressive-compaction.ts handler against the live local LM Studio server.
 * Validates: TS loads, serialization, prompt assembly, direct fetch with
 * reasoning_effort:"none", response parsing, and that a real summary comes back. */

const PI_MODULES = "C:\\Users\\User\\AppData\\Roaming\\npm\\node_modules\\@earendil-works\\pi-coding-agent\\node_modules";
process.env.NODE_PATH = PI_MODULES;
require("module").Module._initPaths();

(async () => {
  const jitiMod = require("jiti");
  const createJiti = jitiMod.createJiti || (typeof jitiMod === "function" ? undefined : undefined);
  let jiti;
  if (createJiti) jiti = createJiti(__filename);
  else {
    const J = jitiMod.default || jitiMod.Jiti || jitiMod;
    jiti = new J.__esModule ? (new (jitiMod.default || jitiMod)) : new (require("jiti").default)(__filename);
  }

  const EXT_PATH = "C:/Users/User/.pi/agent/extensions/aggressive-compaction.ts";
  console.log("[1] importing extension (syntax + top-level check)...");
  const mod = await jiti.import(EXT_PATH);
  const extFactory = mod.default;
  if (typeof extFactory !== "function") throw new Error("no default export function");
  console.log("    ok — module loaded, default export is a function\n");

  // --- build realistic messages (~90k chars raw) --------------------------
  const fillerFile =
    "import { useState } from 'react';\n" +
    Array.from({ length: 40 }, (_, i) => `function Component${i}() {\n  const [state, setState] = useState(${i});\n  return <div className={'panel-' + ${i}}>{'label-' + ${i}}</div>;\n}\nexport { Component${i} };\n`).join("\n");

  const bigBashOut =
    "npm warn config production Use --omit=dev instead.\n" +
    Array.from({ length: 120 }, (_, i) => `  ${String(i).padStart(4)} kB  dist/chunks/Module_${i}.js` ).join("\n");

  const msgs = [];
  const mkUser = (t) => ({ role: "user", content: [{ type: "text", text: t }] });
  const mkAsst = (text, calls) => ({
    role: "assistant",
    content: [
      ...(text ? [{ type: "text", text }] : []),
      ...calls.map((name, i) => ({ type: "toolCall", name, arguments: { path: `/proj/src/file${i}.ts`, command: `echo step ${i}` } })),
    ],
  });
  const mkTool = (t) => ({ role: "toolResult", content: [{ type: "text", text: t }] });

  // long thinking block that MUST be stripped from serialization
  msgs.push({ role: "assistant", content: [{ type: "thinking", text: "THINKING-BLOCK-MARKER-".repeat(200) + "END" }, { type: "text", text: "I'll look at the project structure first." }] });
  msgs.push(mkUser("Please refactor the UI panels in src/components and fix the build errors. Start by reading AGENTS.md"));
  msgs.push(mkAsst(null, ["read"]));
  msgs.push(mkTool("# AGENTS.md\n# DOX — Agent Workspace\nUse conventional commits. Push after every task.\n" + fillerFile.slice(0, 800)));
  for (let i = 0; i < 12; i++) {
    msgs.push(mkAsst(`Reading and editing component batch ${i}.`, ["read", "edit"]));
    msgs.push(mkTool(fillerFile)); // ~9KB each -> total well over 50k to exercise the cap
    if (i % 3 === 0) {
      msgs.push(mkAsst(null, ["bash"]));
      msgs.push(mkTool(bigBashOut));
    }
  }
  const turnPrefix = [mkUser("Keep going — did you finish batch 12?"), mkAsst("Almost done with the refactor.", [])];

  console.log("[2] running handler (live call to localhost:1234)...");
  let notifications = [];
  const piMock = { on(name, fn) { globalThis.__handler = fn; } };
  extFactory(piMock);
  if (!globalThis.__handler) throw new Error("session_before_compact not registered");

  const model = { provider: "lmstudio", id: "qwen3.8-27b", name: "Qwen3.8 27B (IQ3_XXS)", baseUrl: "http://localhost:1234/v1" };
  const ctx = {
    model,
    modelRegistry: { getApiKeyAndHeaders: async () => ({ ok: true, apiKey: "", headers: {} }) },
    ui: { notify: (m, t) => notifications.push(`${t}: ${m}`), },
  };
  const event = {
    preparation: {
      messagesToSummarize: msgs,
      turnPrefixMessages: turnPrefix,
      tokensBefore: 95981,
      firstKeptEntryId: "entry-test-001",
      previousSummary: null,
    },
    signal: new AbortController().signal,
  };

  const t0 = Date.now();
  const result = await globalThis.__handler(event, ctx);
  const secs = ((Date.now() - t0) / 1000).toFixed(1);

  console.log("    notifications:", notifications.length ? notifications.join(" | ") : "(none)");
  if (!result || !result.compaction) {
    console.error(`\nFAIL — no compaction returned after ${secs}s (falls through to pi built-in)`);
    process.exit(1);
  }
  const s = result.compaction.summary;
  console.log(`[3] summary received in ${secs}s — length: ${s.length} chars`);
  const checks = [
    ["has '## Goal' heading", /(^|\n)##\s+Goal/m.test(s)],
    ["has '## Progress' section", /(^|\n)##\s+Progress/m.test(s)],
    ["has '## Continue With'", /(^|\n)##\s+Continue\s+With/m.test(s)],
    ["thinking block stripped (no marker)", !s.includes("THINKING-BLOCK-MARKER")],
    ["mentions user request", s.toLowerCase().includes("refactor") || s.toLowerCase().includes("component")],
  ];
  let pass = true;
  for (const [name, ok] of checks) {
    console.log(`    ${ok ? "PASS" : "FAIL"}  ${name}`);
    if (!ok) pass = false;
  }
  console.log("\n--- summary head ---");
  console.log(s.split("\n").slice(0, 30).join("\n"));
  console.log("--- end head ---\n");

  if (result.compaction.firstKeptEntryId !== "entry-test-001" || result.compaction.tokensBefore !== 95981) {
    pass = false;
    console.error("FAIL — firstKeptEntryId/tokensBefore not passed through");
  } else {
    console.log("PASS  firstKeptEntryId + tokensBefore passthrough");
  }

  console.log(pass ? `\n=== ALL CHECKS PASSED ===` : `\n=== SOME CHECKS FAILED ===`);
  process.exit(pass ? 0 : 1);
})().catch((e) => {
  console.error("FATAL:", e.message || e);
  process.exit(2);
});
