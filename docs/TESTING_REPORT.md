# Testing report (advanced features)

Date: 2026-11-09

## Summary

| Area | Result |
| --- | --- |
| Automated tests (offline, no network) | **93 / 93 pass** |
| Security suite | **47 / 48 pass** (the one failure is a documented known gap, SEC-A08) |
| Live LangChain chains A–E | Pass |
| Live multi-turn interview through LangGraph | Pass |
| Live semantic duplicate detection | Pass |
| Live error handling: blocked model, automatic fallback | Pass |
| Existing features | All pages render; original flows covered by tests |

Live runs used the configured model, `openai/gpt-4o-mini`.

## Automated tests

Run with `uv run python -m unittest discover -s tests -t .` (about 10 seconds, no API key or network needed).

| Module | Tests | Covers |
| --- | --- | --- |
| `test_core` | 5 | original guard and question-bank behaviour (unchanged from the first version) |
| `test_features` | 33 | catalog, question bank, sanitisation, injection rules, output validation, secrets, rate limit, request building, prompts, comparison metrics, all original pages, practice flow |
| `test_engine` | 27 | parameter filtering, JSON Schemas, cost maths, retries and backoff, failover, structured pipeline, settings page |
| `test_security_suite` | 7 | security suite (deterministic part), file ingestion, upload page |
| `test_langchain` | 16 | chains A–E with fake chat models, guard inside chains, schema and canary rejection, benign-overflow trimming, mislabelled-difficulty replacement, de-duplication (decorators then generators), streaming sanitisation, full three-turn graph run, early finish, follow-up limit, difficulty rules |
| `test_pages_advanced` | 5 | every new page renders; full Interview chat flow (start, streamed feedback, next question, end, summary); blocked answer never reaches the graph; Job description via chain A; Question memory check |

Fakes (`tests/fakes.py`): LangChain's `GenericFakeChatModel` returns scripted responses per chain, and a deterministic bag-of-words `EmbeddingFunction` replaces the 80 MB embedding model.

## Live verification

| Scenario | Evidence | Outcome |
| --- | --- | --- |
| Chains A–E individually | [demos/langchain_chains.md](demos/langchain_chains.md) | All five in strict `json_schema` mode; token usage and OpenRouter-billed cost returned per call; $0.0017 total |
| Complete multi-turn interview | [demos/interview_transcript.md](demos/interview_transcript.md) | 5 turns with a simulated candidate (strong, strong, partial, weak, injection attempt). Scores 4, 4, 3, 1, 3; difficulty Medium → Medium → Hard → Hard → Medium; chain D chose follow-ups and new topics; the injection was flagged and not rewarded; summary and learning plan produced; 19 calls, $0.0055 |
| Semantic duplicate detection | [demos/duplicate_detection.md](demos/duplicate_detection.md) | Reworded decorators question 0.928 (duplicate). Chain B output: a mislabelled-difficulty question and a decorator duplicate (0.669) were rejected; a generators question (0.461, similar) and a context-managers question (0.406, new) were accepted |
| Blocked model, no fallback | console | `NotFoundResponseError` mapped to a clear, safe message |
| Blocked model with fallback configured | console | LangChain `with_fallbacks` served the request from the fallback model |
| Live jailbreak attempts | [SECURITY_TEST_REPORT.md](SECURITY_TEST_REPORT.md) | 8/8 resisted |

## Defects found by live testing, and fixes

Offline tests with fake models passed before these were found. Each was reproduced live, fixed, and given a regression test.

| # | Found | Problem | Fix |
| --- | --- | --- | --- |
| 1 | Account probe | The account's OpenRouter guardrail blocked the planned default model, which would have broken every AI feature | Kept `openai/gpt-4o-mini` as the default; the 404 message now explains guardrail blocks |
| 2 | Chain B live | The model labelled one question "Easy" in a Medium set, and the whole valid set was rejected | Mislabelled questions are dropped and regenerated |
| 3 | Chain C live | An off-topic answer correctly had no strengths, but the schema required at least one | `strengths`/`weaknesses` (and summary `strengths`/`knowledge_gaps`) may be empty |
| 4 | Chain E live | A valid summary listed 7 knowledge gaps (maximum 6), and strict mode cannot enforce maximum lengths | Benign overflow is trimmed and recorded as a repair; structural errors still fail |
| 5 | Interview demo | Fixed scripted answers did not match generated questions | A simulated candidate answers each actual question at a planned quality |
| 6 | Interview demo | Chain D followed up five times in a row, producing near-duplicate questions | Code enforces a new topic after two consecutive follow-ups; follow-ups may be similar but not duplicates |
| 7 | Code review | Feedback streaming could read the *next* question while the worker thread advanced the graph | The answered question is captured before the graph runs |
| 8 | Page test | "End interview" was not offered after a failed planning step | Offered in that state too |
| 9 | Threshold calibration | The planned similarity thresholds (0.90 / 0.75) would have missed most duplicates | Calibrated to 0.62 / 0.45 on labelled pairs |

## Existing features

The original features (practice room, job description, structured output, interviewer guide, model settings, model lab, security lab, app review) are covered by the original page tests, which all pass after the navigation restructure. The practice room's "AI-generated" source now goes through chain B with de-duplication and still falls back to the curated bank on any failure. The Job description page now uses chain A and keeps all earlier output (skills, likely questions, prep plan), adding competencies, topics, and company.

## Error handling and invalid input

- Input: empty, oversized, flooded, control-character, Unicode-obfuscated, and template-token inputs (security suite B and A).
- Chain inputs: the guard runs inside every chain, so injection through any field (for example the topic hint) is blocked even if a page forgot to check (SEC-A14).
- Model output: malformed JSON, non-objects, wrong shape, errors inside HTTP 200, truncation, canary echoes, schema violations, oversize fields (security suite D), and benign overflow (trimmed).
- Streaming: exfiltration links and split canary tokens are stopped before reaching the browser (SEC-D14, SEC-D15).
- Provider: blocked or unknown model, 503 with `require_parameters`, and transient errors (retries and fallbacks). A failed interview step keeps the answer and offers Retry.

## Known behaviour

If chain D produces a near-duplicate three times in a row, the third attempt is used and labelled "duplicate" in the transcript rather than failing the turn (seen once in the interview demo, turn 4).
