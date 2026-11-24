# Protocol: Part B

Written and approved before any Part B model call, and frozen by hash in `data/FROZEN-B.json` with the code that applies it. Part A's protocol ([PROTOCOL.md](PROTOCOL.md)) still applies to everything it defines: email outcome, the grader, the blind label format, the paired comparison and sign test. If anything here has to change after the freeze, the change is recorded as a deviation in the README; this file is not edited.

## Question

A teammate makes the support assistant's drafting prompt "sound friendlier" by changing one sentence. On the same test emails, does that change make replies better or worse, email by email, and how much would two identical runs have differed anyway?

## The change

`data/prompts-v4.json` is 01's `data/prompts.json` (v3) with the version label `v4` and one drafting sentence replaced. The extraction and retry prompts and the draft user template are unchanged; `freeze_b.py` and the tests fail on any other difference.

```text
v3: - Be polite and brief. Greet the customer by name, don't repeat their email, and sign the reply "Support team".
v4: - Be warm and friendly, and thank the customer for getting in touch. Greet the customer by name, don't repeat their email, and sign the reply "Support team".
```

Dropping "brief" is deliberate: a warmth edit that also relaxes brevity is the realistic version of the change.

## Setup for every run

- **Pipeline:** 01's `pipeline.py`, unchanged, with policy `none` (the end-to-end chain of 01's article).
- **Models:** `llama3.2:3b` (ID `a80c4f17acd5`) and `nomic-embed-text` (ID `0a109f422b47`), through Ollama 0.40.17.
- **Settings:** 01's `data/settings.json`, unchanged: temperature 0, seed 1, `num_ctx` 8192, at most 400 output tokens for extraction and 700 for a draft.
- **Python:** 3.12.13, with `requests` 2.34.2 and `python-dotenv` 1.2.4 in the demo's `.venv`.

## Runs, in this order

| Name | Prompt | Split | Purpose |
|---|---|---|---|
| `v3a` | v3 | test | The fresh baseline |
| `v3b` | v3 | test | The same run again: how much two identical runs differ in this setup |
| — | | | `run_b.py reproduce`, then a **pause** for review before any v4 call |
| `v4dev` | v4 | dev | Sanity check on development emails only: output format and tone |
| `v4test` | v4 | test | The candidate, run once |

**Each run, before its first model call:**
1. Both freezes are verified.
2. The Ollama version, the model IDs, the installed packages and 01's resolved model settings are checked.
3. The shared Ollama lock (`$TMPDIR/snehalagrawal-ollama.lock`) is taken. It is never taken over: the run waits for it.
4. The run waits for 60 seconds with no connection to the server and no change to its log.
5. Both models are unloaded.

**After the run:** both models are unloaded again, and the run records its own model calls and the `/api/chat` lines in the server log during its window.

**Model calls:** about 40 chat calls per run, about 160 in all.

## Stop conditions and rules

- **Before a run:** stop if a hash, the Ollama version, a model ID or a package version doesn't match; if a model setting is overridden; or if the server isn't quiet within 30 minutes.
- **At the reproduction, stop and investigate before any v4 call if:**
  - retrieved chunks differ for an email whose extraction is identical (the embedding setup may have changed);
  - an error appears where the earlier run had none.
- **Replies that differ from #18's:** a finding to report, not a reason to stop. `v3a` is the baseline either way, because it runs in the same environment as v4. #18's stored replies (Ollama 0.40.16) are never the baseline.
- **Isolation:** if the server log shows more `/api/chat` lines in a run's window than the run's own calls, the run is flagged. It is repeated once under a new name, recorded as a deviation.
- **Revising v4:**
  - at most once, only after `v4dev`;
  - only if v4 breaks the output format (a usable draft that v3's development run produced is missing) or the tone change visibly didn't happen;
  - never for accuracy, because the experiment measures what a tone change does to accuracy;
  - development replies are read for format and tone only, never inspected for accuracy, and never labelled.
  
  A revision means a new prompt file and a new freeze, recorded as a deviation.
- **After `v4test`:** no change of any kind.

## Labels

- **Format and rules:** Part A's blind label format and rules apply.
- **What the worksheet covers:** one worksheet holds every distinct test reply: Part A's 39, plus every `v3a`, `v3b` and `v4test` reply, deduplicated by label key. Which arm or run produced each reply stays in `data/replies.json` and `data/replies-b.json`, and never appears on the worksheet.
- **What the worksheet shows:** the email, each question with its fact sentences and evidence passages, and the replies under neutral ids. Emails, and the replies within each email, are shuffled with seed 33.
- **What the worksheet hides:** no arm, run, prompt version, grader verdict, original label or note, and not the grader's accepted wordings.
- **Limit of the blinding:** it can't hide tone. Friendlier replies may be recognisable as v4.

## Analysis (`report_b.py`)

- **Reproduction,** as text only:
  - `v3a` against #18's stored chain, and `v3a` against `v3b`: per email, same extraction, same chunks, same reply;
  - how many replies changed between `v3a` and `v4test`.
- **Outcome agreement between `v3a` and `v3b`,** from the labels. Kept apart from reproduction: identical replies are not the same claim as identical outcomes.
- **Main comparison:** email outcome, `v3a` against `v4test`, per email (fixed, broken, both correct, both wrong), with an exact two-sided sign test. No other test, and no claim of improvement without the case-level changes.
- **Gates per run:** false refusals out of answerable questions, false answers out of uncovered questions.
- **The grader per run:** its verdicts against the blind labels, missed errors and false alarms with denominators.
- **Reply length per run:** median characters.
- **Agreement:** blind labels against 01's original labels, on `v3a` replies identical to a reply 01 labelled.

## Expectations, written before any run

These are expectations, not guaranteed outcomes. If the results differ, the difference is reported and the expectation is not rewritten.

- **EB1:** v4 replies are longer.
- **EB2:** most reply texts change, but email outcomes change for only a few emails, in both directions, and the sign test can't rule out no difference.
- **EB3:** `v3a` reproduces most or all of #18's replies (same model IDs, temperature 0, seed 1). The Ollama patch-version change could alter some.
- **EB4:** `v3a` and `v3b` are identical.
