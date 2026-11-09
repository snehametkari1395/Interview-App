"""Trusted, enumerated interview settings: domains, difficulty, depth, and personas.

Everything in this module is application-controlled. Only values that appear in
these catalogs are ever placed in a system prompt, so user-chosen settings cannot
smuggle free text into the model's instructions.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Domain:
    name: str
    roles: tuple[str, ...]
    focuses: tuple[str, ...]
    expertise: str
    behavioral: str
    evaluation: str


@dataclass(frozen=True)
class Level:
    name: str
    summary: str
    question_guidance: str
    evaluation_guidance: str


@dataclass(frozen=True)
class Depth:
    name: str
    summary: str
    guidance: str
    word_budget: int


@dataclass(frozen=True)
class Persona:
    name: str
    summary: str
    tone: str
    questioning: str
    feedback: str


DOMAINS: dict[str, Domain] = {
    domain.name: domain
    for domain in (
        Domain(
            name="IT / Software Engineering",
            roles=(
                "Software Engineer",
                "Full-Stack Developer",
                "Frontend Developer",
                "Backend Developer",
                "Product Engineer",
                "DevOps / Platform Engineer",
            ),
            focuses=("Balanced", "Technical depth", "System design", "Behavioral"),
            expertise="Software design, data structures, APIs, testing, debugging, reliability, security, and delivery practices.",
            behavioral="ownership, collaboration in code review, handling incidents, and trade-off communication",
            evaluation="technical correctness, sound trade-offs, testing and failure-mode awareness, and clear reasoning about design choices",
        ),
        Domain(
            name="Artificial Intelligence / Machine Learning",
            roles=(
                "AI Engineer",
                "Machine Learning Engineer",
                "Applied Scientist",
                "MLOps Engineer",
            ),
            focuses=("Balanced", "Technical depth", "ML system design", "Behavioral"),
            expertise="Model selection and training, evaluation methodology, LLM applications, retrieval, data quality, deployment, monitoring, and responsible AI.",
            behavioral="experiment discipline, communicating uncertainty, and collaborating with product and data teams",
            evaluation="correct ML concepts, rigorous evaluation thinking, awareness of data leakage and bias, and production realism",
        ),
        Domain(
            name="Data Science",
            roles=("Data Scientist", "Data Analyst", "Analytics Engineer"),
            focuses=("Balanced", "Technical depth", "Case / scenario", "Behavioral"),
            expertise="Statistics, experimentation, SQL and data modelling, exploratory analysis, metrics design, and communicating insights.",
            behavioral="stakeholder management, translating questions into analyses, and defending conclusions with evidence",
            evaluation="statistical correctness, appropriate method choice, metric definitions, and clear business interpretation",
        ),
        Domain(
            name="Finance",
            roles=("Financial Analyst", "Investment Analyst", "Accountant", "Risk Analyst"),
            focuses=("Balanced", "Technical depth", "Case / scenario", "Behavioral"),
            expertise="Financial statements, valuation, budgeting and forecasting, accounting principles, risk, and regulatory awareness.",
            behavioral="integrity, attention to detail, deadline pressure, and explaining numbers to non-finance stakeholders",
            evaluation="accuracy of financial concepts, sound assumptions, quantitative reasoning, and risk and compliance awareness",
        ),
        Domain(
            name="Human Resources",
            roles=(
                "HR Generalist",
                "Talent Acquisition Specialist",
                "HR Business Partner",
                "Learning and Development Specialist",
            ),
            focuses=("Balanced", "Technical depth", "Case / scenario", "Behavioral"),
            expertise="Recruitment, employee relations, performance management, compensation, employment law awareness, and people analytics.",
            behavioral="confidentiality, empathy with fairness, conflict resolution, and influencing managers",
            evaluation="fair and lawful practice, confidentiality, balanced judgment between employee and business needs, and clear process",
        ),
        Domain(
            name="Business / Management",
            roles=(
                "Product Manager",
                "Project Manager",
                "Operations Manager",
                "Management Consultant",
            ),
            focuses=("Balanced", "Technical depth", "Case / scenario", "Behavioral"),
            expertise="Strategy, prioritisation, planning, operations, stakeholder management, metrics, and business case reasoning.",
            behavioral="leadership, decision-making under ambiguity, managing conflict, and delivering through others",
            evaluation="structured thinking, data-informed decisions, stakeholder awareness, and measurable outcomes",
        ),
        Domain(
            name="Communication",
            roles=(
                "Communications Specialist",
                "Public Relations Specialist",
                "Marketing Communications Manager",
                "Content Strategist",
            ),
            focuses=("Balanced", "Technical depth", "Case / scenario", "Behavioral"),
            expertise="Audience analysis, messaging, writing and editing, media relations, crisis communication, channel strategy, and measuring impact.",
            behavioral="clarity under pressure, receiving editorial feedback, cross-team alignment, and representing the organisation",
            evaluation="audience-appropriate messaging, clarity and structure, ethical communication, and measurable communication goals",
        ),
    )
}

DIFFICULTIES: dict[str, Level] = {
    level.name: level
    for level in (
        Level(
            name="Easy",
            summary="Fundamentals and entry-level concepts.",
            question_guidance=(
                "Ask about one fundamental concept per question: definitions, core principles, and simple examples "
                "suitable for a graduate or entry-level candidate. Avoid multi-part questions, edge cases, and scale."
            ),
            evaluation_guidance=(
                "A correct explanation of the core concept with a simple, relevant example deserves a 4. "
                "Do not penalise the absence of advanced trade-offs."
            ),
        ),
        Level(
            name="Medium",
            summary="Applied knowledge and practical problem-solving.",
            question_guidance=(
                "Ask practical, applied questions drawn from day-to-day work at a mid-level: a realistic situation that "
                "requires choosing an approach and weighing two or three considerations."
            ),
            evaluation_guidance=(
                "A 4 requires a correct, structured approach applied to the situation with at least one concrete example "
                "or justification. Generic textbook answers score 3 at most."
            ),
        ),
        Level(
            name="Hard",
            summary="Advanced scenarios, trade-offs, and deeper reasoning.",
            question_guidance=(
                "Ask senior-level questions: ambiguous, multi-constraint scenarios involving trade-offs, edge cases, failure "
                "modes, scale, risk, or competing stakeholders. Questions may require quantitative or second-order reasoning."
            ),
            evaluation_guidance=(
                "A 4 requires explicit trade-offs, justified decisions, and awareness of risks or failure modes. "
                "Correct but surface-level answers score 3 at most."
            ),
        ),
    )
}

DEPTHS: dict[str, Depth] = {
    depth.name: depth
    for depth in (
        Depth(
            name="Concise",
            summary="Short, direct answers with key points.",
            guidance="Keep explanations short and direct. Sample answers stay under about 120 words and lead with the key points.",
            word_budget=120,
        ),
        Depth(
            name="Balanced",
            summary="Moderate explanations with a relevant example.",
            guidance="Give moderate explanations with one relevant example. Sample answers stay under about 250 words.",
            word_budget=250,
        ),
        Depth(
            name="Detailed",
            summary="Comprehensive explanations, examples, and reasoning.",
            guidance=(
                "Give comprehensive explanations: reasoning, examples, and practical insights or pitfalls. "
                "Sample answers stay under about 450 words."
            ),
            word_budget=450,
        ),
    )
}

DEPTH_INVARIANT = (
    "Response depth changes only length and elaboration. It never changes facts, the score, "
    "or the substance of the assessment."
)

PERSONAS: dict[str, Persona] = {
    persona.name: persona
    for persona in (
        Persona(
            name="Strict",
            summary="Challenging questions, direct feedback, deep probing.",
            tone="Direct, terse, and professional; maintains interview pressure without being rude or demeaning.",
            questioning="Asks challenging questions and probes weak or vague points with pointed follow-ups that demand specifics.",
            feedback="States shortcomings plainly and first; praise is brief and only where earned.",
        ),
        Persona(
            name="Neutral",
            summary="Professional, objective, and balanced.",
            tone="Professional, objective, and even-handed.",
            questioning="Asks balanced questions and follow-ups that clarify reasoning.",
            feedback="Gives constructive, unbiased feedback weighted evenly between strengths and gaps.",
        ),
        Persona(
            name="Friendly",
            summary="Supportive, encouraging, and low pressure.",
            tone="Warm, supportive, and encouraging; helps the candidate feel comfortable.",
            questioning="Asks approachable questions and offers gentle follow-ups that invite the candidate to expand.",
            feedback="Opens with genuine strengths, then frames improvements as constructive next steps without pressure.",
        ),
    )
}

FAIRNESS_RULE = (
    "The persona affects only tone, phrasing, and how follow-ups are framed. Scores, criteria ratings, and the "
    "substance of strengths and improvements must be identical to what a neutral, fair evaluator would give."
)

INTERVIEW_TYPES = ("Technical", "Behavioural")

FOCUS_KIND = {
    "Technical depth": "technical",
    "System design": "scenario",
    "ML system design": "scenario",
    "Case / scenario": "scenario",
    "Behavioral": "behavioral",
}

DEFAULT_DOMAIN = "IT / Software Engineering"
DEFAULT_DIFFICULTY = "Medium"
DEFAULT_DEPTH = "Balanced"
DEFAULT_PERSONA = "Neutral"


def all_roles() -> list[str]:
    roles: list[str] = []
    for domain in DOMAINS.values():
        roles.extend(role for role in domain.roles if role not in roles)
    return roles


def domain_for_role(role: str) -> str:
    for domain in DOMAINS.values():
        if role in domain.roles:
            return domain.name
    return DEFAULT_DOMAIN


@dataclass(frozen=True)
class PrepProfile:
    """The interview settings for one round, guide, or comparison."""

    domain: str = DEFAULT_DOMAIN
    role: str = "Software Engineer"
    difficulty: str = DEFAULT_DIFFICULTY
    depth: str = DEFAULT_DEPTH
    persona: str = DEFAULT_PERSONA

    def validated(self) -> "PrepProfile":
        """Reject any value outside the catalogs (defence in depth for prompt construction)."""
        if self.domain not in DOMAINS:
            raise ValueError(f"Unknown domain: {self.domain!r}")
        if self.role not in DOMAINS[self.domain].roles:
            raise ValueError(f"Unknown role for {self.domain}: {self.role!r}")
        if self.difficulty not in DIFFICULTIES:
            raise ValueError(f"Unknown difficulty: {self.difficulty!r}")
        if self.depth not in DEPTHS:
            raise ValueError(f"Unknown response depth: {self.depth!r}")
        if self.persona not in PERSONAS:
            raise ValueError(f"Unknown persona: {self.persona!r}")
        return self

    def label(self) -> str:
        return f"{self.role} · {self.difficulty} · {self.persona} interviewer · {self.depth} responses"
