# Runbook: Acquired-site onboarding

Owner: Integration Lead Italy. Spec: `config/usecases/site_onboarding.yaml`. Code: `src/cpokit/usecases/site_onboarding.py`.

## What runs
1. `site.map` maps one export row or commissioning protocol to location fields.
2. Checks: coordinates inside Italy (swapped coordinates are swapped back and recorded), connector
   power consistent with the site, a postal code, opening hours, and AFIR card payment at rapid points.
3. Only a location without open issues is proposed for publishing; an `integration_lead` approves.
   Issues go to a person: the tool never fills a postal code or a payment method it was not given.

## When something looks wrong
- **A published location is corrected later** (alert: any): stop publishing, find the field in the
  export row, add the row to the dev set with the right value.
- **A new export layout**: the header map is in the reader; add the new headers and a labelled sample.

## Switching it off
Remove the wave; the integration team maps rows by hand.
