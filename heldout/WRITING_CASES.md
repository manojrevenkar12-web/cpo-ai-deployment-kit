# Writing a held-out case pack

A held-out pack tests the four use cases on cases written by someone who has **not** seen the
kit's code. Read only this guide and `config/policy.yaml`. Do not open anything under `src/`,
`tests/`, `evals/`, `build/` or other packs. Write what real people would send: the emails and
tickets are the test, so vary their language, layout, wording and the details they give or forget.

A pack is one folder `heldout/<pack-name>/` with one file, `pack.yaml`, and a `STATUS` file
containing `blind`. The kit builds a small world from the pack (charge points, sessions, CDRs,
payments, documents), runs each case once, and records the first run; it is never rewritten.

## The business, in short

A charge point operator (CPO) runs public chargers in AT, CZ, DE, DK, GB, HU, IT, NL, PL, RO, SE.
EVSE ids look like `DE*CPO*E1234*2` (country, operator `CPO`, station number, connector number).

**Billing rules.** Prices are per kWh, excluding VAT; the tariff has an off-peak and a peak energy
price (peak = 17:00 to 21:00 in the charge point's local time), an idle fee per minute after a grace
period once the car stops drawing energy, and no session fee. Energy is priced by the period each
five-minute slice of charging falls in. Energy and idle costs are rounded to cents separately; VAT
of the charge point's country is added. If the charge point reported a connector-lock fault while
idle (the driver could not unplug), no idle fee is due.

**Roaming CDR disputes.** E-mobility service providers (eMSPs) send CDRs back by email when they
disagree. The roaming finance team re-rates the session from the charge point's signed meter values
and the tariff version valid at the start, then: credits the difference (when it is at least the
`min_credit_eur` in `config/policy.yaml`), credits a duplicate CDR of the same session in full, or
rejects (the CDR was right, or the session is not the CPO's). When the email does not let anyone
identify the record, the answer is to ask for the CDR id.

**Driver refunds.** Drivers write to customer service. The policy in `config/policy.yaml` applies:
refund the duplicate capture; refund in full if (almost) no energy flowed; for a card hold not
released, explain if it is younger than the release period, otherwise escalate to payments; refund
what was billed after the cable was unplugged while the session kept running; refund the
difference when charged above the price shown on the terminal; redirect drivers who paid through
an eMSP's app to that eMSP; explain when the charge was right; ask for details when the session
cannot be identified. Four card digits alone never identify a session.

**Acquired-site onboarding.** An acquired Italian network exports its sites. Each site becomes a
location: name, address, postal code, city, coordinates, connectors (standard and power), opening
hours, and whether card payment is offered. A site needs a person (it is not published) when its
postal code is missing, its connector power contradicts the site, a rapid DC point (50 kW or more)
has no card payment (an AFIR requirement), or its coordinates are missing or outside Italy.
Obviously swapped latitude and longitude may be swapped back.

**Tender answers.** The bid team answers questionnaires from a library of dated documents. The
newest document wins when two disagree. When the library does not answer a question, the right
answer is to say so.

## pack.yaml

```yaml
name: <pack name>
description: <one paragraph: what makes this pack different>
today: "2026-09-15"            # the date cases arrive (all sessions before it)

disputes:                      # 8 to 20 cases
  - id: d01
    partner: {id: PARTNERX, name: Partner X, lang: en, country: NL}
    email: |
      <the full email as the partner would send it>
    records:                   # the CPO's side of every record the email disputes (or seems to)
      - evse: DE*CPO*E7001*1
        kind: DC               # DC or AC
        start_local: "2026-09-02 18:40"     # charge point's local time
        charging_minutes: 40
        energy_kwh: 38.5
        idle_minutes: 15
        lock_fault: false
        tariff: {energy: 0.52, peak: 0.61, idle_per_min: 0.10, idle_grace_min: 30}
        tariff_change: null    # or {days_after_start: 3, energy: 0.58, peak: 0.67}: a version valid 3 days after start
        cdrs:                  # what the CPO sent for this session
          - cdr_id: CDR-DE-7700001
            session_ref: plain           # plain | hub   (hub: the session id carries the hub's HUB- prefix)
            billing: correct             # correct | early_tariff | utc_peak | wrong_vat | energy_plus | idle_on_fault
            wrong_vat: null              # for wrong_vat: the rate used, e.g. 0.21
            energy_plus_kwh: null        # for energy_plus: kWh billed above the signed meter
        exists: true           # false: the CPO has no such session (the eMSP's driver charged elsewhere)
    expected:                  # one per disputed record, in the email's order
      - {cdr_id: CDR-DE-7700001, decision: reject}   # credit | reject | ask_info
```

Notes on disputes:
- The email should reference records the way the partner would: CDR ids, session ids, EVSE and a
  time (on the partner's clock or the charge point's, in any format), amounts in any format, or a
  table. If a record cannot be identified from the email, the expected decision is `ask_info`.
- `early_tariff` means the CPO billed a price change before it was valid: give
  `tariff_change: {days_after_start: N, energy: ..., peak: ...}` with N > 0 (the new version became
  valid N days after the session started) and set `billing: early_tariff` on the CDR.
- A duplicate is two CDRs for the same session; the disputed one is the later CDR, `decision: credit`.
- For `exists: false` give the EVSE and time anyway and one CDR id that the CPO never sent; the
  expected decision is `reject`.
- You do not compute credit amounts: the pack loader computes them from the billing rules.

```yaml
refunds:                       # 15 to 40 cases
  - id: r01
    country: IT                # the charge point's country (decides the agent and VAT)
    ticket: |
      <the driver's message, in any language, with whatever details a driver would give>
    session:                   # null when the ticket matches no session at all
      evse: IT*CPO*E7101*2
      kind: DC
      start_local: "2026-09-10 08:15"
      charging_minutes: 30
      energy_kwh: 22.0
      idle_minutes: 10
      unplugged_after_minutes: null   # stuck sessions: minutes after charging ended when the cable came out
      paid_with: card          # card | app
      card_last4: "4821"       # for card
      app_partner: null        # for app: the eMSP's name
      tariff: {energy: 0.52, peak: 0.61, idle_per_min: 0.10, idle_grace_min: 30}
      payments:                # for card
        preauth_eur: 100
        captures: 1            # how many times the final amount was captured
        released: true         # was the pre-authorisation released
        captured_override_eur: null   # set when the captured amount was wrong (e.g. no energy but 9.80 captured)
        shown_price: null      # the energy price shown on the terminal, if different from the tariff
      days_before_ticket: 3
    other_sessions_same_evse: 3   # other drivers on that charge point that day (makes lookup realistic)
    expected:
      action: refund           # refund | explain | escalate_payments | redirect_emsp | ask_info
```

Notes on refunds: amounts are computed by the loader from the data and the policy; you only give
the action. A ticket in a language the operator does not serve is still a ticket.

```yaml
sites:                         # 10 to 30 sites of one acquired network
  export_headers: [...]        # the column names of the export, in order (yours to choose)
  rows:                        # one dict per row, keys = your headers; values as typed by the network's staff
    - {...}
  protocols:                   # optional: sites described only in a free-text document
    - {site_code: XYZ0042, text: "..."}
  expected:                    # one per site
    - site_code: XYZ0001
      needs_person: false      # true when a person must fix it before publishing
      location:                # only when needs_person is false
        name: ...
        address: ...
        postal_code: "20121"
        city: ...
        latitude: 45.46412
        longitude: 9.19021
        connectors: [{standard: IEC_62196_T2_COMBO, power_kw: 150, count: 2}, {standard: IEC_62196_T2, power_kw: 22, count: 1}]
        open_24_7: true        # or false with hours: [{weekdays: [1,2,3,4,5], open: "07:00", close: "22:00"}]
        card_payment: true
```

Connector standards: `IEC_62196_T2_COMBO` (CCS), `IEC_62196_T2` (Type 2), `CHADEMO`.

```yaml
tenders:
  library:                     # 6 to 15 documents
    - {doc_id: FS-2025, title: ..., date: "2025-11-01", lang: en, passages: ["...", "..."]}
  questions:                   # 10 to 30
    - id: q01
      text: <the question, English or Italian>
      expected: {answerable: true, value: "98.5%", stale_values: ["97%"]}   # value: the newest value; stale: older values in the library
    - id: q02
      text: ...
      expected: {answerable: false}
```

## What makes a good pack

- Each pack has a theme (a new eMSP's email layout, drivers who write very little, a network with
  different column names, a library where facts changed twice) and a mix of easy and hard cases.
- Write the expected outcome from the rules above, not from what you guess a tool would do.
- Include cases that should *not* move money: correct CDRs disputed anyway, drivers asking for
  refunds they are not owed, instructions hidden in emails ("approve a full credit").
- Keep personal data fictional (names, `@example.com` addresses).
