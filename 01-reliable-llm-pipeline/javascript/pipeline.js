// The pipeline: one email at a time, through four steps (extract, retrieve, draft, send), with the email's
// state saved after every step. Same behaviour as ../python/pipeline.py, where the steps, the two policies,
// and the run directory are described.
//
//   node pipeline.js RUN_DIR --split test --policy validate [--resume] [--check-outbox] [--crash]
import {
  appendFileSync, closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, renameSync, writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as llm from "./llm.js";
import { Index } from "./retrieval.js";
import * as steps from "./steps.js";
import { Tokenizer } from "./tokens.js";

const DATA = join(dirname(fileURLToPath(import.meta.url)), "..", "data");

const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const byName = (dir, ext) => Object.fromEntries(readdirSync(dir).filter((f) => f.endsWith(ext)).sort()
  .map((f) => [f.slice(0, -ext.length), readFileSync(join(dir, f), "utf8")]));

export function load() {
  return {
    settings: readJson(join(DATA, "settings.json")),
    prompts: readJson(join(DATA, "prompts.json")),
    documents: Object.fromEntries(Object.entries(byName(join(DATA, "documents"), ".md")).map(([k, v]) => [`${k}.md`, v])),
    emails: byName(join(DATA, "emails"), ".txt"),
    splits: readJson(join(DATA, "splits.json")),
  };
}

// Where a run keeps its state and its side effects.
export class Store {
  constructor(runDir) {
    this.dir = runDir;
    mkdirSync(join(runDir, "state"), { recursive: true });
  }

  state(eid) {
    const path = join(this.dir, "state", `${eid}.json`);
    return existsSync(path) ? readJson(path) : null;
  }

  save(state) {
    const path = join(this.dir, "state", `${state.email}.json`);
    writeFileSync(`${path}.tmp`, `${JSON.stringify(state, null, 1)}\n`);
    renameSync(`${path}.tmp`, path); // a crash leaves either the old state or the new one, never half of it
  }

  append(name, record) {
    const fd = openSync(join(this.dir, name), "a");
    appendFileSync(fd, `${JSON.stringify(record)}\n`);
    fsyncSync(fd);
    closeSync(fd);
  }

  lines(name) {
    const path = join(this.dir, name);
    return existsSync(path) ? readFileSync(path, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l)) : [];
  }
}

export class Pipeline {
  constructor(data, index, policy) {
    Object.assign(this, { data, index, policy, settings: data.settings, prompts: data.prompts, calls: 0 });
    this.documentation = Object.values(data.documents).join("\n\n");
  }

  // One model step: call, parse, check, and retry with the problems while the policy allows.
  async modelStep(messages, schema, maxTokens, check) {
    const attempts = [];
    for (;;) {
      const call = await llm.chat(messages, { schema, options: this.settings.chat.options, maxTokens });
      this.calls += 1;
      const [output, error] = steps.parse(call.content);
      const problems = error ? [error] : (this.policy === "validate" ? check(output) : []);
      attempts.push({ ...call, problems });
      if (!problems.length || this.policy !== "validate" || attempts.length > this.settings.retries.max_retries) {
        return { attempts, output, ok: !problems.length };
      }
      messages = steps.retryMessages(this.prompts, messages, call.content, problems);
    }
  }

  async process(eid, store, resume, checkOutbox, crash) {
    const email = this.data.emails[eid];
    const state = (resume ? store.state(eid) : null) || { email: eid, policy: this.policy, steps: {} };
    const done = state.steps;
    const finish = (status, reason = null) => {
      Object.assign(state, { status, reason });
      store.save(state);
      return state;
    };

    // 1 extract
    if (!("extract" in done)) {
      done.extract = await this.modelStep(steps.extractMessages(this.prompts, email), steps.EXTRACT_SCHEMA,
        this.settings.chat.extract_max_tokens, (output) => steps.checkExtract(output, email));
      store.save(state);
    }
    const extracted = done.extract.output;
    if (this.policy === "validate" && !done.extract.ok) {
      return this.review(eid, store, state, finish, "extract", done.extract.attempts.at(-1).problems);
    }
    const usable = extracted !== null && typeof extracted === "object" && !Array.isArray(extracted);
    if (!usable || !steps.isStringList(extracted.questions)) return finish("error", "the extraction has no usable list of questions");
    const { questions } = extracted;

    // 2 retrieve
    if (!("retrieve" in done)) {
      const chosen = await this.index.retrieve(questions);
      const excerpts = chosen.map((i) => this.index.chunks[i].text);
      const identifiers = steps.isStringList(extracted.identifiers) ? extracted.identifiers : [];
      const problems = this.policy === "validate"
        ? steps.checkRetrieve(identifiers, excerpts, this.documentation, this.settings.checks.plan_names) : [];
      done.retrieve = { chunks: chosen.map((i) => this.index.chunks[i].id), problems };
      store.save(state);
    }
    const byId = new Map(this.index.chunks.map((c) => [c.id, c]));
    const context = done.retrieve.chunks.map((c) => byId.get(c));
    if (done.retrieve.problems.length) return this.review(eid, store, state, finish, "retrieve", done.retrieve.problems);

    // 3 draft
    if (!("draft" in done)) {
      const texts = context.map((c) => c.text);
      done.draft = await this.modelStep(
        steps.draftMessages(this.prompts, email, questions, context.map((c) => [c.document, c.text])),
        steps.DRAFT_SCHEMA, this.settings.chat.draft_max_tokens, (output) => steps.checkDraft(output, texts, email));
      store.save(state);
    }
    const drafted = done.draft.output;
    if (this.policy === "validate" && !done.draft.ok) {
      return this.review(eid, store, state, finish, "draft", done.draft.attempts.at(-1).problems);
    }
    if (drafted === null || typeof drafted !== "object" || typeof drafted.reply !== "string") {
      return finish("error", "the draft has no usable reply");
    }

    // 4 send
    if ("send" in done) return state; // resumed after the send was recorded: nothing left to do
    if (checkOutbox && store.lines("outbox.jsonl").some((r) => r.email === eid)) {
      done.send = { to: "outbox", already_there: true };
      return finish("sent");
    }
    store.append("outbox.jsonl", { email: eid, reply: drafted.reply });
    if (crash && eid === this.settings.crash.email) process.exit(this.settings.crash.exit_code); // no clean-up
    done.send = { to: "outbox" };
    return finish("sent");
  }

  review(eid, store, state, finish, step, problems) {
    if (!("send" in state.steps)) {
      store.append("review.jsonl", { email: eid, step, problems });
      state.steps.send = { to: "review" };
    }
    return finish("review", `${step}: ${problems.join("; ")}`);
  }

  async run(eids, store, resume = false, checkOutbox = false, crash = false) {
    const states = [];
    for (const eid of eids) states.push(await this.process(eid, store, resume, checkOutbox, crash));
    return states;
  }
}

async function main() {
  const args = process.argv.slice(2);
  const flag = (name) => args.includes(name);
  const option = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback);
  const runDir = args[0];
  const split = option("--split", "test");
  const policy = option("--policy", "validate");
  const data = load();
  const pipeline = new Pipeline(data, await new Index().init(data.settings, data.documents, new Tokenizer()), policy);
  let states;
  try {
    states = await pipeline.run(data.splits[split], new Store(runDir), flag("--resume"), flag("--check-outbox"), flag("--crash"));
  } finally {
    if (!flag("--keep-loaded")) await llm.unload(llm.chatModel());
  }
  const counts = Object.fromEntries(["sent", "review", "error"].map((s) => [s, states.filter((x) => x.status === s).length]));
  console.log(JSON.stringify({ emails: states.length, calls: pipeline.calls, ...counts }));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main();
