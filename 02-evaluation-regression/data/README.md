# Data

| File | What it is |
|---|---|
| `replies.json` | The 39 test replies that [01-reliable-llm-pipeline](../../01-reliable-llm-pipeline/) hand-labelled for its article: 19 from the pipeline end to end with no checks (`chain`; e14 produced none), and 20 from drafting alone with every evidence passage in context (`perfect_inputs`). Exported once from 01's local runs by [`../python/export_replies.py`](../python/export_replies.py). |
| `FROZEN.json` | The SHA-256 of every input and every file of code that decides a result, written once by [`../python/freeze.py`](../python/freeze.py) before the first report. |
| `prompts-v4.json` | 01's v3 prompts with the version label `v4` and one drafting sentence replaced ([`../PROTOCOL-B.md`](../PROTOCOL-B.md)). |
| `FROZEN-B.json` | Part B's freeze: every input (01's prompts, settings, documents, emails, tokenizer and pipeline modules, Part A's `FROZEN.json`, the v4 prompt, the pinned requirements) and every file of Part B code, with the Ollama version and model IDs every run must use. Written once by [`../python/freeze_b.py`](../python/freeze_b.py) before any Part B model call. |
| `replies-b.json` | Every Part B run (`v3a`, `v3b`, `v4dev`, `v4test`): its run record, and per email the extraction, retrieved chunk ids, reply, label key and SHA-256. Also #18's stored chain run, for the reproduction comparison. Exported once by `run_b.py export`. |
| `blind_labels.json` | The blind labels for all 58 distinct test replies, imported from `../worksheet/labels.csv` by `import_labels.py`. Written by a separate Claude agent, not the user (the README's deviation D1). Format in [`../PROTOCOL.md`](../PROTOCOL.md). |

Everything else is read from 01, unchanged: the emails' labels (`labels.json`), the split (`splits.json`), and 01's hand labels (`hand_labels.json`).

## Where the replies came from

01's `runs/` folder isn't committed, so the export can't be repeated from the repository. It can be checked: each entry's `key` is 01's label key (the first 16 hex digits of SHA-256 over "email id, newline, reply"), and [`../python/check.py`](../python/check.py) confirms that every key appears in 01's committed `hand_labels.json`. A reply whose text differed by one character would have a key that isn't there.

The replies were produced for 01's published results:

- prompts v3;
- `llama3.2:3b` (ID `a80c4f17acd5`) and `nomic-embed-text` (ID `0a109f422b47`);
- Ollama 0.40.16;
- temperature 0, seed 1, `num_ctx` 8192.

01's README has the full setup.
