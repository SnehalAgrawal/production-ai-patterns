// Experiment 4: a crash, and three ways to recover from it. Same behaviour and output as ../python/recovery.py,
// where the recoveries are described. Each process starts with the chat model unloaded.
import { spawnSync } from "node:child_process";
import { copyFileSync, cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as llm from "./llm.js";
import * as pipeline from "./pipeline.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const RUNS = join(HERE, "..", "runs", "javascript", "recovery");
const r = (v, w) => String(v).padStart(w);

async function run(runDir, split, ...flags) {
  await llm.unload(llm.chatModel());
  return spawnSync(process.execPath, [join(HERE, "pipeline.js"), runDir, "--split", split, "--policy", "validate", ...flags],
    { cwd: HERE, encoding: "utf8" });
}

function twice(store, name) {
  const counts = new Map();
  for (const rec of store.lines(name)) counts.set(rec.email, (counts.get(rec.email) || 0) + 1);
  return [...counts].filter(([, n]) => n > 1).map(([e]) => e).sort();
}

const data = pipeline.load();
const { crash } = data.settings;
const { split } = crash;
if (existsSync(RUNS)) rmSync(RUNS, { recursive: true });
mkdirSync(RUNS, { recursive: true });

const crashed = join(RUNS, "crashed");
let result = await run(crashed, split, "--crash", "--keep-loaded");
const store = new pipeline.Store(crashed);
const states = data.splits[split].map((e) => store.state(e)).filter(Boolean);
const calls = states.reduce((s, st) => s + ["extract", "draft"].reduce((t, k) => t + (k in st.steps ? st.steps[k].attempts.length : 0), 0), 0);
console.log(`4. A crash right after the reply to ${crash.email} was written to the outbox, before its state recorded it`);
console.log(`   the crashed run: exit code ${result.status}, ${states.length} of ${data.splits[split].length} emails `
  + `started, ${calls} model calls, ${store.lines("outbox.jsonl").length} replies in the outbox, `
  + `${store.lines("review.jsonl").length} in the review queue`);
console.log(`   state of ${crash.email} after the crash: steps ${Object.keys(store.state(crash.email).steps).join(", ")}`);

const first = Object.fromEntries(store.lines("outbox.jsonl").map((rec) => [rec.email, rec.reply]));
console.log(`   ${"recovery".padEnd(30)}${r("exit", 5)}${r("calls", 7)}${r("outbox", 8)}${r("sent twice", 12)}`
  + `${r("same text", 11)}${r("reviewed twice", 16)}`);
for (const [name, flags, keepState] of [["restart", [], false], ["resume", ["--resume"], true],
  ["resume, check outbox", ["--resume", "--check-outbox"], true]]) {
  const target = join(RUNS, name.replace(", ", "-").replaceAll(" ", "-"));
  if (keepState) cpSync(crashed, target, { recursive: true });
  else {
    mkdirSync(target);
    for (const f of ["outbox.jsonl", "review.jsonl"]) if (existsSync(join(crashed, f))) copyFileSync(join(crashed, f), join(target, f));
  }
  result = await run(target, split, ...flags);
  const summary = JSON.parse(result.stdout.trim().split("\n").at(-1));
  const out = new pipeline.Store(target);
  const doubled = twice(out, "outbox.jsonl");
  const same = doubled.filter((e) => out.lines("outbox.jsonl").filter((rec) => rec.email === e).every((rec) => rec.reply === first[e])).length;
  console.log(`   ${name.padEnd(30)}${r(result.status, 5)}${r(summary.calls, 7)}${r(out.lines("outbox.jsonl").length, 8)}`
    + `${r(doubled.length, 12)}${r(same, 11)}${r(twice(out, "review.jsonl").length, 16)}`);
  if (doubled.length) console.log(`     sent twice: ${doubled.join(", ")}`);
}
await llm.unload(llm.chatModel());
await llm.unload(llm.embeddingModel());
