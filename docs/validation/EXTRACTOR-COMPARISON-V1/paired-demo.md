# Paired consistency on the cue challenge slice

Exact unless marked. Paired consistency = every variant of a group got the same decision; paired accuracy = every variant got the reference decision and unit count. Aggregate numbers are reported beside them, never combined.

| System | Paired consistency | Paired accuracy | Cue flips | Count consistent | Objective consistent (heuristic) | Aggregate F1 (heuristic) | Abstention | Over-abstention | Validity |
|---|---|---|---|---|---|---|---|---|---|
| oracle | 32/32 (1.0) | 32/32 (1.0) | 0 | 32 | 32 | 1.0 | 1.0 | 0.0 | 1.0 |
| category_only | 0/32 (0.0) | 0/32 (0.0) | 32 | 0 | 0 | 0.662 | 0.333 | 0.333 | 1.0 |
| constant_empty | 32/32 (1.0) | 12/32 (0.375) | 0 | 32 | 32 | None | 1.0 | 1.0 | 1.0 |

## By intent (paired consistency / paired accuracy)

| System | extract groups | abstain groups |
|---|---|---|
| oracle | 20/20 / 20/20 | 12/12 / 12/12 |
| category_only | 0/20 / 0/20 | 0/12 / 0/12 |
| constant_empty | 20/20 / 0/20 | 12/12 / 12/12 |

## Per variant (decision accuracy · abstention on abstain groups · over-abstention on extract groups)

| System | aligned | conflicting | rb |
|---|---|---|---|
| oracle | 1.0 · 1.0 · 0.0 | 1.0 · 1.0 · 0.0 | 1.0 · 1.0 · 0.0 |
| category_only | 1.0 · 1.0 · 0.0 | 0.0 · 0.0 · 1.0 | 0.625 · 0.0 · 0.0 |
| constant_empty | 0.375 · 1.0 · 1.0 | 0.375 · 1.0 · 1.0 | 0.375 · 1.0 · 1.0 |
