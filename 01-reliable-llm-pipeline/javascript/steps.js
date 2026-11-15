// The pipeline's model steps, and the checks that run between steps. Same behaviour as ../python/steps.py,
// where they are described. Each check returns a list of problems in plain words; an empty list means the
// output passed. The same words are sent back to the model when a step is retried.

export const EXTRACT_SCHEMA = {
  type: "object",
  properties: { questions: { type: "array", items: { type: "string" } }, identifiers: { type: "array", items: { type: "string" } } },
  required: ["questions", "identifiers"],
};
export const DRAFT_SCHEMA = {
  type: "object",
  properties: { reply: { type: "string" }, sources: { type: "array", items: { type: "integer" } } },
  required: ["reply", "sources"],
};

// ---------------------------------------------------------------------------------------------- matching

export function normalize(text) {
  return text.toLowerCase().replace(/’|‘/g, "'").replace(/“|”/g, '"')
    .replace(/–|—/g, "-")
    .replace(/(?<=\d),(?=\d{3}\b)/g, "")
    .replace(/\s+/g, " ");
}

const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// The phrase appears in the text as a whole word or phrase: no letter or digit directly before or after.
export function contains(text, phrase) {
  return new RegExp(`(?<![a-z0-9])${escape(normalize(phrase).trim())}(?![a-z0-9])`).test(normalize(text));
}

const EMAIL_ADDRESS = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/g;
const CODE = /\b[A-Z][A-Z0-9]*-[0-9]+\b/g;
const SNAKE = /\b[a-z0-9]+(?:_[a-z0-9]+)+\b/g;
const NUMBER = /[A-Za-z]*[0-9]+(?:[.,][0-9]+)*[A-Za-z]*/g; // a word with digits, whole: "16th", "SHA256", "v2"

// The values a reply states: email addresses, codes such as SSO-101, snake_case identifiers, and numbers
// (taken with any letters joined to them, so "16th", "SHA256", and "v2" are compared whole). Citation markers such as [2] and list numbers at the start of a
// line are not values.
export function values(reply) {
  let text = reply.replace(/\[[0-9]+(?:\s*,\s*[0-9]+)*\]/g, " ").replace(/^\s*[0-9]+[.)]\s/gm, " ");
  const found = [];
  for (const pattern of [EMAIL_ADDRESS, CODE, SNAKE]) {
    found.push(...(text.match(pattern) || []));
    text = text.replace(pattern, " ");
  }
  found.push(...(text.match(NUMBER) || []).map((n) => n.replace(/(?<=[0-9]),(?=[0-9]{3}\b)/g, "")));
  return [...new Set(found)];
}

// ---------------------------------------------------------------------------------------------- messages

export function parse(content) {
  try {
    return [JSON.parse(content), null];
  } catch {
    return [null, "the output isn't valid JSON"];
  }
}

export function extractMessages(prompts, email) {
  const p = prompts.extract;
  return [{ role: "system", content: p.system }, { role: "user", content: p.user.replaceAll("{email}", () => email) }];
}

// excerpts: [document name, chunk text] pairs, numbered from 1 in this order.
export function draftMessages(prompts, email, questions, excerpts) {
  const p = prompts.draft;
  const numbered = questions.map((q, k) => `${k + 1}. ${q}`).join("\n");
  const blocks = excerpts.map(([doc, text], k) => `[${k + 1}] (${doc})\n${text}`).join("\n\n");
  const user = p.user.replaceAll("{email}", () => email).replaceAll("{questions}", () => numbered)
    .replaceAll("{excerpts}", () => blocks);
  return [{ role: "system", content: p.system }, { role: "user", content: user }];
}

export function retryMessages(prompts, messages, previous, problems) {
  const feedback = prompts.retry.replaceAll("{problems}", () => problems.map((p) => `- ${p}`).join("\n"));
  return [...messages, { role: "assistant", content: previous }, { role: "user", content: feedback }];
}

// ---------------------------------------------------------------------------------------------- checks

export const isStringList = (v) => Array.isArray(v) && v.every((x) => typeof x === "string");
const isObject = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

export function checkExtract(output, email) {
  if (!isObject(output)) return ["the output isn't a JSON object"];
  const problems = [];
  const { questions, identifiers } = output;
  if (!isStringList(questions)) problems.push('"questions" must be a list of strings');
  else if (!questions.length) problems.push("no questions were found; every customer email asks at least one");
  else if (questions.some((q) => !q.trim())) problems.push("a question is empty");
  if (!isStringList(identifiers)) problems.push('"identifiers" must be a list of strings');
  else {
    for (const identifier of identifiers) {
      if (!identifier.trim() || !contains(email, identifier)) problems.push(`the identifier "${identifier}" doesn't appear in the email`);
    }
  }
  return problems;
}

export function checkRetrieve(identifiers, excerpts, documentation, planNames) {
  const plans = new Set(planNames.map((p) => normalize(p)));
  return identifiers
    .filter((i) => !plans.has(normalize(i).trim()) && contains(documentation, i) && !excerpts.some((t) => contains(t, i)))
    .map((i) => `the identifier "${i}" is in the documentation but not in the retrieved excerpts`);
}

export function checkDraft(output, excerpts, email) {
  if (!isObject(output)) return ["the output isn't a JSON object"];
  let { reply } = output;
  const { sources } = output;
  const problems = [];
  if (typeof reply !== "string" || !reply.trim()) {
    problems.push('"reply" must be a non-empty string');
    reply = "";
  }
  const cited = [];
  if (!Array.isArray(sources) || !sources.every((s) => Number.isInteger(s))) {
    problems.push('"sources" must be a list of excerpt numbers');
  } else {
    for (const s of sources) {
      if (s >= 1 && s <= excerpts.length) cited.push(excerpts[s - 1]);
      else problems.push(`source ${s} doesn't exist; the excerpts are numbered 1 to ${excerpts.length}`);
    }
  }
  for (const value of values(reply)) {
    if (![...cited, email].some((t) => contains(t, value))) {
      problems.push(`the reply says "${value}", which isn't in the excerpts it cites or in the customer's email`);
    }
  }
  return problems;
}
