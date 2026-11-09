"""Semantic question memory: ChromaDB + the project's approved embedding model.

Why ChromaDB: it stores vectors *and* metadata together (domain, role, company, difficulty,
category, timestamp) with metadata filtering, persists to a local folder, and needs no server.
FAISS would need a separate metadata store.

Embeddings: ``qwen/qwen3-embedding-8b`` (the project's recommended embedding model) through the
OpenRouter embeddings endpoint. Only generated question text is sent for embedding (about
$0.01 per million tokens). Each embedding model gets its own collection, because vector sizes differ.

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
EMBEDDINGS_URL = "https://openrouter.ai/api/v1/embeddings"
EMBEDDING_MODEL = "qwen/qwen3-embedding-8b"
COLLECTION = "interview_questions_qwen3_embedding_8b"

# Calibrated on labelled question pairs with qwen/qwen3-embedding-8b (see docs/VECTOR_DB.md).
DEFAULT_DUPLICATE_THRESHOLD = 0.85
DEFAULT_SIMILAR_THRESHOLD = 0.70
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


class OpenRouterEmbedding:
    """ChromaDB embedding function backed by the OpenRouter embeddings API.

    The API key is resolved at call time from the app configuration and is never stored in the
    collection's persisted configuration.
    """

    def __init__(self, model: str = EMBEDDING_MODEL, api_key: str | None = None):
        self.model = model
        self._api_key = api_key

    def __call__(self, input):  # noqa: A002 - ChromaDB's protocol name
        import httpx
        import numpy as np

        from interview_app.openrouter import ModelServiceError, get_api_key

        texts = [str(text) for text in input]
        if not texts:
            return []
        api_key = self._api_key or get_api_key()
        if not api_key:
            raise ModelServiceError("Add OPENROUTER_API_KEY to enable question memory (embeddings).")
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                response = httpx.post(EMBEDDINGS_URL, headers={"Authorization": f"Bearer {api_key}"},
                                      json={"model": self.model, "input": texts}, timeout=60.0)
                response.raise_for_status()
                payload = response.json()
                if payload.get("error") or not isinstance(payload.get("data"), list):
                    raise ModelServiceError("The embedding service returned an unexpected response.")
                rows = sorted(payload["data"], key=lambda row: row.get("index", 0))
                return [np.asarray(row["embedding"], dtype=np.float32) for row in rows]
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                last_error = error
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code < 500 and error.response.status_code != 429:
                    break
        raise last_error

    @staticmethod
    def name() -> str:
        return "openrouter"

    def get_config(self) -> dict:
        return {"model": self.model}

    @staticmethod
    def build_from_config(config: dict) -> "OpenRouterEmbedding":
        return OpenRouterEmbedding(model=config.get("model", EMBEDDING_MODEL))

    def is_legacy(self) -> bool:
        return False

    def default_space(self) -> str:
        return "cosine"

    def supported_spaces(self) -> list[str]:
        return ["cosine", "l2", "ip"]

    def embed_query(self, input):  # noqa: A002
        return self(input)


def default_embedding_function():
    return OpenRouterEmbedding()


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
