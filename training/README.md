# Fine-tuning path (honest guide)

This folder contains the practical fine-tuning route for Career Copilot's agents.
**No model was fine-tuned inside this repo** — and here is exactly why, plus how to do it
properly on real hardware.

## Why not locally?

| Requirement | This environment / a typical laptop | Verdict |
|---|---|---|
| Model weights (HF download) | huggingface.co unreachable from the sandbox; 0.5–7 B weights are 1–15 GB | ❌ here |
| Training compute | No GPU; a LoRA pass on 1 B model ≈ minutes–hours even on a Colab T4 | ❌ here |
| Data volume | Fine-tuning needs ≥ few hundred consistent pairs — you build these over real usage | 🟡 growing |
| Worth it? | Gemini (primary + standby chain) already does generation well; the deterministic scorers handle offline | depends |

**Verdict:** fine-tuning is a *post-deployment optimization*, not a blocker. Do it when you
have (a) GPU access (free Colab T4 is enough for LoRA) and (b) a few hundred real
tailoring examples — the exporter below creates them from your own usage.

## What IS worth fine-tuning here

1. **Resume-tailoring style adapter (LoRA on Qwen2.5-0.5B / TinyLlama-1.1B)**
   Learns your output format (ALL-CAPS sections, `- ` bullets, contact block) and the
   anti-hallucination habit (only skills evidenced in the base resume).
   Would let the *fallback generator* be a real local model instead of a template.
2. **JD skill extractor (sequence-tagging or tiny classifier)**
   Could feed the scorer better signals than token overlap — though BM25+TF-IDF already
   discriminates well (Spearman 0.750 on the eval corpus).

## Step-by-step (Colab, free tier)

1. Export pairs:
   ```bash
   python training/export_training_data.py --out training/data/tailoring_pairs.jsonl
   ```
   Each line: `{"instruction": ..., "input": <base resume + JD>, "output": <tailored resume>}`.
2. Open `https://colab.research.google.com` → new notebook → Runtime: **T4 GPU**.
3. `pip install unsloth` (fastest LoRA path for ≤4 B models on one GPU):
   ```python
   from unsloth import FastLanguageModel
   model, tok = FastLanguageModel.from_pretrained("unsloth/Qwen2.5-0.5B-bnb-4bit",
                                                  load_in_4bit=True)
   model = FastLanguageModel.get_peft_model(model, r=16, lora_alpha=32)
   # load your jsonl with datasets.load_dataset("json", data_files=...)
   # SFTTrainer: max_seq_length=2048, ~2 epochs, lr=2e-4 — ≈15-30 min on a T4
   ```
4. Export the adapter (`model.save_pretrained("cc-tailor-lora")`), copy it into
   `models/cc-tailor-lora/`.
5. Wire it in: `config.call_gemini` already supports a model *chain* — a local backend
   plug point is `GEMINI_MODEL`/`GEMINI_STANDBY_MODEL`; a local adapter would slot in as
   the final fallback behind Gemini (replace `_generate_fallback_resume`'s template body
   with adapter inference guarded by `try/except ImportError`).

## Rules that keep this honest

- The anti-hallucination **guardrail still runs after any model**, fine-tuned or not —
  generation source never bypasses `find_unverified_skills` (see `resume_evaluator.py`).
- Evals must stay green: run `python -m career_copilot.evals.run_evals` after wiring any
  new generator. If `fallback_grounding` or `guardrail_recall` drops, the model doesn't ship.
