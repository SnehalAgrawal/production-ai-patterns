# Test material

This material was written and committed before any pipeline code: the emails, what a correct reply to each must contain, the scoring rules below, and the split into development and test emails. The pipeline's prompts and settings are chosen on the development emails. The test emails are used only for the reported results.

## Documents

The `documents/` folder holds the support documentation for a fictional project-management app. It contains five Markdown files, about 7,800 words in total. They are copied unchanged from [`rag-engineering/04-chunking/data/documents`](https://github.com/SnehalAgrawal/rag-engineering/tree/main/04-chunking/data/documents), as frozen in commit 3aa330a:

| File | SHA-256 |
|---|---|
| admin-guide.md | `7c1a52a88e50491804781b050e982e34b07bf9f93593675a340f8521cb9c47b3` |
| api-reference.md | `1cff46f15a5d64d551cd1d1c236235792844214c50fba68cb0b49b03c874aa39` |
| billing-guide.md | `1ad6b1a83f3ebcd9cbf4b8772e013b9113213309e47074a6ed090519e1e4328a` |
| data-processing-policy.md | `405a982c49ef6d7e267de04352b3a81661f1fec310e83765de4ef5255c36a230` |
| release-notes.md | `77ee5458d3c57753cc0d6a8dc35ea140f405d6518350ac82a81e7a687527c25b` |

The documents contradict each other on one point, which was noticed while writing these labels and left as it is. The billing guide's downgrade checklist says "Remove or suspend members until no more than 5 remain". The administrator guide says "Suspended members still count toward the member limit." No label depends on the billing guide's wording. Email e28 asks about this point, and its label follows the administrator guide, which states the rule directly.

## Emails

`emails/e01.txt` to `emails/e40.txt` are 40 customer emails. Each has a `From:` line, a `Subject:` line, a blank line, and the body. The senders, their companies and their addresses are invented, and every address uses the reserved `.example` domain.

| Questions per email | Emails | Development | Test |
|---|---|---|---|
| 1 | 14 | 7 | 7 |
| 2 | 16 | 8 | 8 |
| 3 | 10 | 5 | 5 |

Of the 76 questions, 6 can't be answered from the documents, 3 in each split: e10, e24, e27, e33, e37 and e40 each contain one. Some emails also contain numbers that belong to the customer, such as member counts, file sizes and an account reference.

`splits.json` assigns odd-numbered emails to development and even-numbered emails to test. This rule was fixed before the emails were written, and the emails were then ordered so that each split has the same mix of question counts and unanswerable questions. Development has more labelled facts and identifiers than test: 66 facts and 17 identifiers, against 54 and 12.

## Labels

`labels.json` holds the labels for each email:

- `identifiers` are the product identifiers the email mentions, written as they appear in it. These are only:
  - plan names (`Basic`, `Pro`);
  - error codes (`SSO-101` to `SSO-105`, and API error codes such as `cursor_expired`);
  - HTTP status codes;
  - HTTP header names;
  - webhook event names;
  - API versions (`v1`, `v2`).

  The customer's own numbers and references are not identifiers. Extraction is scored by comparing sets, ignoring case.
- `questions` lists each question the email asks:
  - `asks`: a reference wording of the question, for people reading the labels.
  - `match`: terms used to pair the pipeline's extracted questions with this one.
  - `answerable`: whether the documents answer it.
  - `facts`: what a correct reply must contain.
- Each fact has:
  - `check`: `mechanical` or `human`.
  - `any_of` (mechanical facts only): accepted wordings of its value.
  - `evidence`: one or more passages that support it, each with its file and exact text. Any one passage is enough.

### Scoring rules

**Extracted questions.** An extracted question is paired with every labelled question in the same email that has a `match` term in it. A term matches as a substring, ignoring case. Extraction succeeds for an email when two things hold:
- every labelled question is paired with at least one extracted question;
- every extracted question is paired with at least one labelled question.

Splitting one question in two, or merging two into one, therefore doesn't count as a failure. Pairings for failed emails are read by hand.

**Mechanical facts.** A mechanical fact is present in a reply when one of its `any_of` wordings appears in the reply as a whole word or phrase, comparing normalized text. Normalizing means:
- making the text lowercase;
- turning curly quotes into straight ones, and en and em dashes into hyphens;
- removing commas between digits (`1,000` becomes `1000`);
- collapsing runs of whitespace into one space.

A whole word or phrase is one with no letter or digit directly before or after it. Every mechanical fact has at least one wording that appears in its own evidence.

**Human facts.** Human facts, and replies to unanswerable questions, are read by hand. A correct reply to an unanswerable question says that the documentation doesn't cover it and states nothing about it as fact.

**Evidence.** Evidence is recorded as passages, not chunk IDs, because chunking is a setting of the pipeline. A retrieved chunk supports a fact if it contains one of the fact's evidence passages whole, as in the evidence-span scoring of [rag-engineering/04](https://github.com/SnehalAgrawal/rag-engineering/tree/main/04-chunking). This makes it possible to tell where a reply went wrong:
- **extraction:** the question was missed;
- **retrieval:** no supporting chunk was retrieved;
- **drafting:** the evidence was retrieved but the fact is missing or wrong;
- **verification:** a check passed a bad reply or rejected a good one.

## Counts

| | Development | Test |
|---|---|---|
| Emails | 20 | 20 |
| Questions | 38 | 38 |
| Unanswerable questions | 3 | 3 |
| Facts (mechanical / human) | 66 (51 / 15) | 54 (37 / 17) |
| Identifiers | 17 | 12 |
