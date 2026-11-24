# Protocol

Written on 2026-11-24, after the data in `data/` and before any code in `python/` existed. `results/freeze-inputs.json` records the SHA-256 of this file and of every data file at that moment. A second freeze, `results/freeze.json`, records the code before the first reported run, and every run checks both. If anything here has to change after a freeze, the change is recorded under "Deviations" in the README; this file is not edited.

Development runs (single scenarios, and full runs used to find bugs in the code and the report) were allowed before the code freeze. They are not reported.

## Question

A regulated customer asks of every AI-assisted decision: what went in, what came out, which system produced it, who approved it, what was executed, and can you still show that later. This demo asks a narrower, testable question:

> Given the records a workflow keeps, which questions about one decision can be answered from the records alone, which controls can be shown to have operated, and which failures can the records detect, and which can't they?

It is an engineering illustration, not a compliance test. Passing every check here says nothing about whether any law is met.

## What is simulated, configured, and measured

- **Fictional:** the lender, the 12 borrowers, their letters and accounts, the staff, the policy (`data/`).
- **Simulated:** the model. `data/stand_in_outputs.json` holds hand-written extraction and recommendation outputs, returned by a stand-in that also returns a model identifier string. No model is called and nothing leaves the machine. The provider identifiers (`lender-recommender`, `lender-recommender-2026-10-01`) are invented strings; the stand-in returns no version metadata, and the records say so.
- **Configured:** the release definitions, the policy limits, the retention periods (`data/retention.json`: illustrative, not legal periods), the reviewers' decisions (`data/decisions.json`), and a fake clock starting 2026-11-03.
- **Measured:** only E10's timings (how long enumerating a hash takes on this machine). Everything else is a deterministic outcome: what the records contain, what a gate refused, what the checker reported.

## The system under test

One workflow per hardship request, as in the article: receive the letter and income statement, extract facts (stand-in), retrieve the policy at its version and an account snapshot, recommend (stand-in), run rule checks, route to a reviewer by role, record the reviewer's decision, execute the approved action through an executor, keep the evidence.

### Stores (each a file under the run's directory)

| Store | Holds | Keyed by subject? |
|---|---|---|
| `audit.jsonl` | The audit log: one hash-chained event per step. No letter text, names, or account values; references and keyed digests instead | Holds the internal subject ID (pseudonymous, still personal data) |
| `content/` | Letters, income statements, account snapshots, rendered prompts, raw outputs | Yes |
| `keys.json` | One random HMAC key per subject | Yes |
| `outbound.jsonl` | What was sent to the (simulated) provider, and the model string it returned | Yes |
| `eval_cases.jsonl` | A derived copy: cases C03 and C07 added to an evaluation set | Yes |
| `traces.jsonl` | Debug spans: step names, durations, model strings; no content | No (decision ID only) |
| `app.log` | The application log: one line per step, no content | No |
| `ledger.jsonl` | The system of record for fee waivers and payment plans | Decision ID |
| `anchor/anchors.jsonl` | The external anchor: log length and head hash, written after each batch | No |
| `releases/` | Each release's manifest | No |
| `purge_log.jsonl` | What retention deleted: rule, store, count, date range; no personal data | No |

### Rules fixed in advance

- **Canonical JSON** is `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8.
- **Event hash:** `sha256(prev_hash + canonical(body))`, where `body` is the event without `prev` and `hash`, and the first `prev` is 64 zeros.
- **Manifest:** `{"release": id, "components": {...}}`, where each component is its entry in `data/releases.json` plus a `sha256`: the file's bytes for a prompt file, and the canonical JSON of the policy version for the policy. The model and workflow components carry no hash. The manifest SHA-256 is the hash of its canonical JSON. For the two releases these are `f83e1fdc…` (assistant-2026.11.1, policy v14) and `9cc4c56e…` (assistant-2026.11.2, policy v15); the code must reproduce them.
- **Action fingerprint:** SHA-256 of the canonical JSON of the action (`action`, and `amount` in cents or `months`).
- **Content digests** in the audit log are HMAC-SHA256 with the subject's key.
- **Deploy gate:** a release may be activated only if its computed manifest SHA-256 equals an evaluation record's, and that evaluation is dated before the activation.
- **Execution gate (and decision gate)**, checked when a reviewer decides and again when the executor runs: an approve or modify decision exists for this decision ID (execution only); the action to execute has the approved fingerprint (execution only); the release and policy version active now are the ones the decision was made under; the reviewer's role allows the amount under the active policy; the reviewer did not raise the exception. A refusal is written to the audit log.
- **Routing:** waivers above the agent limit go to a hardship lead; everything else to a hardship agent. Every recommendation is reviewed before any action.
- **Rule checks** recorded per decision: `surplus_below_threshold` (income minus expenses below 200, or the recommendation is a decline), `amount_within_fees` (waiver at most the fees outstanding), `plan_within_limit` (at most 3 months).

### The independent checker (`checker.py`)

It reads only the stores, never the workflow's state:

- **K1** the chain verifies; report the first broken sequence number.
- **K2** the anchor: the log is at least as long as the anchored count, and the hash at that count equals the anchored head.
- **K3** every `executed` event has an earlier approve or modify decision for that decision ID, with the same action fingerprint, by a role allowed for the amount under the policy version active at execution, by someone other than the exception's raiser, with no release change between decision and execution.
- **K5** reconciliation: every ledger entry has exactly one `executed` event naming it, and every `executed` event has its ledger entry.
- **K6** every model call's returned model string equals the one observed in the evaluation of the release in use.
- **K7** an executed action that differs from the recommendation has a `modify` decision.
- **K8** every decision has the required steps in order: received, context, two model calls, recommended, checked, routed, and then decided and executed or no action.

(K4 was dropped during drafting, before the freeze; the numbering is kept.)

### Reconstruction (`reconstruct.py`)

Given a decision ID, it answers the nine questions in `data/questionnaire.json` from the audit log, the content store, the release manifests and the policy store. Each answer is `answered`, `content erased` or `content deleted by retention` (with the date and request or rule), or `not answerable` (with the reason). Content is shown only if its HMAC digest matches the one in the audit log.

## Expectations

Each run starts from an empty directory. "Baseline" is all 12 cases under assistant-2026.11.1, activated at 2026-11-03T08:00:00Z. Each scenario works on its own copy of the baseline, or on decisions it creates itself, so no scenario affects another.

| | Scenario | Expected |
|---|---|---|
| B | Baseline | The deploy gate admits assistant-2026.11.1 (manifest `f83e1fdc…`). 12 decisions; 10 executed (C01–C05, C07–C11), 2 with no action (C06, a confirmed decline; C12, rejected). 10 ledger entries. C05 and C10 routed to a hardship lead, the other 10 to an agent. C12's `surplus_below_threshold` check fails; every other check passes. The checker reports 0 findings |
| E1 | Reconstruct D-C01 and D-C04 from the records alone | All nine questions `answered`. Q3 shows the requested and returned model strings and "no version metadata returned". D-C04 shows the recommendation (waiver 35.00), the decision (modify, 20.00) and the execution (20.00) as three separate facts, and Q7 says the execution matches the approval and differs from the recommendation by a recorded modification |
| E2a | One character appended to `recommendation_prompt.txt` in a copy | The deploy gate refuses; the manifest diff names exactly one component, `recommendation_prompt`; no decision is made under it |
| E2b | The stand-in starts returning `lender-recommender-2026-11-20`; two new decisions (C02's and C09's inputs) | Both run and execute normally (no gate reads the returned string); K6 flags exactly those two decisions and none of the baseline |
| E3 | A new decision on C01's inputs, approved at 35.00 | (a) Asked to execute 50.00, the executor refuses; the ledger is unchanged and the refusal is in the audit log. (b) A forced write (an `executed` event and a ledger entry for 50.00, written without the executor): K3 flags it. (c) In the baseline, D-C04 (modify) is not flagged by K7; a forced `executed` event that differs from the recommendation after an `approve` decision is flagged by K7 and K3 |
| E4 | A new decision on C08's inputs (45.00) approved by S-103 under 2026.11.1; then 2026.11.2 (policy v15) is activated | The deploy gate admits 2026.11.2 (`9cc4c56e…`). Execution is refused as stale (release and policy changed since the decision). A new approval by S-103 is refused (the agent limit is 40.00 under v15). A forced `executed` event for the stale approval is flagged by K3 |
| E5 | (a) C10's inputs; S-104, who raised the exception, approves. (b) C05's inputs (120.00); S-101, an agent, approves | Both decisions refused by the decision gate. Forced decision and execution records for both are flagged by K3: one for separation of duties, one for the role's limit |
| E6 | (a) An `executed` event and a ledger entry for a decision that was routed but never decided. (b) A ledger entry with no audit event | K3 flags (a). K5 flags (b). Negative control: the checker with K5 turned off reports nothing for (b) |
| E7 | On the baseline log: (a) the reviewer in D-C01's decision event changed; (b) D-C02's `routed` event deleted; (c) the last 3 events (D-C12's tail) removed | (a) K1 broken at the edited event. (b) K1 broken at the event after the deleted one. (c) K1 verifies (truncation leaves a valid chain); K2 flags the log as shorter than the anchor; K8 flags D-C12 as incomplete |
| E8 | D-C01's reviewer changed and every hash from there recomputed | K1 verifies. K2 flags a head-hash mismatch. With K2 turned off, the checker reports nothing |
| E9 | The canary `CANARY-7Q4K-2291` is in C07's letter; borrower names are in `cases.json` only | After the baseline the canary is in the content store and in `outbound.jsonl` (the extraction request), and in none of `audit.jsonl`, `app.log`, `traces.jsonl`, `ledger.jsonl`, the anchors, or any recommendation prompt. No borrower name appears outside the content store. Negative control: C07 rerun with a logger that writes rendered prompts at DEBUG: the canary is found in `app.log` |
| E10 | Account numbers are `L-` plus 6 digits (1,000,000 values). C07's is `L-398841` | Plain SHA-256: enumerating `L-000000` to `L-999999` recovers it after 398,842 attempts. HMAC with C07's key: whoever holds the key recovers it the same way. HMAC with a different random key: 0 matches in 1,000,000. Timings measured and reported; no expectation on them |
| E11 | Erasure request ER-0001 for subject B-1003 (C03) on 2026-11-20, with a response cache keyed by prompt hash added in this copy | Before: B-1003 has items in content, keys, outbound and eval_cases. After: none in any of them; the audit log gains one `erased` event and K1 verifies. Reconstructing D-C03: Q1 and the account snapshot in Q2 say `content erased` with the date and ER-0001; the policy version in Q2 and Q3–Q9 are `answered`. Negative control: the cache, not keyed by subject, still holds C03's extraction prompt (the phrase "reduced hours until January" is found in it, and only in it) |
| E12 | Retention on the fake clock, on the baseline: purge at 2026-11-03, 2026-12-04, 2027-11-04 and 2028-11-03 | Day 0: nothing purged; D-C01's nine questions `answered`. 2026-12-04: all traces and outbound requests purged; still nine `answered`. 2027-11-04: content, keys and eval_cases purged; Q1 and the snapshot in Q2 say `content deleted by retention` (rule and date), the rest `answered`, K1 verifies. 2028-11-03: the audit log is purged; reconstruction of D-C01 says `not answerable` and names the purge-log entry (rule `audit-730d`, event count, date range) |

## Negative control for the report

`report.py --negative-control` runs the same checks with two expectations changed on purpose (E7c expects K1 to fail; E9 expects the canary to be absent from `outbound.jsonl`). It must report those two failures and exit 1.

## Repeats

Three full runs after the code freeze. Every outcome except E10's timings is deterministic, so the report's stable section (everything except timings, random keys and digests) is compared by SHA-256 across the three runs. E10's timings are reported as ranges.
