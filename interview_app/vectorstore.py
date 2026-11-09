"""Semantic question memory: ChromaDB + an open-source local embedding model.

Why ChromaDB: it stores vectors *and* metadata together (domain, role, company, difficulty,
category, timestamp) with metadata filtering, persists to a local folder, and needs no server.
FAISS would need a separate metadata store.

Embeddings: ``all-MiniLM-L6-v2`` (Apache-2.0), run locally through ChromaDB's ONNX runtime. No
question text leaves the machine for embedding, and there is no per-call cost. The model is
downloaded once (~80 MB) on first use.

Similarity is cosine similarity (1 - cosine distance) between question embeddings. Each new
question is labelled:
- duplicate (>= duplicate threshold): the same question in different words; regenerated.
- similar (>= similar threshold): same sub-topic, different angle; kept and labelled.
- new: kept.
Only generated question text and its metadata are stored. Candidate answers are never stored.
"""

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "chroma"
COLLECTION = "interview_questions"

# Calibrated on labelled question pairs with all-MiniLM-L6-v2 (see docs/VECTOR_DB.md).
DEFAULT_DUPLICATE_THRESHOLD = 0.62
DEFAULT_SIMILAR_THRESHOLD = 0.45
METADATA_FIELDS = ("domain", "role", "company", "difficulty", "category", "topic", "source", "created_at")


@dataclass(frozen=True)
class Thresholds:
    duplicate: float = DEFAULT_DUPLICATE_THRESHOLD
    similar: float = DEFAULT_SIMILAR_THRESHOLD

    def validated(self) -> "Thresholds":
        duplicate = min(0.99, max(0.5, float(self.duplicate)))
        similar = min(duplicate - 0.01, max(0.3, float(self.similar)))
        return Thresholds(round(duplicate, 3), round(similar, 3))

    def label(self, similarity: float) -> str:
        if similarity >= self.duplicate:
            return "duplicate"
        if similarity >= self.similar:
            return "similar"
        return "new"


@dataclass(frozen=True)
class Match:
    id: str
    text: str
    similarity: float
    metadata: dict


@dataclass(frozen=True)
class NoveltyCheck:
    label: str
    best: Match | None
    matches: tuple[Match, ...] = field(default_factory=tuple)

    @property
    def similarity(self) -> float:
        return self.best.similarity if self.best else 0.0


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def question_id(text: str, domain: str) -> str:
    return hashlib.sha1(f"{domain}|{normalise(text)}".encode()).hexdigest()[:20]


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def default_embedding_function():
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    return DefaultEmbeddingFunction()


class QuestionMemory:
    def __init__(self, path: Path | str | None = DEFAULT_PATH, *, client=None, embedding_function=None):
        import chromadb

        if client is None:
            if path is None:
                client = chromadb.EphemeralClient()
            else:
                Path(path).mkdir(parents=True, exist_ok=True)
                client = chromadb.PersistentClient(path=str(path))
        self.embedding_function = embedding_function or default_embedding_function()
        self.collection = client.get_or_create_collection(
            COLLECTION,
            embedding_function=self.embedding_function,
            metadata={"hnsw:space": "cosine"},
        )

    # -- reads ----------------------------------------------------------------

    def count(self) -> int:
        return self.collection.count()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, vector)) for vector in self.embedding_function(texts)]

    def similar(self, text: str, *, k: int = 5, domain: str | None = None) -> list[Match]:
        total = self.count()
        if not total or not text.strip():
            return []
        result = self.collection.query(
            query_texts=[text],
            n_results=min(k, total),
            where={"domain": domain} if domain else None,
            include=["documents", "metadatas", "distances"],
        )
        matches = []
        for item_id, document, metadata, distance in zip(
            result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
        ):
            matches.append(Match(item_id, document, round(1.0 - float(distance), 4), dict(metadata or {})))
        return matches

    def check(self, text: str, thresholds: Thresholds, *, domain: str | None = None, extra_texts: list[str] | None = None) -> NoveltyCheck:
        """Label ``text`` against stored questions and, optionally, unsaved ``extra_texts`` (same batch)."""
        thresholds = thresholds.validated()
        matches = list(self.similar(text, k=5, domain=domain))
        if extra_texts:
            vectors = self.embed([text, *extra_texts])
            for other, vector in zip(extra_texts, vectors[1:]):
                matches.append(Match("batch", other, round(cosine(vectors[0], vector), 4), {"source": "this batch"}))
        matches.sort(key=lambda match: match.similarity, reverse=True)
        best = matches[0] if matches else None
        return NoveltyCheck(thresholds.label(best.similarity) if best else "new", best, tuple(matches[:5]))

    def avoid_list(self, query: str, *, domain: str | None, k: int = 8) -> list[str]:
        """Stored questions closest to what is about to be generated (sent to the LLM as 'avoid')."""
        return [match.text for match in self.similar(query, k=k, domain=domain)]

    def list_questions(self, *, domain: str | None = None, limit: int = 1000) -> list[dict]:
        result = self.collection.get(where={"domain": domain} if domain else None, limit=limit, include=["documents", "metadatas"])
        rows = [{"id": item_id, "question": document, **(metadata or {})} for item_id, document, metadata in zip(result["ids"], result["documents"], result["metadatas"])]
        return sorted(rows, key=lambda row: row.get("created_at", ""), reverse=True)

    # -- writes ---------------------------------------------------------------

    def add(self, text: str, metadata: dict) -> str:
        """Store a generated question. Only whitelisted, non-sensitive metadata is kept."""
        domain = str(metadata.get("domain", ""))
        clean = {key: str(metadata.get(key, ""))[:200] for key in METADATA_FIELDS}
        clean["created_at"] = clean["created_at"] or datetime.now(timezone.utc).isoformat(timespec="seconds")
        item_id = question_id(text, domain)
        self.collection.upsert(ids=[item_id], documents=[text.strip()[:600]], metadatas=[clean])
        return item_id

    def delete(self, ids: list[str]) -> None:
        if ids:
            self.collection.delete(ids=ids)

    def clear(self, domain: str | None = None) -> None:
        ids = [row["id"] for row in self.list_questions(domain=domain, limit=100000)]
        self.delete(ids)
