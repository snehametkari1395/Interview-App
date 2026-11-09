# Architecture

Fieldnotes is a Streamlit application backed by OpenRouter. The original one-shot features (practice room, job description, structured output, interviewer guide) are preserved. The advanced features add a LangChain/LangGraph layer and a ChromaDB vector store on top of the same security, model-configuration, and cost modules.

## Components

```mermaid
flowchart TB
    subgraph UI["Streamlit UI (app.py + app_pages/, grouped navigation)"]
        direction LR
        P["Practice<br/>Practice room · Interview chat · Job description<br/>Structured output · Interviewer guide"]
        D["Developer tools<br/>Model settings · Model lab<br/>Question memory · Security lab · App review"]
    end

    subgraph LC["LangChain / LangGraph layer (interview_app/chains/)"]
        G["interview_graph.py<br/>LangGraph state machine"]
        W["workflows.py<br/>chains A–E + de-duplicated generation"]
        B["base.py<br/>StructuredChain (LCEL) · SafeStream · ReplyStream"]
        L["llm.py<br/>ChatOpenRouter + fallbacks"]
    end

    subgraph CORE["Shared core (interview_app/)"]
        PR["prompts.py · chain_prompts.py<br/>security rules + canary"]
        SC["schemas.py · chain_schemas.py<br/>JSON Schemas, trim + validate"]
        SG["security_guard.py<br/>sanitise · injection rules · output cleaning"]
        MC["model_config.py<br/>capability-aware params"]
        PRC["pricing.py<br/>estimated + actual cost"]
        OR["openrouter.py<br/>direct client: retries, failover, catalog"]
    end

    subgraph DATA["Data"]
        VS["vectorstore.py<br/>ChromaDB (data/chroma) + all-MiniLM-L6-v2 (local ONNX)"]
    end

    API[("OpenRouter API<br/>chat completions · models · key")]

    P --> G
    P --> W
    P --> OR
    D --> MC
    D --> VS
    G --> W --> B --> L --> API
    W --> VS
    B --> PR
    B --> SC
    B --> SG
    B --> PRC
    L --> MC
    OR --> API
    OR --> MC
```

- **Original features** call `openrouter.py` directly (retries, `require_parameters` routing, failover, cost).
- **Advanced features** go through LangChain: `ChatOpenRouter` from `langchain-openrouter`, configured from the same `build_request_body`, so both paths send identical, capability-filtered parameters.
- Every model output, on either path, is parsed, schema-validated, and sanitised before display.

## LangChain chain pipeline (every chain A–E)

```mermaid
flowchart LR
    I["payload (dict)"] --> GU["guard<br/>RunnableLambda"]
    GU -->|"sanitise, length-check,<br/>block score dictation,<br/>attach input_flags"| PT["ChatPromptTemplate<br/>system = trusted prompt<br/>human = JSON data"]
    PT --> M["ChatOpenRouter<br/>json_schema strict"]
    M -->|"503 no provider"| M2["same model,<br/>no require_parameters"]
    M -->|"transient / unavailable"| M3["fallback model"]
    M --> V["validate<br/>RunnableLambda"]
    M2 --> V
    M3 --> V
    V -->|"canary check · JSON parse ·<br/>trim overflow · JSON Schema ·<br/>content rules · sanitise"| O["ChainOutput<br/>data · usage · billed cost · repairs"]
```

## Interview workflow (LangGraph)

```mermaid
stateDiagram-v2
    [*] --> route
    route --> opening: nothing asked yet
    route --> evaluate: answer pending
    route --> plan_next: question still needed (retry)
    route --> summarize: finish requested / limit reached
    opening --> [*]: first question (chain B + de-duplication)
    evaluate --> adapt: chain C score
    adapt --> plan_next: more questions
    adapt --> summarize: limit reached or finish requested
    plan_next --> [*]: chain D follow-up or new topic (de-duplicated)
    summarize --> [*]: chain E summary + learning plan
```

One graph invocation per user action. State is checkpointed per interview thread with `InMemorySaver` (browser session only, never written to disk), which provides resume. The Streamlit page runs the graph in a worker thread and streams the interviewer's feedback (chain C result → streamed reply) while chain D chooses the next question.

## Data and context flow per chat turn

| Step | Sent to the model | Not sent |
| --- | --- | --- |
| Chain C (evaluate) | current question, the answer, expected answer points, job context | earlier turns |
| Streamed reply | the question and a compact evaluation | the answer itself, history |
| Chain D (next question) | latest turn (answer ≤2,000 chars), previous turn (≤600 chars), one-line memories of older turns, topics covered, asked questions to avoid | full transcript |
| Chain E (summary) | compact per-turn records (scores, strengths, weaknesses, missing concepts) | answers, transcript |

The UI transcript is stored in graph state for display and resume, but no node ever sends it to the model.

## Security boundaries

1. **Input**: `security_guard` (deterministic) at the UI boundary and again as the first step of every chain.
2. **Prompt**: trusted catalog values only in system prompts; untrusted text only as JSON data; canary token.
3. **Output**: canary rejection, JSON Schema validation, benign-overflow trimming, string sanitisation; streamed text is sanitised incrementally (`SafeStream`).
4. **Data at rest**: only generated question text and non-sensitive metadata are stored in ChromaDB; interviews live in memory for the browser session.
5. **Secrets**: the API key stays server-side, is never rendered or logged, and error messages are mapped to fixed text.
