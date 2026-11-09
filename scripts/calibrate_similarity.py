"""Measure embedding similarity on labelled question pairs to calibrate the duplicate/similar thresholds.

    uv run python scripts/calibrate_similarity.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from interview_app.vectorstore import QuestionMemory, cosine  # noqa: E402

PAIRS = [
    ("What are Python decorators and how do they work?", "Can you explain how decorators function in Python?", "duplicate"),
    ("How would you implement a caching decorator in Python?", "Write a Python decorator that memoizes function results.", "duplicate"),
    ("What is the difference between a process and a thread?", "How do threads differ from processes?", "duplicate"),
    ("Explain precision and recall.", "What do precision and recall measure in a classifier?", "duplicate"),
    ("How would you design an A/B test for a new checkout button?", "Describe how you'd set up an A/B experiment for a new checkout button.", "duplicate"),
    ("Tell me about a time you resolved a conflict on your team.", "Describe a situation where you handled a disagreement within your team.", "duplicate"),
    ("What are Python decorators and how do they work?", "How would you use a decorator to add logging to functions?", "similar"),
    ("How would you design an A/B test for a new checkout button?", "How do you decide the sample size for an A/B test?", "similar"),
    ("What is overfitting and how can you detect it?", "How does regularisation reduce overfitting?", "similar"),
    ("Walk me through a DCF valuation.", "How do you choose the discount rate in a DCF?", "similar"),
    ("How would you reduce hallucinations in a RAG assistant?", "How would you evaluate the retrieval quality of a RAG system?", "similar"),
    ("What are Python decorators and how do they work?", "What are Python generators and when would you use them?", "new"),
    ("What are Python decorators and how do they work?", "Explain list comprehensions in Python.", "new"),
    ("How would you design an A/B test for a new checkout button?", "Tell me about a time you resolved a conflict on your team.", "new"),
    ("Explain precision and recall.", "How do you handle missing data in a dataset?", "new"),
    ("What is the difference between a process and a thread?", "How would you design a rate limiter for an API?", "new"),
    ("Walk me through a DCF valuation.", "Walk me through the three financial statements.", "new"),
]


def main() -> None:
    memory = QuestionMemory(path=None)
    texts = sorted({text for a, b, _ in PAIRS for text in (a, b)})
    vectors = dict(zip(texts, memory.embed(texts)))
    by_label: dict[str, list[float]] = {}
    for a, b, label in PAIRS:
        score = cosine(vectors[a], vectors[b])
        by_label.setdefault(label, []).append(score)
        print(f"{score:.3f}  {label:9}  {a[:45]:45} | {b[:55]}")
    for label, scores in by_label.items():
        print(f"{label:9} min {min(scores):.3f}  max {max(scores):.3f}")


if __name__ == "__main__":
    main()
