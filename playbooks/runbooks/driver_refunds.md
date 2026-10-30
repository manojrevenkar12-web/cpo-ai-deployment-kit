# Runbook: Driver refund tickets

Owner: Head of Customer Service. Spec: `config/usecases/driver_refunds.yaml`. Code: `src/cpokit/usecases/driver_refunds.py`.

## What runs
1. `ticket.read` gives language, what the driver reports and the details given (charge point, address,
   time, card digits, app). E-mail addresses, phone numbers and card numbers are masked before the call.
2. The session is found from the charge point and time, or address and time; card digits narrow it
   down but are never enough on their own (four digits are shared by many drivers).
3. The policy in `config/policy.yaml` decides from the records: refund (duplicate capture, no energy,
   billed after unplugging, charged above the price shown), explain, escalate a stuck card hold,
   redirect a roaming driver to their provider, or ask for details.
4. Refunds above 40 EUR need a `cs_lead`; smaller ones are approved by the agent who sends them.

## When something looks wrong
- **Many "ask for details" outcomes in one country**: drivers there describe stations differently
  (street names, landmarks). Collect examples, label them, extend the reader.
- **Refunds reopened by drivers**: compare the refund with the payment provider's records.
- **Policy change** (for example a new card-hold period): change `config/policy.yaml`, re-run
  `cpokit eval driver_refunds`, then `cpokit ready`.

## Switching it off
Remove the country from its wave in the spec; agents in that country work as before.
