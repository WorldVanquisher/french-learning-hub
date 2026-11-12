# Category-only abstention shortcut: reproduction

Scoring version `e5b4e012c563860a…` (flh_extraction_scoring_v1). Systems are synthetic: `oracle` returns the references, `category_only` abstains iff the effective category is `other` and otherwise returns the references (an invented unit on a zero-unit reference), `constant_empty` always returns `{"units": []}`. Every output went through the production validator.

## Inputs

| Slice | File | Records | SHA-256 |
|---|---|---|---|
| frozen | `eval_candidates.jsonl` | 200 | `99602feba1cd13f526ad9530888ab2d57d7807beadfd1692be7536b78ecfe32a` |
| rb | `probe-rb.jsonl` | 200 | `9e9e0b24b51635abeea3c0381222723cefa6c36893044593de1e2d25accd6653` |
| swap | `probe-swap.jsonl` | 200 | `5a3ec4de7b29f3edf2a4c2c0ea7949ab78a0afbe74d71afbd648afc12d832e18` |

## Confusion counts (exact)

Positive class = the reference has zero units. TA true abstain, FE false extraction (units on a zero reference), OA over-abstention (empty on a unit reference), TE true extraction; invalid/missing never fold into a decision.

| Slice / system | TA | FE | OA | TE | invalid+missing | abstention | over-abstention | heuristic F1 |
|---|---|---|---|---|---|---|---|---|
| frozen/oracle | 20 | 0 | 0 | 180 | 0 | 1.0 | 0.0 | 1.0 |
| frozen/category_only | 20 | 0 | 0 | 180 | 0 | 1.0 | 0.0 | 1.0 |
| frozen/constant_empty | 20 | 0 | 180 | 0 | 0 | 1.0 | 1.0 | None |
| rb/oracle | 20 | 0 | 0 | 180 | 0 | 1.0 | 0.0 | 1.0 |
| rb/category_only | 0 | 20 | 0 | 180 | 0 | 0.0 | 0.0 | 0.953 |
| rb/constant_empty | 20 | 0 | 180 | 0 | 0 | 1.0 | 1.0 | None |
| swap/oracle | 20 | 0 | 0 | 180 | 0 | 1.0 | 0.0 | 1.0 |
| swap/category_only | 0 | 20 | 180 | 0 | 0 | 0.0 | 1.0 | None |
| swap/constant_empty | 20 | 0 | 180 | 0 | 0 | 1.0 | 1.0 | None |

## By category cue (category_only)

| Slice | cue | ref zero → empty / units | ref units → empty / units |
|---|---|---|---|
| frozen | category_other | 20 / 0 | 0 / 0 |
| frozen | category_not_other | 0 / 0 | 0 / 180 |
| rb | category_other | 0 / 0 | 0 / 0 |
| rb | category_not_other | 0 / 20 | 0 / 180 |
| swap | category_other | 0 / 0 | 180 / 0 |
| swap | category_not_other | 0 / 20 | 0 / 0 |

## Output manifests

| Run | outputs SHA-256 | validated SHA-256 |
|---|---|---|
| frozen/oracle | `89e157a04694545e…` | `f07738874d6b7c41…` |
| frozen/category_only | `89e157a04694545e…` | `f07738874d6b7c41…` |
| frozen/constant_empty | `b632235b1ea3b0aa…` | `1bf16ac8ac92a066…` |
| rb/oracle | `1bcd386cb635b731…` | `0b5502b76223c771…` |
| rb/category_only | `11c474dd81085e99…` | `89c6def2ed3feb4f…` |
| rb/constant_empty | `b9758fc44a87f59d…` | `4330bdc2a12a1b43…` |
| swap/oracle | `cd7b104da597a0bf…` | `dd76efa5194274a7…` |
| swap/category_only | `4b444164e0f6c2e9…` | `7443858cb7a1f183…` |
| swap/constant_empty | `fcdfa334b3a43af4…` | `39533eba256e421c…` |
