# Protocol

Written before any code in `python/` existed (2026-11-24). `results/freeze.json` records the SHA-256 of this file, the data, and the code before the first reported run, and `run.py` checks them. If anything here turns out to be wrong after the freeze, the README records it under "Deviations"; this file is not edited.

Development runs (single scenarios, and full runs used to debug the code and the report) were allowed before the freeze. They are not reported.

## Question

A review desk is the part of a product where proposals that need a person wait, get decided, and turn into actions. Article #29's demo (`ai-agent-patterns/07-human-in-the-loop`) built one agent's checkpoint: pause, decide, expire, re-check, execute once. This demo builds the desk around many proposals and many reviewers, and asks one question per safeguard:

> In these scenarios, what goes wrong when this one safeguard is missing and every other one is in place?

## What is simulated, scripted, and observed

- **Simulated:** the billing service (the system of record for invoices, payments, refunds, credits, and disputes), the message outbox, the reviewer directory, and the clock (a fake clock; nothing waits).
- **Scripted:** every proposal (no model is called: the proposals are what an assistant could submit) and every reviewer action (who claims, views, decides what, and when). **No reviewer behaviour is simulated or measured.** When a scenario has a reviewer approve a wrong proposal, that is a scripted input standing for a reviewer who missed it, not an estimate of how often people do.
- **Observed:** what the desk and the executor did: routes, statuses, accepted and refused decisions with their reasons, money moved in the billing service, messages sent, labels exported.

## The safeguards

Each can be switched off on its own (`desk.SAFEGUARDS`).

| Id | Safeguard | What the desk does with it |
|---|---|---|
| G1 | authority_from_directory | The reviewer's role comes from the directory, never from the request |
| G2 | authority_at_decision | Authority is checked when the decision is recorded, not when the item was claimed |
| G3 | requester_cannot_approve | Whoever raised a request can't approve it |
| G4 | two_person_rule | A high-value item needs two approvals from different authorized reviewers |
| G5 | bind_to_action | A decision quotes the action fingerprint it was shown; a different current action refuses it |
| G6 | bind_to_evidence | A decision quotes the evidence fingerprint it was shown; if the evidence differs at decision or at execution, the approval doesn't count and the item goes back to the queue |
| G7 | validate_at_execution | The executor runs the hard checks on the final action against current records, whatever was approved |
| G8 | execute_final_version | The executor runs the reviewer's edited version, not the original proposal |
| G9 | executor_checks_decision | The executor runs only items whose current status is approved |
| G10 | execute_once | One execution per approval: a lookup and an idempotency key at the billing service |
| G11 | silence_is_not_consent | At the SLA the item escalates; at expiry it expires; it never approves itself |
| G12 | claim_lease | A claim on an item lapses after the lease, so someone else can take it |
| G13 | dedupe_submissions | A second submission of the same proposal in the same conversation returns the open item |
| G14 | evidence_gate | A proposal whose claim the records don't support (a duplicate charge with one payment) can't be approved; it can be rejected, sent back, or escalated |
| G15 | label_provenance | Exported decisions keep their provenance: an approval is an operational decision, a rejection or edit with a reason is feedback, and only an independent audit, a seeded case, or two independent reviewers agreeing produce a gold label |
| G16 | seeded_cases_inert | A seeded test case can be decided but never executed |

## Scenarios and expected outcomes (all safeguards on)

The account is C-1001 from #29 (INV-1002, October, $25, charged twice; INV-1001, September, $25, 45 days old; INV-1003, November extra seats, $15, charged once), plus C-3001 (INV-3001, $600 annual, charged once). Clock starts 2026-11-12 09:00 UTC. "Money moved" lists billing-service writes.

| Id | Situation (scripted) | Expected |
|---|---|---|
| R01 | Informational reply, no money words | Route auto (audit-eligible); sent; no review item |
| R02 | $25 store credit on INV-1002, duplicate charge | Route auto (reversible, within the auto limit); credit written; no review item |
| R03 | $25 cash refund on INV-1002; ana approves | Review, within_policy; approved; one $25 refund |
| R04 | $25 refund on INV-1001 (45 days old); ana approves, then chen approves | Review, exception; ana refused (role not allowed for the tier); chen accepted; one $25 refund |
| R05 | Exception item; ana sends an approval that claims the billing_lead role | Refused (directory says support); no money |
| R06 | Exception item; dee (billing_lead) claims it; the directory then removes dee's billing_lead role; dee approves | Refused (not authorized now); no money |
| R07 | chen raises a $25 goodwill refund on INV-1001 (exception) himself, then approves it; dee approves | chen refused (requester); dee accepted; one $25 refund |
| R08 | $600 refund on INV-3001 (high_value); chen approves; then dee approves | After chen: still pending, no money. After dee: approved; one $600 refund |
| R09 | $25 refund on INV-1002; ana views it; the proposal is revised to $15 on INV-1003 before she decides; ana approves with the fingerprint she saw | Refused (action changed since viewed); no money |
| R10 | $25 refund on INV-1002; ana approves; a chargeback is opened on PAY-5006 before execution | Execution finds the evidence changed; approval invalidated; item back to pending (version 2) with the change listed; no money |
| R11 | $25 refund on INV-1002; chen approves with an edit to $30 | Execution refused by the hard check (only $25 left to refund); no money |
| R12 | Draft reply "We've refunded your duplicate charge..."; ana edits it to say the request is with billing; approves | The edited text is sent; the original is kept in the record, not sent |
| R13 | $25 refund on INV-1002 with an execution job queued at submission; ana rejects (wrong_invoice); the worker runs the job | Executor refuses (status rejected); no money |
| R14 | $10 refund on INV-1002; ana approves; two workers both pass the checks, then both commit | One $10 refund; the second commit returns the first |
| R15 | $25 refund on INV-1002; nobody decides | At 4 h escalated (a notification to billing_lead); at 24 h expired; customer told nothing was refunded; no money |
| R16 | $25 refund on INV-1002; ana claims it at 09:00 and leaves; ben claims at 09:45 and approves at 09:50 | Ben's claim accepted (ana's lease lapsed at 09:30); approved; one $25 refund |
| R17 | The same $25 proposal on INV-1002 submitted twice in one conversation; ana approves every open item | One review item; one decision; one $25 refund |
| R18 | $15 refund on INV-1003 claimed as a duplicate charge (one payment on record); ana approves | Route needs_evidence; approval refused; no money |
| R19 | $15 refund on INV-1003 for the October complaint (#29's wrong-but-allowed request); ana approves; executed; eli audits it as wrong_invoice | One $15 refund (the error is not prevented: review can miss it). Export: the approval as an operational decision, eli's audit as a gold label "wrong" |
| R20 | A seeded case (should be rejected: refund on INV-1003 for an October complaint) in the queue; ana approves it | Seeded catch rate 0 of 1; executor refuses the seeded item; no money |
| R21 | $25 refund on INV-1001 (exception); ana rejects it (outside_policy) and escalates; chen approves the escalated item | ana's rejection recorded with reason; the item escalated to billing_lead; chen accepted; one $25 refund |
| R22 | $25 refund on INV-1002; ana approves; the billing service writes the refund and then fails before answering; the executor retries | First attempt: execution_failed (outcome unknown). Retry: finds the refund by its key; completed; one $25 refund |

## Ablation: predictions

For each safeguard, all 22 scenarios run with only that safeguard off. A scenario "changes" if its observed outcome differs from the all-on run. Predicted changes:

| Off | Changes, with the predicted harm |
|---|---|
| G1 | R05: $25 refunded on an exception approved by a support reviewer (money) |
| G2 | R06: $25 refunded on an approval by someone who no longer holds the role (money) |
| G3 | R07: $25 refunded on chen's approval of his own request (money) |
| G4 | R08: $600 refunded after one approval (money) |
| G5 | R09: $15 refunded on INV-1003, an action nobody was shown (money) |
| G6 | R10: $25 refunded while a chargeback is open on the same payment (money) |
| G7 | R11: $30 refunded on a $25 invoice (money) |
| G8 | R12: the original reply, claiming a refund that never happened, is sent (message) |
| G9 | R13: $25 refunded after a rejection (money) |
| G10 | R14: two $10 refunds (money). R22: also changes, without a second refund: with no lookup, the retry sees the evidence changed and the item goes back to pending (no harm in money) |
| G11 | R15: $25 refunded at 24 h by the timeout (money) |
| G12 | R16: ben refused while ana's claim stands; the item escalates at 4 h and expires at 24 h; the correct refund is never issued (operational) |
| G13 | R17: two review items and two decisions for one request; one $25 refund (reviewer load, no money) |
| G14 | R18: $15 refunded for a duplicate the records don't show (money) |
| G15 | R19: the approval exported as a gold label "correct", contradicting the audit (label) |
| G16 | R20: the seeded case's $15 refund executed (money) |

Every other cell: no change.

## Decision rule

- A safeguard is **shown to matter in this desk** if its target scenario changes with the predicted harm when it alone is off.
- Unpredicted changes, and predictions that don't hold, are reported as they are, in the README and the article. They are not fixed by editing this file.
- Negative control: a run with nothing switched off must reproduce the all-on outcomes exactly (every cell "no change").
- Three full runs; the outcomes must be byte-identical (the clock is fake and nothing is random).

## What this can and can't show

- The tests (all safeguards on) show that this desk produces the outcomes above for these scripted inputs.
- The ablation shows, for each scenario, which single safeguard stands between it and the harm, in this code. Where two safeguards cover the same case, removing either alone shows nothing; the matrix makes that visible.
- Neither shows that a production review system is safe, that these 22 scenarios are complete, that the policy limits are right, or anything about how real reviewers decide, how often they miss errors, or how fast they work.
