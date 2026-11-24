# 04-cost-quality

Companion code for **[Reducing LLM Costs Without Destroying Quality](https://snehalagrawal.com/articles/reducing-llm-costs-without-destroying-quality/)** (Article #36).

The support assistant from [01-reliable-llm-pipeline](../01-reliable-llm-pipeline/) made cheaper in four ways, one change at a time, on the same 20 test emails. Each version is measured for what it saves and labelled for what it gets right:

| Version | The one change | The lever |
|---|---|---|
| `b0` | none: 01's pipeline as #18 and #33 ran it | |
| `v1` | retrieval budget 1,000 → 500 tokens per question | send less |
| `v2` | reply output cap 700 → 150 tokens (the median baseline reply on the development emails, rounded up) | write less |
| `v3` | `llama3.2:1b` drafts the reply; extraction stays on `llama3.2:3b` | a cheaper model |
| `v4` | v3's reply unless 01's draft check rejects it, then b0's reply | a cascade |

v4 makes no model call of its own. It is assembled from b0 and v3, which drafted from identical extractions and excerpts on all 20 emails (checked by hash). Its cost counts v3's calls plus b0's drafting call for each escalated email.

## Measured, labelled, and hypothetical

- **Measured:** model calls, prompt and output tokens per step, calls cut off at their limit (`done_reason: length`), emails with no reply, 01's draft check, 02's mechanical fact check.
- **Labelled:** each distinct reply, per question, with #33's rubric (02's worksheet and import code, unchanged). The labeller was a separate Claude model that saw only the blind worksheet and 01's documents. A second Claude model then verified every label (`verify.py`); see deviation D1.
- **Hypothetical:** dollars. The local token counts are priced at published rates checked on 2026-11-24 (`data/prices.json`). The 3B model stands in for a larger hosted model ($2 / $10 per million input / output tokens: `gpt-6.2-sol` and Claude Sonnet 5.5), the 1B model for a smaller one ($0.10 / $0.50: `gpt-6-luna` and Claude Haiku 5.5). **These are not hosted inference costs.** A hosted model would count the same text in different tokens, and answer differently.
- **Not measured:** fixed infrastructure, labelling and review effort, and what a failed email really costs downstream. The report gives a break-even for that last one instead of assuming a number.

## Results

Recorded on 2026-11-24 (runs 14:30–14:51 UTC). Labelled outcomes are from `data/final_labels.json`: blind model labels, checked by a second model (D1).

| | b0 | v1 | v2 | v3 | v4 |
|---|---|---|---|---|---|
| model calls | 40 | 40 | 40 | 40 | 47 |
| input tokens | 62,707 | 37,295 | 62,707 | 62,707 | 84,165 |
| output tokens | 4,299 | 3,571 | 3,516 | 7,717 | 9,105 |
| calls cut off at their limit | 1 | 0 | 5 | 7 | 8 |
| emails with no reply | 1 | 0 | 5 | 7 | 1 |
| labelled correct (of 20) | 7 | 5 | 5 | 3 | 3 |
| false answers (3 uncovered questions) | 3 | 3 | 2 | 1 | 2 |
| replies with a false statement | 8 | 12 | 6 | 2 | 5 |
| spend per 20 emails (hypothetical) | $0.1684 | $0.1103 | $0.1606 | $0.0326 | $0.0894 |
| spend per correct email (hypothetical) | $0.0241 | $0.0221 | $0.0321 | $0.0109 | $0.0298 |
| break-even per failed email vs b0 | | $0.029 | $0.0039 | $0.034 | $0.020 |

- **Against b0, email by email:**
  - v1 broke e02, e06 and e28, and fixed e14 (b0's draft for e14 ran to the 700-token limit).
  - v2 broke e02 and e36, both cut off by the cap.
  - v3 broke e02, e08, e28 and e36.
  - v4's outcomes are identical to v3's.

  Under the rule in [PROTOCOL.md](PROTOCOL.md), all four are rejected. With 20 emails, no significance is claimed.
- **Input was about three quarters of b0's hypothetical model spend.** Halving the retrieval budget cut the spend by about a third. The 150-token cap saved under 5%, all of it from the five replies it cut off (four inside their sources list, after a finished reply text), which still paid for 15,500 prompt tokens. Replies under the cap were word for word b0's.
- **The 1B model wrote more than twice the output** (6,421 draft tokens against 3,003). Seven drafts ran to the 700-token limit and produced nothing: three copied the excerpts into the reply, one repeated a sentence as items 6 to 19, and three listed source numbers up to 218 or 226 (`data/post_hoc.json`).
- **The cascade escalated only unfinished JSON.** 01's draft check passed all 10 v3 replies labelled wrong, so none was escalated. The 7 escalated emails got b0's replies, all wrong or missing too.
- **Spend per correct email favours v3 and v1** when a failure costs nothing extra. The break-even says how much a failure may cost before each saving stops paying: 3.4 cents for v3. The break-even doesn't depend on volume.
- **Expectations:** E1–E8 in [PROTOCOL.md](PROTOCOL.md) all held. b0 reproduced #33's `v3a` word for word (20 of 20), and v3r reproduced v3 (20 of 20).
- **The labeller vs #33's labeller:** the 19 b0 replies are #33's `v3a` replies, and the two blind labellers agreed on all 37 per-question values and all 19 false-statement flags (`data/post_hoc.json`). Both are models, so this is weak evidence.

The full report is `runs/report.txt`, regenerated by the commands below.

## Run it

Python 3.10 or later (tested with 3.12.13). The report, the tests and the labelling tools need no model. From `python/`:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # requests and python-dotenv, pinned
.venv/bin/python -m unittest -v test_cost test_report               # made-up inputs and documented examples
.venv/bin/python freeze.py --check                                   # every frozen input and module unchanged (needs 01's tokenizer.json)
.venv/bin/python report.py                                           # every number above, from data/
```

To run the experiment again, you need [Ollama](https://ollama.com) 0.40.17 with `llama3.2:3b`, `llama3.2:1b` and `nomic-embed-text` (IDs in `data/variants.json`), and 01's tokenizer in `01-reliable-llm-pipeline/data/tokenizer.json` (see 01's README). Move `data/runs.json` aside first (the export never overwrites):

```bash
.venv/bin/python run.py preflight                  # hashes, packages, Ollama version, model IDs; no model call
for n in b0dev b0 v1 v2 v3 v3r; do .venv/bin/python run.py run $n; done   # about 15 minutes in all
.venv/bin/python run.py export                     # data/runs.json
.venv/bin/python report.py
```

Each run waits for a shared lock and a quiet Ollama server, unloads models before and after, and checks the server log to confirm no other client used the server during the run. Expect the same shape, not necessarily the same digits.

### Labels

```bash
.venv/bin/python labels.py worksheet                         # worksheet/worksheet.md and labels.csv (blind)
.venv/bin/python labels.py import --labeller "..."           # data/blind_labels.json
.venv/bin/python verify.py sheet                             # worksheet/verify.md and verify.csv
.venv/bin/python verify.py import --verifier "..."           # data/final_labels.json, after a person reviews every reply
```

## How it works

- **Reuse, not copies.** 01's pipeline, prompts, retrieval, checks and labels, and 02's rubric, worksheet, label import and grader are imported from their folders. A run changes only the chat model per step (by wrapping 01's model step) and values in 01's settings.
- **Frozen first.** [PROTOCOL.md](PROTOCOL.md) fixes the runs, v2's cap rule, v4's rule, the measures, the decision rule and eight expectations before any run. `data/FROZEN.json` holds the SHA-256 of 78 files: this demo's code and data, and every input and module used from 01 and 02. `run.py` stops if any of them changed.
- **Costs never default to zero.** `cost.py` raises on a token category with no rate, on a category it doesn't know, on a count that wasn't reported, and on adding a cost category that wasn't measured. Its tests reproduce OpenAI's and Anthropic's documented usage examples.

## Files

| File | Purpose |
|---|---|
| [PROTOCOL.md](PROTOCOL.md) | Runs, rules, measures, decision rule, expectations, stop conditions, deviations |
| [data/](data/) | Variants, prices, the freeze, the exported runs and the labels; see [data/README.md](data/README.md) |
| [python/shared.py](python/shared.py) | Paths, hashing, access to 01's and 02's modules |
| [python/run.py](python/run.py) | Preflight, the runs, the export |
| [python/cost.py](python/cost.py) | Usage fields to priced categories, the five cost categories, cost per success, break-even |
| [python/analysis.py](python/analysis.py) | v4's assembly, outcomes, spend, comparisons, the decision rule, expectations E1–E6 |
| [python/report.py](python/report.py) | The report, and E7–E8 |
| [python/labels.py](python/labels.py) | The blind worksheet and its import |
| [python/verify.py](python/verify.py) | The human verification sheet and its import |
| [python/freeze.py](python/freeze.py) | Writes and checks `FROZEN.json` |
| [python/post_hoc.py](python/post_hoc.py) | After the runs (D2): the raw cut-off drafts and the agreement with #33's labeller, to `data/post_hoc.json` |
| [python/test_cost.py](python/test_cost.py), [python/test_report.py](python/test_report.py) | Tests |

## Deviations from PROTOCOL.md

- **D1, the verifier (2026-11-24).** PROTOCOL.md says a person verifies every label. At the user's request, a second, separate Claude agent did it instead.
  - **What it saw:** the blind worksheet, the verification sheet (with the proposed labels) and 01's five documents, nothing that says which version wrote a reply. It formed its own judgment of each reply before reading the proposed label.
  - **Result:** it marked all 52 replies reviewed and changed no value.
  - **Ambiguous rules it named:** a reply that only restates an uncovered question; whether answering an uncovered question is also a false statement; a correct fact with an unsupported added instruction. Only the last changes an outcome (the two emails under Limitations).
  - **What this changes:** every labelled number is a model's judgment checked by another model. `data/final_labels.json` records the verifier as such.
- **D2, post-hoc evidence (2026-11-24).** `data/runs.json` keeps no text for drafts cut off at their limit (they aren't valid JSON), and the agreement with #33's labeller isn't in `report.py`. `post_hoc.py`, written after the runs and outside the freeze, saves the raw cut-off drafts and those agreement counts to `data/post_hoc.json`. It changes no result.

## Limitations

- **Two small local models and 20 emails.** The baseline gets 7 right. This shows a method, not how hosted models compare.
- **Dollars are hypothetical,** and the ratio between the two price levels is the same at both providers on the date checked, so the two scenarios give identical numbers.
- **Each change was run once** (v3 twice). At temperature 0 the 3B baseline reproduced #33's run exactly; other settings or servers may not.
- **The labels are a model's, checked by another model** (D1), not by a person.
- **Two outcomes depend on a rubric choice.** b0's reply to e18 and v1's reply to e02 state the needed fact correctly but add an unsupported instruction ("upgrade to a plan that supports more webhooks"; "invite her in the identity provider"). #33's rule counts any false or unsupported statement as wrong. Counted as correct instead, b0 would have 8 correct and v1 6, and every version would still fail the decision rule.
