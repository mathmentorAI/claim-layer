# Evidence contracts in 2.0.1

## Checked derivations

A list of premise IDs is a dependency declaration, not a proof. `EpistemicJudge`
requires both `verified_premise_ids` and `premise_lookup`, checks the ancestor
graph, and runs an explicitly named `derivation_rule`. Missing or invalid proof
context produces `unverified`; it cannot produce `rule_derived` by default.

The built-in `identity` rule permits exactly one premise and the same typed
entity, predicate, value, canonical fields, validity interval, attribution,
unit, event identity, and origin tier. It does not infer eligibility, legal
authority, or payment authorization from an unrelated fact.

```python
from dataclasses import replace
from core.interfaces import Claim, SourceRef
from core.epistemic_judge import EpistemicJudge

leaf = Claim("p1", "ACME", "status", "active", SourceRef("registry", 1, "p1"), 0.9)
copy = replace(leaf, id="c1", premises=["p1"], derivation_rule="identity")
audit = EpistemicJudge().audit_claim(
    copy, verified_premise_ids={"p1"}, premise_lookup={"p1": leaf}
)
assert audit.derivation_status == "rule_derived"
```

Applications may construct `EpistemicJudge(rule_checkers={"rule_id": checker})`.
A checker takes `(conclusion, premises)` and must return the boolean `True`
only when its rule justifies that conclusion. Exceptions and other results
reject the derivation. These checkers are trusted application policy: never
load their code from evidence, model output, or a message. The default public
`ClaimLayer` uses only the built-in rules and carries `derivation_rule` through
typed and dictionary ingestion. Register source premises before derivatives.

The verified-ID set remains an input trust boundary, not source authentication.
`source_supported` denotes a source claim passing the existing audit; it is not
independent verification that its text is true. Existing explicit audit bypass
options remain opt-outs and must not be used as security enforcement.

## Conflict classification

For the selected value, alternatives are retained as:

- `contradictions`: incompatible claims that may contribute opposition;
- `compatible_values`: compatible alternatives, such as multiple offices;
- `unresolved_comparisons`: alternatives whose comparability is unknown.

The core resolver returns the latter two lists in `Result.metadata` and its
trace; `ClaimLayer.ask()` places them on each result. The selected scalar value
remains a representative, not a declaration that compatible alternatives are
false or that an unknown comparison has been settled. An unknown alternative
does not justify an automatic action. Consumers requiring a settled value must
inspect these fields and obtain the missing scope or attribution first.

Only incompatible alternatives contribute to opposing support and the conflict
penalty. Explicit noise thresholds may omit weak opposing support from scoring,
but incompatible claims remain in the contradiction list. Compatible/unknown
entries retain their IDs and source coordinates. The existing certificate binds
the selected result and its supporting/contradicting claims; it does not certify
the truth of the source or cover the additional alternative lists.

The legacy SQLite resolver has no temporal or speaker metadata and can only
apply predicate cardinality. The public facade refines its alternatives using
the full claim records. Predicate cardinality remains the existing built-in
policy, including its functional fallback for unlisted predicates. Neither
classification nor a confidence score is an authorization decision.
