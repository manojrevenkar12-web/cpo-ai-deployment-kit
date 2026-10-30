# Handover: Acquired-site onboarding

Owner: Integration Lead Italy (integration_ops). Spec: `config/usecases/site_onboarding.yaml`. Runbook: `playbooks/runbooks/site_onboarding.md`.

## What it does
An acquired network hands over 120 sites as a spreadsheet with Italian headers and some commissioning protocols. Each site must become an OCPI location with AFIR-compliant data before it is published to roaming partners and the national access point.

Models read: site.map. Code decides: validation, AFIR checks, publish or needs a person. Approvals: publish_location by integration_lead.

## Why it is handed over now
- a second acquisition
- or onboarding becomes a continuous feed

## Go-live gate
- pass: spec_complete (all sections present)
- pass: sprint_within_budget (5 person-days planned (limit 10))
- pass: evals_pass (all thresholds met)
- pass: no_money_from_injected_text (no money moves in this use case)
- pass: access_enforced (outsiders refused)
- pass: approvals_on_money_and_publishing (every money or publishing action names an approver role)
- pass: runbook_present (playbooks/runbooks/site_onboarding.md)
- pass: cost_per_case_within_alert (0.00211 EUR per case (alert above 0.05))

## In use
- 3 of 4 people have used it; 48% of live cases go through it; 100% of proposals accepted.
- Usage share by training: not trained 0%, trained 72%
- Handling time per case: -45% (95% interval -59% to -26%), interrupted time series (no control group).
- Hours saved so far: 22 (interval -4 to 47)

## Known failure modes (from the evals)
- field_errors: {}
- Share of cases sent to a person for review: 20%

## Monitoring
- quality: ['locations corrected after publishing', 'issues overruled by people']
- operations: ['cost per site']
- alerts: {'corrected_after_publish_above': 0}
