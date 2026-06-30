# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Coding Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. **Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## Workflow

Every feature must be developed on its own branch and merged via a pull request — no feature commits directly to `main`. Merging to `main` triggers automatic deployment to the VPS via GitHub Actions — treat `main` as a live deploy target.

When making any change, update the relevant documentation: `README.md` for user-facing behaviour (CLI usage, Docker commands, new env vars), and this file for architecture or development workflow changes.

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
- `MEMORY_DB_PATH` — path to the SQLite file for conversation memory (default: `/var/lib/sre-agent/memory.db`); directory is created automatically on first run

Copy `.env.example` to `.env` and fill in values. `app/main.py` loads `.env` via `python-dotenv`.

## Architecture

This is a **read-only SRE Q&A agent** built on LangChain + LangGraph that translates natural language questions into Kubernetes API calls.

**Request flow:**
1. Question enters via CLI (`app/main.py`) or Telegram bot (`app/telegram_bot.py`)
2. Both build the agent via `app/graph.py::build_agent()`, which wires `ChatAnthropic` (claude-haiku-4-5-20251001) together with a fixed set of K8s tools using `langgraph.prebuilt.create_react_agent`
3. The agent follows the structured 4-step investigation sequence defined in `app/prompts.py` — always starting with a cluster-wide scan before any namespaced lookups
4. K8s tools in `app/tools_k8s.py` call the official `kubernetes` Python client; each returns a `ToolResult` TypedDict (`ok`, `items`, `error`) defined in `app/schemas.py`

**Tool list** (all read-only): `list_pods`, `list_nodes`, `list_events`, `list_deployments`, `get_pod`, `get_deployment`, `get_pod_logs`

**Result capping:** All list tools cap at `_MAX_ITEMS = 50`, sorting unhealthy/unavailable resources first to prioritize signal within the LLM context window.

**Conversation memory:** The Telegram bot uses a `SqliteSaver` checkpointer (from `langgraph-checkpoint-sqlite`) keyed by `str(chat_id)` — each Telegram chat has its own persistent thread that survives bot restarts. The CLI is stateless; each invocation is independent. The SQLite file lives at `MEMORY_DB_PATH` (default `/var/lib/sre-agent/memory.db`), outside the git working directory so it survives `git reset --hard` deploys.

**Telegram bot specifics:** `handle_message` enforces `ALLOWED_CHAT_IDS`, wraps the synchronous agent in `asyncio.to_thread` (with `check_same_thread=False` on the SQLite connection), applies a 120-second timeout, and truncates output to Telegram's 4096-character limit. Only the `Answer:` section is sent to Telegram; the full `Investigation:` trace stays server-side.

## Related repositories

The Kubernetes cluster infrastructure (Terraform modules, Ansible, Helm charts, ArgoCD, environments) and RBAC configuration live in `../siloed-project/infra/`. Consult that repo when investigating kubeconfig setup, cluster permissions, or namespace/RBAC changes that affect what this agent can query.

## Testing

All tests use `unittest.mock` to patch the `kubernetes.client` — no live cluster required. Tools are invoked via `tool.invoke({"arg": value})` (LangChain's tool invocation interface, not direct function calls).

`pytest-asyncio` is configured with `asyncio_mode = "auto"` so async test functions work without decorators.
