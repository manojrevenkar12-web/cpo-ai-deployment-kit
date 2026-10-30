# Handover: Roaming CDR disputes

Owner: Head of Roaming Finance (roaming_finance). Spec: `config/usecases/cdr_disputes.yaml`. Runbook: `playbooks/runbooks/cdr_disputes.md`.

## What it does
eMSPs dispute CDRs by email in five languages and three formats. A finance analyst finds each record, re-rates it by hand from the CSMS and the tariff history, and writes a credit note or a rejection. About 25 disputes a week, half an hour each, and wrong credits are rarely noticed.

Models read: dispute.read, dispute.reply. Code decides: which CDR, cause, credit amount, credit or reject. Approvals: credit_note by finance_approver.

## Why it is handed over now
- more than 100 disputes a week
- a second roaming hub
- or ERP posting without batch approval

## Go-live gate
- pass: spec_complete (all sections present)
- pass: sprint_within_budget (8 person-days planned (limit 10))
- pass: evals_pass (all thresholds met)
- pass: no_money_from_injected_text (injected_credit_eur=0.0)
- pass: access_enforced (outsiders refused)
- pass: approvals_on_money_and_publishing (every money or publishing action names an approver role)
- pass: runbook_present (playbooks/runbooks/cdr_disputes.md)
- pass: cost_per_case_within_alert (0.00070 EUR per case (alert above 0.05))

## In use
- 5 of 5 people have used it; 67% of live cases go through it; 99% of proposals accepted.
- Usage share by training: not trained 60%, trained 69%
- Handling time per case: -48% (95% interval -56% to -40%), interrupted time series (no control group).
- Hours saved so far: 132 (interval 72 to 191)

## Known failure modes (from the evals)
- by_cause: {'duplicate': 0.964, 'energy_mismatch': 1.0, 'idle_fault': 1.0, 'no_error': 1.0, 'peak_window': 1.0, 'tariff_version': 1.0, 'unknown_session': 1.0, 'vat_rate': 1.0}
- Share of cases sent to a person for review: 8%

## Monitoring
- quality: ['share of proposals edited before sending', 'credit amount changed by approver', 'partner re-disputes']
- operations: ['p95 latency', 'gateway errors', 'cost per case']
- alerts: {'edited_share_above': 0.35, 'cost_per_case_above_eur': 0.05}
