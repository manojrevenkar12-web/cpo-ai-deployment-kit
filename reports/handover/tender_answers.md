# Handover: Tender and grant questionnaires

Owner: Head of Business Development (bid_team). Spec: `config/usecases/tender_answers.yaml`. Runbook: `playbooks/runbooks/tender_answers.md`.

## What it does
Motorway concession tenders and EU grant reports ask the same hundred questions again, in English and Italian. The bid team searches old answers by hand and sometimes copies a number that has since changed.

Models read: tender.query, tender.answer. Code decides: which passages may be used (newest only), verification of citations and numbers, abstain. Approvals: send_answer by bid_manager.

## Why it is handed over now
- library above 5
- 000 documents (move to Azure AI Search)
- or answers sent without review

## Go-live gate
- pass: spec_complete (all sections present)
- pass: sprint_within_budget (6 person-days planned (limit 10))
- pass: evals_pass (all thresholds met)
- pass: no_money_from_injected_text (no money moves in this use case)
- pass: access_enforced (outsiders refused)
- pass: approvals_on_money_and_publishing (every money or publishing action names an approver role)
- pass: runbook_present (playbooks/runbooks/tender_answers.md)
- pass: cost_per_case_within_alert (0.00076 EUR per case (alert above 0.05))

## In use
- 4 of 4 people have used it; 63% of live cases go through it; 88% of proposals accepted.
- Usage share by training: trained 63%
- Handling time: no cases before launch: the effect on handling time cannot be measured.

## Known failure modes (from the evals)
- Share of cases sent to a person for review: 28%

## Monitoring
- quality: ['answers rewritten by bid managers', 'stale-number findings']
- operations: ['p95 latency', 'cost per question']
- alerts: {'rewritten_share_above': 0.4}
