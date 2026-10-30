# Runbook: Tender and grant questionnaires

Owner: Head of Business Development. Spec: `config/usecases/tender_answers.yaml`. Code: `src/cpokit/usecases/tender_answers.py`.

## What runs
1. `tender.query` turns the question (English or Italian) into English keywords; BM25 retrieves passages.
2. Passages stating the same fact are grouped and only the newest document's is kept.
3. `tender.answer` drafts with citations; the verifier rejects a sentence without a valid citation or
   with a number that is not in the cited passage. Below the retrieval threshold the answer is
   "the library does not answer this", for a bid manager to write.
4. A `bid_manager` approves each answer before it goes into a bid.

## When something looks wrong
- **A stale number reached a draft**: the newer document probably words the fact differently; add a
  fact sheet entry with the same wording, or lower the grouping threshold after an eval run.
- **Many abstentions**: the library lacks the topic; that is a content gap for the fact owners, not a
  reason to lower the threshold.

## Switching it off
Remove the wave; the library stays searchable as before.
