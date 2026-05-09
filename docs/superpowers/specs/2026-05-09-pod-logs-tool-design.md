# Design: `get_pod_logs` tool

**Date:** 2026-05-09
**Status:** Approved

## Problem

The SRE agent can identify unhealthy pods (via `list_pods`, `get_pod`, `list_events`) but has no way to read what those pods are actually logging. Log content is often the fastest path to root cause — especially for crash-looping or OOMKilled containers.

## Tool Signature

```python
@tool
def get_pod_logs(
    namespace: str,
    name: str,
    container: str | None = None,
    tail_lines: int = 100,
    previous: bool = False,
    all_containers: bool = False,
) -> dict:
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `namespace` | `str` | required | Kubernetes namespace of the pod |
| `name` | `str` | required | Pod name |
| `container` | `str \| None` | `None` | Container name. Required when pod has multiple containers (unless `all_containers=True`) |
| `tail_lines` | `int` | `100` | Number of log lines to fetch. Capped internally at 200 regardless of input |
| `previous` | `bool` | `False` | If `True`, fetch logs from the previous (crashed/terminated) container instance |
| `all_containers` | `bool` | `False` | If `True`, fetch logs from every container in the pod. Overrides `container` |

## Multi-Container Routing Logic

The tool reads the pod spec first to enumerate containers, then routes as follows:

1. **Single container, `container=None`** — fetch that container's logs directly.
2. **Multiple containers, `all_containers=True`** — fetch each container in sequence; return one item per container.
3. **Multiple containers, explicit `container="<name>"`** — validate name is in the list, fetch it.
4. **Multiple containers, `container=None`, `all_containers=False`** — return `ok=False` with error:
   `"Pod has multiple containers: [main, sidecar, proxy]. Specify container=<name> or all_containers=True."`

## Return Shape

`ToolResult` with `items` containing one entry per container fetched:

```python
{
    "container": "main",
    "previous": False,
    "lines_returned": 87,
    "logs": "<newline-joined log text>"
}
```

`lines_returned` lets the agent know whether output was truncated relative to `tail_lines`.

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Pod not found | `ok=False`, Kubernetes API exception message |
| Container name invalid | `ok=False`, error lists valid container names |
| `previous=True` but no previous instance | `ok=False`, `"No previous container instance found for <name>"` |
| Empty logs | `ok=True`, `logs=""`, `lines_returned=0` |
| `tail_lines > 200` | Silently clamped to 200; no error |
| Any other API exception | `ok=False`, exception message |

## Where It Wires In

- **`app/tools_k8s.py`** — new `get_pod_logs` function added alongside existing tools.
- **`app/graph.py`** — `get_pod_logs` imported and appended to `TOOLS`. No other changes.
- **`app/prompts.py`** — no changes; the agent discovers the tool from its docstring.

## Tests (`tests/test_tools_k8s.py`)

| Test | Scenario |
|------|----------|
| `test_get_pod_logs_single_container_no_name` | Single container pod, `container=None` → succeeds |
| `test_get_pod_logs_multi_container_no_name_returns_error` | Multi-container pod, `container=None`, `all_containers=False` → `ok=False` with container list |
| `test_get_pod_logs_multi_container_valid_name` | Multi-container pod, valid `container` specified → succeeds |
| `test_get_pod_logs_all_containers` | `all_containers=True` → one item per container |
| `test_get_pod_logs_previous_flag` | `previous=True` → flag passed to Kubernetes API |
| `test_get_pod_logs_tail_lines_capped` | `tail_lines=500` → API called with 200 |
| `test_get_pod_logs_api_error` | API raises exception → `ok=False` |
| `test_get_pod_logs_empty_logs` | API returns empty string → `ok=True`, `logs=""`, `lines_returned=0` |
