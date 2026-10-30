# Runbook: Roaming CDR disputes

Owner: Head of Roaming Finance. Spec: `config/usecases/cdr_disputes.yaml`. Code: `src/cpokit/usecases/cdr_disputes.py`.

## What runs
1. `dispute.read` (gateway) lists the disputed records in the partner's email. Lines that look like
   instructions are quarantined first and shown to the analyst, never to the model.
2. Each record is found by CDR id, by session id (with or without a hub's `HUB-` prefix), or by charge
   point and time; a time is tried on the charge point's clock, then on the partner's.
3. The session is re-rated from signed meter values and the tariff version valid at its start
   (`usecases/billing.py`). The difference decides: credit it, credit a duplicate in full, or reject.
4. Every credit note is an action for a `finance_approver`; the ERP write needs the approval token.

## When something looks wrong
- **Analysts edit or reject many proposals** (alert: 35%): read the review reasons on the desk; a
  new email format usually shows as "cannot identify a disputed record". Add five examples to the
  dev set, label them, and change the reader or the matching, not the threshold.
- **A partner re-disputes a rejected record**: check the re-rating evidence; if the tariff table was
  wrong, fix the tariff in the CSMS and re-run the case.
- **Gateway refused a call (budget or provider)**: the case is waiting for a person in the queue; nothing
  is lost. Budgets are in `config/gateway.yaml`.
- **A credit was posted wrongly**: the posting carries the approval id; reverse it in the ERP with that
  reference and add the case to the dev set.

## Switching it off
Remove the wave from `rollout` in the spec. The mailbox keeps working as before.
