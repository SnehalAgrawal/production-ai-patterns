"""
One-time export of the 39 hand-labelled test replies from 01's local runs into data/replies.json.

01's runs/ folder is not committed, so readers can't run this script. It is kept to show exactly where each
reply came from. check.py verifies the result against what is committed: every reply's key appears in 01's
data/hand_labels.json, so these are the exact texts that were read and labelled for 01's article.

  chain            01-reliable-llm-pipeline/runs/python/test-none/state/<email>.json, steps.draft.output.reply
  perfect_inputs   01-reliable-llm-pipeline/runs/python/test-isolated/<email>.json, output.reply

Run once: python export_replies.py
"""
import json
import sys

from common import BASELINE, CANDIDATE, DATA, SOURCE, rel, reply_key, sha256_text, test_emails


def entry(eid: str, arm: str, reply: object, source: str, reason: str | None = None) -> dict:
    if not isinstance(reply, str):
        return {"email": eid, "arm": arm, "reply": None, "key": None, "sha256": None, "source": source,
                "missing": reason or "no reply"}
    return {"email": eid, "arm": arm, "reply": reply, "key": reply_key(eid, reply), "sha256": sha256_text(reply),
            "source": source}


def main() -> None:
    out = DATA / "replies.json"
    if out.exists():
        sys.exit(f"{rel(out)} already exists; the export runs once.")
    if not (SOURCE / "runs" / "python").exists():
        sys.exit("01's runs/python folder is missing.")
    chain, alone = [], []
    for eid in sorted(test_emails()):
        source = f"runs/python/test-none/state/{eid}.json"
        state = json.loads((SOURCE / source).read_text())
        output = state["steps"]["draft"]["output"]
        reply = output.get("reply") if isinstance(output, dict) else None
        chain.append(entry(eid, BASELINE, reply, source, state.get("reason")))

        source = f"runs/python/test-isolated/{eid}.json"
        record = json.loads((SOURCE / source).read_text())
        output = record["output"]
        reply = output.get("reply") if isinstance(output, dict) else None
        alone.append(entry(eid, CANDIDATE, reply, source))
    document = {
        "_comment": (
            "The 39 test replies hand-labelled for 01-reliable-llm-pipeline (Article #18), exported once from 01's "
            "local runs by export_replies.py. 'key' is 01's label key (score.py); 'sha256' is over the reply text "
            "alone; 'source' is relative to 01-reliable-llm-pipeline/. A reply of null means the arm produced none."
        ),
        "produced_by": {
            "demo": "01-reliable-llm-pipeline (published results; code at commit 0f51f32)",
            "prompts": "v3 (01's data/prompts.json)",
            "chat_model": "llama3.2:3b, ID a80c4f17acd5 (Q4_K_M)",
            "embedding_model": "nomic-embed-text, ID 0a109f422b47",
            "ollama": "0.40.16",
            "options": "temperature 0, seed 1, num_ctx 8192 (01's data/settings.json)",
            "split": "test (20 emails)",
        },
        "replies": chain + alone,
    }
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {rel(out)}: {sum(e['reply'] is not None for e in chain)} {BASELINE} replies, "
          f"{sum(e['reply'] is not None for e in alone)} {CANDIDATE} replies")


if __name__ == "__main__":
    main()
