# Protocol

Written before any of the demo's code existed. Its SHA-256 and the time it was written are recorded in the README. Before the first reported run, `results/freeze.json` records the SHA-256 of this file, the code and the data, and every run and report checks them, so a later change shows. If anything here turns out to be wrong after it was written, the correction is recorded under "Deviations" in the README; this file is not edited.

Development runs (single scenarios, used to find bugs in the code) are allowed before the freeze. They are not reported.

## Question

A workflow of seven steps reads a customer's email with a model, checks it, changes a plan in a billing service, applies a credit in a credit service, updates a helpdesk ticket, drafts a reply with a model, and sends it. When steps fail, run twice, or the process dies in between:

1. Which checks stop a wrong action, and at which level, before anything outside the workflow changes?
2. After a crash at each boundary, how many plan changes, credits and emails exist in the receiving systems, and does the workflow's record agree with them?
3. What do idempotency keys, saved step outputs, a key retention limit, compensation, a polling outbox and degraded modes each change?

## The central distinction

Five things are recorded separately and never inferred from each other:

| | Where it lives |
|---|---|
| What the model proposed | the step's saved output in the workflow record |
| What validation established | the step's saved validation result (level, rule, pass or fail), with the policy version |
| What a receiving system committed | that system's own database |
| What the workflow durably recorded | the step's status and result in the workflow record |
| What a person approved | nothing in this demo: cases that need a person end as `handed_over` with a reason |

## What is simulated, configured, and measured

- **Simulated:** the model and four receiving systems.
  - **The model** is scripted: each email has a list of raw text outputs per step, returned in order of calls (`data/fixtures.json`). An entry can be malformed JSON, a valid but wrong reading, or "unavailable". No model is run. Nothing here says how often a real model produces any of these.
  - **The receiving systems** are a billing service, a credit service, a helpdesk and an email service, each in its own SQLite database file. Each opens its own connection and commits its own transaction. None of their writes can be part of a workflow-record transaction, or of each other's. They are called in-process, which keeps the runs deterministic. What this simulates is separate transaction boundaries, not a network.
  - **The faults** are configured: a lost response after a commit, a permanent rejection, a service that is down, a failure that happens once.
- **Configured:**
  - a fake clock (a file in each scenario directory);
  - the key retention of the credit service;
  - the auto-approval cap (`policy_version` 1: $50.00; version 2: $15.00);
  - the lease length (60 s);
  - every crash point.
- **Measured:**
  - rows in each receiving system's database;
  - calls each system received;
  - the workflow record (step statuses, events, outbox);
  - model calls (an append-only log);
  - each process's exit code.
- **No timing is measured.** Every expected value is a count, a status, or a value. Runs should be identical.

## The workflow and its step contracts

The workflow id is derived from the email's id, `wf-<email id>`. A key is `<workflow id>:<step>`.

| Step | Who | Input | Output | Validation | Side effect | Recovery class |
|---|---|---|---|---|---|---|
| 1 understand | model | the email | a reading: intent, target plan, when, the invoice named | syntactic (JSON), schema | none | reuse the saved output; if none, call again. On a syntactic or schema failure, one repair call with the problems; then hand over. Model unavailable: hold |
| 2 check | code | the reading, billing records (read only), policy | a decision: plan, effective date, credit amount computed by code | business rules, evidence, approval cap | none | run again on every resume, against the current policy (revalidation). If the decision no longer passes: hand over when no effect has committed; when one has, hand over with the committed effects listed. Never reset a committed step |
| 3 change plan | billing | the decision | the scheduled change | the decision is the one step 2 recorded | **compensable** (set the plan back; the stand-in re-prices at list price) | "set plan" is state-based, so a repeat leaves the same state |
| 4 apply credit | credit service | the amount step 2 computed | credit id | cross-step: the amount sent equals step 2's amount | **pivot**: the last step before the workflow only moves forward | `started` with no result after a crash means unknown. Retry with the same key while the key is within the service's retention minus a 1 h margin; otherwise look it up by reference; if the service has no lookup, hand over. Lost response: mark unknown, then the same rule |
| 5 update ticket | helpdesk | the ticket | status set | none | optional, state-based | the helpdesk is down: `degraded`, continue |
| 6 draft | model | facts from the record | reply text; in the same transaction, an outbox row | the body contains the amount and the date from the record | none | reuse saved output. Model unavailable: a fixed template built from the record (`degraded`) |
| 7 send | outbox relay | the outbox row | email id | none | forward only | the relay sends rows not marked sent, with the row id as the message id; it may send twice, so the email service deduplicates by message id |

Step statuses:
- `pending`: not started;
- `started`: recorded before a call that changes something;
- `done`;
- `unknown`;
- `degraded`;
- `failed`.

Workflow statuses: `running`, `held`, `handed_over`, `completed`, `completed_degraded`.

A worker claims a workflow with a conditional update. It succeeds only if no one holds an unexpired lease, and it raises the record's version. A worker that crashed keeps its lease, so the harness advances the clock past the lease before a resume.

## Designs compared in the crash sweep

- **A (restart):** the saved record is ignored; the workflow runs again from step 1 under a new run id. No idempotency keys and no message ids are sent.
- **B (resume, no keys):** resumes from the record. A step left `started` is run again without a key; the relay sends without a message id.
- **C (resume with keys):** resumes from the record. Model outputs are saved before use. Keys are derived from the workflow id and the step. A step left `started` is treated as unknown (the recovery class above). The relay sends the outbox row id as the message id.

Every scenario uses design C unless it says otherwise.

## Fixtures

These are fictional: organizations, invoices and emails written for this demo. Prices follow the fictional product's billing guide (`01-reliable-llm-pipeline/data/documents/billing-guide.md`): plans are priced per organization (Basic $10, Pro $25 monthly), and downgrades take effect at the start of the next billing period. Basic allows 5 members, pending invitations included.

- `org-acme`:
  - Pro at a legacy price of $20.00, 4 members, next period 2026-12-01, ticket T-301.
  - Invoice INV-1043 (October, $20.00) has two successful charges, so one is a duplicate.
  - Invoice INV-1044 (November) has one charge.
- `org-other`: owns INV-1034.
- `org-big`: Pro, 7 members including pending invitations, with a duplicate on INV-3301.
- `org-annual`: Pro annual; INV-2207 ($250.00) charged twice.
- The clock starts at 2026-11-02 09:00:00 UTC.

The main email (e01, from org-acme): "Please move us to Basic from the next billing period, and credit us for invoice INV-1043: the October payment went through twice."

## Validation levels

| Level | What it establishes | Rule here |
|---|---|---|
| syntactic | the output parses | JSON |
| schema | well-formed | required fields, types, enums |
| business rule | allowed by policy | effective at the next billing period; Basic only if members ≤ 5 |
| evidence | consistent with the systems of record | the invoice is named in the email, exists, belongs to this organization, and has more than one successful charge for its period |
| approval | within what may run without a person | computed credit ≤ the policy's cap |
| cross-step | later steps act on what was decided | step 4 sends step 2's amount; on resume, step 2 is re-run under the current policy |
| outcome | the record agrees with the receivers | after the run: for every effect, the receivers' rows equal what the record says happened |

## Expected outcomes

"Effects" means rows created in the receiving systems: a scheduled plan change, credits, a ticket status, emails. "Matches" means the outcome check passes.

### E1. Invalid structured output

| Case | Expected |
|---|---|
| e02: the first understanding is cut-off JSON, the repair is valid | Syntactic failure recorded on attempt 1. 2 model calls for step 1. Completed with exactly one of each effect. The first billing call comes after the second model call |
| e03: both attempts invalid | Handed over at step 1, reason syntactic. 0 effects, 0 calls to any receiving system |

### E2. Valid structure, failed business validation

| Case | Expected |
|---|---|
| e04: reading says "immediately" | Handed over at step 2, level business rule. 0 effects |
| e05 (org-big): valid reading | Handed over at step 2, level business rule (member limit). 0 effects |
| e06 (org-annual): valid reading, computed credit $250.00 | Handed over at step 2, level approval (reason `needs_approval`). 0 effects |

In every case the model's output passed the syntactic and schema levels.

### E3. Insufficient or conflicting evidence

| Case | Expected |
|---|---|
| e07: reading names INV-1034, the email says INV-1043 | Handed over at step 2, level evidence |
| e08: INV-1044 has one charge | Handed over at step 2, level evidence |
| e09: INV-9999 doesn't exist | Handed over at step 2, level evidence |

All three: 0 effects, 0 calls to billing write operations or the credit service.

### E4. Fallbacks and degraded modes

| Case | Expected |
|---|---|
| 4a: model unavailable at step 6 | Draft `degraded`. The email body is the template and contains "$20.00" and "1 December 2026". Workflow `completed_degraded`. One of each effect. Matches |
| 4b: model unavailable at step 1 | Workflow `held`, 0 effects. A second run, model available: completed, one of each effect, 2 model calls for step 1 |
| 4c: helpdesk down | Step 5 `degraded`, ticket status unchanged. Workflow `completed_degraded`. Plan, credit and email: one each. Matches |

### E5. Duplicate execution

| Case | Expected |
|---|---|
| 5a: two workers claim e01 at the same moment (threads released by a barrier) | Exactly one claim succeeds and the other is refused. One of each effect |
| 5b: 8 threads send the same key to the credit service, 20 trials, all held at a barrier after their lookup and before their write | Check-then-insert service: 8 credits in every trial (160). Key recorded in the same transaction under a unique constraint: 1 credit in every trial (20), and the other 7 calls return the first result, marked replayed |
| 5c: e01 delivered again after the workflow completed | No new workflow, 0 new effects, 0 model calls |

### E6. Interruption and restart: the crash sweep

The process exits (`os._exit`) at one point, and a new process recovers with the design under test. Crash points:
- P01: step 1 model call returned, output not saved;
- P02: step 1 saved;
- P03: step 2 saved;
- P04: step 3 `started` recorded;
- P05: billing committed, before it returns;
- P06: step 3 recorded;
- P07: step 4 `started` recorded;
- P08: credit committed, before it returns;
- P09: step 4 recorded;
- P10: helpdesk committed;
- P11: step 6 saved together with its outbox row;
- P12: email service committed, before the relay marks the row;
- P13: everything done.

Expected:

| Design | Credits | Emails | Plan and ticket | Record matches receivers |
|---|---|---|---|---|
| C | 1 at every point | 1 at every point | scheduled Basic and status set, at every point | yes, at every point; completed at every point |
| B | 2 at P08, otherwise 1 | 2 at P12, otherwise 1 | scheduled Basic, status set (state-based) | no at P08 and P12, yes elsewhere |
| A | 2 at P08–P13, otherwise 1 | 2 at P12–P13, otherwise 1 | scheduled Basic, status set (state-based) | no wherever credits or emails are 2 |

Model calls under C: 3 at P01 (the unsaved output is asked for again), 2 at every other point.

### E7. Recovery from a persisted checkpoint

| Case | Expected |
|---|---|
| 7a: crash at P03, resume | 2 model calls in total. Resume calls only step 6. Completed, one of each effect |
| 7b: crash at P03; policy changed to version 2 (cap $15.00) before resume | Revalidation fails at approval. Handed over. 0 effects |
| 7c: crash at P06 (plan change committed and recorded); policy version 2 before resume | Revalidation fails. Step 3 stays `done` (not reset). Handed over with the committed effects listed (change_plan). Plan scheduled Basic, 0 credits, 0 emails, no compensation |
| 7d: crash at P03; the record's schema version is changed to 0 before resume | Resume refuses (exit code 3). No further model or receiver calls. Status unchanged |
| 7e: crash at P09 with a design that doesn't save step 1's output; the regenerated reading says "immediately" | Step 2 fails at business rule. Handed over with change_plan and apply_credit listed as committed. 1 plan change, 1 credit, 0 emails. Under design C, the same crash: completed, no new step 1 call |

### E8. Ambiguous external outcome

| Case | Expected |
|---|---|
| 8a: credit service commits, then the response is lost (once) | An `unknown` event is recorded. The same key is sent again, and the service returns the first result marked replayed. 1 credit, 2 credit calls. Completed, matches |
| 8b: the same, against a service without keys that supports lookup by reference | Unknown, then a lookup finds the credit. 1 credit, 1 write call. Completed, matches |
| 8c: the same, without keys and without lookup | Handed over with step 4 `unknown`. 1 credit in the service. The record says unknown, not done or failed |
| 8d: crash at P08 against a service that keeps keys for 24 h; resume 30 h later | Naive policy (same key regardless of age): the key has been pruned, so a second credit (2), and the record doesn't match. Retention-aware policy: no write; a lookup finds the credit; 1 credit, completed, matches |

### E9. Compensation

The credit service rejects the credit permanently (invoice disputed) after the plan change committed.

| Case | Expected |
|---|---|
| 9a: policy hand over (default) | Plan scheduled Basic, 0 credits, 0 compensations, 0 emails. Handed over with change_plan listed |
| 9b: policy compensate; the first compensation call fails, the second succeeds | 2 compensation calls. The plan stays Pro, now at $25.00 (was $20.00): compensated, not undone. 0 credits. Handed over (compensated) |
| 9c: the dispute is checked in step 2 (before the pivot) | Handed over at step 2, level evidence. 0 effects, 0 compensations |

### E10. Outbox (a polling relay; CDC is not implemented)

| Case | Expected |
|---|---|
| 10a: crash at P12, email service deduplicates by message id | 2 send calls, 1 email |
| 10b: crash at P12, no deduplication | 2 emails |
| 10c: no outbox; step 6's done and the send request are written to two different stores, with a crash between them | 0 emails after recovery (the request is lost), and the record says step 6 is done. With the outbox (same transaction): 1 email |

### E11. Negative control

`report.py --negative-control` checks the same results with two expectations changed on purpose:
- E5b's constraint design expects 8 credits per trial;
- E6's design C expects 2 credits at P08.

It must report both as failures and exit 1. Because the runs are deterministic, it must fail the same way every time.

## Repeats and reproducibility

- **Three full runs after the freeze.** `results.json` (counts, statuses, values; no timings, no absolute paths) must be identical across the three by SHA-256.
- **Unit tests** cover:
  - the validation levels;
  - the credit service's key handling, mismatch and retention;
  - the claim;
  - the relay.
- **Ruff** must be clean under the repository's `ruff.toml`.
