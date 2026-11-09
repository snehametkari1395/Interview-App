# Demo: semantic duplicate detection (ChromaDB + qwen/qwen3-embedding-8b)

Run 2026-11-09 09:35 UTC · model `openai/gpt-6-luna`

Thresholds: duplicate ≥ 0.85, similar ≥ 0.7. Isolated in-memory collection.

## Step 1 · First request stored a decorators question

Stored: *What are Python decorators and how do they work?*

## Step 2 · Direct checks against memory (no LLM)

| Candidate question | Best similarity | Label |
| --- | --- | --- |
| Can you explain how decorators function in Python? | 0.955 | **duplicate** |
| How would you use a decorator to add logging to functions? | 0.833 | **similar** |
| What are Python generators and when would you use them? | 0.684 | **new** |
| Explain list comprehensions in Python. | 0.590 | **new** |

## Step 3 · Second request: generate a Python question (chain B + de-duplication)

Sent as "avoid": ['What are Python decorators and how do they work?']

- ACCEPTED new (0.355): A service processes a large stream of records but currently builds a list of all transformed records before writing them out. How would you decide whether to replace that list with a generator, and what would you check when integrating the change?  
  nearest: What are Python decorators and how do they work?
- ACCEPTED new (0.563): A Python function is wrapped with a decorator for logging, and a test or framework that inspects the function reports the wrapper's name and signature instead of the original function's. How would you address this while keeping the logging behavior?  
  nearest: What are Python decorators and how do they work?

## Stored metadata

```json
[
  {
    "id": "38606a00f4118b6cb265",
    "question": "A Python function is wrapped with a decorator for logging, and a test or framework that inspects the function reports the wrapper's name and signature instead of the original function's. How would you address this while keeping the logging behavior?",
    "category": "technical",
    "role": "Software Engineer",
    "difficulty": "Medium",
    "source": "question generation",
    "domain": "IT / Software Engineering",
    "created_at": "2026-11-09T09:36:36+00:00",
    "company": "",
    "topic": "Decorators"
  },
  {
    "id": "9371fa7077090c35dbb1",
    "question": "A service processes a large stream of records but currently builds a list of all transformed records before writing them out. How would you decide whether to replace that list with a generator, and what would you check when integrating the change?",
    "created_at": "2026-11-09T09:36:34+00:00",
    "topic": "Generators",
    "source": "question generation",
    "role": "Software Engineer",
    "difficulty": "Medium",
    "domain": "IT / Software Engineering",
    "category": "scenario",
    "company": ""
  },
  {
    "id": "e18fe2d46c8f00eddeb7",
    "question": "What are Python decorators and how do they work?",
    "created_at": "2026-11-09T09:35:40+00:00",
    "category": "technical",
    "domain": "IT / Software Engineering",
    "source": "demo seed",
    "difficulty": "Medium",
    "topic": "Decorators",
    "role": "Software Engineer",
    "company": ""
  }
]
```
