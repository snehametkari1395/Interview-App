"""Curated interview questions, used offline or when AI question generation is unavailable.

Two sources are combined:
- ``QUESTION_BANK``: the original role-specific questions (practical, mid-level, so they are
  treated as the Medium pool for their roles).
- ``DOMAIN_QUESTIONS``: questions for every domain at every difficulty level, tagged with a kind
  (technical, scenario, behavioral) so the focus filter works across domains.
"""

from random import sample

from interview_app.catalog import DOMAINS, FOCUS_KIND, all_roles, domain_for_role

ROLES = all_roles()

FOCUSES = ["Balanced", "Technical depth", "System design", "Behavioural"]

QUESTION_BANK = {
    "Full-Stack Developer": [
        ("How would you design a feature that updates the UI optimistically while keeping the server as the source of truth?", "Frontend and API design"),
        ("Walk through how you would investigate a slow page that makes several API calls.", "Performance"),
        ("How would you model permissions for a team-based application across the frontend and backend?", "Security and data modelling"),
        ("Describe a database migration you would make without interrupting active users.", "Data and reliability"),
        ("Tell me about a product decision you influenced with technical evidence.", "Product thinking"),
        ("How would you test a checkout flow that spans browser state, an API, and a database?", "Testing"),
        ("When would you move logic from the browser to the server, or the other way around?", "Architecture"),
        ("Tell me about a production issue you helped resolve and what you changed afterward.", "Ownership"),
        ("How would you make a large table usable on both mobile and desktop?", "Frontend engineering"),
        ("How do you decide what to log and measure for a new feature?", "Observability"),
    ],
    "Product Engineer": [
        ("How do you turn an ambiguous product request into a small, testable first release?", "Product thinking"),
        ("Tell me about a time you used customer evidence to change a technical direction.", "Customer focus"),
        ("How would you measure whether a new onboarding flow is working?", "Metrics"),
        ("Describe a trade-off you made between delivery speed and long-term maintainability.", "Judgment"),
        ("How would you design an experiment when traffic is limited?", "Experimentation"),
        ("How do you collaborate with design when a proposed interaction is expensive to build?", "Collaboration"),
        ("How would you prioritise reliability work against a feature commitment?", "Prioritisation"),
        ("Tell me about a feature you shipped that did not achieve its goal. What did you learn?", "Learning"),
        ("How would you handle conflicting feedback from users and internal stakeholders?", "Communication"),
        ("What signals would you use to decide whether to iterate on or remove a feature?", "Product judgment"),
    ],
    "AI Engineer": [
        ("How would you evaluate whether a retrieval-augmented generation system is returning useful evidence?", "Evaluation"),
        ("How would you reduce hallucinations in an assistant that answers from a document collection?", "Reliability"),
        ("Describe how you would build an offline evaluation set for a language-model feature.", "Evaluation design"),
        ("How would you choose between fine-tuning, retrieval, and prompt changes for a new use case?", "Model selection"),
        ("How would you handle prompt injection in user-provided documents?", "AI security"),
        ("What would you monitor after deploying a model-backed feature?", "Operations"),
        ("How would you control latency and cost in a multi-step model workflow?", "Performance and cost"),
        ("How do you communicate model uncertainty in a user-facing product?", "Product design"),
        ("How would you investigate a quality regression after changing an embedding model?", "Debugging"),
        ("When is a deterministic system a better choice than a language model?", "Engineering judgment"),
    ],
    "Frontend Developer": [
        ("How would you structure a complex form so it remains accessible and easy to validate?", "Accessibility"),
        ("What causes layout shift, and how would you find and prevent it?", "Performance"),
        ("How would you manage server state and optimistic updates in a data-heavy interface?", "State management"),
        ("How do you decide where a component boundary should be?", "Architecture"),
        ("How would you debug a page that performs well locally but slowly on mobile devices?", "Debugging"),
        ("How would you make a reusable component flexible without turning it into a large API?", "Component design"),
        ("What does keyboard accessibility mean for a custom dropdown?", "Accessibility"),
        ("How would you test a responsive navigation menu?", "Testing"),
        ("How would you prevent stale data from overwriting a more recent user action?", "Concurrency"),
        ("Tell me about a UI performance improvement you made and how you measured it.", "Impact"),
    ],
    "Backend Developer": [
        ("How would you design an API endpoint that must be safe to retry?", "API design"),
        ("How would you find the cause of rising database latency under load?", "Performance"),
        ("How do you choose transaction boundaries for a workflow spanning multiple services?", "Distributed systems"),
        ("How would you roll out a breaking API change to several clients?", "Compatibility"),
        ("What would you consider when designing rate limits for a public API?", "Reliability"),
        ("How would you protect sensitive data in logs and error messages?", "Security"),
        ("How would you design a background job system that avoids duplicate processing?", "Queues"),
        ("What signals would you use to detect a partial service outage?", "Observability"),
        ("How do you decide whether a workload belongs in a relational database or a cache?", "Data architecture"),
        ("Describe a difficult production bug and how you narrowed down its cause.", "Debugging"),
    ],
    "Software Engineer": [
        ("How would you choose data structures for a feature that needs fast lookups and ordered results?", "Data structures"),
        ("How do you approach a problem when the requirements are incomplete?", "Problem solving"),
        ("How would you design a service that processes events exactly once from the user's perspective?", "Distributed systems"),
        ("Tell me about a code review that changed how you approached a problem.", "Collaboration"),
        ("How would you test a function with many edge cases and external dependencies?", "Testing"),
        ("How do you decide whether to refactor existing code while adding a feature?", "Trade-offs"),
        ("What would you do when a dependency introduces a production regression?", "Ownership"),
        ("How would you explain a technical risk to a non-technical stakeholder?", "Communication"),
        ("How do you make a service resilient to a downstream dependency failure?", "Reliability"),
        ("Describe a technical decision you would make differently today.", "Reflection"),
    ],
}


# (question, topic, kind) where kind is technical | scenario | behavioral.
DOMAIN_QUESTIONS: dict[str, dict[str, list[tuple[str, str, str]]]] = {
    "IT / Software Engineering": {
        "Easy": [
            ("What is the difference between a process and a thread?", "Fundamentals", "technical"),
            ("Explain what an API is and give an example of one you have used.", "APIs", "technical"),
            ("What is version control, and why do teams use branches?", "Tooling", "technical"),
            ("When would you use a list versus a dictionary (hash map)?", "Data structures", "technical"),
            ("Tell me about a time you learned a new tool or language quickly.", "Learning", "behavioral"),
        ],
        "Medium": [
            ("How would you add caching to a slow endpoint without serving stale data to users?", "Performance", "scenario"),
            ("Walk me through how you would debug an intermittent test failure in CI.", "Debugging", "technical"),
            ("How do you decide what to cover with unit tests versus integration tests?", "Testing", "technical"),
            ("Tell me about a disagreement in a code review and how you resolved it.", "Collaboration", "behavioral"),
        ],
        "Hard": [
            ("Design a rate limiter for a multi-region API. How do you keep limits accurate without adding latency?", "Distributed systems", "scenario"),
            ("A deployment caused a 2% error rate in one region only. How do you triage, mitigate, and prevent recurrence?", "Incident response", "scenario"),
            ("How would you migrate a monolith's shared database to service-owned data without downtime?", "Architecture", "scenario"),
            ("When is eventual consistency unacceptable, and how would you design around it?", "Consistency", "technical"),
            ("Tell me about a technical decision you championed that others opposed. How did you build consensus, and what happened?", "Leadership", "behavioral"),
        ],
    },
    "Artificial Intelligence / Machine Learning": {
        "Easy": [
            ("What is the difference between supervised and unsupervised learning?", "ML fundamentals", "technical"),
            ("What is overfitting, and how can you detect it?", "Generalisation", "technical"),
            ("Explain precision and recall in plain language.", "Metrics", "technical"),
            ("Tell me about an ML or AI project you enjoyed and what you learned from it.", "Motivation", "behavioral"),
        ],
        "Medium": [
            ("Your classifier has 95% accuracy but users say it is useless. How do you investigate?", "Evaluation", "scenario"),
            ("How would you build a retrieval-augmented assistant over internal documents?", "LLM applications", "scenario"),
            ("How do you detect and handle data drift after a model is deployed?", "Monitoring", "technical"),
            ("Describe how you explained a model's limitations to a non-technical stakeholder.", "Communication", "behavioral"),
        ],
        "Hard": [
            ("Design an evaluation strategy for an LLM feature where there is no single correct answer.", "Evaluation design", "scenario"),
            ("Offline metrics improved but the online A/B test shows no gain. What could explain this, and what do you do next?", "Experimentation", "scenario"),
            ("How would you defend an LLM agent that reads untrusted web pages against prompt injection?", "AI security", "technical"),
            ("How would you cut inference cost by 60% for a model-backed feature without hurting quality?", "Performance and cost", "scenario"),
            ("Tell me about a time a model you shipped caused an unexpected harm or failure. How did you respond?", "Responsible AI", "behavioral"),
        ],
    },
    "Data Science": {
        "Easy": [
            ("What is the difference between mean and median, and when would you prefer the median?", "Statistics", "technical"),
            ("Explain what a p-value tells you, and what it does not.", "Statistics", "technical"),
            ("What is the difference between an INNER JOIN and a LEFT JOIN?", "SQL", "technical"),
            ("Tell me about a dataset you cleaned and the problems you found.", "Data quality", "behavioral"),
        ],
        "Medium": [
            ("Weekly active users dropped 10% last week. How do you find out why?", "Root-cause analysis", "scenario"),
            ("How would you design an A/B test for a new checkout button?", "Experimentation", "scenario"),
            ("How do you handle missing data, and how do you choose a method?", "Data preparation", "technical"),
            ("Describe a time your analysis changed a stakeholder's decision.", "Influence", "behavioral"),
        ],
        "Hard": [
            ("You cannot randomise a policy change. How would you estimate its causal impact?", "Causal inference", "scenario"),
            ("An experiment shows a significant lift, but the effect differs widely across segments. How do you decide whether to launch?", "Experimentation", "scenario"),
            ("How would you build a churn model that the business will trust and act on?", "Modelling", "scenario"),
            ("When can optimising a metric harm the business, and how would you design guardrail metrics?", "Metrics design", "technical"),
            ("Tell me about a time you had to tell leadership that the data did not support their hypothesis.", "Integrity", "behavioral"),
        ],
    },
    "Finance": {
        "Easy": [
            ("Walk me through the three main financial statements and how they connect.", "Accounting", "technical"),
            ("What is the difference between revenue and profit?", "Fundamentals", "technical"),
            ("Explain the time value of money in simple terms.", "Fundamentals", "technical"),
            ("Tell me about a time accuracy and attention to detail mattered in your work.", "Attention to detail", "behavioral"),
        ],
        "Medium": [
            ("How would you build a 12-month budget forecast for a growing department?", "Forecasting", "scenario"),
            ("Walk me through a discounted cash flow valuation and its key assumptions.", "Valuation", "technical"),
            ("Actual spend is 15% over budget mid-year. How do you analyse and report it?", "Variance analysis", "scenario"),
            ("Describe how you explained a financial result to a non-finance manager.", "Communication", "behavioral"),
        ],
        "Hard": [
            ("Two acquisition targets have similar EBITDA but different working-capital profiles. How do you compare them?", "M&A", "scenario"),
            ("How would you stress-test a portfolio for a sudden 200 basis point rate rise?", "Risk", "scenario"),
            ("A manager asks you to book revenue early to hit the quarter. What do you do?", "Ethics and compliance", "behavioral"),
            ("How do changes in a company's capital structure affect its cost of capital and valuation?", "Corporate finance", "technical"),
        ],
    },
    "Human Resources": {
        "Easy": [
            ("What are the main stages of a recruitment process?", "Recruitment", "technical"),
            ("Why is confidentiality important in HR, and how do you maintain it?", "Ethics", "technical"),
            ("What is the purpose of an onboarding programme?", "Onboarding", "technical"),
            ("Tell me about a time you helped someone resolve a workplace concern.", "Employee support", "behavioral"),
        ],
        "Medium": [
            ("A manager wants to dismiss an underperforming employee immediately. How do you advise them?", "Employee relations", "scenario"),
            ("How would you reduce time-to-hire for engineering roles without lowering quality?", "Talent acquisition", "scenario"),
            ("How do you design a fair and consistent structured interview process?", "Selection", "technical"),
            ("Describe a time you balanced an employee's needs with business priorities.", "Judgment", "behavioral"),
        ],
        "Hard": [
            ("An exit survey suggests a pattern of bias in one team. How do you investigate and act?", "Investigations", "scenario"),
            ("How would you redesign a compensation structure to close an unexplained pay gap?", "Compensation", "scenario"),
            ("How do you plan and communicate a restructuring that affects 15% of staff?", "Change management", "scenario"),
            ("Tell me about a time you had to challenge a senior leader on a people decision.", "Influence", "behavioral"),
        ],
    },
    "Business / Management": {
        "Easy": [
            ("What is the difference between a goal, an objective, and a KPI?", "Fundamentals", "technical"),
            ("How do you prioritise when everything seems urgent?", "Prioritisation", "technical"),
            ("What makes a good project plan?", "Planning", "technical"),
            ("Tell me about a team project where you took the lead.", "Leadership", "behavioral"),
        ],
        "Medium": [
            ("A key project is two weeks behind schedule. What do you do?", "Delivery", "scenario"),
            ("How would you decide whether to build a feature or buy a vendor solution?", "Decision-making", "scenario"),
            ("How do you measure the success of a product launch?", "Metrics", "technical"),
            ("Describe a time you managed conflict between two stakeholders.", "Stakeholder management", "behavioral"),
        ],
        "Hard": [
            ("Revenue is flat while costs are rising 20% a year. Build a plan to restore profitability.", "Strategy", "scenario"),
            ("How would you evaluate entering a new market with limited data?", "Market entry", "scenario"),
            ("How would you turn around an underperforming team that has lost trust in leadership?", "Leadership", "scenario"),
            ("Tell me about a decision you made with incomplete information that turned out wrong. What did you change?", "Accountability", "behavioral"),
        ],
    },
    "Communication": {
        "Easy": [
            ("How do you tailor a message for different audiences?", "Audience", "technical"),
            ("What makes a press release effective?", "Writing", "technical"),
            ("How do you decide which channel to use for an announcement?", "Channels", "technical"),
            ("Tell me about a piece of writing you are proud of and why.", "Craft", "behavioral"),
        ],
        "Medium": [
            ("You must announce an unpopular policy change to employees. How do you plan the communication?", "Internal comms", "scenario"),
            ("How do you measure whether a communication campaign worked?", "Measurement", "technical"),
            ("A subject-matter expert rejects your simplified version of their message. How do you handle it?", "Collaboration", "behavioral"),
            ("How would you build a content calendar for a product launch?", "Planning", "scenario"),
        ],
        "Hard": [
            ("A product defect is trending on social media. Walk me through your first 24 hours.", "Crisis communication", "scenario"),
            ("How do you keep a consistent brand voice across many teams and regions?", "Governance", "scenario"),
            ("A journalist has partially accurate information about a sensitive issue. How do you respond?", "Media relations", "scenario"),
            ("Tell me about a time you had to deliver a difficult message to senior leadership.", "Influence", "behavioral"),
        ],
    },
}

_BEHAVIORAL_WORDS = ("product", "ownership", "collaboration", "communication", "learning", "judgment", "impact", "reflection", "customer", "prioritisation")
_SCENARIO_WORDS = ("system", "architecture", "reliability", "api design", "distributed", "queues", "data architecture", "data and reliability")


def _role_bank_kind(topic: str) -> str:
    lowered = topic.lower()
    if any(word in lowered for word in _BEHAVIORAL_WORDS):
        return "behavioral"
    if any(word in lowered for word in _SCENARIO_WORDS):
        return "scenario"
    return "technical"


def get_questions(
    role: str,
    focus: str,
    count: int,
    domain: str | None = None,
    difficulty: str = "Medium",
) -> list[dict[str, str]]:
    """Return a varied question set for a role, focus, domain, and difficulty."""
    domain = domain if domain in DOMAINS else domain_for_role(role)
    by_level = DOMAIN_QUESTIONS[domain]
    pool: list[tuple[str, str, str]] = list(by_level.get(difficulty, by_level["Medium"]))
    if difficulty == "Medium" and role in QUESTION_BANK:
        pool = [(question, topic, _role_bank_kind(topic)) for question, topic in QUESTION_BANK[role]] + pool

    kind = FOCUS_KIND.get(focus)
    selected = [item for item in pool if item[2] == kind] if kind else list(pool)
    if len(selected) < count:
        selected = selected + [item for item in pool if item not in selected]
    if len(selected) > count:
        selected = sample(selected, count)
    return [{"question": question, "topic": topic, "kind": item_kind} for question, topic, item_kind in selected]