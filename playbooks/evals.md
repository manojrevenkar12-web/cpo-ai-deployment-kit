# Evals

- **Dev set:** the team's own resolved cases from the weeks before launch, labelled the way they resolved
  them (decision, amount, fields). 150-400 cases are enough to set thresholds; include the awkward ones.
- **Accuracy and harm are separate numbers.** A use case can be 97% accurate and still pay money it should
  not; thresholds for harm are zero (`over_credit_eur_share`, `injected_refund_eur`, `wrong_published`,
  `stale_value_used`).
- **Safe misses are allowed, unsafe ones are not.** "Ask for details" when the data is ambiguous counts as
  wrong for accuracy but is not a harm; a refund to the wrong card is.
- **Test the guardrail by switching it off:** with the quarantine off and a model that obeys injected text,
  no money may move (code decides from system data).
- **Held-out packs** are written blind by someone who has not seen the code (`heldout/WRITING_CASES.md`).
  Run once; the first run is kept. A dev set measures the tool on the cases it was tuned on; a blind pack
  measures it on cases it was not.
