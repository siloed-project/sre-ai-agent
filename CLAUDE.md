# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow

Every feature must be developed on its own branch and merged via a pull request — no feature commits directly to `main`.

## Commands

```bash
# Install dependencies (uses .venv)
pip install -r requirements.txt

# Run all tests
pytest

# Run a single test file
pytest tests/test_tools_k8s.py

# Run a single test by name
pytest tests/test_tools_k8s.py::test_list_pods_all_namespaces

# Run the CLI agent locally (requires ANTHROPIC_API_KEY and ~/.kube/config)
python -m app.main "Which pods are unhealthy?"

# Run the Telegram bot
python -m app.telegram_bot

# Build Docker image
docker build -t sre-agent .

# Run via Docker
docker run --rm \
  -v ~/.kube/config:/root/.kube/config:ro \
  -e ANTHROPIC_API_KEY=your-key-here \
  sre-agent "Which pods are unhealthy?"
```

## Environment variables

- `ANTHROPIC_API_KEY` — required for both CLI and Telegram bot
- `TELEGRAM_BOT_TOKEN` — required for the Telegram bot
- `ALLOWED_CHAT_IDS` — comma-separated list of Telegram chat IDs allowed to query the bot

Copy `.env.example` to `.env` and fill in values. `app/main.py` loads `.env` via `python-dotenv`.

## Architecture

This is a **read-only SRE Q&A agent** built on LangChain + LangGraph that translates natural language questions into Kubernetes API calls.

**Request flow:**
1. Question enters via CLI (`app/main.py`) or Telegram bot (`app/telegram_bot.py`)
2. Both build the agent via `app/graph.py::build_agent()`, which wires `ChatAnthropic` (claude-haiku-4-5-20251001) together with a fixed set of K8s tools using `langchain.agents.create_agent`
3. The agent follows the structured 4-step investigation sequence defined in `app/prompts.py` — always starting with a cluster-wide scan before any namespaced lookups
4. K8s tools in `app/tools_k8s.py` call the official `kubernetes` Python client; each returns a `ToolResult` TypedDict (`ok`, `items`, `error`) defined in `app/schemas.py`

**Tool list** (all read-only): `list_pods`, `list_nodes`, `list_events`, `list_deployments`, `get_pod`, `get_deployment`, `get_pod_logs`

**Result capping:** All list tools cap at `_MAX_ITEMS = 50`, sorting unhealthy/unavailable resources first to prioritize signal within the LLM context window.

**Telegram bot specifics:** `handle_message` enforces `ALLOWED_CHAT_IDS`, wraps the synchronous agent in `asyncio.to_thread`, applies a 120-second timeout, and truncates output to Telegram's 4096-character limit. Only the `Answer:` section is sent to Telegram; the full `Investigation:` trace stays server-side.

## Related repositories

The Kubernetes cluster infrastructure (Terraform modules, Ansible, Helm charts, ArgoCD, environments) and RBAC configuration live in `../siloed-project/infra/`. Consult that repo when investigating kubeconfig setup, cluster permissions, or namespace/RBAC changes that affect what this agent can query.

## Testing

All tests use `unittest.mock` to patch the `kubernetes.client` — no live cluster required. Tools are invoked via `tool.invoke({"arg": value})` (LangChain's tool invocation interface, not direct function calls).

`pytest-asyncio` is configured with `asyncio_mode = "auto"` so async test functions work without decorators.
