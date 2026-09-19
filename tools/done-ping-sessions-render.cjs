/ Regression harness for done-ping !sessions rendering (2026-09-15).
/ Extracts liveSessions/parkedSessions/sessionIdentity/etc from
/ ~/.pi/agent/extensions/done-ping/discord-bot.cjs by marker and runs the exact
/ !sessions render path against live beacon + session data.
/ Run: node tools/done-ping-sessions-render.cjs  (no model call, no bot needed)
//
// Replicates discord-bot.cjs `!sessions` output against live data, using the bot's own source.
const fs = require("fs");
const path = require("path");
const os = require("os");
const SRC_PATH = "C:/Users/User/.pi/agent/extensions/done-ping/discord-bot.cjs";
const srcLines = fs.readFileSync(SRC_PATH, "utf8").split("\n");

function cut(symbol) {
  let start = -1;
  for (let i = 0; i < srcLines.length; i++) {
    const l = srcLines[i];
    const isDecl = l.startsWith("function " + symbol + " ") || l.startsWith("function " + symbol + "(") || (l.startsWith("const " + symbol + " =") && !l.trim().startsWith("//"));
    if (isDecl) { start = i; break; }
  }
  if (start < 0) throw new Error("symbol not found: " + symbol);
  let bal = 0;
  const out = [];
  for (let i = start; ; i++) {
    const l = srcLines[i];
    if (!l || i > start + 120) break;
    out.push(l);
    for (const ch of l) { if (ch === "{") bal++; else if (ch === "}") bal--; }
    if (bal <= 0 && /\}\s*;?\s*$/.test(l)) break;
  }
  return out.join("\n");
}

const parts = [];
const a = srcLines.findIndex((l) => l.startsWith("const CONVERSE_PENDING"));
const b = srcLines.findIndex((l) => l.startsWith("const SESSIONS_ROOT"));
parts.push(srcLines.slice(a, b + 1).join("\n"));
// loadState/findSessionFile omitted: only reachable on paths this case can't hit.
for (const sym of ["loadRouting", "pidAlive", "liveSessions", "parkedSessions", "normPath", "ageStr", "resolveTarget", "routingTarget", "shortName", "sessionIdentity"]) {
  parts.push(cut(sym));
}

const BT = String.fromCharCode(92) + String.fromCharCode(120) + "60"; // "\x60" escape text, inserted into driver below
const driverLines = [
  ";(() => {",
  '  const BT = "\\x60";',
  "  const live = liveSessions();",
  "  const t = resolveTarget();",
  '  let out = "**Live pi sessions:**\\n";',
  "  for (const s of live) {",
  '    const star = normPath(t.sessionFile || "") === normPath(s.sessionFile) ? "\\u2605 " : "";',
  "    const id = sessionIdentity(s.sessionFile);",
  '    const whoRaw = (id && (id.label || id.first) || "").trim();',
  "    const who = whoRaw ? (whoRaw.length > 52 ? whoRaw.slice(0, 52).replace(/[\\s]+$/g, \"\") + \"\\u2026\" : whoRaw) : shortName(s.sessionFile);",
  '    out += BT + star + s.sessionId.slice(0, 8) + BT + " \\u00b7 " + (s.busy ? "\\u23f3 busy" : "\\u25cf idle") + " \\u00b7 " + who + "\\n";',
  '  }',
  '  if (!live.length) out = "**No live pi sessions** \\u2014 headless turn on pinned file.\\n";',
  "  let parkedListed = false;",
  "  for (const s of parkedSessions(5)) {",
  '    const star = normPath(t.sessionFile || "") === normPath(s.sessionFile) ? "\\u2605 " : "";',
  "    const idp = sessionIdentity(s.sessionFile);",
  '    const whoRawP = (idp && (idp.label || idp.first) || "").trim();',
  "    const whoP = whoRawP ? (whoRawP.length > 40 ? whoRawP.slice(0, 40).replace(/[\\s]+$/g, \"\") + \"\\u2026\" : whoRawP) : shortName(s.sessionFile);",
  '    if (!parkedListed) { out += "\\n**Recent (parked):**\\n"; parkedListed = true; }',
  '    out += BT + star + s.sessionId.slice(0, 8) + BT + " \\u00b7 " + ageStr(s.at) + " ago \\u00b7 " + whoP + "\\n";',
  "  }",
  "  const rt = routingTarget();",
  '  out += "\\ncurrent target: " + BT + (rt === "active" ? "active (auto)" : rt.slice(0, 8)) + BT;',
  "  console.log(out);",
  "})()",
];

// bare fs/path/os in cut code resolve to the module-level consts (same objects)
const prelude = [
  'var CONVERSE_DIR = "C:/Users/User/.pi/agent/extensions/done-ping";',
  "function findSessionFile() { return null; }",
  "function loadState() { return {}; }",
].join("\n");

try {
  // eslint-disable-next-line no-eval
  // direct eval: module scope (require) visible; sloppy-mode leaks are fine here
  eval(prelude + "\n" + parts.join("\n\n") + "\n" + driverLines.join("\n"));
} catch (e) {
  console.error("HARNESS FAIL:", e.message);
  process.exit(1);
}
