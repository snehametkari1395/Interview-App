# Demo: semantic duplicate detection (ChromaDB + all-MiniLM-L6-v2)

Run 2026-11-09 08:45 UTC · model `openai/gpt-4o-mini` · Proprietary (Commercial API)

> **Stand-in model:** this run used a proprietary model because open-weight models were unavailable to the account. Re-run with an open-weight model.

Thresholds: duplicate ≥ 0.62, similar ≥ 0.45. Isolated in-memory collection.

## Step 1 · First request stored a decorators question

Stored: *What are Python decorators and how do they work?*

## Step 2 · Direct checks against memory (no LLM)

| Candidate question | Best similarity | Label |
| --- | --- | --- |
| Can you explain how decorators function in Python? | 0.928 | **duplicate** |
| How would you use a decorator to add logging to functions? | 0.563 | **similar** |
| What are Python generators and when would you use them? | 0.573 | **similar** |
| Explain list comprehensions in Python. | 0.417 | **new** |

## Step 3 · Second request: generate a Python question (chain B + de-duplication)

Sent as "avoid": ['What are Python decorators and how do they work?']

- ACCEPTED similar (0.531): What are Python generators and when would you choose to use them over lists?  
  nearest: What are Python decorators and how do they work?
- ACCEPTED new (0.392): How would you implement a simple caching mechanism in Python to optimize function calls?  
  nearest: What are Python generators and when would you choose to use them over lists?

## Stored metadata

```json
[
  {
    "id": "f2d24d51f61c955f926f",
    "question": "What are Python generators and when would you choose to use them over lists?",
    "company": "",
    "category": "technical",
    "created_at": "2026-11-09T08:45:43+00:00",
    "difficulty": "Medium",
    "topic": "Python generators",
    "source": "question generation",
    "domain": "IT / Software Engineering",
    "role": "Software Engineer"
  },
  {
    "id": "54513f73373100fe3db2",
    "question": "How would you implement a simple caching mechanism in Python to optimize function calls?",
    "source": "question generation",
    "company": "",
    "role": "Software Engineer",
    "domain": "IT / Software Engineering",
    "created_at": "2026-11-09T08:45:43+00:00",
    "topic": "Caching in Python",
    "category": "scenario",
    "difficulty": "Medium"
  },
  {
    "id": "e18fe2d46c8f00eddeb7",
    "question": "What are Python decorators and how do they work?",
    "topic": "Decorators",
    "role": "Software Engineer",
    "domain": "IT / Software Engineering",
    "category": "technical",
    "source": "demo seed",
    "created_at": "2026-11-09T08:45:36+00:00",
    "company": "",
    "difficulty": "Medium"
  }
]
```
