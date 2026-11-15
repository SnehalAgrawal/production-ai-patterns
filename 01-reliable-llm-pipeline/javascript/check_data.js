// Checks the frozen test material for consistency, with no model calls. Same checks and output as
// ../python/check_data.py, where they are listed.
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as chunkers from "./chunkers.js";
import { contains } from "./steps.js";
import { Tokenizer } from "./tokens.js";

const DATA = join(dirname(fileURLToPath(import.meta.url)), "..", "data");
const readJson = (name) => JSON.parse(readFileSync(join(DATA, name), "utf8"));
const byName = (dir, ext, keepExt) => Object.fromEntries(readdirSync(join(DATA, dir)).filter((f) => f.endsWith(ext)).sort()
  .map((f) => [keepExt ? f : f.slice(0, -ext.length), readFileSync(join(DATA, dir, f), "utf8")]));

const documents = byName("documents", ".md", true);
const emails = byName("emails", ".txt", false);
const labels = readJson("labels.json").emails;
const splits = readJson("splits.json");
const settings = readJson("settings.json");
const chunks = chunkers.chunk(settings.chunking, documents, new Tokenizer()).map((c) => c.text);
const problems = [];
const same = (a, b) => JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());
if (!same(Object.keys(emails), Object.keys(labels)) || !same(Object.keys(emails), [...splits.dev, ...splits.test])) {
  problems.push("emails, labels, and splits don't list the same emails exactly once");
}
const ids = new Map();
const count = (id) => ids.set(id, (ids.get(id) || 0) + 1);
for (const eid of Object.keys(labels).sort()) {
  const lab = labels[eid];
  for (const identifier of lab.identifiers) {
    if (!emails[eid].includes(identifier)) problems.push(`${eid}: identifier ${identifier} isn't in the email`);
  }
  for (const q of lab.questions) {
    count(q.id);
    const asks = q.asks.toLowerCase();
    if (!q.match.some((t) => asks.includes(t))) problems.push(`${q.id}: the reference wording doesn't match its own terms`);
    for (const other of lab.questions) {
      if (other !== q && other.match.some((t) => asks.includes(t))) {
        problems.push(`${q.id}: the reference wording also matches ${other.id}'s terms`);
      }
    }
    if (q.answerable !== q.facts.length > 0) problems.push(`${q.id}: answerable doesn't agree with its facts`);
    for (const f of q.facts) {
      count(f.id);
      for (const e of f.evidence) {
        if (!documents[e.doc].includes(e.text)) problems.push(`${f.id}: evidence isn't in ${e.doc}`);
        else if (!chunks.some((c) => c.includes(e.text))) problems.push(`${f.id}: evidence isn't whole inside any chunk`);
      }
      if (f.check === "mechanical" && !f.evidence.some((e) => f.any_of.some((a) => contains(e.text, a)))) {
        problems.push(`${f.id}: no accepted wording appears in its evidence`);
      }
    }
  }
}
for (const [id, n] of ids) if (n > 1) problems.push(`${id}: id used ${n} times`);

console.log(`${Object.keys(emails).length} emails, ${chunks.length} chunks`);
console.log(`${"".padEnd(34)}${"dev".padStart(6)}${"test".padStart(6)}`);
const rows = ["dev", "test"].map((name) => {
  const es = splits[name];
  const qs = es.flatMap((e) => labels[e].questions);
  const facts = qs.flatMap((q) => q.facts);
  return [es.length, ...[1, 2, 3].map((k) => es.filter((e) => labels[e].questions.length === k).length),
    qs.length, qs.filter((q) => !q.answerable).length, facts.length,
    facts.filter((f) => f.check === "mechanical").length, facts.filter((f) => f.check === "human").length,
    es.reduce((s, e) => s + labels[e].identifiers.length, 0)];
});
const names = ["emails", "  with 1 question", "  with 2 questions", "  with 3 questions", "questions",
  "  unanswerable", "facts", "  mechanical", "  human", "identifiers"];
names.forEach((name, k) => console.log(`${name.padEnd(34)}${String(rows[0][k]).padStart(6)}${String(rows[1][k]).padStart(6)}`));
console.log(problems.length ? ["PROBLEMS:", ...problems].join("\n") : "no problems");
