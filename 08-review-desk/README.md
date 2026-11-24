# 08-review-desk

The companion demo for the article [Human Review and Approval in AI Systems](https://snehalagrawal.com/articles/human-review-and-approval-in-ai-systems/) (#40).

A review desk is where proposals that need a person wait, get decided, and turn into actions. [`ai-agent-patterns/07-human-in-the-loop`](https://github.com/SnehalAgrawal/ai-agent-patterns/tree/main/07-human-in-the-loop) (Article #29) built one agent's checkpoint: pause, decide, expire, re-check, execute once. Its README lists what it left out: "authenticated reviewers (here the role is a command-line argument)", and nothing about how review is operated. This demo builds that part: many proposals, many reviewers, and the rules that make an approval mean something.

- **Who may approve:** roles come from a directory, are checked at the moment the decision is recorded, the requester can't approve their own request, and a high-value refund needs two people. The number needed comes from the tier of the action that would run, and an edit can't take an item below the tier of the original proposal.
- **What exactly they approve:** each approval records the fingerprint of the action it approved. The executor runs an action only if enough distinct reviewers approved exactly that action on the current version. A decision must also quote the version of the screen it was made on. A revised proposal is a new version that needs new approvals, and it goes through the same intake as a new submission.
- **What evidence they saw:** a decision also quotes the fingerprint of the account's records it was shown (invoices, charges, refunds, credits, open disputes); if they changed before the decision or before execution, the approval doesn't count and the item goes back to the queue.
- **What runs:** only an approved item, only the reviewer's final (edited) version, with the tool that was approved (a store credit runs as a credit), only if it still passes the hard checks against current records, only if nothing changed between the checks and the write, and only once.
- **When nobody responds:** a claim lapses after 30 minutes, an item escalates at 4 hours and expires at 24. It never approves itself.
- **What the decisions are worth as data:** an approval is an operational decision; a rejection or edit with a reason is feedback; only an independent audit or a seeded case with a known answer produces a gold label. Seeded cases never take an automatic route, never execute, and never message a customer.

Every one of those 16 safeguards can be switched off on its own. The ablation runs 35 scripted scenarios with each one off and reports what changes.

**No model is called and no reviewer is simulated.** Proposals are written in `scenarios.py`; every reviewer action (who claims, views, approves, rejects, when) is scripted. When a scenario has a reviewer approve a wrong refund, that stands for a reviewer who missed it, not for how often people do. Nothing here measures human behaviour.

## Run it

Python 3.10 or later, standard library only.

```bash
cd 08-review-desk/python
python3 -m unittest test_desk -v                 # 45 tests, about 0.03 s
cd .. && python3 python/run.py --run 4           # writes results/report-run4.txt and observations-run4.json
cmp results/observations-run4.json results/observations-run1.json && echo identical
```

(`--run 1` to `--run 3` would overwrite the recorded runs.)

## Files

| File | What it is |
|---|---|
| `PROTOCOL.md` | The question, the 16 safeguards, scenarios R01 to R22 with their expected outcomes, and the ablation predictions. Written before any code (SHA-256 `2b1c8c96...` at 2026-11-24 16:52:47 UTC, unchanged) |
| `PROTOCOL-ADDENDUM.md` | Written after the first independent review (D4) and before any code change: the fix, scenarios R23 to R26, amended predictions (`3f3c2a69...` at 17:18:38 UTC, unchanged) |
| `PROTOCOL-ADDENDUM-2.md` | Written after the second independent review (D8) and before any code change: the fixes, scenarios R27 to R32, amended predictions (`367f684c...` at 17:31:50 UTC, unchanged) |
| `PROTOCOL-ADDENDUM-3.md` | Written after the second reviewer's follow-up (D13) and before any code change: the fixes, scenarios R33 to R35, amended predictions (`31baaa46...` at 17:37:56 UTC, unchanged) |
| `data/accounts.json` | Synthetic billing records. C-1001 is #29's account, unchanged: INV-1002 (October, $25) charged twice. C-3001 adds one $600 annual invoice |
| `data/directory.json` | The reviewers and their roles: ana and ben (support); chen, dee and eli (billing_lead) |
| `data/policy.json` | Tiers, who may decide each, approvals needed, SLA, expiry, lease, reasons for rejection. A demo policy, not advice on real limits |
| `python/billing.py` | The simulated billing service (system of record and outbox) and the fake clock |
| `python/desk.py` | The desk: routing, review items, revisions, claims, decisions, the two-phase executor, the sweeper, audits, label export. `SAFEGUARDS` lists the 16 switches |
| `python/scenarios.py` | The 35 scenarios |
| `python/test_desk.py` | The expected outcomes with every safeguard on, plus unit checks |
| `python/run.py` | Runs everything, a determinism check, and the ablation; writes the report |
| `results/` | `freeze.json` (fourth freeze), `tests.txt`, three runs (`report-run1..3.txt`, `observations-run1..3.json`) |
| `results/v1/`, `v2/`, `v3/` | The first three freezes and their runs, kept as they were |

## Results (2026-11-24, Python 3.12.13, macOS)

Four freezes, each after the protocol for it was written and before any of its runs:

| Freeze | When (UTC) | Tests | Runs (observations SHA-256) | Why it ended |
|---|---|---|---|---|
| 1 | 16:59:00 | 29 of 29 | 3 identical (`ba4a705e...`) | The first review found that action binding was checked only when a decision landed (D4) |
| 2 | 17:20:05 | 34 of 34 | 3 identical (`25ebc83d...`) | The second review found the fix incomplete: a two-person bypass, revisions skipping intake, every action run as a refund, and more (D8) |
| 3 | 17:34:34 | 41 of 41 | 3 identical (`818195d7...`) | The second reviewer's follow-up found store credits outside the invoice cap and the evidence, decisions not tied to the screen's version, and revisions that could duplicate an open item (D13) |
| 4 | 17:38:49 | 45 of 45 | 3 identical (`93c2ed26...`) | Current |

The reports differ only in their first line ("run N"). Lint: `ruff check` (ruff 0.17.6, run with `uvx`) passes. The tables below are from the fourth freeze.

### With every safeguard on

| | Situation (scripted) | What the desk did |
|---|---|---|
| R01 | Informational reply | Sent automatically, no review item |
| R02 | $25 store credit, duplicate charge | Credited automatically (reversible, within the auto limit) |
| R03 | $25 refund, within policy; ana approves | One refund |
| R04 | $25 refund on a 45-day-old invoice (exception); ana approves, then chen | ana refused (support may not approve an exception); chen's approval executed |
| R05 | ana's approval claims the billing_lead role | Refused: the directory says support |
| R06 | dee claims an exception as billing_lead, moves to support, then approves | Refused: authority is checked when the decision lands |
| R07 | chen raises a goodwill refund and approves it; dee approves | chen refused (requester); dee's approval executed |
| R08 | $600 refund; chen approves, then dee | Pending after chen; executed after dee |
| R09 | The proposal is revised from $25 on INV-1002 to $15 on INV-1003 after ana viewed it; she approves | Refused: action changed since viewed (the revision opened version 2) |
| R10 | Approved; a chargeback opens on the duplicate payment before execution | Not executed; back in the queue as version 2, with the change listed |
| R11 | chen approves with an edit to $30 on a $25 invoice | Refused at execution by the hard check |
| R12 | A draft reply claims a refund that never happened; ana edits and approves | The edited reply is sent |
| R13 | A worker job queued at submission runs after ana rejects | Refused: the item isn't approved |
| R14 | Two workers both pass the checks, then both commit | One refund: the second write finds the first by its key |
| R15 | Nobody decides | Escalated at 4 h, expired at 24 h, customer told nothing was refunded |
| R16 | ana claims and leaves; ben claims at 45 min and approves | ben's approval executed (ana's lease lapsed at 30 min) |
| R17 | The same proposal submitted twice | One review item, one decision, one refund |
| R18 | A "duplicate charge" refund on an invoice charged once | Needs evidence: ana's approval refused |
| R19 | #29's wrong-but-allowed refund ($15 on INV-1003 for an October complaint); ana approves; eli audits it | Executed (review missed it; nothing in code could tell). Exported: ana's approval as an operational decision, eli's audit as the gold label "wrong" |
| R20 | A seeded case that should be rejected; ana approves | Seeded catch rate 0 of 1; never executed |
| R21 | ana escalates with a recommendation to reject; chen approves | Escalated with ana's reason; chen's approval executed |
| R22 | The billing service writes the refund, then the connection drops; the executor retries | First attempt: execution_failed (outcome unknown). Retry: found the refund by its key. One refund |
| R23 | ana approves $25 on INV-1002; the proposal is revised to $15 on INV-1003; the worker runs | The revision opened version 2; the worker is refused; no money |
| R24 | $600; chen approves; revised to $599; dee approves; chen approves again | Pending after dee (chen's approval was of $600); one $599 refund after chen approves it |
| R25 | $600; dee opens it; chen approves with an edit to $550; dee approves from her earlier screen | dee refused (action changed); pending; no money |
| R26 | A seeded case nobody decides | Expired at 24 h; no customer message |
| R27 | $600; chen approves; dee edits to $450 and approves; chen approves $450 | Pending after dee (still two approvers needed); one $450 refund approved by dee and chen |
| R28 | Revisions to another customer's invoice, to `close_account`, then to $15 on INV-1003 claiming a duplicate; ana approves | First two refused; the third is version 2, needs evidence; ana refused; no money |
| R29 | $100 store credit (above the auto limit); chen tries an edit to a refund, then approves | Edit refused; one $100 credit, no refund |
| R30 | A seeded $20 store credit | No automatic credit; a review item; no money |
| R31 | Refund written, answer lost; the assistant re-submits the same refund as a revision; the executor retries | Revision refused (outcome unknown); retry finds the refund by its key; one refund |
| R32 | ana approves $25; the executor's checks pass; the proposal is revised to $10; the executor writes | Write refused (the item changed after the checks); version 2 pending; no money |
| R33 | ana approves a $25 refund on INV-1002; before it runs, a $25 store credit on INV-1002 is paid automatically | The credit is written; the refund goes back to the queue (evidence changed); no refund |
| R34 | A refund with no claims; ana opens it; revised with the same action and a duplicate claim; ana approves from her first screen | Refused (screen out of date); version 2 pending; no money |
| R35 | Two open refunds in one conversation ($25 and $10 on INV-1002); the $10 one is revised to $25 | Revision refused (it would duplicate the open item) |

### Ablation: one safeguard off

Each row is one safeguard off, everything else on. "Changed" means the scenario's observed outcome differs from the all-on run; whether the change is the predicted harm was checked by reading the differences in `report-run1.txt` (`run.py` checks only that the predicted scenarios changed). Every predicted scenario changed. Where the harm differs from the prediction, it's marked.

| Off | What changed |
|---|---|
| G1 authority_from_directory | R05: $25 refunded on an exception approved by a support reviewer |
| G2 authority_at_decision | R06: $25 refunded on the approval of someone who no longer held the role |
| G3 requester_cannot_approve | R07: $25 refunded on chen's approval of his own request |
| G4 two_person_rule | R08, R24: $600 refunded on chen's approval alone. R25: $550 on chen's edit alone. R27: $600 on chen's approval alone, before dee's edit (**the predicted harm was $450 on dee's alone**; it's a one-approval refund either way) |
| G5 bind_to_action | R09: $15 refunded on INV-1003, an action nobody was shown. R23: $15 refunded on ana's approval of $25 on INV-1002. R24: $599 with chen's approval of $600 counted. R25: $550 with dee's approval of $600 counted. R27: $450 with chen's approval of $600 counted. R28: the revision didn't open a new version (no money). R32: $25 written after the proposal was revised to $10. R34: $25 refunded on a decision from a screen that didn't show the claim |
| G6 bind_to_evidence | R10: $25 refunded while a chargeback was open on the same payment. R33: no harm; the hard check at execution refuses the refund instead (nothing left after the credit) |
| G7 validate_at_execution | R11: $30 refunded on a $25 invoice |
| G8 execute_final_version | R11, R12, and **R27 (not predicted)**: no harm. The executor's approval-count check (G5) refused the original version, which nobody approved, and the item went back to the queue. In the first freeze, without that check, R12's original reply was sent and R11 ran $25 instead of chen's $30 |
| G9 executor_checks_decision | R32: $25 written after the proposal was revised. R13 and R23 change **without the predicted harm**: in the second freeze they moved money; now the executor's approval-count check (G5) refuses them, because nobody approved the action on the current version |
| G10 execute_once | R14: two $10 refunds. R22 and R31 (predicted): no second refund, because the retry saw the evidence changed and sent the item back to the queue |
| G11 silence_is_not_consent | R15: $25 refunded at 24 h by the timeout. **Also R26 (not predicted):** the seeded case was approved by the timeout; it didn't execute (G16) |
| G12 claim_lease | R16: ben refused while ana's claim stood; escalated at 4 h, expired at 24 h; the correct refund was never issued. The escalation released ana's claim, so the item could have been taken for 20 hours; the script has nobody act after the escalation |
| G13 dedupe_submissions | R17: two review items and two decisions for one request (one refund: the second item went back to the queue when the evidence changed). R35: the revision accepted; two open items for the same $25 refund |
| G14 evidence_gate | R18: $15 refunded for a duplicate the records don't show. R28: the same, through a revision |
| G15 label_provenance | R19: the approval exported as gold "correct", next to the audit's gold "wrong". The other scenarios with an accepted decision or a seeded case (10 predicted, **14 not predicted**; R34 was predicted but has no accepted decision, so nothing changed): every accepted decision became a gold label, including R21's escalation (gold "wrong") and chen's approval (gold "correct") on the same item; seeded cases lost their known answer, and in R20 ana's approval replaced it as gold "correct" |
| G16 seeded_cases_inert | R20: the seeded case's $15 refund executed. R26: the expiry message sent to the customer for a seeded case. R30: the seeded $20 store credit paid automatically |

Overlaps: some harm is stopped twice. With G8 off, G5 stops R11, R12 and R27; with G9 off, G5 stops R13 and R23; with G13 off, G6 stops R17's second approval; with G10 off, G6 stops the retries in R22 and R31; with G6 off, G7 stops R33. A safeguard whose case another one also covers shows nothing when it alone is removed.

The all-on run is repeated in every run as a determinism check (identical in all 35 scenarios). It isn't a negative control in the usual sense; what shows the comparison can fail is the ablation itself.

## What this shows and what it doesn't

- **The tests** show that this desk produces the expected outcomes for these scripted inputs, with every safeguard on.
- **The ablation** shows, for each scenario, which single safeguard stands between it and the harm in this code, and where two safeguards overlap. It shows necessity within these scenarios, not that the 16 are sufficient or complete: the first freeze passed 29 tests with a hole in its central safeguard, the second passed 34 with more, and the third passed 41 with store credits outside the invoice cap.
- **Neither** shows that a production review system is safe, that the policy limits are right, or anything about real reviewers: how often they miss a wrong proposal, how long they take, or how they respond to the screen. R19 and R20 have a reviewer approve a wrong refund because the script says so.

## Design choices worth knowing

- **Evidence is the account's records** (invoices, charges, refunds, open disputes). Any change on the account invalidates a pending approval. That's conservative: it catches R10's chargeback, and it also sends items back for changes that don't matter to them, which costs reviewer time. The proposal's claims are shown next to the records but aren't part of the evidence fingerprint.
- **Store credit counts toward the invoice:** what can still be refunded or credited on an invoice is its amount minus both.
- **The evidence gate checks structured claims only.** R18 and R28 claim `duplicate_charge`; R19's free-text reason isn't checked, so R19 reaches a person.
- **A revision carries its own claims.** If it states none, the gate has nothing to check (R09, R23), and the screen shows the empty claims. Carrying the earlier claims forward was suggested in review and not adopted: it's a policy choice, and R09 and R23 depend on this one.
- **A revision can't change the customer or the tool, use a tool the assistant isn't allowed, duplicate another open item, or happen while an execution's outcome is unknown.** A different customer is a new proposal.
- **An edit is checked at execution, not when it's made.** R11 shows the check catching it. Article #29's demo checks a modified action at decision time too, which is friendlier to the reviewer. An edit can't change the tool or the customer.
- **An edit becomes what the next approver sees:** the screen shows the edited action, who edited it, and the original.
- **The write re-checks the item:** `commit()` refuses if the item's version changed after `prepare()`, or its status is no longer approved, execution_failed or completed. A completed item still reaches the billing service, so that R14's second worker is decided by the idempotency key, as in a real race.
- **Rejecting or escalating needs a role, not the authority to approve.** Anyone in the directory can stop an action or send it up.
- **`request_changes` closes the item.** The requester submits a new proposal; the desk doesn't tell the customer anything. A real desk would route that back to whoever owns the conversation.
- **Gold labels come from audits and seeded cases only.** Agreement between two independent reviewers is another valid source; it isn't implemented here.
- **The requester is named by the proposal** (`requested_by`), the same kind of trust in the request that R05 refuses for roles. A real desk takes the requester's identity from the authenticated session or the calling service.

## Limitations

- **Scripted inputs.** No model and no people: the scenarios are written to exercise each safeguard.
- **One process, SQLite in memory, a fake clock.** A real desk has many workers, a shared database, notifications that can fail, and clocks that disagree. The two-worker race in R14 and the revision between checks and write in R32 are interleaved by hand.
- **Simulated money.** "Refunding" appends a row in `billing.py`.
- **All data is synthetic.**
- **No audit-log integrity.** Events are plain rows. Tamper evidence and what a record must hold in a regulated setting are Article #41's subject (`07-audit-evidence`).

## Deviations

- **D1 (all freezes).** In R22 and R31, the report shows the refund as "approved by: no approval". The approvers are recorded when the executor sees the billing service's answer; in those scenarios the refund was written and the answer was lost. ana's accepted approval is in the decision log (`observations-run1.json`).
- **D2 (first freeze).** `PROTOCOL.md`'s G15 prediction listed only R19. With label provenance off, every scenario with an accepted decision exports gold labels, so 14 more scenarios changed.
- **D3 (first freeze).** `PROTOCOL.md`'s G8 prediction listed only R12; R11 changed too (the executor ran $25, not chen's $30). From the second freeze on, both are stopped by G5.
- **D4 (found after the first freeze by an independent review; fixed in the second).** Action binding was checked only when a decision landed. With every safeguard on: an approval of $25 on INV-1002 executed as $15 on INV-1003 after a revision; a two-person approval of $600 counted toward a revised $599; after an edit to $550, the second approver's screen still showed $600; an expired seeded case messaged the customer. Fix and R23 to R26: `PROTOCOL-ADDENDUM.md`.
- **D5 (second freeze).** `PROTOCOL-ADDENDUM.md` predicted R01 to R22's all-on outcomes unchanged. R09 changed in one detail: its item is version 2, because the revision now opens a new version. ana is still refused and no money moves.
- **D6 (second freeze, still present).** With G11 off, R26 changed, not predicted: the timeout approved the seeded case, which G16 kept from executing.
- **D7.** `PROTOCOL.md`'s R21 reads "ana rejects it (outside_policy) and escalates". The code records one decision, `escalate`, carrying ana's recommendation (reject) and reason (outside_policy), and the item stays open for billing_lead. The expected outcome holds; the recorded decision type differs from the protocol's wording.
- **D8 (found after the second freeze by a second independent review; fixed in the third).** With every safeguard on: after an edit lowered the stored tier and the executor sent the item back, one billing lead approved $600 alone; a revision could change the customer, use `close_account`, or skip the evidence gate; an approved store credit (and any non-reply action) ran as a cash refund; a seeded store credit was paid automatically; a revision while an outcome was unknown led to a second refund; a revision between the checks and the write was swallowed; and stale approvals blocked an edit-then-reapprove flow. Fixes and R27 to R32: `PROTOCOL-ADDENDUM-2.md`.
- **D9 (third freeze).** `PROTOCOL-ADDENDUM-2.md` predicted the R01 to R26 ablation cells unchanged from the second freeze. Three differ: with G9 off, R13 and R23 no longer move money (G5's approval count now stops them); with G8 off, R11's reopened item shows the proposal's tier (within_policy) instead of exception.
- **D10 (third freeze).** With G4 off, R27's harm is $600 on chen's approval alone (before dee's edit), not the predicted $450 on dee's alone. With G8 off, R27 changed, not predicted, without harm.
- **D11 (third freeze).** R30's script first used INV-1003 ($15), which the hard checks refuse for $20 before any routing; it was changed to INV-1002 during development, before the freeze. The addendum doesn't name the invoice.
- **D12.** The observation format changed in the third freeze: each credit now lists its approvers (`None` for automatic credits), so `observations-run1.json` isn't byte-comparable with `results/v2/`. With that column set aside, R01 to R26's all-on outcomes are identical to the second freeze's.
- **D13 (found after the third freeze by the second reviewer's follow-up; fixed in the fourth).** With every safeguard on: a $600 store credit and a $600 refund both executed on the $600 invoice, because credits counted toward neither the invoice cap nor the evidence (this came in with the third freeze's dispatch); a decision from the screen of an earlier version was accepted after a revision that changed only the claims; a revision could make an item identical to another open item. Fixes and R33 to R35: `PROTOCOL-ADDENDUM-3.md`. R01 to R32 came out identical to the third freeze, all-on and in every ablation cell.
- **D14 (fourth freeze).** `PROTOCOL-ADDENDUM-3.md` predicted that G15 off would change R34's labels; R34 has no accepted decision, so nothing changed.
