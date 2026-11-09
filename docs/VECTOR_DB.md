# Vector database and duplicate detection

## Choice

**ChromaDB** (`chromadb` 1.5) with a persistent local collection in `data/chroma/` (git-ignored). FAISS was considered and rejected for this app: it stores only vectors, so metadata filtering (domain, role, company, difficulty) would need a second store kept in sync. ChromaDB keeps vectors, documents, and metadata together, supports `where` filters, and needs no server.

**Embedding model:** `qwen/qwen3-embedding-8b` (the project's recommended embedding model, 4,096 dimensions), called through the OpenRouter embeddings endpoint by a custom ChromaDB embedding function (`OpenRouterEmbedding` in `vectorstore.py`). Only generated question text is sent for embedding, at about $0.01 per million tokens. The API key is resolved at call time and never stored in the collection's persisted configuration. Each embedding model uses its own collection, because vector sizes differ.

## What is stored

| Field | Example | Notes |
| --- | --- | --- |
| document | "What are Python generators and when would you use them?" | the generated question only |
| domain | IT / Software Engineering | used to scope similarity checks |
| role | Software Engineer | |
| company | Northwind Payments | only if the user provides one or chain A finds one |
| difficulty | Medium | |
| category | `technical` / `scenario` / `behavioral` | stored value; shown as "Behavioural" in the app |
| topic | Generators | |
| source | interview chat / practice room / question memory | |
| created_at | 2026-11-09T09:40:12+00:00 | generation timestamp |

Metadata is whitelisted in `QuestionMemory.add`; anything else (for example a candidate answer passed by mistake) is dropped. A unit test verifies this. Candidate answers, transcripts, and scores are never stored or embedded.

## How detection works

```
request → avoid = nearest stored questions (top 8, same domain)          [retrieval before generation]
        → chain B generates N questions, told to avoid those
        → for each question: cosine similarity to stored questions (same domain) and to this batch
              ≥ duplicate threshold → rejected; added to avoid; regenerate (≤2 more rounds)
              ≥ similar threshold   → kept, labelled "similar"
              otherwise             → kept, labelled "new"
        → accepted questions are stored with metadata
```

Similarity is cosine similarity (1 − ChromaDB's cosine distance) between embeddings, so paraphrases are matched by meaning, not by text. In the interview chat, follow-up questions may be "similar" to earlier ones (they stay on topic) but never duplicates; new-topic questions are checked the same way.

## Calibrating the thresholds

Thresholds depend on the embedding model, so they were measured on 17 labelled question pairs (`scripts/calibrate_similarity.py`) with `qwen/qwen3-embedding-8b`:

| Label | Similarity range | Examples |
| --- | --- | --- |
| Duplicate (same question reworded) | 0.828 – 0.957 | decorators reworded: 0.957 · "caching decorator" vs "memoizing decorator": 0.828 |
| Similar (same sub-topic, different angle) | 0.703 – 0.833 | decorators vs "decorator for logging": 0.833 · A/B test vs sample size: 0.706 |
| New (different question) | 0.336 – 0.692 | decorators vs generators: 0.692 · A/B test vs team conflict: 0.336 |

Defaults:

- **Similar ≥ 0.70**: separates "similar" from "new" cleanly on this set (highest new pair 0.692, lowest similar pair 0.703). This is why a decorators question and a generators question are *not* confused: generators scores 0.692 and is a new question.
- **Duplicate ≥ 0.85**: duplicates and similar questions overlap slightly (the memoizing-decorator duplicate scores 0.828, the decorator-for-logging question 0.833). At 0.85, no useful question is rejected and 5 of 6 duplicates are caught; the remaining one is kept and labelled "similar". Wrongly rejecting a good question was judged worse than letting one close rewording through, and the LLM "avoid" list is a second layer against repeats.

Both thresholds are sliders on the Question memory page. An earlier version used a local MiniLM model, where the same pairs scored much lower (duplicates 0.63–0.93), which shows why thresholds must be recalibrated whenever the embedding model changes.

**Limitations.** 17 pairs is a small calibration set; generated questions are often longer than the calibration pairs, which can shift scores; and two questions on the same concept phrased very differently can fall below the duplicate threshold.

## Live demonstration

[demos/duplicate_detection.md](demos/duplicate_detection.md) (`openai/gpt-6-luna` for generation, isolated in-memory collection):

| Candidate question vs stored "What are Python decorators and how do they work?" | Similarity | Label |
| --- | --- | --- |
| Can you explain how decorators function in Python? | 0.955 | duplicate |
| How would you use a decorator to add logging to functions? | 0.833 | similar |
| What are Python generators and when would you use them? | 0.684 | new |
| Explain list comprehensions in Python. | 0.590 | new |

Chain B was then asked for two more Python questions with the stored decorators question in its avoid list. It produced a generators scenario (0.355, new) and a `functools.wraps` decorator scenario (0.563, new: same feature, different concept), both accepted.

## Code

- `interview_app/vectorstore.py`: `OpenRouterEmbedding`, `QuestionMemory` (`check`, `similar`, `avoid_list`, `add`, `list_questions`, `delete`, `clear`), `Thresholds`.
- `interview_app/chains/workflows.py`: `generate_unique_questions`.
- `interview_app/chains/interview_graph.py`: de-duplication in `opening` and `plan_next`.
- `app_pages/question_memory.py`: thresholds, check tool, generate-without-repeats demo, browse and delete.
