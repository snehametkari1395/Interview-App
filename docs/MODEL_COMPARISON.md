# Open-weight models: selection, licensing, and comparison

## Status

> **The open-weight comparison has not been run yet.** On 2026-11-09 the OpenRouter account used for development had a workspace guardrail (`model-ignored-by-guardrail`) that blocked every open-weight model tested. All live runs so far used `openai/gpt-4o-mini` as a clearly labelled stand-in. The code, defaults, and scripts are ready; once the models below are allowed at https://openrouter.ai/workspaces/default/guardrails, run:
>
> ```powershell
> uv run python scripts/run_evaluation.py --yes      # model + prompt comparison (~96 calls, est. $0.30)
> uv run python scripts/run_demos.py all             # interview, chains, duplicates on the open-weight default
> ```
>
> Results are written to `docs/EVALUATION_RESULTS.md` and `docs/demos/`.

### Access probe (5-token requests, 2026-11-09)

| Model | Licence category | Result |
| --- | --- | --- |
| qwen/qwen3-235b-a22b-2507, qwen3-32b, qwen3-30b-a3b-instruct-2507, qwen3-next-80b | Open weights, OSI (Apache-2.0) | Blocked by guardrail |
| deepseek/deepseek-v3.2, deepseek-chat-v3.1, deepseek-chat-v3-0324 | Open weights, OSI (MIT) | Blocked by guardrail |
| mistralai/mistral-small-3.2-24b-instruct, mistral-nemo | Open weights, OSI (Apache-2.0) | Blocked by guardrail |
| meta-llama/llama-3.3-70b-instruct, llama-4-maverick, llama-4-scout | Open weights, restricted (Llama Community Licence) | Blocked by guardrail |
| openai/gpt-oss-120b, gpt-oss-20b; z-ai/glm-4.6, glm-4.5; microsoft/phi-4 | Open weights, OSI | Blocked by guardrail |
| moonshotai/kimi-k2-0905; google/gemma-3-27b-it; nvidia/nemotron-3-super | Open weights, restricted | Blocked by guardrail |
| openai/gpt-4o-mini | Proprietary | Allowed (stand-in) |

The app handles this case: a blocked model returns HTTP 404 with a routing explanation, which is mapped to "The selected model was not found on OpenRouter. Choose another model in Model settings." The configured fallback model (if any) is tried automatically.

## Selected models

| Role | Model | Licence | Price per 1M tokens (in / out) | Why |
| --- | --- | --- | --- | --- |
| Primary (default) | `qwen/qwen3-235b-a22b-2507` | Apache-2.0 | $0.14 / $0.80 | Strong instruction following; JSON Schema structured outputs; OSI licence |
| Comparison | `deepseek/deepseek-v3.2` | MIT | $0.26 / $0.38 | Different lab and architecture; MIT; structured outputs and reasoning |
| Comparison | `mistralai/mistral-small-3.2-24b-instruct` | Apache-2.0 | $0.075 / $0.20 | Small, cheap, fast; tests whether a 24B model is good enough |
| Judge | `moonshotai/kimi-k2-0905` | Modified MIT (restricted) | $0.60 / $2.50 | A different family from all three generators (reduces self-preference bias) |
| Embeddings | `all-MiniLM-L6-v2` (local) | Apache-2.0 | free | Runs offline via ONNX; no data leaves the machine |

Prices are read live from the OpenRouter models endpoint at runtime; the values above were current on 2026-11-09.

All three generators support `structured_outputs` (strict JSON Schema), `response_format`, `temperature`, and `max_tokens` on OpenRouter, so the app's capability filtering sends the same parameter set to each. DeepSeek V3.2 also supports `reasoning`; the reasoning-effort control appears only for it.

## Open source vs open weight

The app classifies models with a curated, conservative table (`interview_app/licensing.py`), because OpenRouter publishes no licence field:

- **Open weights, OSI licence** (Apache-2.0, MIT): weights can be downloaded, modified, and used commercially. Training data and full training code are generally *not* released, so these are not "open-source AI" under the OSI Open Source AI Definition. This is the most permissive category actually available.
- **Open weights, restricted licence**: downloadable, but with use, scale, or attribution restrictions. Examples: the Llama Community Licence (acceptable-use policy; more than 700M monthly users requires a Meta licence), Gemma Terms of Use, NVIDIA Open Model Licence, Kimi's modified MIT (attribution above 100M MAU or $20M monthly revenue), and the Qwen Licence for Qwen2.5-72B.
- **Proprietary**: API only, even within "open" families. Qwen-Plus/Max/Flash, Mistral Medium/Saba, and Gemini are proprietary despite open siblings.
- **Unknown**: anything not covered by a rule (184 of 461 catalog models). These are never assumed open; the Model settings "Open-weight models only" filter hides them.

## Deployment limitations

- **Through OpenRouter, open weights are still a hosted dependency.** Requests go to third-party inference providers (for example DeepInfra, Together, Fireworks), whose data-retention and training policies differ. OpenRouter's data-policy guardrails can restrict which providers are used. Self-hosting the weights (vLLM, Ollama, TGI) is what removes the dependency.
- **Provider variance.** The same model can differ between providers in quantisation, context length, supported parameters, and latency. The app sets `provider.require_parameters` so a request only routes to providers that honour every parameter sent.
- **Structured-output support varies by provider.** Strict JSON Schema is not universal; the app falls back to JSON mode or prompted JSON and always validates server-side.
- **Self-hosting cost.** A 235B mixture-of-experts model needs multiple high-memory GPUs; Mistral Small 24B fits on a single 48 GB GPU, or smaller with quantisation.
- **Licences can change** between model versions; re-check the model card before commercial use.

## Comparison method

The comparison uses the evaluation framework ([EVALUATION.md](EVALUATION.md)): identical dataset cases, job context, difficulty, and question count for every model; the same deterministic checks; and the same judge and rubric. Reported per model: judge score per dimension and overall, success rate (schema-valid generations), deterministic coverage and repetition, mean latency, output tokens, and actual cost per case (OpenRouter's billed amount).

## Stand-in results (gpt-4o-mini, proprietary)

These validate the pipeline end to end; they are not open-weight results.

| Run | Calls | Cost | Notes |
| --- | --- | --- | --- |
| Chains A–E ([demo](demos/langchain_chains.md)) | 5 | $0.0017 | All in `json_schema` strict mode; 3.6–6.8 s per call |
| Five-turn interview ([demo](demos/interview_transcript.md)) | 17 | $0.0049 | Difficulty Medium → Hard → Medium; ~18 s per turn including the simulated candidate |
| Security suite, live attacks | 8 | $0.0030 | 8/8 resisted |
