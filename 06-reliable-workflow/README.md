# 06-reliable-workflow

Companion code for **[Designing Reliable LLM Workflows](https://snehalagrawal.com/articles/designing-reliable-llm-workflows/)** (Article #38).

A support workflow reads a customer's email with a model, checks it, changes a plan in a billing service, applies a credit in a credit service, updates a helpdesk ticket, drafts a reply with a model, and sends it. This demo breaks that workflow on purpose and counts what is left in each receiving system afterwards:

1. **Which check stops a wrong action, at which level, before anything outside the workflow changes?**
2. **After a crash at each of 13 boundaries, how many plan changes, credits and emails exist, and does the workflow's record agree with the systems that hold them?**
3. **What do idempotency keys, saved model outputs, a key retention limit, compensation, an outbox and degraded modes each change?**

It is a small reference implementation of one workflow, not a workflow engine. It runs in about 10 seconds with Python and nothing else: no model, no network, no API key. It is written for Python 3.10 or later (the repository's Ruff target) and was run on 3.12.13.

## The two rules it implements

- **The record decides what to do next; the receiving system decides what happened.**
- **Every step ends by writing one of a few outcomes into the record** (`done`, `failed`, `unknown`, `degraded`, and `compensated` for a step that was counteracted), and recovery is reading that record, not rerunning the code.

The record keeps five things apart, and the code never infers one from another:
- what the model proposed (a step's saved output);
- what validation established (its checks, with the policy version);
- what a receiving system committed (that system's own database);
- what the workflow recorded (the step's status and result);
- what a person approved. Nothing here: cases that need a person end as `handed_over` with a reason.

## The step contracts

| Step | Who | Side effect | Recovery |
|---|---|---|---|
| 1 understand | model (scripted) | none | reuse the saved reading; one repair call on a syntactic or schema failure; model unavailable: hold |
| 2 check | code | none | re-run on every resume under the current policy; never reset a committed step |
| 3 change plan | billing | compensable: "set the plan" is state-based | call again: a repeat leaves the same state |
| 4 apply credit | credit service | the pivot | `started` or `unknown`: same key while it's within the service's retention, else look it up, else hand over |
| 5 update ticket | helpdesk | optional, state-based | helpdesk down: `degraded`, continue |
| 6 draft | model (scripted) | none; writes the outbox row in the same transaction | reuse the saved draft; model unavailable: a fixed template from the record |
| 7 send | outbox relay | forward only | send unsent rows with the row id as the message id |

The validation levels are syntactic, schema, business rule, evidence, approval, cross-step and outcome. What each one establishes and what it can't is in [PROTOCOL.md](PROTOCOL.md). The model only *identifies* things (which invoice, which plan, when). The credit amount and the effective date are computed in `validate.py` from the billing records.

## What is simulated, configured, and measured

This matters for every number below.

- **Simulated: the model.** It is scripted. Each email has a list of raw outputs per step in `data/fixtures.json`: valid, cut off, valid but wrong, or "unavailable". **No model is run**, so nothing here says how often a real model produces any of these.
- **Simulated: four receiving systems** (billing, credits, helpdesk, email).
  - Each owns its own SQLite file, opens its own connections, and commits its own transactions. No transaction spans two of them, or one of them and the workflow record.
  - They are called in-process to keep the runs deterministic. What this simulates is **separate transaction boundaries, not a network**: there is no latency, no partition, and no request still in flight after a timeout. (Article #37's demo, `05-retries-timeouts`, has a lookup racing a write that is still in flight.)
- **Simulated: the organizations, invoices and emails.** They are fictional. Prices follow the fictional product's billing guide in `01-reliable-llm-pipeline`: per organization, Pro $25 a month, with a legacy $20.00 for `org-acme`.
- **Configured:**
  - the faults (a lost response after a commit, a permanent rejection, a service that is down, a failure that happens once);
  - the credit service's mode and key retention;
  - the auto-approval cap: $50.00 under policy version 1, $15.00 under version 2;
  - a fake clock shared by every process in a scenario;
  - every crash point. A crash is `os._exit(70)` in a separate process; a new process then recovers.
- **Measured:**
  - the rows in each receiving system;
  - the calls each received;
  - the workflow record (step statuses, events, outbox);
  - model calls;
  - process exit codes.

  **No timing is measured.**
- **The outbox relay polls the record's outbox table.** Change data capture (reading the database's log, as Debezium does) is described in the article. It is not implemented here, and nothing here measures it.
- **The relay runs inside each workflow run, for that workflow's rows only.** A separate process polling every row would also send the rows that design A's restart leaves behind.

## Run it

```bash
cd python
python -m unittest test_workflow.py   # validation levels, keys, retention, the race, the claim, email deduplication (13 tests)
python run.py                         # every scenario; checks results/freeze.json first; writes runs/<time>/results.json
python report.py                      # checks the latest run against PROTOCOL.md; exit 1 if anything fails
python report.py --negative-control   # two expectations changed on purpose: must exit 1
python compare.py runs/<a> runs/<b> runs/<c>   # repeat runs: results.json identical?
```

`runs/` is not committed. `python run.py --dev` skips the freeze check (for changing the code); `python freeze.py --check` compares the files with the freeze.

## Files

| File | What it is |
|---|---|
| `PROTOCOL.md` | The question, the step contracts, the designs, and every expected outcome, written before any code |
| `data/fixtures.json` | Organizations, invoices, charges, emails, scripted model outputs, the two policy versions |
| `python/workflow.py` | The workflow: step contracts, designs A/B/C and variants, the runner, recovery of an unknown outcome, compensation, the relay |
| `python/record.py` | The workflow record: steps, events, outbox; the claim with a lease and a version |
| `python/validate.py` | Validation by level; the credit amount computed from billing |
| `python/services.py` | Billing, credits (three modes, lookup, key retention), helpdesk, email, each in its own SQLite file |
| `python/model.py` | The scripted model |
| `python/scenarios.py` | E1–E10; the outcome check that compares the record with the receivers |
| `python/worker.py` | One workflow run in its own process |
| `python/run.py`, `report.py`, `compare.py`, `freeze.py` | Run, check against the protocol, compare repeats, freeze |
| `results/freeze.json` | SHA-256 of the protocol, data and code at the freeze |
| `results/report-run*.txt`, `compare.txt`, `negative-control.txt`, `results-run3.json` | The three reported runs, their comparison, the negative control, and the third run's full results |

## The runs described here

- **Protocol.** `PROTOCOL.md` was written before any code: 2026-11-24 16:14:11 UTC, SHA-256 `e4bf1b85d670d1742eae48942a43a8cbfada416c82cd21dd78ba0db367d903b4`. It is unchanged since; the freeze records the same hash.
- **Freeze.** The protocol, data and code were frozen at 2026-11-24 16:24:55 UTC (`results/freeze.json`, 15 files). Before the freeze there were development runs of single scenarios and one full development run; none is reported.
- **Runs.** Three full runs at 16:24:55, 16:25:05 and 16:25:14 UTC on 2026-11-24.
  - Python 3.12.13, SQLite 3.51.0 (as reported by Python's sqlite3 module), macOS 26.6.2, Apple M4 Pro.
  - Command: `python run.py` (about 9 s each).
- **Results.** All **194 checks** passed in each run.
  - `results.json` was identical in all three, byte for byte: SHA-256 `6b67eedebbb3d8587fae3fbe6fffd84c61d90b66496ab94a40b32ad3aab392bf` (`results/compare.txt`).
  - The negative control reported 3 failures and exited 1 (`results/negative-control.txt`). The changes were E5b's constraint design expecting 8 credits per trial, and E6's design C expecting 2 credits at P08; the third failure is P08's outcome check, which follows from the second.
- **Tests.** 13 unit tests pass; Ruff is clean with the repository's `ruff.toml`.

## Results

Every count was identical in all three runs.

### Checks before anything changes (E1–E3)

| Email | What the model returned | Stopped at | Effects |
|---|---|---|---|
| e02 | cut-off JSON, then a valid reading after one repair call | (completed) | one of each, after the repaired reading was accepted |
| e03 | cut-off JSON twice | step 1, syntactic | 0; no call to any receiving system |
| e04 | valid reading: "immediately" | step 2, business rule (downgrades start next period) | 0 |
| e05 | valid reading (org has 7 members) | step 2, business rule (Basic allows 5) | 0 |
| e06 | valid reading; computed credit $250.00 | step 2, approval (`needs_approval`) | 0 |
| e07 | valid reading naming INV-1034; the email says INV-1043 | step 2, evidence (not in the email) | 0 |
| e08 | valid reading; INV-1044 was charged once | step 2, evidence | 0 |
| e09 | valid reading; INV-9999 doesn't exist | step 2, evidence | 0 |

Every reading in e04–e09 passed the syntactic and schema levels.

### Degraded modes (E4)

| Case | Result |
|---|---|
| Model unavailable at step 6 | The template, filled from the record ("$20.00", "1 December 2026"); `completed_degraded`; one of each effect |
| Model unavailable at step 1 | `held`, 0 effects; the next run completed with one of each |
| Helpdesk down | Step 5 `degraded`, ticket still `open`; plan, credit and email one each; `completed_degraded` |

### Duplicates (E5)

| Case | Result |
|---|---|
| Two workers claim the same workflow at once | One claim succeeded, the other was refused; one of each effect |
| 8 threads, the same key, held at a barrier between lookup and write, 20 trials: check-then-insert | **8 credits in every trial** (160) |
| The same, with the key recorded in the credit's transaction under a unique constraint | **1 credit in every trial** (20); the other 7 calls got the first result, marked replayed |
| The email delivered again after the workflow completed | Nothing new: no workflow, effect or model call |

### The crash sweep (E6)

The process exits at one of 13 points, and a new process recovers using design A (restart from scratch, no keys), B (resume from the record, no keys) or C (resume, keys, saved model outputs).

| Design | Credits | Emails | Plan and ticket | Record matches the receivers |
|---|---|---|---|---|
| A | 2 at P08–P13, 1 at P01–P07 | 2 at P12–P13 | right at every point | no at P08–P13 |
| B | 2 at P08 only | 2 at P12 only | right at every point | no at P08 and P12 |
| C | 1 at every point | 1 at every point | right at every point | yes at every point; completed at every point |

- P08 is "credit committed, before the service answered"; P12 is "email sent, before the relay marked the row".
- The plan and the ticket were right under every design because "set the plan" and "set the status" are state-based: repeating them changed nothing.
- Under B, the record after P08 says `apply_credit done, credit 2, completed`: the workflow looks healthy. Only comparing it with the credit service shows two credits.
- Model calls under C: 3 at P01 (the reading was lost before it was saved, so it was asked for again), 2 everywhere else.

### Recovery from the record (E7)

| Case | Result |
|---|---|
| Crash after step 2, resume | 2 model calls in total; the resume called only step 6; completed |
| Cap lowered to $15.00 before resume, no effect committed yet | Revalidation failed at approval; handed over; 0 effects |
| Cap lowered after the plan change committed | Revalidation failed; step 3 stayed `done`; handed over listing `change_plan`; plan scheduled, 0 credits, 0 emails, no compensation |
| The record's schema version made incompatible | Resume refused (exit 3); no further calls of any kind |
| Step 1's output not saved; crash after the credit; the regenerated reading says "immediately" | Step 2 failed; handed over listing `change_plan` and `apply_credit`; 1 plan change, 1 credit, 0 emails. With the output saved: completed, step 1 not called again |

### Unknown outcomes (E8)

| Case | Result |
|---|---|
| Credit committed, response lost; service has keys | `unknown` recorded; the same key sent again; the service replayed the first result; 1 credit, 2 calls |
| The same; no keys, lookup by reference | `unknown`; a lookup found the credit; 1 credit, 1 write call |
| The same; no keys, no lookup | Handed over with step 4 `unknown`. The service holds 1 credit; the record says unknown, not done or failed |
| Crash after the credit; resume 30 h later; keys kept 24 h; same key regardless of age | The key had been pruned: **2 credits**; the record doesn't match |
| The same; the workflow checks the key's age first | No write; a lookup found the credit; 1 credit, completed |

### Compensation (E9)

The credit service rejects the credit permanently (invoice disputed) after the plan change committed.

| Policy | Result |
|---|---|
| Hand over (default) | Plan change kept (scheduled Basic), 0 credits, 0 emails; handed over listing `change_plan` |
| Compensate; the first compensation call fails | 2 compensation calls. The plan stays Pro, now at **$25.00 (was $20.00)**: the stand-in re-prices at list price, so the compensation didn't restore the old state |
| Dispute checked in step 2, before the pivot | Handed over at step 2 (evidence); 0 effects, nothing to compensate |

### Outbox (E10)

| Case | Result |
|---|---|
| Crash after the email was sent, before the row was marked; the email service deduplicates by message id | 2 send calls, 1 email |
| The same, without deduplication | 2 emails |
| No outbox: step 6's result and the send request written to two stores, a crash between them | 0 emails, and the record says step 6 is done |
| The same crash with the outbox (one transaction) | 1 email |

## Limits

- **The model is scripted.** These results are about the workflow's mechanics, not about how often a model is wrong.
- **The receiving systems are stand-ins with rules chosen for the demo.**
  - Billing's "re-price at list price" is the stand-in's rule. It illustrates why compensation isn't an undo; it isn't a claim about any real billing system.
  - Real services differ in what they save for a key, for how long, and what they do with concurrent repeats. Read the provider's documentation (Article #38 quotes Stripe's and an IETF draft's).
- **There is no network.** A lost response is simulated by raising an error after the commit. A request still in flight while the lookup runs can't happen here.
- **The concurrency cases are coordinated with barriers on purpose,** so the result doesn't depend on thread timing. They show what each design allows when the interleaving happens, not how often it happens.
- **One worker runs a workflow at a time,** with a lease and a version check on writes to the record (marking an outbox row sent is not version-checked). No scenario exercises a stale worker (`LostOwnership`), and the receiving systems are not fenced: a worker past its lease could still reach them before its next record write failed. Queues, worker pools, long waits and durable-execution engines are out of scope.

Found in review, after the freeze (the files are frozen, so these are documented here, not changed):

- **The outcome check derives what to expect from the record's own send list.** In E10's no-outbox case the record said it sent nothing, so 0 emails "matched" and the workflow ended `completed`. A sound check derives the expectation from the decisions (a draft recorded as done means one email expected).
- **Step 2 re-runs on every resume, even after the pivot.** The better rule is to revalidate until the pivot commits and then move forward on the recorded decision. The reviewer ran extra crashes outside the protocol, with policy version 2 set before resume: at P09 the workflow handed over with 1 credit and 0 emails; at P11 an outbox row written by step 6 was left unsent; at P12 the hand-over's list omitted the email already sent.
- **The relay runs inside a workflow run,** so a run that hands over after step 6 strands its outbox row until someone runs it. A separate relay process would send it.
- **A hand-over's `committed` list is the record's view** (steps recorded `done` or `compensated`), not something read from the receivers.
- **Billing records the compensation's key but doesn't enforce keys.** Repeating the compensation is safe because "set the plan" is state-based.
- **The unit test named for the relay re-runs a finished workflow,** which returns at once; the relay's crash-and-resend behaviour is covered by E10, not by the unit tests.

## Review

An independent reviewer (a separate agent, working on a copy of this directory) ran the tests, a fourth full run, the report and the negative control: 13 tests OK, freeze ok, 194 of 194 checks, the same `results.json` digest (`6b67eede...`), and the negative control at 191 of 194 with exit 1. It confirmed every number in this README and the article against `results/results-run3.json`. Its findings about the code are listed under Limits above.

## Deviations

None. The protocol, data and code are unchanged since the freeze.
