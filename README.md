# Fieldnotes Interview Practice

A Streamlit app for role-focused interview practice, answer coaching, and job-description preparation. Practice sessions stay in Streamlit session state; they are not written to a database. Answers and job descriptions are sent to OpenRouter when you request AI feedback or analysis.

## Run locally

1. Install [uv](https://docs.astral.sh/uv/).
2. Set `OPENROUTER_API_KEY` in your environment, or add it to `.streamlit/secrets.toml`:

   ```toml
   OPENROUTER_API_KEY = "your-key"
   # Optional; defaults to openai/gpt-4o-mini
   OPENROUTER_MODEL = "openai/gpt-4o-mini"
   ```

3. Start the app:

   ```powershell
   uv run streamlit run app.py
   ```

## App structure

- `app.py`: practice setup and one-question-at-a-time session flow.
- `pages/1_Job_Description.py`: role analysis, likely questions, and prep plan.
- `interview_app/`: curated question bank, OpenRouter client, coaching prompts, and input/output guard.

The guard enforces input size limits, treats pasted content as untrusted data in model prompts, and validates the expected JSON response shape. It is an application-level boundary, not a guarantee against every prompt-injection or model-output risk.