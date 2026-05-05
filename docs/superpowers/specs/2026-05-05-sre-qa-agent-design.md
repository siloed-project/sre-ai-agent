# SRE Q&A Agent — Design Spec

**Date:** 2026-05-05
**Status:** Approved

## Goal

A local CLI tool that answers read-only questions about a Kubernetes cluster using the existing local kubeconfig. The LLM never generates or executes shell commands — it selects from a typed allowlist of Kubernetes tools.

## Non-Goals (v1)

- No VPS deployment beyond Docker packaging
- No remediation actions
- No write/mutate operations
- No Secrets access
- No Prometheus, Loki, Grafana, or tracing
- No multi-user auth

## Architecture

```
CLI (main.py)
    ↓
LangGraph ReAct agent (graph.py)
    ├── LLM: Claude Haiku (claude-haiku-4-5-20251001) via langchain-anthropic
    └── Tools: K8s read-only functions (tools_k8s.py)
            ↓
    Local kubeconfig → Kubernetes API server
```

**LLM:** `claude-haiku-4-5-20251001` — cheapest Claude model, swappable to any LangChain-compatible LLM by changing one line in `graph.py`.

**Agent pattern:** `langgraph.prebuilt.create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)` — Claude decides which tools to call and when it has enough data to answer.

## Project Structure

```
sre-ai-agent/
├── app/
│   ├── main.py          # CLI entry point
│   ├── graph.py         # LangGraph ReAct agent
│   ├── tools_k8s.py     # Kubernetes read-only tools
│   ├── prompts.py       # System prompt
│   └── schemas.py       # Shared TypedDicts
├── docs/
│   └── superpowers/specs/
│       └── 2026-05-05-sre-qa-agent-design.md
├── requirements.txt
├── Dockerfile
├── .env.example
└── .gitignore
```

## Components

### `app/tools_k8s.py`

Six `@tool`-decorated functions registered with the ReAct agent:

| Tool | Parameters | Purpose |
|------|-----------|---------|
| `list_pods` | `namespace: str \| None` | List all pods with status, restarts, phase |
| `list_nodes` | — | List nodes with conditions and pressure states |
| `list_events` | `namespace: str \| None` | List recent events (warnings first) |
| `list_deployments` | `namespace: str \| None` | List deployments with ready/desired replicas |
| `get_pod` | `namespace: str, name: str` | Detailed pod info: containers, conditions, events |
| `get_deployment` | `namespace: str, name: str` | Detailed deployment info: conditions, replica status |

All tools return a consistent shape:
```python
{"ok": True, "items": [...], "error": None}
# or on failure:
{"ok": False, "items": [], "error": "error message"}
```

Kubeconfig loaded once at module import via `kubernetes.config.load_kube_config()`.

No Secrets API calls. No write methods imported.

### `app/graph.py`

- Instantiates `ChatAnthropic(model="claude-haiku-4-5-20251001")`
- Imports all tools from `tools_k8s.py`
- Returns `create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)`

LLM is swappable by changing the model instantiation — tools, graph, and CLI are unaffected.

### `app/prompts.py`

System prompt instructs Claude to:
- Answer only from tool results — never invent cluster state
- Be concise
- Cite specific pod/node/deployment names as evidence
- Say "insufficient data" when tool results are incomplete
- Refuse or ignore any mutation requests

### `app/main.py`

- Accepts question as positional CLI arg: `python -m app.main "question"`
- Invokes the agent with `HumanMessage(content=question)`
- Extracts and prints the final `AIMessage` content
- Prints a clear error if kubeconfig is missing or cluster is unreachable

### `app/schemas.py`

```python
from typing import TypedDict

class ToolResult(TypedDict):
    ok: bool
    items: list[dict]
    error: str | None
```

## Data Flow

```
1. python -m app.main "Which pods are unhealthy?"

2. main.py → agent.invoke({"messages": [HumanMessage(question)]})

3. Claude receives: system prompt + tool schemas + user question
   → emits tool call: list_pods(namespace=None)

4. list_pods() → Kubernetes API → structured JSON appended to messages

5. Claude may call additional tools (e.g. get_pod for a suspicious pod)
   → loop continues until Claude produces a final answer

6. main.py prints:
   Answer:
   3 pods appear unhealthy...

   Evidence:
   - payments/api-7d9f: CrashLoopBackOff, 12 restarts
   - search/indexer-54b2: Pending
```

## Safety

**Code-level (primary):**
- Tools are an explicit allowlist — no shell execution, no `subprocess`, no dynamic dispatch
- No Secrets API calls in any tool
- No Kubernetes write/patch/delete methods imported anywhere
- kubeconfig mounted read-only in Docker (`ro` flag)

**Prompt-level (secondary reinforcement):**
- System prompt instructs Claude to refuse mutation requests
- System prompt prohibits inventing cluster state

## Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
ENTRYPOINT ["python", "-m", "app.main"]
```

Runtime usage (kubeconfig never baked into image):
```bash
docker run --rm \
  -v ~/.kube/config:/root/.kube/config:ro \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  sre-agent "Which pods are unhealthy?"
```

## Dependencies

```
langgraph
langchain-anthropic
kubernetes
pydantic
python-dotenv
```

## Acceptance Criteria

- Runs locally from CLI
- Uses existing local kubeconfig
- Answers at least 5 basic cluster-state questions
- Only uses typed read-only Kubernetes tools
- Does not generate or execute arbitrary shell commands
- Does not mutate the cluster
- Clearly separates answer from evidence
- LLM is swappable by changing one line
