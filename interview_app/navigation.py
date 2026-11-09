"""Page registry: the single list of pages, grouped for candidates and for developers."""

from pathlib import Path

PRACTICE = "Practice"
DEVELOPER = "Developer tools"

# (file, title, icon, section). Pages whose file does not exist yet are skipped by the router.
PAGES = (
    ("app_pages/practice.py", "Practice room", ":material/record_voice_over:", PRACTICE),
    ("app_pages/interview_chat.py", "Interview chat", ":material/forum:", PRACTICE),
    ("app_pages/job_description.py", "Job description", ":material/description:", PRACTICE),
    ("app_pages/structured_output.py", "Structured output", ":material/data_object:", PRACTICE),
    ("app_pages/interviewer_guide.py", "Interviewer guide", ":material/fact_check:", PRACTICE),
    ("app_pages/model_settings.py", "Model settings", ":material/settings:", DEVELOPER),
    ("app_pages/model_lab.py", "Model lab", ":material/tune:", DEVELOPER),
    ("app_pages/prompt_lab.py", "Prompt lab", ":material/science:", DEVELOPER),
    ("app_pages/question_memory.py", "Question memory", ":material/database:", DEVELOPER),
    ("app_pages/security_lab.py", "Security lab", ":material/shield:", DEVELOPER),
    ("app_pages/app_review.py", "App review", ":material/rate_review:", DEVELOPER),
)

ROOT = Path(__file__).resolve().parent.parent


def available_pages():
    return [page for page in PAGES if (ROOT / page[0]).is_file()]
