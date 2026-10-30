# Handover: Driver refund tickets

Owner: Head of Customer Service (customer_service). Spec: `config/usecases/driver_refunds.yaml`. Runbook: `playbooks/runbooks/driver_refunds.md`.

## What it does
Drivers write to customer service in ten languages about failed sessions, double payments, card holds and prices. Agents search the CSMS and the payment provider by hand to decide a refund. About 100 tickets a week across eleven countries.

Models read: ticket.read, ticket.reply. Code decides: which session, refund amount, explain / escalate / redirect. Approvals: refund_above_40_eur by cs_lead.

## Why it is handed over now
- refunds without a person in the loop
- a new payment provider
- more than 500 tickets a week

## Go-live gate
- pass: spec_complete (all sections present)
- pass: sprint_within_budget (9 person-days planned (limit 10))
- pass: evals_pass (all thresholds met)
- pass: no_money_from_injected_text (injected_refund_eur=0.0)
- pass: access_enforced (outsiders refused)
- pass: approvals_on_money_and_publishing (every money or publishing action names an approver role)
- pass: runbook_present (playbooks/runbooks/driver_refunds.md)
- pass: cost_per_case_within_alert (0.00009 EUR per case (alert above 0.02))

## In use
- 43 of 43 people have used it; 38% of live cases go through it; 95% of proposals accepted.
- Usage share by training: not trained 17%, trained 49%
- Handling time per case: -20% (95% interval -33% to -7%), staggered difference-in-differences.
- Hours saved so far: 108 (interval 36 to 193)

## Known failure modes (from the evals)
- by_kind: {'double_capture': 0.972, 'no_energy': 0.967, 'preauth_hold': 0.947, 'price_display': 0.969, 'roaming_driver': 0.905, 'stuck_session': 0.978, 'unidentifiable': 1.0, 'valid_charge': 0.926}
- errors: {'explain->ask_info': 7, 'redirect_emsp->ask_info': 6, 'refund->ask_info': 5, 'escalate_payments->ask_info': 2}
- Share of cases sent to a person for review: 7%

## Monitoring
- quality: ['share of drafts edited', 'refunds changed by leads', 'tickets reopened']
- operations: ['p95 latency', 'gateway errors', 'cost per case']
- alerts: {'edited_share_above': 0.35, 'cost_per_case_above_eur': 0.02}
