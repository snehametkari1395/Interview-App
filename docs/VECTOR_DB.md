# Vector database and duplicate detection

## Choice

**ChromaDB** (`chromadb` 1.5) with a persistent local collection in `data/chroma/` (git-ignored). FAISS was considered but rejected for this app: it stores only vectors, so metadata filtering (domain, role, company, difficulty) would need a second store kept in sync. ChromaDB keeps vectors, documents, and metadata together, supports `where` filters, and needs no server.

**Embedding model:** `all-MiniLM-L6-v2` (Apache-2.0), run locally through ChromaDB's ONNX runtime. It is downloaded once (~80 MB) to `~/.cache/chroma`. Question text never leaves the machine for embedding and there is no per-call cost.

## What is stored

| Field | Example | Notes |
| --- | --- | --- |
| document | "What are Python generators and when would you use them?" | the generated question only |
| domain | IT / Software Engineering | used to scope similarity checks |
| role | Software Engineer | |
| company | Northwind Payments | only if the user provides one or chain A finds one |
| difficulty | Medium | |
| category | technical / scenario / behavioral | |
| topic | Generators | |
| source | interview chat / practice room / question memory | |
| created_at | 2026-11-09T09:40:12+00:00 | generation timestamp |

Metadata is whitelisted in `QuestionMemory.add`; anything else (for example a candidate answer passed by mistake) is dropped. A unit test verifies this. Candidate answers, transcripts, and scores are never stored.

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

Similarity is cosine similarity (1 − ChromaDB's cosine distance) between embeddings, so paraphrases are matched by meaning, not text. Follow-up questions in the interview chat may be "similar" to earlier ones (they stay on topic) but never duplicates, and new-topic questions are checked the same way.

## Calibrating the thresholds

The initial plan proposed 0.90 / 0.75. Measuring 17 labelled question pairs with this embedding model (`scripts/calibrate_similarity.py`) showed those values were wrong for MiniLM:

| Label | Similarity range | Example |
| --- | --- | --- |
| Duplicate (same question reworded) | 0.630 – 0.928 | "caching decorator" vs "memoizing decorator": 0.630 · decorators reworded: 0.928 |
| Similar (same sub-topic, different angle) | 0.446 – 0.602 | DCF vs choosing the discount rate: 0.602 |
| New (different question) | −0.030 – 0.573 | decorators vs generators: 0.573 · A/B test vs team conflict: −0.030 |

At 0.90, most real duplicates would have passed as new. The defaults are therefore:

- **Duplicate ≥ 0.62**: just below the lowest duplicate (0.630) and above the highest similar pair (0.602). This is the only boundary that matters for rejection, and it separates the labelled set cleanly, with a narrow margin.
- **Similar ≥ 0.45**: "similar" and "new" overlap (decorators vs generators scores 0.573), so this label is informational only. Overlap here is harmless because similar questions are kept.

This is why "decorators" and "generators" are not confused: the generators question is labelled *similar* (same language, different concept) and accepted, while a reworded decorators question is a *duplicate* and rejected. Both thresholds are sliders on the Question memory page.

**Limitations.** 17 pairs is a small calibration set; thresholds are specific to the embedding model (switching to, say, `bge-m3` requires recalibrating); generated questions are often longer than the calibration pairs, which can shift scores; and two questions on the same concept phrased very differently can fall below the duplicate threshold. The LLM "avoid" list is a second, semantic layer that catches some of these.

## Live demonstration

[demos/duplicate_detection.md](demos/duplicate_detection.md) (stand-in model, isolated in-memory collection):

| Candidate question vs stored "What are Python decorators and how do they work?" | Similarity | Label |
| --- | --- | --- |
| Can you explain how decorators function in Python? | 0.928 | duplicate |
| How would you use a decorator to add logging to functions? | 0.563 | similar |
| What are Python generators and when would you use them? | 0.573 | similar |
| Explain list comprehensions in Python. | 0.417 | new |

Then chain B, asked for Python questions with the stored decorators question in its avoid list, produced a generators question (0.531, similar, accepted) and a caching question (0.392, new, accepted).

## Code

- `interview_app/vectorstore.py`: `QuestionMemory` (`check`, `similar`, `avoid_list`, `add`, `list_questions`, `delete`, `clear`), `Thresholds`.
- `interview_app/chains/workflows.py`: `generate_unique_questions`.
- `interview_app/chains/interview_graph.py`: de-duplication in `opening` and `plan_next`.
- `app_pages/question_memory.py`: thresholds, check tool, generate-without-repeats demo, browse and delete.
