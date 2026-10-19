# Changelog

## 2.0.1

- Require verified premise records and an explicit application-installed rule
  checker before declaring a claim `rule_derived`. Check transitive premises and
  reject missing context, cycles, unknown rules, and invalid implications.
- Include a conservative `identity` rule for restating the same proposition
  without changing its scope, units, or attribution. Other domain rules require
  trusted application code; this is not a general natural-language proof solver.
- Exclude unverified derivations from core resolution and reject them on default
  public ingestion. Previously, premise IDs alone could be treated as a proof.
- Keep multivalued alternatives in `compatible_values` and unknown comparisons
  in `unresolved_comparisons`. Only incompatible alternatives count as opposing
  evidence, under all three scoring strategies. Apply the distinction in public
  queries and prevent compatible lower-tier values from being retracted.
- Install test dependencies in CI, test Python 3.9/3.11/3.12, and run regression
  tests against a built wheel outside the checkout.
- Document installation from the tagged GitHub release using distribution name
  `claim-layer` and import name `claimlayer`. No PyPI publication is claimed.

The Harvey LAB results are unchanged. These corrections are software regression
fixes, not a new empirical benchmark or a demonstrated prompt-injection defense.
