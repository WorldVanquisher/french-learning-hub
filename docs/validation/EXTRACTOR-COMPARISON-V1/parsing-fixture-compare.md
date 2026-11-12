# Extractor comparison matrix

Matrix `b3f66edaf76b0886…`; slice 472 records (challenge_test 72, frozen 200, rb 200); output schema `knowledge_extraction_v2` `8335a158738dbde4…`; scoring `e5b4e012c563860a…`.

| System | Status | Model / provenance | Decoding | How (owner) |
|---|---|---|---|---|
| current_extractor | **NOT_PERFORMED** | openai:<OPENAI_MODEL>:knowledge_extraction_v2 (record the model at run time) | api=OpenAI Responses, requests=472, retries=0, store=false, structured_output=json_schema strict (knowledge_units), temperature=not set by the request (provider default) | EXTRACTOR_PROVIDER=openai with OPENAI_MODEL set: extraction-render run -in comparison-inputs.jsonl -out current-results.jsonl -max-requests 472 -confirm-paid-calls |
| qwen3.5-4b-untuned | **MEASURED** | Qwen/Qwen3.5-4B@851bf6e8 | add_generation_prompt=true, batch_size=1, chat_template_kwargs={"enable_thinking": false}, do_sample=false, dtype=bfloat16, max_new_tokens=512, num_beams=1 | rendered/predict-base-a.json then predict-base-b.json (owner submits; concatenate a, b) |
| qwen3.5-4b-tuned | **NOT_PERFORMED** | Qwen/Qwen3.5-4B@851bf6e8 + adapter | add_generation_prompt=true, batch_size=1, chat_template_kwargs={"enable_thinking": false}, do_sample=false, dtype=bfloat16, max_new_tokens=512, num_beams=1 | rendered/predict-eval-a.json then predict-eval-b.json (owner submits; concatenate a, b) |

| System | Rows (scorable/ref) | Status counts | Frozen abstention | rb abstention | rb false extraction | Paired consistency | Paired accuracy | Frozen F1 (heur.) |
|---|---|---|---|---|---|---|---|---|
| current_extractor | — | NOT_PERFORMED | — | — | — | — | — | — |
| qwen3.5-4b-untuned | 405/472 | `{"duplicate_prediction": 6, "invalid_output": 12, "missing_prediction": 6, "unparseable:code_fence": 7, "unparseable:leading_text": 9, "unparseable:think_block": 7, "unparseable:trailing_text": 7, "unparseable:truncated_at_max_new_tokens": 7, "valid_empty": 57, "valid_extra_keys": 6, "valid_units": 348}` | 0.85 | 0.85 | 0 | 0.583 | 0.583 | 1.0 |
| qwen3.5-4b-tuned | — | NOT_PERFORMED | — | — | — | — | — | — |
