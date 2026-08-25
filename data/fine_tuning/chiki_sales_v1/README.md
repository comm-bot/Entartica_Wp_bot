# Chiki Sales Composer v1

Supervised fine-tuning data for how Chiki phrases a supplied `SalesResponseBrief`. It does not train Entartica facts as model memory; production facts, policy, recommendations, and next actions remain code-controlled.

Files:

- `train.jsonl`: 80 examples
- `validation.jsonl`: 20 examples
- `holdout.jsonl`: 20 untouched evaluation examples
- `dataset_manifest.json`: distributions, coverage, provenance, and validation status

Each JSONL row uses OpenAI chat format with exactly one system, user, and assistant message. The user message is serialized JSON matching the production brief: response goal, language, service identity, approved facts, `CustomerFacts`, approved options, known sales slots, deterministic recommendations, next action/question, and restrictions.

Run offline validation:

```powershell
python scripts/validate_chiki_sales_dataset.py
```

The validator checks structure, service and numeric grounding, required-question behavior, unsupported commercial claims, PII, governance wording, length, and cross-split near-duplicates. No API calls are made.

The holdout contract compares a base composer with a future opt-in fine-tuned composer on sales tone, grounding, next-action compliance, conciseness, language match, unsupported claims, governance leakage, and service-name accuracy. FT-1 does not upload data or submit a training job.
