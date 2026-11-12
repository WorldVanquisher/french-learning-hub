# Extractor comparison matrix

Matrix `b3f66edaf76b0886…`; slice 472 records (challenge_test 72, frozen 200, rb 200); output schema `knowledge_extraction_v2` `8335a158738dbde4…`; scoring `e5b4e012c563860a…`.

| System | Status | Model / provenance | Decoding | How (owner) |
|---|---|---|---|---|
| current_extractor | **NOT_PERFORMED** | openai:<OPENAI_MODEL>:knowledge_extraction_v2 (record the model at run time) | api=OpenAI Responses, structured_output=json_schema strict (knowledge_units), store=false, temperature=not set by the request (provider default), retries=0, requests=472 | EXTRACTOR_PROVIDER=openai with OPENAI_MODEL set: extraction-render run -in comparison-inputs.jsonl -out current-results.jsonl -max-requests 472 -confirm-paid-calls |
| qwen3.5-4b-untuned | **NOT_PERFORMED** | Qwen/Qwen3.5-4B@851bf6e8 | do_sample=false, num_beams=1, max_new_tokens=512, dtype=bfloat16, chat_template_kwargs={"enable_thinking": false}, add_generation_prompt=true, batch_size=1 | rendered/predict-base-a.json then predict-base-b.json (owner submits; concatenate a, b) |
| qwen3.5-4b-tuned | **NOT_PERFORMED** | Qwen/Qwen3.5-4B@851bf6e8 + adapter | do_sample=false, num_beams=1, max_new_tokens=512, dtype=bfloat16, chat_template_kwargs={"enable_thinking": false}, add_generation_prompt=true, batch_size=1 | rendered/predict-eval-a.json then predict-eval-b.json (owner submits; concatenate a, b) |
