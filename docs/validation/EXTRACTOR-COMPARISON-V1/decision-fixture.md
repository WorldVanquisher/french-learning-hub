# Extractor decision: **PENDING**

Criteria: flh_extractor_decision_v1 (pre-registered 2026-11-12). A winner is only proposed to the owner; nothing is routed to production.

- runs not performed: current_extractor, qwen3.5-4b-tuned
- qwen3.5-4b-untuned ineligible: abstention on frozen >= 0.9; abstention on rb probe >= 0.9; challenge paired consistency >= 0.9; challenge abstain-group paired accuracy >= 0.8

## current_extractor: NOT_PERFORMED

## qwen3.5-4b-untuned: MEASURED, eligible: False

| Criterion | Basis | Status | Evidence |
|---|---|---|---|
| strict structural validity >= 0.98 (scorable rows / slice rows) | exact | FAIL | `{"scorable": 405, "references": 472}` |
| abstention on frozen >= 0.9 | exact | FAIL | `0.85` |
| abstention on rb probe >= 0.9 | exact | FAIL | `0.85` |
| over-abstention on frozen <= 0.1 | exact | PASS | `0.0` |
| over-abstention on rb probe <= 0.1 | exact | PASS | `0.0` |
| challenge paired consistency >= 0.9 | exact | FAIL | `0.583` |
| challenge abstain-group paired accuracy >= 0.8 | exact | FAIL | `0.556` |
| human-judged unit F1 recorded (>= 100 judged examples) | human | PENDING | `null` |

## qwen3.5-4b-tuned: NOT_PERFORMED

Review packets: PENDING `{"items": 44, "verdicts": 0, "rejected": 0}`
