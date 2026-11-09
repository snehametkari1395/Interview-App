# Demo: semantic duplicate detection (ChromaDB + all-MiniLM-L6-v2)

Run 2026-11-09 09:10 UTC · model `openai/gpt-4o-mini`

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

- REJECTED wrong difficulty (Easy) (0.000): Can you explain what a Python generator is and when you would use it?  
  nearest: —
- REJECTED duplicate (0.669): Imagine you need to implement a caching mechanism in a Python application. Would you use a decorator for this purpose? Why or why not?  
  nearest: What are Python decorators and how do they work?
- ACCEPTED similar (0.461): Can you explain what a generator is in Python and when you might choose to use one over a list?  
  nearest: What are Python decorators and how do they work?
- ACCEPTED new (0.406): Describe a scenario where you would use context managers in Python. What are the benefits of using them?  
  nearest: What are Python decorators and how do they work?

## Stored metadata

```json
[
  {
    "id": "ec0feaa5f8303eb0b27b",
    "question": "Can you explain what a generator is in Python and when you might choose to use one over a list?",
    "domain": "IT / Software Engineering",
    "created_at": "2026-11-09T09:10:37+00:00",
    "company": "",
    "role": "Software Engineer",
    "source": "question generation",
    "difficulty": "Medium",
    "topic": "Python generators",
    "category": "technical"
  },
  {
    "id": "a9a53f97a62a2911223b",
    "question": "Describe a scenario where you would use context managers in Python. What are the benefits of using them?",
    "category": "scenario",
    "difficulty": "Medium",
    "topic": "Python context managers",
    "created_at": "2026-11-09T09:10:37+00:00",
    "company": "",
    "domain": "IT / Software Engineering",
    "role": "Software Engineer",
    "source": "question generation"
  },
  {
    "id": "e18fe2d46c8f00eddeb7",
    "question": "What are Python decorators and how do they work?",
    "role": "Software Engineer",
    "category": "technical",
    "created_at": "2026-11-09T09:10:19+00:00",
    "domain": "IT / Software Engineering",
    "topic": "Decorators",
    "difficulty": "Medium",
    "company": "",
    "source": "demo seed"
  }
]
```
