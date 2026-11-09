"""Deterministic checks on generated question sets.

These run before (and independently of) the LLM judge, cost nothing, and give the same result
every time. They cover what code can verify reliably: schema validity, required fields, count,
difficulty labels, topic coverage against the dataset's expected topics, semantic repetition
(embedding similarity), follow-up distinctness, and a readability proxy.
"""

import re
from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Callable

from interview_app.chain_schemas import QUESTION_SET_SCHEMA
from interview_app.schemas import schema_errors
from interview_app.vectorstore import Thresholds, cosine

Embedder = Callable[[list[str]], list[list[float]]]
QUESTION_WORDS = (6, 60)


@dataclass
class DeterministicResult:
    schema_valid: bool
    schema_issues: list[str]
    required_fields_ok: float
    count_ok: bool
    difficulty_ok: float
    topic_coverage: float
    covered_topics: list[str]
    missing_topics: list[str]
    max_pair_similarity: float
    duplicate_pairs: int
    repetition_score: int
    follow_up_distinct: float
    readability_ok: float
    avg_question_words: float
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def repetition_score(max_similarity: float, duplicates: int, thresholds: Thresholds) -> int:
    """1-5, higher is better (less repetition). Mirrors the judge's scale for comparison."""
    if duplicates > 1:
        return 1
    if duplicates == 1:
        return 2
    if max_similarity >= thresholds.similar + (thresholds.duplicate - thresholds.similar) / 2:
        return 3
    if max_similarity >= thresholds.similar:
        return 4
    return 5


def run_checks(data: dict, case: dict, embed: Embedder, thresholds: Thresholds) -> DeterministicResult:
    questions = data.get("questions", []) if isinstance(data, dict) else []
    issues: list[str] = []
    schema_issues = schema_errors(data, QUESTION_SET_SCHEMA)

    complete = [
        bool(item.get("question", "").strip()) and len([p for p in item.get("expected_answer_points", []) if p.strip()]) >= 2
        and len([f for f in item.get("follow_up_questions", []) if f.strip()]) >= 1 and bool(item.get("topic", "").strip())
        for item in questions
    ]
    required_ok = sum(complete) / len(questions) if questions else 0.0
    count_ok = len(questions) == case["count"]
    difficulty_ok = sum(item.get("difficulty") == case["difficulty"] for item in questions) / len(questions) if questions else 0.0

    corpus = " ".join(
        " ".join([item.get("question", ""), item.get("topic", ""), *item.get("expected_answer_points", [])]) for item in questions
    ).lower()
    covered = [topic["topic"] for topic in case["expected_topics"] if any(keyword in corpus for keyword in topic["keywords"])]
    missing = [topic["topic"] for topic in case["expected_topics"] if topic["topic"] not in covered]
    coverage = len(covered) / len(case["expected_topics"]) if case["expected_topics"] else 1.0

    texts = [item.get("question", "") for item in questions]
    max_similarity, duplicates, distinct = 0.0, 0, 1.0
    if texts:
        follow_ups = [(index, follow_up) for index, item in enumerate(questions) for follow_up in item.get("follow_up_questions", [])]
        vectors = embed(texts + [text for _, text in follow_ups])
        question_vectors, follow_vectors = vectors[: len(texts)], vectors[len(texts):]
        pair_scores = [cosine(a, b) for a, b in combinations(question_vectors, 2)]
        max_similarity = max(pair_scores, default=0.0)
        duplicates = sum(score >= thresholds.duplicate for score in pair_scores)
        if follow_ups:
            distinct_flags = [cosine(question_vectors[index], vector) < thresholds.duplicate for (index, _), vector in zip(follow_ups, follow_vectors)]
            distinct = sum(distinct_flags) / len(distinct_flags)

    word_counts = [_words(text) for text in texts]
    readable = sum(QUESTION_WORDS[0] <= count <= QUESTION_WORDS[1] for count in word_counts) / len(word_counts) if word_counts else 0.0

    if schema_issues:
        issues.append(f"{len(schema_issues)} schema violation(s)")
    if required_ok < 1:
        issues.append("some questions lack expected answer points, follow-ups, or a topic")
    if not count_ok:
        issues.append(f"expected {case['count']} questions, got {len(questions)}")
    if difficulty_ok < 1:
        issues.append("difficulty label differs from the request")
    if missing:
        issues.append("missing expected topics: " + ", ".join(missing))
    if duplicates:
        issues.append(f"{duplicates} near-duplicate question pair(s)")
    if distinct < 1:
        issues.append("some follow-ups restate their question")
    if readable < 1:
        issues.append("some questions are very short or very long")

    return DeterministicResult(
        schema_valid=not schema_issues,
        schema_issues=schema_issues[:5],
        required_fields_ok=round(required_ok, 3),
        count_ok=count_ok,
        difficulty_ok=round(difficulty_ok, 3),
        topic_coverage=round(coverage, 3),
        covered_topics=covered,
        missing_topics=missing,
        max_pair_similarity=round(max_similarity, 3),
        duplicate_pairs=duplicates,
        repetition_score=repetition_score(max_similarity, duplicates, thresholds),
        follow_up_distinct=round(distinct, 3),
        readability_ok=round(readable, 3),
        avg_question_words=round(sum(word_counts) / len(word_counts), 1) if word_counts else 0.0,
        issues=issues,
    )
