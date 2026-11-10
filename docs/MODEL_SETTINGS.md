# Model settings: comparison

Run 2026-11-10T08:19:14+00:00 · model `openai/gpt-6-luna` · script `scripts/compare_settings.py`

Task: review the same partially correct answer (expected score about 2–3 out of 5).

- Question: *How would you design a rate limiter for a public REST API?*
- Answer: *I would count how many requests each user makes and block them when they go over a limit, for example 100 requests per minute. I would return an error so the client knows to slow down. The limit could be stored somewhere like a database.*

**Why not temperature?** The approved models are reasoning models and do not accept `temperature`; the app checks each model's supported parameters and never sends it. The settings this model does accept are reasoning effort and max output tokens, so those are compared here.

## Experiment 1: reasoning effort (3 runs each, max tokens 4000)

| Effort | Successful runs | Scores | Avg latency (s) | Avg output tokens | of which reasoning | Avg words shown | Consistency | Avg cost per call | Judge quality (1–5) | Judge accuracy (1–5) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **low** | 3/3 | 2, 2, 3 | 13.6 | 894 | 105 | 203 | 0.386 | $0.000547 | 4.7 | 5 |
| **medium** | 3/3 | 3, 2, 3 | 10.7 | 1059 | 281 | 202 | 0.385 | $0.000629 | 4.7 | 4.7 |
| **high** | 3/3 | 2, 3, 2 | 10.6 | 1064 | 292 | 198 | 0.42 | $0.000632 | 4.7 | 4.7 |

*Consistency* is word-sequence similarity between runs (1.0 = identical text). *Judge* scores come from the same model rating all outputs anonymously in shuffled order (LLM-as-a-judge, so treat them as a rough signal).

## Experiment 2: max output tokens (reasoning effort low)

| Max tokens | Result | Output tokens used | Finish reason |
| --- | --- | --- | --- |
| 300 | **Failed:** The response was cut off before it finished. Increase max output tokens and try again. | – | – |
| 800 | **Failed:** The response was cut off before it finished. Increase max output tokens and try again. | – | – |
| 2000 | Complete review, score 3 | 843 | stop |

## Findings (computed from the table above)

- Output tokens: **low** used the fewest (894), **high** the most (1064). Higher effort spends more tokens on hidden reasoning.
- Cost: **low** was cheapest ($0.000547 per call), **high** the most expensive ($0.000632). Cost follows output tokens.
- Latency: **high** was fastest (10.6s), **low** slowest (13.6s). Latency is measured end to end, so it also depends on provider load and routing, not only on reasoning effort.
- Scores per effort: low: 2, 2, 3; medium: 3, 2, 3; high: 2, 3, 2.
- Max tokens 300, 800 cut the review off before the JSON was complete; 2000 was enough. The app detects the cut-off and asks for a larger budget instead of showing broken output.
- Caveat: one question and a few runs per setting is a small sample.
## Decision

The app keeps **reasoning effort low** and **max tokens 2000** by default.

- **Reasoning effort.** Higher effort did not improve the result on this task: the scores stayed in the expected 2–3 range at every level, and the judge rated quality the same (4.7 out of 5). Low used the fewest tokens and was about 13% cheaper per call than high. One surprise: low was about 3 seconds *slower* than medium and high, in this run and in an earlier, non-interleaved run, even though it produced fewer tokens. A likely cause is the provider routing or serving low-effort requests differently, but this test cannot confirm that. If speed mattered more than cost, medium would be a reasonable alternative. Users can change the effort on the Model settings page.
- **Max tokens.** 300 and 800 were too small: hidden reasoning plus the full JSON review needs about 850–1,050 tokens. 2000 leaves headroom without risking a cut-off.
