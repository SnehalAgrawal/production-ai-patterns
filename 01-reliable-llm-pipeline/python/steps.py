"""
The pipeline's model steps, and the checks that run between steps.

  extract   the email -> {"questions": [...], "identifiers": [...]}
  draft     the email, the questions, and numbered excerpts -> {"reply": "...", "sources": [excerpt numbers]}

Each check returns a list of problems in plain words; an empty list means the output passed. The same words
are sent back to the model when a step is retried.
"""
import json
import math
import re

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {"type": "string"}},
                   "identifiers": {"type": "array", "items": {"type": "string"}}},
    "required": ["questions", "identifiers"],
}
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, "sources": {"type": "array", "items": {"type": "integer"}}},
    "required": ["reply", "sources"],
}

# ------------------------------------------------------------------------------------------- matching


def normalize(text: str) -> str:
    """Lowercase, straight quotes, hyphens for dashes, no commas between digits, single spaces (data/README.md)."""
    text = text.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    return re.sub(r"\s+", " ", text)


def contains(text: str, phrase: str) -> bool:
    """The phrase appears in the text as a whole word or phrase: no letter or digit directly before or after."""
    pattern = r"(?<![a-z0-9])" + re.escape(normalize(phrase).strip()) + r"(?![a-z0-9])"
    return re.search(pattern, normalize(text)) is not None


EMAIL_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
CODE = re.compile(r"\b[A-Z][A-Z0-9]*-[0-9]+\b")
SNAKE = re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b")
NUMBER = re.compile(r"[A-Za-z]*[0-9]+(?:[.,][0-9]+)*[A-Za-z]*")  # a word with digits, whole: "16th", "SHA256", "v2"


def values(reply: str) -> list[str]:
    """The values a reply states: email addresses, codes such as SSO-101, snake_case identifiers, and numbers
    (taken with any letters joined to them, so "16th", "SHA256", and "v2" are compared whole).

    Citation markers such as [2] and list numbers at the start of a line are not values.
    """
    text = re.sub(r"\[[0-9]+(?:\s*,\s*[0-9]+)*\]", " ", reply)
    text = re.sub(r"(?m)^\s*[0-9]+[.)]\s", " ", text)
    found = []
    for pattern in (EMAIL_ADDRESS, CODE, SNAKE):
        found += pattern.findall(text)
        text = pattern.sub(" ", text)
    found += [re.sub(r"(?<=[0-9]),(?=[0-9]{3}\b)", "", n) for n in NUMBER.findall(text)]
    return list(dict.fromkeys(found))


# ------------------------------------------------------------------------------------------- messages


def parse(content: str) -> tuple[object, str | None]:
    try:
        return json.loads(content), None
    except json.JSONDecodeError:
        return None, "the output isn't valid JSON"


def extract_messages(prompts: dict, email: str) -> list[dict]:
    p = prompts["extract"]
    return [{"role": "system", "content": p["system"]}, {"role": "user", "content": p["user"].replace("{email}", email)}]


def draft_messages(prompts: dict, email: str, questions: list[str], excerpts: list[tuple[str, str]]) -> list[dict]:
    """excerpts: (document name, chunk text) pairs, numbered from 1 in this order."""
    p = prompts["draft"]
    numbered = "\n".join(f"{k}. {q}" for k, q in enumerate(questions, 1))
    blocks = "\n\n".join(f"[{k}] ({doc})\n{text}" for k, (doc, text) in enumerate(excerpts, 1))
    user = p["user"].replace("{email}", email).replace("{questions}", numbered).replace("{excerpts}", blocks)
    return [{"role": "system", "content": p["system"]}, {"role": "user", "content": user}]


def retry_messages(prompts: dict, messages: list[dict], previous: str, problems: list[str]) -> list[dict]:
    feedback = prompts["retry"].replace("{problems}", "\n".join(f"- {p}" for p in problems))
    return messages + [{"role": "assistant", "content": previous}, {"role": "user", "content": feedback}]


# ------------------------------------------------------------------------------------------- checks


def is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def check_extract(output: object, email: str) -> list[str]:
    if not isinstance(output, dict):
        return ["the output isn't a JSON object"]
    problems = []
    questions, identifiers = output.get("questions"), output.get("identifiers")
    if not is_string_list(questions):
        problems.append('"questions" must be a list of strings')
    elif not questions:
        problems.append("no questions were found; every customer email asks at least one")
    elif any(not q.strip() for q in questions):
        problems.append("a question is empty")
    if not is_string_list(identifiers):
        problems.append('"identifiers" must be a list of strings')
    else:
        for identifier in identifiers:
            if not identifier.strip() or not contains(email, identifier):
                problems.append(f'the identifier "{identifier}" doesn\'t appear in the email')
    return problems


def check_retrieve(identifiers: list[str], excerpts: list[str], documentation: str, plan_names: list[str]) -> list[str]:
    plans = {normalize(p) for p in plan_names}
    return [f'the identifier "{i}" is in the documentation but not in the retrieved excerpts'
            for i in identifiers
            if normalize(i).strip() not in plans and contains(documentation, i) and not any(contains(t, i) for t in excerpts)]


def check_draft(output: object, excerpts: list[str], email: str) -> list[str]:
    if not isinstance(output, dict):
        return ["the output isn't a JSON object"]
    reply, sources = output.get("reply"), output.get("sources")
    problems = []
    if not isinstance(reply, str) or not reply.strip():
        problems.append('"reply" must be a non-empty string')
        reply = ""
    cited = []
    # Any whole number counts (3 or 3.0), as JavaScript's JSON.parse can't tell them apart.
    whole = (isinstance(sources, list)
             and all(isinstance(s, (int, float)) and not isinstance(s, bool) and math.isfinite(s) and s == int(s)
                     for s in sources))
    if not whole:
        problems.append('"sources" must be a list of excerpt numbers')
    else:
        for s in (int(s) for s in sources):
            if 1 <= s <= len(excerpts):
                cited.append(excerpts[s - 1])
            else:
                problems.append(f"source {s} doesn't exist; the excerpts are numbered 1 to {len(excerpts)}")
    for value in values(reply):
        if not any(contains(t, value) for t in cited + [email]):
            problems.append(f'the reply says "{value}", which isn\'t in the excerpts it cites or in the customer\'s email')
    return problems
