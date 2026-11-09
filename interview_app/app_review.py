"""LLM-based critique of this application (usability, security, prompt engineering).

The dossier is built only from an allow-list of source files. It is scrubbed of anything that
looks like a credential, and of the prompt canary, before it leaves the machine. Secrets files
are never included.
"""

from pathlib import Path

from interview_app.model_config import GenerationParams
from interview_app.openrouter import chat_json, get_api_key
from interview_app.prompts import critique_prompt
from interview_app.security_guard import PROMPT_CANARY, choice_field, int_field, list_field, redact_secrets, text_field

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Ordered by review importance: if the size cap is reached, the least important files are dropped.
DOSSIER_FILES = (
    "interview_app/prompts.py",
    "interview_app/security_guard.py",
    "interview_app/openrouter.py",
    "interview_app/file_ingest.py",
    "interview_app/schemas.py",
    "interview_app/model_config.py",
    "app_pages/practice.py",
    "app.py",
    "app_pages/job_description.py",
    "interview_app/structured.py",
    "interview_app/coaching.py",
    "interview_app/ui.py",
    "interview_app/pricing.py",
    "app_pages/structured_output.py",
    "app_pages/model_settings.py",
    "interview_app/catalog.py",
    "app_pages/interviewer_guide.py",
    "app_pages/model_lab.py",
)
MAX_FILE_CHARS = 24000
MAX_DOSSIER_CHARS = 140000

FEATURE_SUMMARY = (
    "Interview App is a Streamlit interview-practice app. Users choose a domain, role, difficulty, response depth, "
    "and interviewer persona, then answer AI-generated or curated questions one at a time and receive structured "
    "feedback. Other pages analyse pasted job descriptions, generate interviewer guides, compare model parameter "
    "settings, and test security screening. All model calls go through OpenRouter from the Python server."
)

PERSPECTIVES = ("Usability", "Security", "Prompt engineering")
SEVERITIES = ("high", "medium", "low")


def build_dossier(root: Path = PROJECT_ROOT) -> tuple[str, list[str]]:
    """Return (dossier text, included file names)."""
    sections, included, total = [], [], 0
    secrets = [get_api_key()]
    for relative in DOSSIER_FILES:
        path = root / relative
        if not path.is_file() or "secrets" in path.name:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        text = redact_secrets(text, *secrets).replace(PROMPT_CANARY, "<canary-token>")
        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + "\n# ... truncated ..."
        if total + len(text) > MAX_DOSSIER_CHARS:
            continue  # skip this file but keep trying smaller ones
        sections.append(f"===== FILE: {relative} =====\n{text}")
        included.append(relative)
        total += len(text)
    return "\n\n".join(sections), included


def normalize_critique(result: dict) -> dict:
    perspectives = []
    raw = result.get("perspectives", [])
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = choice_field(item, "name", PERSPECTIVES, "")
        if not name or any(p["name"] == name for p in perspectives):
            continue
        issues = []
        for issue in item.get("issues", []) if isinstance(item.get("issues"), list) else []:
            if isinstance(issue, dict) and text_field(issue, "title", 160):
                issues.append({
                    "title": text_field(issue, "title", 160),
                    "severity": choice_field(issue, "severity", SEVERITIES, "medium"),
                    "evidence": text_field(issue, "evidence", 500),
                    "recommendation": text_field(issue, "recommendation", 600),
                })
        issues.sort(key=lambda issue: SEVERITIES.index(issue["severity"]))
        perspectives.append({
            "name": name,
            "score": int_field(item, "score", 1, 5, 3),
            "summary": text_field(item, "summary", 800),
            "strengths": list_field(item, "strengths", limit=4, max_chars=400),
            "issues": issues[:6],
        })
    perspectives.sort(key=lambda p: PERSPECTIVES.index(p["name"]))
    return {
        "overall_summary": text_field(result, "overall_summary", 800),
        "perspectives": perspectives,
        "top_priorities": list_field(result, "top_priorities", limit=5, max_chars=400),
    }


def run_critique(params: GenerationParams | None = None) -> tuple[dict, list[str]]:
    dossier, files = build_dossier()
    payload = {"feature_summary": FEATURE_SUMMARY, "application_dossier": dossier}
    params = (params or GenerationParams()).with_min_tokens(4000)
    return normalize_critique(chat_json(critique_prompt(), payload, params)), files


def critique_to_markdown(critique: dict) -> str:
    lines = ["# Interview App application review", "", critique["overall_summary"], "", "## Top priorities"]
    lines += [f"{index}. {item}" for index, item in enumerate(critique["top_priorities"], start=1)]
    for perspective in critique["perspectives"]:
        lines += ["", f"## {perspective['name']} ({perspective['score']}/5)", "", perspective["summary"], "", "**Strengths**"]
        lines += [f"- {item}" for item in perspective["strengths"]]
        lines += ["", "**Issues**"]
        for issue in perspective["issues"]:
            lines += [f"- **[{issue['severity']}] {issue['title']}**: {issue['evidence']}", f"  - Recommendation: {issue['recommendation']}"]
    return "\n".join(lines)
