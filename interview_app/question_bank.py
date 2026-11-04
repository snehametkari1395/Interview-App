"""Curated interview questions for the supported technical roles."""

from random import sample

ROLES = [
    "Full-Stack Developer",
    "Product Engineer",
    "AI Engineer",
    "Frontend Developer",
    "Backend Developer",
    "Software Engineer",
]

FOCUSES = ["Balanced", "Technical depth", "System design", "Behavioral"]

QUESTION_BANK = {
    "Full-Stack Developer": [
        ("How would you design a feature that updates the UI optimistically while keeping the server as the source of truth?", "Frontend and API design"),
        ("Walk through how you would investigate a slow page that makes several API calls.", "Performance"),
        ("How would you model permissions for a team-based application across the frontend and backend?", "Security and data modeling"),
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
        ("How would you prioritize reliability work against a feature commitment?", "Prioritization"),
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


def get_questions(role: str, focus: str, count: int) -> list[dict[str, str]]:
    """Return a varied question set for a role and optional interview focus."""
    questions = QUESTION_BANK.get(role, QUESTION_BANK["Software Engineer"])
    if focus == "System design":
        filtered = [item for item in questions if any(word in item[1].lower() for word in ("system", "architecture", "data", "reliability", "api"))]
    elif focus == "Behavioral":
        filtered = [item for item in questions if any(word in item[1].lower() for word in ("product", "ownership", "collaboration", "communication", "learning", "judgment", "impact"))]
    elif focus == "Technical depth":
        filtered = [item for item in questions if any(word in item[1].lower() for word in ("technical", "performance", "testing", "debugging", "security", "evaluation", "data", "api"))]
    else:
        filtered = questions

    selected = filtered or questions
    if len(selected) < count:
        selected = selected + [item for item in questions if item not in selected]
    if len(selected) > count:
        selected = sample(selected, count)
    return [{"question": question, "topic": topic} for question, topic in selected]