# tools/extraction — knowledge-extraction data, evaluation and training preparation

Offline tooling for the `knowledge_extraction_v2` extractor
(`internal/extractor/openai.go`). It changes nothing in the product: the live
extractor, its prompt, schema and routing are untouched.

| Piece | Where | What it does |
|---|---|---|
| Policy | `ANNOTATION_POLICY.md` | task boundary, labelling rules, error codes, human review rubric |
| Boundary cases | `authoring/boundary_a.py`, `boundary_b.py`, `build_boundary.py` | 80 hand-written decisions with rationales |
| Training candidates | `authoring/bank_train_*.py`, `zero_bank.py`, `generate_train.py` | 1,200 synthetic candidates from 122 learning points, quarantine for ambiguous items |
| Evaluation candidates | `authoring/bank_eval.py`, `generate_eval.py` | 200 held-out candidates from a separate bank and separate scenario formats |
| Production render/validate | `cmd/extraction-render` (Go) | the exact production request; production parsing and validation of any output; a capped, confirmed baseline `run` of the configured extractor |
| Checks and evaluation | `flh_extraction/` | records, duplicates, splits and leakage, manifests, provisional automatic matching with human-judgment override, SFT records, prediction, training |
| Failure-mode audit | `flh_extraction/audit.py` (`audit`) | training data counted by over/under-splitting, duplicates, false premises, abstention cues, bilingual drift and unsupported claims, with examples (HEURISTIC) |
| Increment v2 | `authoring/bank_increment_v2.py`, `generate_increment.py`, `increment_v2_rule_based.json`; `flh_extraction/increment.py` (`increment-check`) | 182 targeted candidates (misconceptions, wrong explanations, production-style abstention and counter-shortcut records, splitting boundaries) reusing training points; validation against base, evaluation and boundary data |
| Quality report | `flh_extraction/quality.py` (`quality`, `quality-compare`) | structural validity with parse diagnostics, unit counts, split/merge, abstention, grounding and bilingual fidelity, each labelled exact / heuristic / human |
| Probes and controls | `flh_extraction/probe.py` (`probe`), `controls.py` (`control-matrix`) | the frozen evaluation as the production analyzer presents it (`rb`, `swap`; never training data); controlled failures showing what each metric catches |
| Review and promotion | `flh_extraction/review_packet.py` (`review-packet`), `promotion.py` (`promotion-check`), `review/` | a 25-item prioritized packet; pre-registered promotion criteria as PASS / FAIL / PENDING |
| Profile verification | `scripts/verify_profile.py`, `configs/qwen3.5-4b-851bf6e8.sha256` | the profile against the checkpoint's own small files: template, text-level masking, LoRA targets on real weight names; token-level with a tokenizer |
| Model profiles | `flh_extraction/models.py` | the only model-specific wiring: base model, pinned revision, loader, chat-template options, LoRA targets. Default candidate `Qwen/Qwen3.5-4B` (Qwen3-1.7B superseded, never run) |
| Training | `flh_extraction/train.py`, `sagemaker_entry.py`, `Dockerfile`, `requirements-train.txt`, `configs/` | SFT with answer-only loss through a model profile; SageMaker train and predict modes |
| Untuned baseline | `scripts/untuned_baseline.sh`, `scripts/select_eval_subset.py`, `flh_extraction/categories.py` | one command: fixed 50-item frozen-eval subset → predict → production validator → harness → schema validity, unsupported claims, abstention and splitting reported separately |
| AWS interface | `deploy/aws/sagemaker-extractor/` | bounded job templates (incl. `predict-base` without an adapter), renderer, IAM templates, `build_readiness.py` and `readiness/` (manifests, rendered jobs, sequence, criteria); prepared, never launched |
| Runbook | `TRAINING_RUNBOOK.md` | the experiment, its gates, owner commands and cost bound |

Every generated record is `origin: synthetic`, `review_status: unreviewed`,
`label_status: machine_authored_unreviewed`. Nothing is gold until a human
reviewer accepts it (`authoring/build_review_queue.py`). Confidence values
follow an authoring convention and are not calibrated.

```sh
python3 -B -m unittest discover -s tests -t tests     # 37 tests; 7 need TINY_SFT and torch (backend, SageMaker-layout dry run)
```

## Generated data (not committed)

The datasets are generated, deterministic outputs and are not stored in the
repository. Regenerate them from `authoring/` (fixed seed 20261110):

```sh
cd tools/extraction/authoring
python3 -B build_boundary.py OUT/boundary     # boundary_cases_v1.jsonl (80)
python3 -B generate_train.py OUT/train        # candidates.jsonl (1,200) + quarantine.jsonl (7)
python3 -B generate_eval.py  OUT/eval         # eval_candidates.jsonl (200)
python3 -B generate_increment.py OUT/inc     # increment_candidates.jsonl (182), uses increment_v2_rule_based.json
```

Expected SHA-256 (verified by regeneration on 2026-11-10):

```text
5960b48a3f0832afb752cefcf37c45ed7a9800ddcf0ff27e143d0e6faff92edc  boundary/boundary_cases_v1.jsonl
8ec9b1724340ad3cd96fcac822290df694def3e8a749e6d4c9b87165b690b59a  train/candidates.jsonl
98e8e58187022a7c8d5ca08da0ba2d8d27cf119cf161c53b61c3acc066bdca66  train/quarantine.jsonl
99602feba1cd13f526ad9530888ab2d57d7807beadfd1692be7536b78ecfe32a  eval/eval_candidates.jsonl
5a40c6e723adfdf9f097e89d5afc68438c143e475518466da86ca73b05ed6655  inc/increment_candidates.jsonl   (2026-11-12)
```

The increment's rule-based fields come from the production default analyzer
(`extraction-render analyze`), frozen in `authoring/increment_v2_rule_based.json`;
`generate_increment.py --analysis-requests` and `--freeze` regenerate them.

Then run `python3 -m flh_extraction check` (splits and leakage) and `manifest`
before any training or evaluation. A hash mismatch means the inputs changed.
