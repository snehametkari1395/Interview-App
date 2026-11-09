"""Model licence classification.

OpenRouter's catalog has no licence field, so this is a curated, conservative registry built from
publishers' model cards. Rules are matched in order on the OpenRouter model id. Anything not
matched is "Unknown" and must be verified by hand; nothing is assumed to be open.

Terminology (deliberately precise):
- "Open weights, OSI licence": weights downloadable under an OSI-approved licence (Apache-2.0, MIT).
  Training data and full training code are generally NOT released, so these are not "open-source
  AI" under the OSI Open Source AI Definition. They are the most permissive open-weight category.
- "Open weights, restricted licence": weights downloadable, but the licence adds use, scale, or
  attribution restrictions (e.g. Llama Community Licence, Gemma Terms, NVIDIA Open Model Licence).
- "Proprietary": API-only; weights not released, even when the family has open siblings.

Using an open-weight model through OpenRouter still sends data to a third-party inference provider.
Self-hosting the weights is what removes that dependency.
"""

import re
from dataclasses import dataclass

OSI_OPEN = "Open weights, OSI licence"
RESTRICTED = "Open weights, restricted licence"
PROPRIETARY = "Proprietary"
UNKNOWN = "Unknown"
OPEN_CATEGORIES = (OSI_OPEN, RESTRICTED)


@dataclass(frozen=True)
class LicenceInfo:
    category: str
    licence: str
    note: str = ""

    @property
    def is_open_weight(self) -> bool:
        return self.category in OPEN_CATEGORIES


# (regex on model id, info). First match wins, so proprietary variants come before open families.
_RULES: tuple[tuple[str, LicenceInfo], ...] = (
    # Qwen: open-weight families vs Alibaba Cloud API-only models.
    (r"^qwen/qwen-(plus|max|turbo)", LicenceInfo(PROPRIETARY, "Alibaba Cloud API", "Hosted-only Qwen models; weights not released.")),
    (r"^qwen/qwen3\.\d+-(plus|max|flash|omni)", LicenceInfo(PROPRIETARY, "Alibaba Cloud API", "Hosted-only Qwen models; weights not released.")),
    (r"^qwen/qwen3-coder-(plus|flash)", LicenceInfo(PROPRIETARY, "Alibaba Cloud API", "Hosted-only variant.")),
    (r"^qwen/qwen-2\.5-72b|^qwen/qwen2\.5-vl-72b", LicenceInfo(RESTRICTED, "Qwen Licence", "Custom licence; commercial use above 100M MAU needs permission.")),
    (r"^qwen/qwen3-(\d|next|coder|vl|embedding)", LicenceInfo(OSI_OPEN, "Apache-2.0")),
    (r"^qwen/qwen-2\.5-(7b|coder-32b)", LicenceInfo(OSI_OPEN, "Apache-2.0")),
    # DeepSeek: V3-0324, V3.1, V3.2, and R1 are MIT; the original V3 used the DeepSeek Model Licence.
    (r"^deepseek/deepseek-(chat-v3-0324|chat-v3\.1|v3\.1|v3\.2|r1)", LicenceInfo(OSI_OPEN, "MIT")),
    (r"^deepseek/deepseek-chat$", LicenceInfo(RESTRICTED, "DeepSeek Model Licence", "Use-based restrictions; OpenRouter may route this alias to newer versions.")),
    # Meta Llama: open weights, but the community licence restricts large-scale and some uses.
    (r"^meta-llama/llama-(3|4)", LicenceInfo(RESTRICTED, "Llama Community Licence", "Acceptable-use policy; >700M MAU requires a Meta licence.")),
    # Mistral: Apache-2.0 open models vs hosted-only or research-licensed models.
    (r"^mistralai/(mistral-small-(24b|3)|mistral-nemo|mixtral|mistral-7b|pixtral-12b)", LicenceInfo(OSI_OPEN, "Apache-2.0")),
    (r"^mistralai/mistral-large-2407|^mistralai/mistral-large$", LicenceInfo(RESTRICTED, "Mistral Research Licence", "Non-commercial use only without a commercial licence.")),
    (r"^mistralai/(mistral-medium|mistral-saba|codestral-2508|mistral-small-2603|mistral-large-4)", LicenceInfo(PROPRIETARY, "Mistral commercial API")),
    # Google Gemma (open, restricted terms) vs Gemini (proprietary).
    (r"^google/gemma-[23]", LicenceInfo(RESTRICTED, "Gemma Terms of Use", "Prohibited-use policy applies.")),
    (r"^google/gemini", LicenceInfo(PROPRIETARY, "Google commercial API")),
    # Others with well-documented licences.
    (r"^openai/gpt-oss", LicenceInfo(OSI_OPEN, "Apache-2.0", "Open-weight model published by OpenAI.")),
    (r"^microsoft/phi-4", LicenceInfo(OSI_OPEN, "MIT")),
    (r"^z-ai/glm-4\.[5-7]", LicenceInfo(OSI_OPEN, "MIT")),
    (r"^moonshotai/kimi-k2", LicenceInfo(RESTRICTED, "Modified MIT", "Attribution required above 100M MAU or $20M monthly revenue.")),
    (r"^nvidia/(llama-)?nemotron", LicenceInfo(RESTRICTED, "NVIDIA Open Model Licence")),
    (r"^(openai|anthropic|x-ai|cohere|perplexity|amazon|inflection)/", LicenceInfo(PROPRIETARY, "Commercial API")),
)

# Open-source embedding model used for duplicate detection (runs locally via ChromaDB/ONNX).
EMBEDDING_MODEL = LicenceInfo(OSI_OPEN, "Apache-2.0", "sentence-transformers/all-MiniLM-L6-v2, run locally; no text leaves the machine.")


def classify(model_id: str) -> LicenceInfo:
    model = (model_id or "").lower().removesuffix(":free").split(":", 1)[0]
    for pattern, info in _RULES:
        if re.search(pattern, model):
            return info
    return LicenceInfo(UNKNOWN, "Unverified", "No licence rule for this model; check the publisher's model card.")


# Defaults for the advanced features. All are open weights under OSI licences.
DEFAULT_OPEN_MODEL = "qwen/qwen3-235b-a22b-2507"
COMPARISON_MODELS = ("qwen/qwen3-235b-a22b-2507", "deepseek/deepseek-v3.2", "mistralai/mistral-small-3.2-24b-instruct")
JUDGE_MODEL = "moonshotai/kimi-k2-0905"  # a different family from every compared model
