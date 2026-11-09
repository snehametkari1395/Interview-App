# Fieldnotes Interview Practice

A Streamlit app for domain-specific interview practice, answer coaching, interviewer guides, structured interview-prep data, and job-description preparation. Practice sessions stay in Streamlit session state; they are not written to a database. Text you submit is sent to OpenRouter when you use an AI feature.

## Run locally

1. Install [uv](https://docs.astral.sh/uv/).
2. Set `OPENROUTER_API_KEY` in your environment, or add it to `.streamlit/secrets.toml` (git-ignored):

   ```toml
   OPENROUTER_API_KEY = "your-key"
   # Optional; defaults to openai/gpt-4o-mini
   OPENROUTER_MODEL = "openai/gpt-4o-mini"
   # Optional; used automatically if the primary model is unavailable
   OPENROUTER_FALLBACK_MODEL = "anthropic/claude-haiku-4.5"
   ```

3. Start the app:

   ```powershell
   uv run streamlit run app.py
   ```

4. Run the tests (no network or API key needed):

   ```powershell
   uv run python -m unittest discover -s tests
   ```

5. Run the security test suite and write `docs/SECURITY_TEST_REPORT.md`:

   ```powershell
   uv run python scripts/run_security_tests.py          # deterministic tests (free)
   uv run python scripts/run_security_tests.py --live   # plus live jailbreak attempts against the model
   ```

## Features

| Page | What it does |
| --- | --- |
| Practice room | Pick a **domain**, role, **difficulty**, **response depth**, and **interviewer persona**. Questions are AI-generated for that combination (or drawn from the curated bank offline). Feedback includes a score, per-criterion ratings, expected points, a sample answer, an in-persona reaction, and the actual cost of the call. |
| Job description | Analyses a pasted or **uploaded** (.txt, .md, .pdf, .docx) job description into skills, likely questions, and a prep plan. Text that isn't a job description is detected and no plan is built. |
| Interviewer guide | Technical and/or behavioural guides: weighted criteria, competencies, a 1–5 rubric, indicators, red flags, common mistakes, a strong-answer example, and follow-ups. |
| Structured output | **Format 1** (Q&A set) and **Format 2** (answer evaluation) as JSON validated against JSON Schemas. View or download the JSON and the schemas. Shows the estimated cost before generation and the actual cost after. |
| Model lab | Runs one task under 2–3 parameter configurations and compares length, latency, tokens, diversity, consistency, score spread, and judge-rated quality, relevance, creativity, and accuracy. |
| Security lab | Checks any text against the guard, benchmarks an LLM security screen, and runs the full security test suite with a downloadable report. |
| App review | Sends a redacted, allow-listed code dossier to the model for a usability, security, and prompt-engineering critique. |
| Model settings | Provider and model selection from the live OpenRouter catalog, a fallback model, every supported sampling parameter, a request preview, account credits, and this session's call log. |

## Model configuration

Models, capabilities, and pricing come from `GET https://openrouter.ai/api/v1/models` (cached for one hour, with a refresh button). Each parameter has a slider and an exact-value field, a valid range, a recommended value, and an explanation:

| Parameter | Range | Recommended | Sent when |
| --- | --- | --- | --- |
| temperature | 0–2 | 0.4 | supported |
| max_tokens | 64 to the model's max | 2000 | supported (capped automatically) |
| top_p | 0–1 | 1.0 | supported and changed from 1.0 |
| top_k | 0–200 | 0 | supported and changed from 0 |
| frequency_penalty, presence_penalty | −2 to 2 | 0 | supported and changed from 0 |
| repetition_penalty | 0–2 | 1.0 | supported and changed from 1.0 |
| min_p, top_a | 0–1 | 0 | supported and changed from 0 |
| seed | integer | off | supported and enabled |
| reasoning effort | the model's own `supported_efforts` | model default | supported |

Controls for unsupported parameters are disabled, and those parameters are never sent. Requests set `provider.require_parameters` so OpenRouter routes only to providers that honour every parameter sent. Otherwise providers can silently ignore them.

## Structured output

Schemas live in `interview_app/schemas.py`. When the model lists `structured_outputs`, the schema is sent as `response_format: json_schema` (strict). Otherwise JSON mode or prompting is used. Every response is validated server-side against the full schema (ranges, sizes, enums, no extra fields) and then against content rules such as unique IDs and matching difficulty. Strings are sanitised, and the document is wrapped with server-controlled metadata. Malformed or invalid output produces a clear error listing each violation, with the raw response available for inspection.

## Cost calculator

- **Estimated** (before the call): input tokens from the exact prompt and payload (about 4 characters per token), and output tokens from the task, count, and response depth. A worst case at the full `max_tokens` is also shown.
- **Actual** (after the call): computed from returned `usage` × live per-token pricing, including cached-token pricing and request fees, alongside OpenRouter's own billed `usage.cost`.
- Missing pricing is reported as "Unavailable", never guessed.

## Reliability improvement (from the OpenRouter docs)

Transient failures (HTTP 408, 429, and 5xx; timeouts; connection errors; errors inside an HTTP 200 body) are retried up to 3 times with exponential backoff and jitter, honouring `Retry-After`. If no provider supports every parameter (503 with `require_parameters`), the request is retried once without that guarantee and labelled. An optional fallback model is used when the primary model is unavailable. Authentication, credit, and moderation errors are never retried.

## Security model

Deterministic checks are the enforcing layer; the LLM screen is advisory only.

- **Input**: Unicode normalisation; removal of invisible, bidi, and control characters; neutralised chat-template tokens; length limits; and injection pattern checks. Score dictation is blocked. Other flags are passed to the model as metadata.
- **Files**: extension allow-list plus content sniffing, a 2 MB size limit, PDF page and encryption limits, DOCX zip-bomb and XML-entity guards. Extracted text goes through the same input guard.
- **Prompts**: trusted settings in the system prompt, untrusted text only as JSON data, and a canary token. Any response that echoes the canary is discarded.
- **Output**: schema validation, per-field limits, and stripped Markdown images, link targets, and HTML.
- **Operations**: the key stays server-side and is never displayed or logged; errors are mapped to fixed messages; each session is limited to 40 AI calls per 10 minutes.

See `docs/SECURITY_TEST_REPORT.md` for the latest test results. These are application-level boundaries, not a guarantee against every prompt-injection or model-output risk.
