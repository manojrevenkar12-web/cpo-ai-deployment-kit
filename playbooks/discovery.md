# Discovery: from a business function's problem to a ranked use case (day 1)

1. **Sit with the people who do the work** for half a day. Write the problem in their words: what arrives,
   what they look up, what they decide, what they send. Count how often and how long (the CRM or a two-week
   tally); that is the baseline.
2. **Name the systems and who owns them** (CSMS, roaming platform, payment provider, ERP, CRM, document
   stores). Ask for read access scoped to one function; a use case never runs with a service account's view.
3. **Split reading from deciding.** List what a model would read (emails, tickets, exports, documents) and
   what code must decide (amounts, eligibility, validation). If a decision cannot be written as rules over
   system data, the use case is a draft-and-review assistant, not an automation.
4. **Write the risks as the business would:** money paid that the data does not support, data published
   wrongly, personal data in prompts, instructions hidden in inbound text.
5. **Score** value, feasibility and risk from 1 to 5 with the owner. Priority = value × feasibility / risk.
   The desk orders the portfolio by it.
6. **Write the spec** with `cpokit new <id> --name ... --function ... --owner ...` and fill the discovery
   section the same day. If the problem statement does not fit in five lines, the use case is too big for
   one sprint: split it.
