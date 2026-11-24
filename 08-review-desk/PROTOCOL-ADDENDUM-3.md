# Protocol addendum 3 (fourth freeze)

Written 2026-11-24 after the third freeze and its three runs, and before any code change. Earlier protocol files are not edited. The third freeze's results are kept in `results/v3/`.

## Why

The second reviewer re-ran its probes against the third freeze. Findings 1 to 7 and 9 of its first report were closed. New, with every safeguard on (N1 reproduced by the author before this addendum):

- **N1.** Store credits were outside the invoice cap and the evidence: a $600 credit and a $600 refund both executed on the $600 invoice INV-3001, and the evidence fingerprint didn't change when a credit was written. This came in with the third freeze's dispatch (before it, a reviewed credit ran as a refund and was counted).
- **N2.** A decision wasn't tied to the claims it was shown: after a revision that changed only the claims (same action), an approval from the earlier screen was accepted.
- **N3.** A revision could turn an item into a duplicate of another open item in the same conversation.

Not adopted: carrying a proposal's claims forward into a revision that states none. A revision carries its own claims (as in the third freeze); the screen shows them, empty or not. R09 and R23 depend on this.

## Changes

- **Always on (intake and hard checks):** store credit written against an invoice counts toward what can still be refunded or credited on it (`left_to_refund`). Credits record their invoice.
- **Evidence:** the account's records include credits per invoice, so a credit written after an approval changes the evidence (G6).
- **G5 bind_to_action:** a decision must also quote the version of the screen it was made on.
- **G13 dedupe_submissions:** a revision that would make an item identical (same conversation and action) to another open item is refused.

## New scenarios (all safeguards on)

| Id | Situation (scripted) | Expected |
|---|---|---|
| R33 | $25 refund on INV-1002 (duplicate claim); ana approves; before it runs, a $25 store credit on INV-1002 is paid automatically (a second conversation); the worker runs the refund | The credit is written; the refund isn't: the evidence changed, the item goes back to the queue as version 2; one $25 credit, no refund |
| R34 | $25 refund on INV-1002 submitted with no claims; ana opens it; it's revised with the same action and a duplicate claim; ana approves from her first screen | Refused (the screen's version is out of date); version 2 pending; no money |
| R35 | One conversation: $25 refund on INV-1002, and $10 on INV-1002; the second is revised to $25 | Revision refused (it would duplicate the open item); two items, the second still $10 |

R01 to R32, all safeguards on: predicted unchanged in outcome. The evidence fingerprints in the report change (credits are now part of the evidence).

## Ablation predictions for the new scenarios

| Off | Changes |
|---|---|
| G5 | R34: ana's approval accepted and $25 refunded on her first screen (money) |
| G6 | R33: the refund is refused by the hard check at execution instead (nothing left after the credit); no refund, status refused_at_execution |
| G13 | R35: the revision is accepted; two open items for the same $25 refund (review load) |
| G15 | R33, R34: labels change |

Every other new cell: no change. Cells for R01 to R32: as in the third freeze.
