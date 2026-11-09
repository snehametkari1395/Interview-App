"""Offline test doubles for the LangChain workflows and the vector store."""

import json
import re
import zlib

import numpy as np
from chromadb.api.types import EmbeddingFunction
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from interview_app.model_config import GenerationParams, ModelCapabilities, RequestPlan

CAPS = ModelCapabilities(
    model="open/test-model",
    known=True,
    supported=frozenset({"temperature", "max_tokens", "structured_outputs", "response_format"}),
    pricing={"prompt": 1e-7, "completion": 4e-7},
)


def make_spec(model: str = "open/test-model"):
    from interview_app.chains.llm import ModelSpec

    return ModelSpec(model=model, params=GenerationParams(), capabilities=CAPS, api_key="test-key")


STOP_WORDS = frozenset("""the and are what how why when which who you your they them their this that with for from into
does did can could would should will was were has have had its use used using about there here then than also just more most
some any all not but only very work works""".split())


class HashEmbedding(EmbeddingFunction):
    """Deterministic bag-of-words embedding: texts sharing words are similar."""

    def __init__(self):
        pass

    def __call__(self, input):  # noqa: A002 - Chroma's protocol name
        return [self._vector(text) for text in input]

    def _vector(self, text: str):
        vector = np.zeros(256, dtype=np.float32)
        for word in re.findall(r"[a-z]+", text.lower()):
            if len(word) > 2 and word not in STOP_WORDS:
                vector[zlib.crc32(word.encode()) % 256] += 1.0
        return vector

    @staticmethod
    def name() -> str:
        return "hash-test-embedding"

    def get_config(self) -> dict:
        return {}

    @staticmethod
    def build_from_config(config: dict) -> "HashEmbedding":
        return HashEmbedding()


def memory():
    """An in-memory QuestionMemory with a unique collection per test."""
    import chromadb

    from interview_app.vectorstore import QuestionMemory

    client = chromadb.EphemeralClient()
    for collection in client.list_collections():
        client.delete_collection(collection.name)
    return QuestionMemory(client=client, embedding_function=HashEmbedding())


class FakeLLMs:
    """Replaces ``build_llm``: returns scripted responses keyed by schema name ("reply" for text)."""

    def __init__(self, responses: dict[str, list]):
        self.responses = {key: list(values) for key, values in responses.items()}
        self.calls: list[str] = []

    def build_llm(self, spec, *, schema=None, schema_name="response", streaming=False):
        key = "reply" if schema is None else schema_name
        if key == "candidate_message_triage" and not self.responses.get(key):
            self.responses[key] = [{"category": "answer", "reply": ""}]  # default: the message is an answer
        if not self.responses.get(key):
            raise AssertionError(f"No scripted response left for {key}")
        content = self.responses[key].pop(0)
        text = content if isinstance(content, str) else json.dumps(content)
        message = AIMessage(
            content=text,
            usage_metadata={"input_tokens": 120, "output_tokens": 60, "total_tokens": 180},
            response_metadata={"cost": 0.0001, "finish_reason": "stop", "model_name": spec.model},
        )
        self.calls.append(key)
        plan = RequestPlan(body={}, applied={}, skipped=(), output_mode="json_schema")
        return GenericFakeChatModel(messages=iter([message])), plan


def question(text: str, difficulty: str = "Medium", topic: str = "Python") -> dict:
    return {
        "question": text,
        "topic": topic,
        "category": "technical",
        "difficulty": difficulty,
        "expected_answer_points": ["point one", "point two"],
        "follow_up_questions": ["Why?"],
        "hint": "Structure: definition, example, trade-off.",
    }


def evaluation(score: int) -> dict:
    return {
        "overall_score": score,
        "summary": "A reasonable answer with gaps.",
        "technical_accuracy": {"score": score, "comment": "Mostly right."},
        "communication_skills": {"score": score, "comment": "Clear enough."},
        "problem_solving": {"score": score, "comment": "Some reasoning."},
        "strengths": ["Clear structure"],
        "weaknesses": ["No metrics"],
        "missing_concepts": ["sample size"],
        "improvement_suggestions": ["Quantify the impact"],
        "recommended_follow_up_questions": ["How would you measure it?"],
    }


def followup(text: str, decision: str = "new_topic", topic: str = "Generators") -> dict:
    return {
        "decision": decision,
        "rationale": "The candidate handled the previous topic well.",
        "next_question": text,
        "topic": topic,
        "category": "technical",
        "expected_answer_points": ["lazy evaluation", "memory efficiency"],
    }


SUMMARY = {
    "overall_score": 3,
    "overall_evaluation": "Solid fundamentals with gaps in experimentation rigour and measurement.",
    "readiness": "nearly ready",
    "competency_scores": [
        {"competency": "Python", "score": 4, "comment": "Good grasp."},
        {"competency": "Experimentation", "score": 2, "comment": "Missed sample size."},
    ],
    "strengths": ["Clear explanations"],
    "knowledge_gaps": ["Statistical power"],
    "learning_plan": [
        {"focus": "Power analysis", "action": "Work through three sample-size calculations.", "timeframe": "1 week"},
        {"focus": "Metrics", "action": "Define primary and guardrail metrics for two products.", "timeframe": "1 week"},
    ],
}
