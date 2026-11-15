// Scoring against the labels in data/labels.json, with the rules in data/README.md, and the hand labels in
// data/hand_labels.json. Same behaviour as ../python/score.py, where a hand label is described.
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { contains, normalize } from "./steps.js";

const DATA = join(dirname(fileURLToPath(import.meta.url)), "..", "data");

export class Scorer {
  constructor() {
    this.labels = JSON.parse(readFileSync(join(DATA, "labels.json"), "utf8")).emails;
    const path = join(DATA, "hand_labels.json");
    this.hand = existsSync(path) ? JSON.parse(readFileSync(path, "utf8")).replies : {};
  }

  questions(eid) {
    return this.labels[eid].questions;
  }

  // Pair extracted questions with labelled ones by their match terms (data/README.md).
  extraction(eid, extracted) {
    const labelled = this.questions(eid);
    const covered = new Map(labelled.map((q) => [q.id, false]));
    const unpaired = [];
    for (const text of extracted) {
      const hits = labelled.filter((q) => q.match.some((t) => text.toLowerCase().includes(t)));
      for (const q of hits) covered.set(q.id, true);
      if (!hits.length) unpaired.push(text);
    }
    const missed = [...covered].filter(([, ok]) => !ok).map(([id]) => id);
    return { ok: !missed.length && !unpaired.length, missed, unpaired };
  }

  identifiers(eid, found) {
    const a = new Set(found.map((i) => normalize(i).trim()));
    const b = new Set(this.labels[eid].identifiers.map((i) => normalize(i).trim()));
    return a.size === b.size && [...a].every((x) => b.has(x));
  }

  static supported(fact, texts) {
    return fact.evidence.some((e) => texts.some((t) => t.includes(e.text)));
  }

  // Every fact of every answerable question has an evidence passage whole inside a retrieved chunk.
  retrieval(eid, texts) {
    const missing = this.questions(eid).flatMap((q) => q.facts).filter((f) => !Scorer.supported(f, texts)).map((f) => f.id);
    return { ok: !missing.length, missing };
  }

  mechanical(eid, reply) {
    return Object.fromEntries(this.questions(eid).flatMap((q) => q.facts).filter((f) => f.check === "mechanical")
      .map((f) => [f.id, f.any_of.some((a) => contains(reply, a))]));
  }

  static key(eid, reply) {
    return createHash("sha256").update(`${eid}\n${reply}`, "utf8").digest("hex").slice(0, 16);
  }

  // "correct", "wrong", or null if the reply hasn't been read yet.
  verdict(eid, reply) {
    const label = this.hand[Scorer.key(eid, reply)];
    return label ? label.verdict : null;
  }
}
