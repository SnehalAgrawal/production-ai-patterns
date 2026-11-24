# Protocol: Part A

Written and approved before any Part A result was computed, and frozen by hash in `data/FROZEN.json` with the code that applies it. If anything here has to change after the freeze, the change is recorded as a deviation in the README; this file is not edited.

Part B (a fresh v3 run and a friendlier v4 prompt, with model calls) gets its own protocol and freeze before its first model call.

## Question

Can a deterministic check identify the same correct and wrong emails as a person, and can a comparison of two versions on the same emails show which emails changed, rather than only whether a total moved?

## Material (all from `01-reliable-llm-pipeline`, read-only)

- **Emails, labels, split:** 01's 20 test emails, with the facts each correct reply must contain (`data/labels.json`) and the split (`data/splits.json`). Both were committed in 01's commit 08bf05c, before any pipeline code or reply existed, and haven't changed since.
- **Replies:** the 39 test replies 01 hand-labelled, exported once into `data/replies.json`. `check.py` confirms each is the exact text that was labelled.
- **Original labels:** `data/hand_labels.json`, one verdict per reply (correct or wrong) with a note. 01 records that the replies were read in full and the labels reviewed. It doesn't record who labelled them; the README states what has been confirmed.

## Arms

Both arms use prompt v3, `llama3.2:3b`, temperature 0, seed 1, on the same 20 test emails.

| Arm | What it is | Replies |
|---|---|---|
| `chain` (baseline) | 01's pipeline end to end with no checks: extract, retrieve, draft | 19; e14 has none (its draft wasn't valid JSON) |
| `perfect_inputs` (candidate) | drafting alone, from the labelled questions with every evidence passage in context | 20 |

## Definitions

- **Unit:** the email.
- **Email outcome:** correct when every labelled fact of the answerable questions is stated correctly, every question the documentation doesn't cover is said to be not covered, and nothing false is stated. An arm with no reply for an email has a wrong outcome for it (e14 in `chain`, as in 01's article).
- **Grader:** 01's mechanical fact check (`score.py`), applied per email:
  - *pass*: every mechanical fact of the answerable questions is present;
  - *fail*: at least one is missing;
  - *not gradeable*: the email has no mechanical fact.
  
  Human facts and uncovered questions are listed as not checked, and never count as passes.
- **What the grader is measured on:** expected mechanical wording present, against a person's judgment of the whole reply. The fact list itself is reused as committed and is not validated here: the labels' rule refers to the same list, so this tests the check, not the list.
- **Positive class:** a reply labelled wrong.
  - *Missed error:* the grader passes a reply labelled wrong.
  - *False alarm:* it fails a reply labelled correct.
  
  Both are reported as counts with their denominators.
- **Calibration denominator:** replies that exist and whose email has at least one mechanical fact. e14 in `chain` is outside it, because it has no reply, but stays a wrong outcome.
- **Comparison:** per email, `chain` against `perfect_inputs`:
  - both correct, both wrong, fixed (wrong to correct), broken (correct to wrong);
  - an exact two-sided sign test on the fixed and broken emails.
  
  No other test, and no claim of improvement without the case-level changes.
- **Slices,** from the labels alone: questions per email (1, 2, 3); contains an uncovered question; fact mix (all mechanical, mixed, all human, no facts). Each slice is reported with its own denominator.

## Labels and sequencing

- **Blind labels:** the human reference for Part A is a new set of labels, written by the user on a worksheet that shows no arm, no grader verdict, no original label and no original note.
  - **Order:** replies are shuffled, behind neutral ids.
  - **Contents:** the worksheet also contains Part B's replies, so both of Part B's arms are labelled blind in the same pass.
  - **Single labeller:** if only one person labels, the report says so.
- **Agreement:** comparing the blind labels with 01's original labels gives an agreement measurement, reported as counts in both directions.
- **Sequencing:** the substantive report (`report.py --labels ...`) runs only after `data/blind_labels.json` exists, and `report.py` enforces this. Before that, only the checks and controls run (`report.py --controls`), and they print counts only.
- **Gates:** false refusals and false answers come only from the blind labels, which record each question. 01's original labels have one verdict per reply and can't give them. The test split has 35 answerable and 3 uncovered questions. An arm with no reply for an email (e14 in `chain`) has no label for that email's questions, so its denominators are smaller; the report prints the denominator it used.

### Blind label format (`data/blind_labels.json`)

```json
{
  "labeller": "who labelled",
  "labels": {
    "<01 label key of the reply>": {
      "email": "e02",
      "questions": {"e02q1": "correct"},
      "false_statement": false,
      "note": "optional"
    }
  }
}
```

- **Answerable question:**
  - `correct`: every labelled fact stated correctly;
  - `wrong`: addressed, but a fact is missing or wrong;
  - `omitted`: not addressed;
  - `declined`: said it can't be answered, which counts as a false refusal.
- **Uncovered question:**
  - `declined`: said to be not covered;
  - `answered`: anything stated as fact about it, which counts as a false answer.
- **`false_statement`:** true when the reply states anything false, anywhere.
- **Errors:** a missing question or a value outside these is an error, never a guess.

## Controls

- `check.py`: every frozen file unchanged; each arm covers the 20 test emails once; every reply's key and SHA-256 match its text; every key is in 01's `hand_labels.json`.
- The grader run twice gives identical records.
- The baseline compared with itself gives 0 flips.
- The baseline compared with a copy with one outcome altered gives exactly 1 flip.

## Expectations, written before any result

These are expectations, not guaranteed outcomes. If the results differ, the difference is reported and the expectation is not rewritten.

- **E1:** the grader misses wrong replies whose fault is a false claim, or a confident answer to an uncovered question, because it only looks for required facts.
- **E2:** it catches omissions where the missing fact is mechanical.
- **E3:** some false alarms, from correct wordings not in the accepted list (01's "API key" against "API keys" is the precedent).
- **E4:** coverage is partial: emails with no mechanical fact can't be graded, and emails with human facts are graded only partly.
- **E5:** `perfect_inputs` against `chain` shows flips in both directions, and an exact sign test at 20 emails can't rule out no difference.

## Stop conditions

Stop and report, rather than adjust, if:
- a frozen hash doesn't match;
- the material or labels can't be reconciled;
- a grader expectation turns out to come from the replies it judges;
- a change would invalidate this protocol;
- a run would require changing 01.
