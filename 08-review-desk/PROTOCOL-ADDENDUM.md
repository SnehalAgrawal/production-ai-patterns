# Protocol addendum (second freeze)

Written 2026-11-24 after the first freeze and its three runs, and before any code change. `PROTOCOL.md` is not edited. The first freeze's results are kept in `results/v1/`.

## Why

An independent review (a separate Claude agent, read-only, which re-ran the demo from a copy) found that action binding was checked only when a decision landed, never at execution or across revisions. With every safeguard on, its probes showed:

- **A.** Ana approves $25 on INV-1002; the proposal is then revised to $15 on INV-1003; the executor refunds $15 on INV-1003, recorded as approved by Ana.
- **B.** On a two-person $600 item, Chen approves, the proposal is revised to $599, Dee approves: $599 executes as approved by Chen and Dee, although Chen never saw $599.
- **C.** On a two-person item, Chen approves with an edit to $550; Dee's screen still shows $600; Dee approves; $550 executes.
- **D.** A seeded case that expires sends the real customer the expiry message.

The 22 scenarios never exercised these paths. They contradict what the article and README say the desk does, so the code is changed, not only documented.

## Changes (all under the existing switches)

- **G5 bind_to_action**, extended:
  - Each accepted approval records the fingerprint of the action it approved: the current action for `approve`, the edited action for `approve_with_edit`.
  - An approval counts toward the required number only if its fingerprint equals the item's effective action (the edit if there is one, else the proposal).
  - A revision of an open item starts a new version: status back to pending, earlier approvals and edits no longer count, the claim is released. A revision of a closed item is refused.
  - The executor runs an action only if every counted approval's fingerprint equals the fingerprint of the action it is about to run; otherwise the item goes back to the queue as a new version.
  - With G5 off, none of this happens, as before.
- **The screen** shows the effective action, with "edited by" and the original, and its fingerprint is the effective action's. This is a display correction, not a switch.
- **G16 seeded_cases_inert**, extended: a seeded case that expires sends no customer message.
- **Report wording:** a prediction is reported as "target changed" (the harm is checked by reading the listed differences, as before). The second all-on run is called what it is: a determinism check. The ablation itself is what shows the comparison can fail.

## New scenarios (all safeguards on)

| Id | Situation (scripted) | Expected |
|---|---|---|
| R23 | $25 refund on INV-1002; ana approves; the proposal is revised to $15 on INV-1003; the worker runs the item | The revision opens version 2 (pending); the worker is refused (not approved); no money |
| R24 | $600 refund on INV-3001; chen approves; the proposal is revised to $599; dee approves; then chen approves again | After dee: pending (1 of 2 on version 2), no money. After chen: one $599 refund approved by dee and chen |
| R25 | $600 refund on INV-3001; dee opens it; chen approves with an edit to $550; dee approves from the screen she opened earlier | dee refused (action changed); item pending (1 of 2); no money |
| R26 | A seeded case nobody decides | At 24 h expired; no customer message; no money |

R01 to R22: every all-on outcome unchanged.

## Ablation predictions for the second freeze

Every cell in `PROTOCOL.md`'s table is predicted unchanged except as listed here. New or changed cells:

| Off | Changes |
|---|---|
| G4 | R08 (as before); R24: $600 refunded on chen's approval alone, before the revision (money); R25: $550 refunded on chen's edit alone (money) |
| G5 | R09 (as before); R23: $15 refunded on INV-1003 on ana's approval of $25 on INV-1002 (money); R24: $599 refunded as approved by chen and dee, chen's approval being of $600 (money); R25: $550 refunded with dee's approval of $600 counted (money) |
| G8 | R11 and R12 change, **without** the earlier harm: the executor's fingerprint check refuses the original version, which no counted approval quoted, and the item goes back to the queue. No $25 in R11, no original reply in R12. (The G8 harm now needs G5 off too.) |
| G9 | R13 (as before); R23: $15 refunded with no approval on version 2 (money) |
| G15 | Also R23, R24, R25, R26: labels change (gold labels from decisions; R26's seeded gold label disappears) |
| G16 | R20 (as before); R26: the expiry message is sent to the customer for a seeded case (message) |

## What this addendum can't fix

The first freeze's protocol and code are on record (`results/v1/freeze.json`); the gap was found after them, by a reviewer's probes outside the protocol. The new scenarios cover the four paths the review found, not every path through revisions and edits.
