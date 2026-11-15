// Experiments 1 to 3 on one split of the emails (test by default), from real runs. Same behaviour and
// output as ../python/experiments.py, where the experiments are described. Runs are kept in
// ../runs/javascript/<split>-*/; with --report, the report is printed from them again without model calls.
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as chunkers from "./chunkers.js";
import * as llm from "./llm.js";
import * as pipeline from "./pipeline.js";
import { Index } from "./retrieval.js";
import { Scorer } from "./score.js";
import * as steps from "./steps.js";
import { Tokenizer } from "./tokens.js";

const DEMO = join(dirname(fileURLToPath(import.meta.url)), "..");
const RUNS = join(DEMO, "runs", "javascript");
const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));

function fresh(path) {
  if (existsSync(path)) rmSync(path, { recursive: true });
  mkdirSync(path, { recursive: true });
  return path;
}

// Chunks retrieved for the labelled questions, plus the first chunk holding each missing evidence passage.
async function goldContext(index, scorer, eid) {
  const chosen = await index.retrieve(scorer.questions(eid).map((q) => q.asks));
  const added = [];
  for (const q of scorer.questions(eid)) {
    for (const fact of q.facts) {
      if (!Scorer.supported(fact, [...chosen, ...added].map((i) => index.chunks[i].text))) {
        added.push(index.chunks.findIndex((c) => Scorer.supported(fact, [c.text])));
      }
    }
  }
  return [chosen, added];
}

async function runAll(data, split) {
  const index = await new Index().init(data.settings, data.documents, new Tokenizer());
  const eids = data.splits[split];
  const scorer = new Scorer();
  const { options } = data.settings.chat;
  const { prompts } = data;
  try {
    for (const policy of ["none", "validate"]) {
      await new pipeline.Pipeline(data, index, policy).run(eids, new pipeline.Store(fresh(join(RUNS, `${split}-${policy}`))));
      await llm.unload(llm.chatModel()); // each run starts with the model freshly loaded
    }

    const isolated = fresh(join(RUNS, `${split}-isolated`));
    for (const eid of eids) {
      const [chosen, added] = await goldContext(index, scorer, eid);
      const context = [...chosen, ...added].map((i) => index.chunks[i]);
      const questions = scorer.questions(eid).map((q) => q.asks);
      const call = await llm.chat(steps.draftMessages(prompts, data.emails[eid], questions, context.map((c) => [c.document, c.text])),
        { schema: steps.DRAFT_SCHEMA, options, maxTokens: data.settings.chat.draft_max_tokens });
      const record = {
        email: eid, questions, chunks: context.map((c) => c.id), added: added.map((i) => index.chunks[i].id),
        call, output: steps.parse(call.content)[0],
      };
      writeFileSync(join(isolated, `${eid}.json`), `${JSON.stringify(record, null, 1)}\n`);
    }
    await llm.unload(llm.chatModel());

    // The same first request again, for every model step whose first attempt failed its checks.
    const store = new pipeline.Store(join(RUNS, `${split}-validate`));
    const repeats = [];
    const byId = new Map(index.chunks.map((c) => [c.id, c]));
    for (const eid of eids) {
      const state = store.state(eid);
      const email = data.emails[eid];
      for (const step of ["extract", "draft"]) {
        if (!(step in state.steps) || !state.steps[step].attempts[0].problems.length) continue;
        let messages, schema, limit;
        if (step === "extract") [messages, schema, limit] = [steps.extractMessages(prompts, email), steps.EXTRACT_SCHEMA, "extract_max_tokens"];
        else {
          const context = state.steps.retrieve.chunks.map((c) => byId.get(c));
          messages = steps.draftMessages(prompts, email, state.steps.extract.output.questions, context.map((c) => [c.document, c.text]));
          [schema, limit] = [steps.DRAFT_SCHEMA, "draft_max_tokens"];
        }
        const call = await llm.chat(messages, { schema, options, maxTokens: data.settings.chat[limit] });
        const first = state.steps[step].attempts[0].content;
        repeats.push({ email: eid, step, same: call.content === first, content: call.content });
      }
    }
    writeFileSync(join(RUNS, `${split}-repeat.json`), `${JSON.stringify(repeats, null, 1)}\n`);
  } finally {
    await llm.unload(llm.chatModel());
    await llm.unload(llm.embeddingModel());
  }
}

// ---------------------------------------------------------------------------------------------- report

// numerator / denominator to one decimal, rounding halves up, with integers only (same in Python).
function tenths(numerator, denominator) {
  const q = Math.floor((20 * numerator + denominator) / (2 * denominator));
  return `${Math.floor(q / 10)}.${q % 10}`;
}

const r = (v, w) => String(v).padStart(w);
const l = (v, w) => String(v).padEnd(w);
const sum = (xs) => xs.reduce((s, x) => s + (x ? 1 : 0), 0);

class Report {
  constructor(data, split) {
    Object.assign(this, { data, split, eids: data.splits[split], scorer: new Scorer() });
    this.chunks = new Map(chunkers.chunk(data.settings.chunking, data.documents, new Tokenizer()).map((c) => [c.id, c]));
    this.none = new pipeline.Store(join(RUNS, `${split}-none`));
    this.checked = new pipeline.Store(join(RUNS, `${split}-validate`));
    this.isolated = Object.fromEntries(this.eids.map((e) => [e, readJson(join(RUNS, `${split}-isolated`, `${e}.json`))]));
    this.repeats = readJson(join(RUNS, `${split}-repeat.json`));
    this.unread = new Map();
  }

  verdict(eid, reply, where) {
    if (reply === null) return "none";
    const v = this.scorer.verdict(eid, reply);
    if (v === null) {
      const key = Scorer.key(eid, reply);
      if (!this.unread.has(key)) this.unread.set(key, [eid, reply, where]);
    }
    return v;
  }

  static reply(state, attempt = -1) {
    const draft = state.steps.draft;
    if (!draft) return null;
    const [output] = steps.parse(draft.attempts.at(attempt).content);
    return output !== null && typeof output === "object" && !Array.isArray(output) && typeof output.reply === "string"
      ? output.reply : null;
  }

  // Where "checks, no retries" stops this email: the first failing check, or null if it is sent.
  static firstStop(state) {
    const s = state.steps;
    if (s.extract.attempts[0].problems.length) return "extract";
    if (s.retrieve.problems.length) return "retrieve";
    if (s.draft.attempts[0].problems.length) return "draft";
    return null;
  }

  print() {
    const n = this.eids.length;
    const sc = this.scorer;
    const none = Object.fromEntries(this.eids.map((e) => [e, this.none.state(e)]));
    const checked = Object.fromEntries(this.eids.map((e) => [e, this.checked.state(e)]));
    console.log(`Split: ${this.split}, ${n} emails, prompts ${this.data.prompts.version}`);

    // 1 ---------------------------------------------------------------------------------------------
    const extractionOk = [], identifiersOk = [], retrievalAlone = [], draftAlone = [], chainOk = [];
    const firstFailure = { extraction: 0, retrieval: 0, draft: 0 };
    for (const eid of this.eids) {
      const s = none[eid].steps;
      const out = s.extract.output;
      const extracted = out !== null && typeof out === "object" && !Array.isArray(out) ? out : {};
      const questions = steps.isStringList(extracted.questions) ? extracted.questions : [];
      const ids = steps.isStringList(extracted.identifiers) ? extracted.identifiers : [];
      const eOk = sc.extraction(eid, questions).ok;
      extractionOk.push(eOk);
      identifiersOk.push(sc.identifiers(eid, ids));
      const alone = this.isolated[eid];
      retrievalAlone.push(sc.retrieval(eid, alone.chunks.filter((c) => !alone.added.includes(c)).map((c) => this.chunks.get(c).text)).ok);
      const o = alone.output;
      const draftReply = o !== null && typeof o === "object" && !Array.isArray(o) && typeof o.reply === "string" ? o.reply : null;
      draftAlone.push(this.verdict(eid, draftReply, "draft on its own") === "correct");
      const rOk = "retrieve" in s && sc.retrieval(eid, s.retrieve.chunks.map((c) => this.chunks.get(c).text)).ok;
      const correct = none[eid].status === "sent" && this.verdict(eid, Report.reply(none[eid]), "no checks") === "correct";
      chainOk.push(correct);
      if (!correct) firstFailure[!eOk ? "extraction" : !rOk ? "retrieval" : "draft"] += 1;
    }
    const [a, b, c] = [sum(extractionOk), sum(retrievalAlone), sum(draftAlone)];
    console.log("\n1. Each step on its own, and the chain with no checks (emails where the step did its job)");
    console.log(`   extraction: questions paired with the labels        ${r(a, 3)} of ${n}`);
    console.log(`     (identifiers exactly as labelled                  ${r(sum(identifiersOk), 3)} of ${n}, not part of the step's score)`);
    console.log(`   retrieval from the labelled questions: evidence for every fact   ${r(b, 3)} of ${n}`);
    console.log(`   draft from the labelled questions and gold excerpts: correct     ${r(c, 3)} of ${n}`);
    console.log(`   if the steps failed independently: ${tenths(a * b * c, n * n)} of ${n} emails correct end to end`);
    console.log(`   measured, the chain with no checks: ${sum(chainOk)} of ${n} replies correct`);
    console.log(`   where each wrong chain reply first went wrong: extraction ${firstFailure.extraction}, `
      + `retrieval ${firstFailure.retrieval}, drafting ${firstFailure.draft}`);

    // 2 ---------------------------------------------------------------------------------------------
    console.log("\n2. What reaches the outbox");
    const unchecked = Object.fromEntries(this.eids.map((e) => [e, none[e].status === "sent" ? Report.reply(none[e]) : null]));
    const stops = Object.fromEntries(this.eids.map((e) => [e, Report.firstStop(checked[e])]));
    const pick = (keys, f) => Object.fromEntries(keys.map((e) => [e, f(e)]));
    const rows = [];
    let sent = this.eids.filter((e) => none[e].status === "sent");
    rows.push(["no checks", sent, this.eids.filter((e) => none[e].status !== "sent"), pick(sent, (e) => unchecked[e])]);
    sent = this.eids.filter((e) => stops[e] === null);
    rows.push(["checks, no retries", sent, this.eids.filter((e) => stops[e] !== null), pick(sent, (e) => Report.reply(checked[e], 0))]);
    sent = this.eids.filter((e) => checked[e].status === "sent");
    rows.push(["checks and retries", sent, this.eids.filter((e) => checked[e].status !== "sent"), pick(sent, (e) => Report.reply(checked[e]))]);
    console.log(`   ${l("policy", 22)}${r("sent", 6)}${r("correct", 9)}${r("wrong", 7)}${r("held", 6)}`
      + `${r("held, would have been wrong", 30)}${r("held, would have been correct", 32)}`);
    for (const [name, sentList, held, replies] of rows) {
      const verdicts = sentList.map((e) => this.verdict(e, replies[e], name));
      const would = held.map((e) => this.verdict(e, unchecked[e], "no checks"));
      console.log(`   ${l(name, 22)}${r(sentList.length, 6)}${r(verdicts.filter((v) => v === "correct").length, 9)}`
        + `${r(verdicts.filter((v) => v === "wrong").length, 7)}${r(held.length, 6)}`
        + `${r(would.filter((v) => v === "wrong" || v === "none").length, 30)}${r(would.filter((v) => v === "correct").length, 32)}`);
    }
    const same = this.eids.filter((e) => none[e].steps.extract.attempts[0].content === checked[e].steps.extract.attempts[0].content
      && (!("draft" in none[e].steps) || !("draft" in checked[e].steps)
        || none[e].steps.draft.attempts[0].content === checked[e].steps.draft.attempts[0].content)).length;
    console.log(`   first attempts identical in the two runs: ${same} of ${n} emails`);
    console.log("   held back, by the first check that failed:");
    for (const e of this.eids) {
      if (stops[e]) {
        const s = checked[e].steps;
        const problems = stops[e] === "retrieve" ? s.retrieve.problems : s[stops[e]].attempts[0].problems;
        console.log(`     ${e} ${stops[e]}: ${problems.join("; ")}`);
      }
    }

    // 3 ---------------------------------------------------------------------------------------------
    console.log("\n3. Retries with the problems");
    for (const step of ["extract", "draft"]) {
      const failed = this.eids.filter((e) => step in checked[e].steps && checked[e].steps[step].attempts[0].problems.length);
      const fixed = failed.filter((e) => checked[e].steps[step].ok);
      const extra = failed.reduce((s, e) => s + checked[e].steps[step].attempts.length - 1, 0);
      const after = (k) => failed.filter((e) => checked[e].steps[step].attempts.length === k + 1 && checked[e].steps[step].ok).length;
      console.log(`   ${step}: ${failed.length} first attempts failed; fixed by retry 1: ${after(1)}, by retry 2: ${after(2)}; `
        + `still failing: ${failed.length - fixed.length}; extra calls: ${extra}`);
    }
    console.log(`   the same first request sent again, without the problems: ${sum(this.repeats.map((x) => x.same))} of `
      + `${this.repeats.length} outputs identical to the first attempt`);
    const calls = { "no checks": 0, "checks, no retries": 0, "checks and retries": 0 };
    for (const e of this.eids) {
      for (const s of ["extract", "draft"]) {
        if (s in none[e].steps) calls["no checks"] += none[e].steps[s].attempts.length;
        if (s in checked[e].steps) calls["checks and retries"] += checked[e].steps[s].attempts.length;
      }
      calls["checks, no retries"] += 1 + (stops[e] === null || stops[e] === "draft" ? 1 : 0);
    }
    console.log(`   model calls: ${Object.entries(calls).map(([k, v]) => `${k} ${v}`).join(", ")}`);

    this.writeUnread();
  }

  writeUnread() {
    const path = join(RUNS, `${this.split}-to-read.md`);
    const lines = [`# Replies without a hand label (${this.unread.size})\n`];
    const entries = [...this.unread].sort((x, y) => (x[1][0] < y[1][0] ? -1 : x[1][0] > y[1][0] ? 1 : x[0] < y[0] ? -1 : 1));
    for (const [key, [eid, reply, where]] of entries) {
      lines.push(`## ${eid} \`${key}\` (${where})\n`);
      const found = this.scorer.mechanical(eid, reply);
      for (const q of this.scorer.questions(eid)) {
        lines.push(`- ${q.id} ${q.answerable ? "" : "(unanswerable) "}${q.asks}`);
        for (const f of q.facts) {
          const mark = f.check === "mechanical" ? (found[f.id] ? "present" : "MISSING") : "human";
          lines.push(`  - ${f.id} [${mark}] ${f.fact}`);
        }
      }
      lines.push(`\n\`\`\`text\n${reply}\n\`\`\`\n`);
    }
    writeFileSync(path, `${lines.join("\n")}\n`);
    console.log(`\n${this.unread.size} replies need a hand label (listed in ${basename(path)})`);
  }
}

const args = process.argv.slice(2);
const split = args.includes("--split") ? args[args.indexOf("--split") + 1] : "test";
const data = pipeline.load();
if (!args.includes("--report")) await runAll(data, split);
new Report(data, split).print();
