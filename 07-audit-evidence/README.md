# 07-audit-evidence

Companion code for **[Building AI Systems for Regulated Environments](https://snehalagrawal.com/articles/building-ai-systems-for-regulated-environments/)** (Article #41).

A control you can't show operating is an assumption. This demo runs a fictional lender's AI-assisted hardship workflow, puts the lender's questionnaire to the records it leaves, and then breaks things on purpose:
- a prompt edited after its evaluation;
- a provider-side model change;
- an execution that differs from its approval;
- a stale approval;
- self-approval;
- a bypass;
- edited, deleted and truncated log events;
- a full rewrite of the log;
- a planted value;
- an erasure request;
- two simulated years of retention.

For each failure it shows what the records can prove, and what they can't.

**It is an engineering illustration, not a compliance test.** Passing every check here says nothing about whether any law or regulation is met. The lender, the borrowers, the staff, the letters and the policy are all fictional.

## What is simulated, configured, and measured

- **Fictional:** everything in `data/`. That includes the 12 hardship requests, the staff directory, and a hardship policy at v14 and v15.
- **Simulated:**
  - **The model.** `data/stand_in_outputs.json` holds hand-written extraction and recommendation outputs. No model is called, and nothing leaves the machine.
  - **The model identifiers.** `lender-recommender` (requested) and `lender-recommender-2026-10-01` (returned) are invented strings. The stand-in returns no version metadata, and the records say so.
- **Configured:**
  - the release definitions and the policy limits;
  - the reviewers' decisions;
  - a fake clock starting 2026-11-03;
  - the retention periods in `data/retention.json`. These are illustrative, not legal periods.
- **Fixtures:** the evaluation records in `data/evaluations.json`. No evaluation is run here. The demo checks that a release can only go live if an evaluation record matches its exact manifest.
- **Measured:** only E10's timings. Every other result is a deterministic outcome: what the records contain, what a gate refused, what the checker reported.

[PROTOCOL.md](PROTOCOL.md) has the design and the expectations E1–E12 (63 checks). They were written after the data and before any code:
- `results/freeze-inputs.json` froze the protocol and the data at 2026-11-24 16:43:06 UTC.
- `results/v1/freeze.json` froze the code at 16:50:19 UTC, before the first reported run. After the delegated review fixed two bugs (D3), `results/freeze.json` re-froze it at 17:11:47 UTC.
- The 63 checks themselves are in `report.py`, which was frozen with the code, not with the protocol.

## The workflow and its records

```text
letter + income statement
  -> extraction (stand-in)          sees the letter; nothing else
  -> policy at its version, account snapshot as of now
  -> recommendation (stand-in)      sees extracted facts, the policy, balance/arrears/fees; no name, no letter, no loan ID
  -> rule checks -> route by role -> reviewer decision (decision gate) -> executor (execution gate) -> ledger
every step -> one hash-chained event in audit.jsonl (references and keyed digests instead of letters and prompts; structured facts such as amounts and check results stay)
```

| Store | Holds |
|---|---|
| `audit.jsonl` | The audit log. One event per step, each holding the hash of the one before. Letters, statements, snapshots, prompts and outputs appear only as references and HMAC-SHA256 digests made with the subject's key. It does hold structured decision facts: amounts, check details such as "surplus 70.00", staff IDs, and the internal subject ID. All of those are personal data, and they survive an erasure (see D4) |
| `content/`, `keys.json` | Letters, income statements, account snapshots, rendered prompts, raw outputs, one directory per subject; one random key per subject |
| `outbound.jsonl` | What was sent to the (simulated) provider, and the model string it returned |
| `eval_cases.jsonl` | A derived copy: C03 and C07 added to an evaluation set |
| `traces.jsonl`, `app.log` | Spans and log lines without content |
| `ledger.jsonl` | The system of record for fee waivers and payment plans |
| `anchor/anchors.jsonl` | The external anchor: the log's length and head hash after each batch. In production, this belongs somewhere the log's writers can't change |
| `releases/`, `purge_log.jsonl` | The manifest of each activated release; what retention deleted |

**Gates:**
- **Deploy gate:** a release goes live only if its manifest SHA-256 matches an earlier evaluation record.
- **Decision gate and execution gate:** both check the role's limit under the active policy, separation of duties, and that the release hasn't changed since the case was routed. The execution gate also requires an approval with the exact action fingerprint.

The **checker** (`checker.py`) reads only the stores. It never sees the workflow's state:

| Check | What it verifies |
|---|---|
| K1 | The chain |
| K2 | The anchor |
| K3 | Every execution has a valid approval |
| K5 | The ledger reconciles with the audit log |
| K6 | The returned model string matches the evaluated one |
| K7 | A difference from the recommendation was recorded as a modification |
| K8 | Every decision has all its steps |

**Reconstruction** (`reconstruct.py`) answers nine questions about one decision from the records alone. Content is shown only when its keyed digest matches the log.

## Run it

Python 3.10 or later, standard library only.

```bash
cd python
python -m unittest test_evidence.py     # 11 tests
python run.py                           # baseline + E1-E12, about 3 seconds; writes runs/<stamp>/ (not committed)
python report.py                        # checks the run against PROTOCOL.md; exit 1 if any check fails
python report.py --negative-control     # two expectations flipped on purpose: must report them and exit 1
python compare.py ../runs/*             # repeat runs: stable section identical? E10 timing ranges
```

## Results (six runs under two code freezes, 2026-11-24)

- **Setup:** Python 3.12.13, macOS 26.6.2, Apple M4 Pro, other programs running.
- **First freeze (16:50:19 UTC):** three runs, 16:50–16:51 UTC, one-minute load averages 3.75, 4.01 and 4.41 at the start of each. Their reports are in `results/v1/`.
- **Second freeze (17:11:47 UTC), after the delegated review:** three runs, 17:11–17:12 UTC, load averages 1.77, 1.77 and 2.19. These fixed two bugs the reported scenarios never reach (D3). Their reports are in `results/`.
- **Result:** 62 of 63 checks passed in every run.
- **Repeats:** the stable section (everything except timings) was identical across all six runs (SHA-256 `f50cd696…`; `results/compare.txt` and `results/v1/compare.txt`).
- **Negative control:** it failed the two flipped checks (E7c.1 and E9.1) as intended, alongside the known E9.2 failure, and exited 1 (`results/negative-control.txt`).

| | Scenario | What happened |
|---|---|---|
| B | Baseline: 12 cases under assistant-2026.11.1 | Deploy gate admitted manifest `f83e1fdc…`. 10 executed, 2 with no action (C06 decline confirmed, C12 rejected), 10 ledger entries. C05 and C10 went to a lead. Only C12's surplus check failed. The checker found nothing |
| E1 | Reconstruct D-C01 and D-C04 | All nine questions answered from the records. Q3 shows both model strings and "no version metadata returned". D-C04 keeps recommended 35.00, modified to 20.00, executed 20.00 as three separate facts |
| E2a | One character appended to the recommendation prompt | Deploy gate refused; the diff named exactly `recommendation_prompt`; no decision was made |
| E2b | The stand-in returns `lender-recommender-2026-11-20` for two new decisions | Both executed normally: no gate reads the returned string. K6 flagged exactly those two |
| E3 | Approved 35.00, asked to execute 50.00 | Executor refused; the ledger was unchanged; the refusal was logged. A forced write (log and ledger) was flagged by K3. A forced 20.00 after an "approve" of 25.00 was flagged by K3 and K7; D-C04's recorded modification was not |
| E4 | Approved under v14, then v15 goes live | Execution refused as stale. Re-processed under v15, the case routes to a lead, and S-103's approval is refused (agent limit 40.00). A forced execution was flagged by K3 (stale, and over the new limit) |
| E5 | Self-approval; an agent approving 120.00 | Both refused by the decision gate; forced records of both flagged by K3 |
| E6 | Execution with no decision; ledger entry with no audit event | K3 flagged the first, K5 the second. **With K5 off, the second went unseen**: the checker only sees what was recorded |
| E7 | Edit one event; delete one; truncate the tail | Edit and delete: K1 broke at the edited event and at the one after the deleted one. **Truncation: the chain still verified.** Only K2 (shorter than the anchor) and K8 (D-C12 incomplete) caught it |
| E8 | Rewrite D-C01's reviewer and recompute every hash | **K1 verified.** Only the anchor (K2) caught it; with K2 off, nothing was reported |
| E9 | Canary `CANARY-7Q4K-2291` in C07's letter | Found in the content store, `outbound.jsonl` and **`eval_cases.jsonl`**. Not found in the audit log, app log, traces, ledger, anchors or any recommendation prompt. **The expectation (E9.2) failed**: the protocol missed the evaluation-set copy that this demo makes itself (see Deviations). Negative control: a logger writing prompts put the canary in `app.log` |
| E10 | A standalone experiment: a loan ID `L-398841` hashed on its own, the way a naive design might log it (the demo's own log never holds a digest of a loan ID). 1,000,000 possible IDs | Plain SHA-256 recovered after 398,842 attempts in 0.159–0.176 s across the six runs. HMAC: whoever holds the key recovers it the same way (0.448–0.479 s). With another random key: 0 matches in 1,000,000 (1.170–1.227 s), which is the expected result, not a discovery |
| E11 | Erasure ER-0001 for B-1003 on 2026-11-20 | 7 content items, the key, 2 outbound requests and 1 eval case deleted; one `erased` event appended; the chain still verified. D-C03's Q1 and account snapshot: "content erased, 2026-11-20, ER-0001"; policy version and Q3–Q9 still answered. Negative control: a cache keyed by prompt hash still held C03's prompt |
| E12 | Retention on the fake clock | 2026-12-04: traces and outbound purged, nine questions still answered (by design: reconstruction never reads them). 2027-11-04: content, keys and the eval set purged; Q1 and the snapshot say "content deleted by retention (content-365d)"; the rest answered; chain verified. 2028-11-03: audit purged; D-C01 not answerable, and the purge log names the rule, the 109 events and their date range |

## What this does and doesn't show

- **It shows** what this record design can answer, and which faults the checker detects: here, the 12 injected ones.
- **It doesn't show:**
  - that the records are complete for a real system, or that unseeded faults are caught;
  - that a decision was right;
  - **that a record is authentic.** The checker verifies that records are consistent with each other and with the policy. A forged decision naming an authorised reviewer, for a case nobody reviewed, passes it. Showing who really approved needs an authenticated decision store, or one written by a separate system;
  - that the anchor itself is secure, or that the purge log is. `chain_start()` trusts `purge_log.jsonl`, so a deleted prefix with a forged purge entry would pass K1 and K2;
  - that the checker distinguishes retention from tampering. Run after the two-year purge, it reports K2 (the log is shorter than the anchor) and K5 (ledger entries with no executed event). A real design re-anchors after an authorised purge, and gives the ledger its own retention;
  - that roles were right *at the time*. The checker reads today's `staff.json`, not a history of roles;
  - that deleting a key or a file counts as erasure in law, or that any retention period is correct.
- **Some checks are true by design:** E9.5 (no letter contains a name, and the workflow never reads the name field), E10.3 (another random key finding no match), and Q8's status (always "answered"; the answer carries whether the chain verifies).
- **No real provider was called.** Which identifiers you can record depends on the provider and endpoint. The article covers what each documents, as of November 2026.

## Deviations

- **D1 (E9.2, a failed expectation, kept).** The protocol expected the canary only in the content store and `outbound.jsonl`. It was also in `eval_cases.jsonl`, the evaluation-set copy that `run_baseline` makes of C03 and C07, letter included. The protocol lists that store, but its E9 expectation missed it. The code was not changed to pass the check, because the miss is the lesson: a derived copy is one more place the data went. E11 shows that the erasure job reaches it, because the copy is keyed by subject.
- **D2 (E4, an implementation detail).** "A new approval by S-103" is made on the case processed again under 2026.11.2, as decision D-E4-r. The original decision can't be approved again, because it was routed under the old release, and the decision gate refuses it as stale before reaching the limit check.

- **D3 (code fixed after the delegated review; reported results unchanged).** The reviewer found two bugs that no reported scenario reaches:
  - after a partial purge of the audit log, the checker crashed, because the release activation had aged out with the oldest events;
  - reconstruction blamed retention for any missing content once any content purge existed, even content deleted without a record.

  The checker now reports the missing release as a K3 finding, and reconstruction blames retention only for content created inside a purge record's date range. Two unit tests cover them. The code was re-frozen (`results/freeze.json`; the original is in `results/v1/`) and run three more times, and the stable section was identical to the first three runs.

  The design lesson stands: release records belong to the system file, with their own retention, not in the same log as the decisions. After a partial purge, surviving decisions here lose Q3 and Q9.
- **D4 (a claim in the frozen protocol corrected).** PROTOCOL.md says the audit log holds "No letter text, names, or account values". It holds no letters or names, but it does hold structured values derived from the account and the statement:
  - check details ("surplus 70.00", "35.00 of 35.00");
  - recommended, approved and executed amounts;
  - staff IDs;
  - the subject ID.

  The ledger holds the loan ID in plain text. All of these survive an erasure. Whether they may stay is the legal decision under GDPR Article 17(3)(b) that the article describes. Moving check details into the content store would shrink what survives.

## Files

| File | What it is |
|---|---|
| `python/workflow.py` | The workflow: deploy gate, the steps, decision gate, execution gate |
| `python/evidence.py` | Hash-chained audit log, content store with per-subject keys, anchor |
| `python/checker.py` | The independent checker, K1–K8 |
| `python/reconstruct.py` | The nine questions, answered from the records |
| `python/lifecycle.py` | Erasure, retention, and a scan of every store for a value |
| `python/hashes.py` | E10: plain vs keyed hashes |
| `python/run.py`, `report.py`, `compare.py`, `freeze.py` | Run, check against the protocol, compare repeats, freeze the code |
| `python/test_evidence.py` | 11 unit tests |
| `results/` | The input freeze, the current code freeze, three reports, their comparison, the negative control, and one run's observations. `results/v1/` holds the same files for the first code freeze |
