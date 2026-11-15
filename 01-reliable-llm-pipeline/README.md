# 01-reliable-llm-pipeline

Companion code for **[Building Reliable LLM Pipelines](https://snehalagrawal.com/articles/building-reliable-llm-pipelines/)** (Article #18).

A support assistant that answers customer emails in four steps:

```text
email ──► 1 extract ──► 2 retrieve ──► 3 draft ──► 4 send
          model call    RRF hybrid     model call   reply written to the outbox
          questions,    search over    a reply that (nothing is emailed), or the
          identifiers   the docs       cites what   email goes to a review queue
                                       it used
```

Every step's output is saved to a state file before the next step starts. The demo asks four questions:

1. **Errors compound.** How well does each step do on its own, and how well does the chain do end to end?
2. **Checks between steps.** What reaches the outbox with no checks, with checks, and with checks and retries?
3. **Retries.** What does retrying a failed step with the error message fix, and what does it cost?
4. **Crash recovery.** After a crash in the middle of a run, what does restarting cost, compared with resuming from the saved state?

It deliberately stays basic. Retries have a fixed limit and no backoff, and there is no circuit breaker; the series plans those for Article #37. Recovery is a saved state per email plus one check of the outbox before writing, with no workflow engine or idempotency keys; the series plans those for Article #38.

The model is a small local one, `llama3.2:3b`. Its replies are often wrong, which makes the failures easy to see. The results describe this pipeline with this model, not what a larger model would do.

## The experiment, and what was fixed when

1. **The test material came first.** It was committed before any pipeline code (commit 08bf05c): five documents, 40 customer emails, their labels, the scoring rules, and the development/test split. See [data/README.md](data/README.md).
2. **The settings came next.** `data/settings.json` was written before the first run: retrieval, budgets, the model and its options, the checks, the retry limit, and the crash point. Retrieval is rag-engineering's, not tuned here: [structure-headings chunks](https://github.com/SnehalAgrawal/rag-engineering/tree/main/04-chunking), [RRF of vector and BM25](https://github.com/SnehalAgrawal/rag-engineering/tree/main/05-hybrid-search), and 1,000 tokens per question.
3. **The prompts and the checks were developed on the 20 development emails only.** Three things changed, each because a development run showed a problem:
   - Prompt v1's extraction instructions gave example identifiers ("SSO-104", "rate_limited"), and the model copied them into its output. v2 removed them.
   - v2 still named the plan names, and the model listed "Basic" and "Pro" for 11 of 20 emails that don't mention them. v3 removed them too. v3's drafting instructions also ask for direct, polite answers to the listed questions only, because v2's drafts copied unrelated excerpts and repeated the customer's email.
   - The value check split "1st" and "HMAC-SHA256" into the numbers "1" and "256" and flagged them. It now compares a word that contains digits as a whole.

   The development replies were read but not hand-labelled.
4. **The test emails were run once per language,** with prompts v3. Python and JavaScript sent the same requests and got the same outputs, so the reports are identical. Every test reply was read and hand-labelled ([data/hand_labels.json](data/hand_labels.json)). That is 39 distinct replies:
   - one per email from the chain with no checks, except e14, whose draft never became valid JSON;
   - one per email from drafting on its own.

   Every reply the checked runs sent is word for word one of these. Statements in a correct reply that go beyond the labelled facts were checked against the documents.
5. **One bug was fixed after the first recovery run.** On resume, the pipeline wrote a new outbox entry even for emails whose send was already recorded. Only the recovery experiment was run again: experiments 1 to 3 never resume, so the fix doesn't change them.

## Results (the 20 test emails)

A reply is **correct** when every fact the labels list for the email's answerable questions is stated correctly, every unanswerable question is said to be not covered, and nothing false is stated.

### 1. Errors compound

| Step, given correct input | Emails where it did its job |
|---|---|
| Extraction: questions paired with the labels | 18 of 20 |
| Retrieval from the labelled questions: evidence for every fact | 20 of 20 |
| Drafting from the labelled questions and gold excerpts: a correct reply | 10 of 20 |

If the steps failed independently, these rates would give 9.0 correct replies in 20 (0.9 × 1.0 × 0.5). The chain, run end to end with no checks, gave **7 of 20**. Of the 13 emails it got wrong, 1 first went wrong at extraction, 1 at retrieval, and 11 at drafting. One of the 13 got no reply at all: its draft wasn't valid JSON.

### 2. What reaches the outbox

| Policy | Sent | Correct | Wrong | Not sent / held back | Of those, unchecked reply wrong or missing | Of those, unchecked reply correct |
|---|---|---|---|---|---|---|
| No checks | 19 | 7 | 12 | 1 (error) | 1 | 0 |
| Checks, no retries | 15 | 5 | 10 | 5 | 3 | 2 |
| Checks and retries | 18 | 6 | 12 | 2 | 1 | 1 |

On the test emails, the checks stopped none of the 12 wrong replies that the unchecked pipeline sent. The 12 were wrong in ways the checks don't look for:
- confident answers to all 3 test questions the documentation doesn't cover ("there is no discount for paying three years upfront", "the mobile app does not work offline");
- false yes/no claims ("the app is available in Italian");
- facts that were left out.

None of these contained a number or code missing from the excerpts the reply cited, which is what the value check looks for.

The checks did catch two other things:
- **e14:** a draft that repeated "5, " in its list of sources until it hit the 700-token cap, so it wasn't valid JSON.
- **Bad extractions:** four extractions listed identifiers that aren't in the email ("Admin role", "3 years upfront").

Retrying the four extractions fixed their identifiers. For three of the four, the questions didn't change, so the reply didn't either; two of those three replies were wrong. The fourth, e28, was stopped by the retrieval check, which held back a correct reply. The retried extraction had listed "API key", and the excerpt that answers the question says "API keys": the check compares whole words, so the plural didn't count.

During development (not counted above), the value check did catch invented values. A reply put the upgrade cost at "$15" instead of $7.50; another invented "99.99% uptime". A retry with the error message corrected both, though the second reply still didn't say that the SLA wasn't covered.

### 3. Retries

| Step | First attempts that failed | Fixed by retry 1 | Fixed by retry 2 | Still failing | Extra calls |
|---|---|---|---|---|---|
| Extract | 4 | 4 | 0 | 0 | 4 |
| Draft | 1 | 0 | 0 | 1 | 2 |

Each of the 5 failed first requests was sent again unchanged, without the error message: all 5 outputs were identical to the first attempt (temperature 0, seed 1, model freshly loaded). Model calls for the 20 emails:

- no checks: 40;
- checks, no retries: 36 (stopping early saves calls);
- checks and retries: 45.

### 4. Crash recovery

The checked pipeline (checks and retries) runs over the test emails as a separate process. It exits abruptly (exit code 3) right after the reply to e24 is written to the outbox, before e24's state records the send. By then it had started 12 of the 20 emails and made 29 model calls; the outbox held 11 replies and the review queue 1 email. Each recovery starts from its own copy of what the crash left. The outbox survives in every case, because it stands for email already sent.

| Recovery | Model calls | Outbox entries | Emails sent twice | Review entries written twice |
|---|---|---|---|---|
| Restart: run every email again, ignoring the saved state | 45 | 29 | 11 | 1 |
| Resume from the saved state | 16 | 19 | 1 (e24) | 0 |
| Resume, and check the outbox before writing | 16 | 18 | 0 | 0 |

A restart costs a full run, 45 calls, because none of the 29 calls already made can be reused. It also sends every reply already sent a second time. Resuming makes only the 16 calls that the 8 unstarted emails need, but it still sends e24 twice: its saved state ends before the send, because the crash came between the outbox write and the state write. Looking in the outbox before writing closes that gap here. With more than one writer, or an outbox that isn't a local file, it is not enough; the series plans that for Article #38.

Every reply in every recovered outbox is identical to the reply the experiment's checked run produced for that email, so the duplicates were identical copies. That was observed in this setup, not guaranteed: a model call repeated with the same input isn't always reproducible (see [rag-engineering/06-reranking](https://github.com/SnehalAgrawal/rag-engineering/tree/main/06-reranking) on Ollama's prompt cache). The saved state is what makes the result of a finished step certain.

## Files

| File | What it does |
|---|---|
| `data/documents/`, `data/emails/`, `data/labels.json`, `data/splits.json` | The frozen test material ([data/README.md](data/README.md)) |
| `data/settings.json` | Retrieval, the model and its options, the checks, the retry limit, and the crash point |
| `data/prompts.json` | The extraction, drafting, and retry prompts (v3) |
| `data/hand_labels.json` | A verdict for every test reply, keyed by a hash of the exact text, with a note for each one that is wrong or has something worth knowing |
| `pipeline.*` | The four steps, the two policies (`none`, `validate`), the saved state, the outbox, and the review queue; runs one split from the command line |
| `steps.*` | The prompts as messages, and the checks between steps |
| `retrieval.*` | Chunking, embeddings, and RRF retrieval within the budgets |
| `score.*` | Scoring against the labels and the hand labels |
| `experiments.*` | Experiments 1 to 3: the two pipeline runs, the steps on their own, and the repeated requests; prints the report |
| `recovery.*` | Experiment 4: a real crash and three recoveries, each a separate process |
| `check_data.*` | Checks the test material for consistency |
| `chunkers.*`, `search.*`, `tokens.*`, `llm.*` | From rag-engineering, reduced to what this demo uses (`llm.*` is rewritten for JSON-schema output) |

## Prerequisites

- Python 3.10+ **or** Node.js 18.2+ (tested with Python 3.12 and Node.js 24)
- [Ollama](https://ollama.com/download) with `llama3.2:3b` and `nomic-embed-text`
- The Llama 3.2 tokenizer in `data/tokenizer.json`, used to count chunk tokens for the budgets: see [rag-engineering/04-chunking: Get the tokenizer](https://github.com/SnehalAgrawal/rag-engineering/tree/main/04-chunking#get-the-tokenizer)

## How to run

```bash
cd python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python check_data.py                  # no model calls
python experiments.py --split test    # about 10 minutes; --report reprints from the saved runs
python recovery.py                    # about 10 minutes
```

```bash
cd javascript
npm install
node check_data.js
node experiments.js --split test
node recovery.js
```

Runs are saved in `runs/python/` or `runs/javascript/`; they aren't committed. A run that produces a reply without a hand label lists it in `runs/<language>/<split>-to-read.md`. Expect the same shape of results, not necessarily the same replies: a different Ollama version or machine can change the model's output.

## Setup used for the published numbers

| | |
|---|---|
| Machine | Apple M4 Pro (24 GB), macOS 26.6.2 |
| Ollama | 0.40.16, `/api/chat` with `format` (a JSON schema) and `/api/embed` |
| Chat model | `llama3.2:3b`, ID `a80c4f17acd5` (Q4_K_M), temperature 0, seed 1, `num_ctx` 8192, at most 400 output tokens for extraction and 700 for a draft |
| Embedding model | `nomic-embed-text`, ID `0a109f422b47`, prefixes `search_document: ` and `search_query: ` |
| Retrieval | structure-headings chunks (98, at most 512 tokens), RRF (k = 60) of cosine similarity and BM25 (k1 1.2, b 0.75), 1,000 tokens per question and 3,000 per email, in Llama 3.2 tokens |
| Prompts | v3 (`data/prompts.json`) |
| Runtimes | Python 3.12.13, Node.js 24.16.0 |
