# Protocol: 04-cost-quality

Written on 2026-11-24, before any run of this demo. `data/FROZEN.json` holds the SHA-256 of this file, the inputs and the code that decides a result. `run.py` refuses to run if any of them changed. Changes after the freeze are listed under **Deviations**, with the reason; nothing below is edited after a result exists.

## Question

Each of four cheaper versions of the same support assistant changes one thing. For each one:
- what does it save, in model calls and tokens?
- which emails does it break or fix, compared with the baseline on the same 20 test emails?
- at what downstream cost per failed email does the saving stop paying for itself?

## The assistant, and what stays fixed

[01-reliable-llm-pipeline](../01-reliable-llm-pipeline/): extract the questions, retrieve excerpts (RRF hybrid search), draft a reply that cites them.
- **Fixed for every run:** 01's prompts v3, emails, documents, labels and retrieval code, imported unchanged.
- **Policy:** `none`. Every reply is sent as the model wrote it, as in #18's chain run and #33's runs.
- **Model options:** temperature 0, seed 1, `num_ctx` 8192.
- **Server and models:** Ollama 0.40.17, with `llama3.2:3b` (a80c4f17acd5), `llama3.2:1b` (baf6a787fdff) and `nomic-embed-text` (0a109f422b47).

## Runs, in this order

| Run | Split | Change from b0 | Labelled |
|---|---|---|---|
| `b0dev` | dev | none; only sets v2's cap | no |
| `b0` | test | none (the baseline) | yes |
| `v1` | test | retrieval budget 1,000 → 500 tokens per question, 3,000 → 1,500 per email | yes |
| `v2` | test | drafting output cap 700 → the cap rule below | yes |
| `v3` | test | drafting model `llama3.2:1b`; extraction stays on `llama3.2:3b` | yes |
| `v3r` | test | v3 again, for text comparison only | no |

**v2's cap rule.** The cap is the median output tokens of b0dev's draft calls, rounded up to the next multiple of 10. It is computed by `run.py` from b0dev's records when v2 starts, and recorded in v2's `run.json`. This is the kind of number someone picks from a dashboard of typical reply lengths. No test email is looked at to set it.

**V4: the cascade.** V4 is assembled by `analysis.py` with no model call:
- for each email, it takes v3's reply when 01's draft check passes v3's draft;
- otherwise it takes b0's reply (an **escalation**), and the email's calls are v3's calls plus b0's draft call.

This reuse is valid only if b0 and v3 drafted from identical inputs (extraction and chunk ids), which holds when extraction is deterministic. It is checked by hash for every escalated email, and V4 is not computed if any differ. The escalation signal is 01's draft check exactly as #18 defined it: JSON with a reply and valid sources, and every value in the reply found in the excerpts it cites or the email.

Each run name is used once. A run takes the shared Ollama lock (`$TMPDIR/snehalagrawal-ollama.lock`, never taken over). It waits for 60 seconds with no client and no server-log change, unloads any loaded model before the run and the run's models after, and compares its model calls with the `/api/chat` lines in the server log for its window.

## What is measured, and how each number is labelled

- **Measured** (from each call's Ollama record):
  - model calls per step and model;
  - prompt and output tokens per step;
  - `done_reason` (a cut-off call says `length`);
  - emails without a reply;
  - 01's draft check result;
  - 02's mechanical fact check verdict (pass, fail, not gradeable, no reply).
- **Labelled.** Each distinct reply gets a per-question label with #33's rubric (02's worksheet and import, unchanged):
  - correct, wrong, omitted or declined per answerable question;
  - declined or answered per question the documentation doesn't cover;
  - a false-statement flag.
  The email's outcome uses 02's rule. An email with no reply is a failure.
- **Hypothetical (spend).** Token counts × the published per-million-token rates in `data/prices.json`, checked 2026-11-24:
  - `llama3.2:3b` stands in for a provider's larger model, and `llama3.2:1b` for its smaller one;
  - query embeddings are priced at a published embedding rate, with tokens counted by 01's Llama 3.2 tokenizer (an approximation).

  These are not hosted inference costs. A hosted model would tokenize the text differently and answer differently.
- **Derived.**
  - Spend per email and per correct email.
  - The break-even downstream cost E per failed email against b0. For a cheaper version with more failures, E* = spend saved ÷ extra failures, and the version costs less overall only while E < E*.
- **Not measured:** fixed infrastructure (hosting, vector storage, workers, observability), labelling and verification effort, and the real downstream cost of a failure. The report names them and never adds them as zero.

## Labelling

1. `labels.py worksheet` writes every distinct reply of b0, v1, v2 and v3 (v4 reuses them) to a blind worksheet. It uses neutral ids and shuffled order (seed 36), and shows no run, check verdict or earlier label.
2. A separate Claude agent labels it (the same arrangement as 02's deviation D1). It sees only the worksheet, `labels.csv` and 01's five documents, and nothing about runs or expectations.
3. A person verifies every label (`verify.py`). Flagged replies are listed first:
   - a different outcome from #33's blind label for the same text;
   - a check that disagrees with the label;
   - a note that sounds unsure;
   - an email whose outcome differs between versions.

   Only verified labels (`data/final_labels.json`) are final. Until then, every labelled number is reported as **unverified**.

## Decision rule (set now, applied to the results)

On these 20 emails, a version would be adopted over b0 only if all of these hold:
- it breaks no email that b0 answers correctly;
- it gives no more false answers to the three questions the documentation doesn't cover;
- it leaves no more emails without a reply.

Otherwise it is rejected, and the report gives the break-even E. With 20 emails this is a teaching rule, not a statistical test. No significance is claimed, and per-email changes are listed by name.

## Expectations (written before any run)

- **E1.** b0 reproduces #33's `v3a` on all 20 test emails: same extraction, same chunks, same reply text.
- **E2.** v1's extraction is identical to b0's on all 20 emails. No email's draft prompt has more tokens than in b0, and the total is lower.
- **E3.** v2 leaves every email whose b0 draft used no more than the cap with exactly b0's reply. Every email whose b0 draft used more is cut off (`length`) with no reply (the JSON is unfinished). v2's draft output tokens equal the sum of min(b0's, cap).
- **E4.** v3's extraction and chunks are identical to b0's on all 20 emails (V4's precondition).
- **E5.** v3r's replies are identical to v3's on all 20 emails.
- **E6.** v3's draft prompts have exactly b0's token counts (the two models share a tokenizer), so v3's saving is in the price per token, not the number of tokens.
- **E7.** v3 has fewer labelled-correct emails than b0.
- **E8.** Fewer than half of v3's replies that are labelled wrong fail 01's draft check, so V4 escalates a minority of v3's wrong replies. #18 found the same check stopped none of the 3b model's 12 wrong replies.

An expectation that doesn't hold is reported as such. The protocol isn't changed to fit.

## Stop conditions

- **Preflight fails** (hashes, packages, Ollama version, model IDs, environment variables): no run.
- **A run's `/api/chat` line count differs from its own calls:** the run is flagged. It is repeated once under a new name, recorded as a deviation.
- **E4 fails for an email that would be escalated:** V4 is not computed, and the report says why.

## Deviations

None yet.
