# Testing report (Hard-level features)

Date: 2026-11-09 · Branch `advanced-interview-features`

## Summary

| Area | Result |
| --- | --- |
| Automated tests (offline, no network) | **101 / 101 pass** |
| Security suite | **47 / 48 pass** (the one failure is a documented known gap, SEC-A08) |
| Live LangChain chains A–E | Pass (stand-in model) |
| Live multi-turn interview through LangGraph | Pass (stand-in model) |
| Live semantic duplicate detection | Pass |
| Live error handling: blocked model, automatic fallback | Pass |
| Existing features | All pages render; original flows covered by tests |
| **Open-weight models live** | **Not yet run**: blocked by the account's OpenRouter guardrail (see below) |
| **Live model and prompt evaluation** | **Not yet run**: requires the open-weight models and judge |

"Stand-in model" means `openai/gpt-4o-mini`, used only because every open-weight model was blocked for this account. Every stand-in output is labelled as such.

## Automated tests

Run with `uv run python -m unittest discover -s tests -t .` (about 10 seconds, no API key or network needed).

| Module | Tests | Covers |
| --- | --- | --- |
| `test_core` | 5 | original guard and question-bank behaviour (unchanged from the first version) |
| `test_features` | 33 | catalog, question bank, sanitisation, injection rules, output validation, secrets, rate limit, request building, prompts, comparison metrics, all original pages, practice flow |
| `test_engine` | 27 | parameter filtering, JSON Schemas, cost maths, retries and backoff, failover, structured pipeline, settings page |
| `test_security_suite` | 7 | security suite (deterministic part), file ingestion, upload page |
| `test_langchain` | 17 | chains A–E with fake chat models, guard inside chains, schema and canary rejection, benign-overflow trimming, mislabelled-difficulty replacement, de-duplication (decorators then generators), streaming sanitisation, full three-turn graph run, early finish, follow-up limit, difficulty rules, licence classification |
| `test_evaluation` | 7 | dataset integrity, deterministic checks, end-to-end evaluation with fake generator and judge, noise threshold, failed-generation handling, Evaluation page |
| `test_pages_advanced` | 5 | every new page renders; full Interview chat flow (start, streamed feedback, next question, end, summary); blocked answer never reaches the graph; Job description via chain A; Question memory check |

Fakes (`tests/fakes.py`): LangChain's `GenericFakeChatModel` returns scripted responses per chain, and a deterministic bag-of-words `EmbeddingFunction` replaces the 80 MB embedding model.

## Live verification

| Scenario | Evidence | Outcome |
| --- | --- | --- |
| Chains A–E individually | [demos/langchain_chains.md](demos/langchain_chains.md) | All five in strict `json_schema` mode; token usage and OpenRouter-billed cost returned per call; $0.0017 total |
| Complete multi-turn interview | [demos/interview_transcript.md](demos/interview_transcript.md) | 5 turns with a simulated candidate (strong, strong, partial, weak, injection). Scores 4, 4, 3, 2, 3; difficulty Medium → Hard → Medium; follow-ups and new topics chosen by chain D; injection flagged and not rewarded; summary and learning plan produced; 17 calls, $0.0049 |
| Semantic duplicate detection | [demos/duplicate_detection.md](demos/duplicate_detection.md) | Reworded decorators question 0.928 (duplicate); generators 0.573 (similar, kept); chain B avoided the stored question and produced a generators question |
| Blocked model, no fallback | console | `NotFoundResponseError` mapped to a clear, safe message |
| Blocked model with fallback configured | console | LangChain `with_fallbacks` served the request from the fallback model |
| Live jailbreak attempts | [SECURITY_TEST_REPORT.md](SECURITY_TEST_REPORT.md) | 8/8 resisted |

## Defects found by live testing, and fixes

Offline tests with fake models passed before these were found; each was reproduced live, fixed, and given a regression test.

| # | Found | Problem | Fix |
| --- | --- | --- | --- |
| 1 | Account probe | Every open-weight model blocked by the workspace guardrail; the new default model would have broken every feature | Reverted the configured model to the working stand-in; documented; clearer 404 message |
| 2 | Chain B live | The model labelled one question "Easy" in a Medium set, and the whole valid set was rejected | Mislabelled questions are dropped and regenerated; evaluation measures the label instead of rejecting |
| 3 | Chain C live | An off-topic answer correctly had no strengths, but the schema required at least one | `strengths`/`weaknesses` (and summary `strengths`/`knowledge_gaps`) may be empty |
| 4 | Chain E live | A valid summary listed 7 knowledge gaps (maximum 6), and strict mode cannot enforce maximum lengths | Benign overflow is trimmed and recorded as a repair; structural errors still fail |
| 5 | Interview demo | Fixed scripted answers did not match generated questions | A simulated candidate answers each actual question at a planned quality |
| 6 | Interview demo | Chain D followed up five times in a row, producing near-duplicate questions | Code enforces a new topic after two consecutive follow-ups; follow-ups may be similar but not duplicates |
| 7 | Code review | Feedback streaming could read the *next* question while the worker thread advanced the graph | The answered question is captured before the graph runs |
| 8 | Page test | "End interview" was not offered after a failed planning step | Offered in that state too |
| 9 | Threshold calibration | The planned similarity thresholds (0.90 / 0.75) would have missed most duplicates | Calibrated to 0.62 / 0.45 on labelled pairs |

## Existing features

The original features (practice room, job description, structured output, interviewer guide, model settings, model lab, security lab, app review) are covered by the original page tests, which all pass after the navigation restructure. The practice room's "AI-generated" source now goes through chain B with de-duplication and still falls back to the curated bank on any failure. The Job description page now uses chain A and keeps all earlier output (skills, likely questions, prep plan) plus competencies, topics, and company.

## Error handling and invalid input

- Input: empty, oversized, flooded, control-character, Unicode-obfuscated, and template-token inputs (security suite B and A).
- Chain inputs: the guard runs inside every chain, so injection through any field (for example the topic hint) is blocked even if a page forgot to check (SEC-A14).
- Model output: malformed JSON, non-objects, wrong shape, errors inside HTTP 200, truncation, canary echoes, schema violations, oversize fields (security suite D), and benign overflow (trimmed).
- Streaming: exfiltration links and split canary tokens are stopped before reaching the browser (SEC-D14, SEC-D15).
- Provider: blocked or unknown model, 503 with `require_parameters`, transient errors (retries and fallbacks); a failed interview step keeps the answer and offers Retry.

## Not yet verified (requires guardrail change)

1. Open-weight models live (Qwen3-235B, DeepSeek V3.2, Mistral Small 3.2) in the app, demos, and comparison.
2. LLM-as-a-judge evaluation with Kimi K2 (model and prompt comparison, 96 calls, estimated $0.30).

Commands, once the models are allowed at https://openrouter.ai/workspaces/default/guardrails:

```powershell
uv run python scripts/run_evaluation.py --yes
uv run python scripts/run_demos.py all
uv run python scripts/run_security_tests.py --live
```
