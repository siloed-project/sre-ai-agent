# `get_pod_logs` Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `get_pod_logs` tool to the SRE agent so it can fetch pod container logs when investigating cluster issues.

**Architecture:** One new `@tool` function in `app/tools_k8s.py` using the existing `CoreV1Api` client. The tool reads the pod spec first to enumerate containers, applies routing logic, then calls `read_namespaced_pod_log`. Wired into `app/graph.py` the same way all other tools are.

**Tech Stack:** `kubernetes` Python client, `langchain_core.tools.tool`, `pytest` with `unittest.mock`

---

## File Map

| File | Change |
|------|--------|
| `app/tools_k8s.py` | Add `get_pod_logs` function |
| `app/graph.py` | Import `get_pod_logs`, append to `TOOLS` |
| `tests/test_tools_k8s.py` | Add `_make_pod_with_containers` helper + 9 test cases |

---

### Task 1: Write all failing tests for `get_pod_logs`

**Files:**
- Modify: `tests/test_tools_k8s.py`

- [ ] **Step 1: Add the `_make_pod_with_containers` helper and all 9 tests**

Append to the bottom of `tests/test_tools_k8s.py`:

```python
# --- get_pod_logs ---

def _make_pod_with_containers(container_names):
    pod = MagicMock()
    containers = []
    for n in container_names:
        c = MagicMock()
        c.name = n
        containers.append(c)
    pod.spec.containers = containers
    return pod


@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_logs_single_container_no_name(mock_api_cls):
    from app.tools_k8s import get_pod_logs

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_pod.return_value = _make_pod_with_containers(["main"])
    mock_api.read_namespaced_pod_log.return_value = "line1\nline2\nline3"

    result = get_pod_logs.invoke({"namespace": "default", "name": "my-pod"})

    assert result["ok"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["container"] == "main"
    assert result["items"][0]["lines_returned"] == 3
    assert result["items"][0]["logs"] == "line1\nline2\nline3"
    assert result["items"][0]["previous"] is False
    mock_api.read_namespaced_pod_log.assert_called_once_with(
        name="my-pod", namespace="default", container="main", tail_lines=100, previous=False
    )


@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_logs_multi_container_no_name_returns_error(mock_api_cls):
    from app.tools_k8s import get_pod_logs

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_pod.return_value = _make_pod_with_containers(["main", "sidecar"])

    result = get_pod_logs.invoke({"namespace": "default", "name": "my-pod"})

    assert result["ok"] is False
    assert result["items"] == []
    assert "main" in result["error"]
    assert "sidecar" in result["error"]
    mock_api.read_namespaced_pod_log.assert_not_called()


@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_logs_multi_container_valid_name(mock_api_cls):
    from app.tools_k8s import get_pod_logs

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_pod.return_value = _make_pod_with_containers(["main", "sidecar"])
    mock_api.read_namespaced_pod_log.return_value = "sidecar log"

    result = get_pod_logs.invoke({"namespace": "default", "name": "my-pod", "container": "sidecar"})

    assert result["ok"] is True
    assert result["items"][0]["container"] == "sidecar"
    mock_api.read_namespaced_pod_log.assert_called_once_with(
        name="my-pod", namespace="default", container="sidecar", tail_lines=100, previous=False
    )


@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_logs_multi_container_invalid_name_returns_error(mock_api_cls):
    from app.tools_k8s import get_pod_logs

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_pod.return_value = _make_pod_with_containers(["main", "sidecar"])

    result = get_pod_logs.invoke({"namespace": "default", "name": "my-pod", "container": "nonexistent"})

    assert result["ok"] is False
    assert result["items"] == []
    assert "main" in result["error"]
    assert "sidecar" in result["error"]


@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_logs_all_containers(mock_api_cls):
    from app.tools_k8s import get_pod_logs

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_pod.return_value = _make_pod_with_containers(["main", "sidecar"])
    mock_api.read_namespaced_pod_log.side_effect = ["main logs", "sidecar logs"]

    result = get_pod_logs.invoke({"namespace": "default", "name": "my-pod", "all_containers": True})

    assert result["ok"] is True
    assert len(result["items"]) == 2
    containers = {item["container"] for item in result["items"]}
    assert containers == {"main", "sidecar"}


@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_logs_previous_flag(mock_api_cls):
    from app.tools_k8s import get_pod_logs

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_pod.return_value = _make_pod_with_containers(["main"])
    mock_api.read_namespaced_pod_log.return_value = "old crash log"

    result = get_pod_logs.invoke({"namespace": "default", "name": "my-pod", "previous": True})

    assert result["ok"] is True
    assert result["items"][0]["previous"] is True
    mock_api.read_namespaced_pod_log.assert_called_once_with(
        name="my-pod", namespace="default", container="main", tail_lines=100, previous=True
    )


@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_logs_tail_lines_capped_at_200(mock_api_cls):
    from app.tools_k8s import get_pod_logs

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_pod.return_value = _make_pod_with_containers(["main"])
    mock_api.read_namespaced_pod_log.return_value = ""

    get_pod_logs.invoke({"namespace": "default", "name": "my-pod", "tail_lines": 500})

    mock_api.read_namespaced_pod_log.assert_called_once_with(
        name="my-pod", namespace="default", container="main", tail_lines=200, previous=False
    )


@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_logs_empty_logs(mock_api_cls):
    from app.tools_k8s import get_pod_logs

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_pod.return_value = _make_pod_with_containers(["main"])
    mock_api.read_namespaced_pod_log.return_value = ""

    result = get_pod_logs.invoke({"namespace": "default", "name": "my-pod"})

    assert result["ok"] is True
    assert result["items"][0]["logs"] == ""
    assert result["items"][0]["lines_returned"] == 0


@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_logs_api_error(mock_api_cls):
    from app.tools_k8s import get_pod_logs

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_pod.side_effect = Exception("pod not found")

    result = get_pod_logs.invoke({"namespace": "default", "name": "ghost"})

    assert result["ok"] is False
    assert result["items"] == []
    assert "pod not found" in result["error"]


@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_logs_all_containers_previous_partial_failure(mock_api_cls):
    """all_containers=True + previous=True: one container has no previous instance,
    the other succeeds. Overall ok=True because at least one item succeeded."""
    from app.tools_k8s import get_pod_logs

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_pod.return_value = _make_pod_with_containers(["main", "sidecar"])
    mock_api.read_namespaced_pod_log.side_effect = [
        "old crash log",               # main succeeds
        Exception("no previous log"),  # sidecar has no previous instance
    ]

    result = get_pod_logs.invoke({
        "namespace": "default", "name": "my-pod",
        "previous": True, "all_containers": True,
    })

    assert result["ok"] is True  # at least one succeeded
    assert len(result["items"]) == 2
    by_container = {item["container"]: item for item in result["items"]}
    assert "error" not in by_container["main"]
    assert by_container["main"]["logs"] == "old crash log"
    assert "error" in by_container["sidecar"]
```

- [ ] **Step 2: Run tests to confirm they all fail**

```bash
cd /home/petrosxen/Documents/sre-ai-agent && .venv/bin/pytest tests/test_tools_k8s.py -k "get_pod_logs" -v 2>&1 | tail -20
```

Expected: all 10 tests fail with `ImportError` or `AttributeError` — `get_pod_logs` does not exist yet.

---

### Task 2: Implement `get_pod_logs` in `tools_k8s.py`

**Files:**
- Modify: `app/tools_k8s.py`

- [ ] **Step 1: Append the implementation to `app/tools_k8s.py`**

Add after the `get_deployment` function at the end of the file:

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
    """Fetch logs from a pod's container(s).

    Args:
        namespace: Kubernetes namespace where the pod lives.
        name: Name of the pod.
        container: Container name. Required when the pod has multiple containers,
            unless all_containers=True. Ignored when all_containers=True.
        tail_lines: Number of log lines to fetch (default 100, capped at 200).
        previous: If True, fetch logs from the previous (crashed/terminated) container instance.
        all_containers: If True, fetch logs from every container in the pod.
    """
    try:
        v1 = client.CoreV1Api()
        pod = v1.read_namespaced_pod(name=name, namespace=namespace)
        container_names = [c.name for c in pod.spec.containers]
        capped = min(tail_lines, 200)

        def _fetch(cname: str) -> dict:
            try:
                logs = v1.read_namespaced_pod_log(
                    name=name,
                    namespace=namespace,
                    container=cname,
                    tail_lines=capped,
                    previous=previous,
                )
                return {
                    "container": cname,
                    "previous": previous,
                    "lines_returned": len(logs.splitlines()),
                    "logs": logs,
                }
            except Exception as e:
                return {
                    "container": cname,
                    "previous": previous,
                    "lines_returned": 0,
                    "logs": "",
                    "error": str(e),
                }

        if all_containers:
            items = [_fetch(cname) for cname in container_names]
            ok = any("error" not in item for item in items)
            return ToolResult(ok=ok, items=items, error=None)

        if len(container_names) > 1:
            if container is None:
                names_str = ", ".join(container_names)
                return ToolResult(
                    ok=False,
                    items=[],
                    error=f"Pod has multiple containers: [{names_str}]. Specify container=<name> or all_containers=True.",
                )
            if container not in container_names:
                names_str = ", ".join(container_names)
                return ToolResult(
                    ok=False,
                    items=[],
                    error=f"Container '{container}' not found. Valid containers: [{names_str}].",
                )
            target = container
        else:
            target = container_names[0]

        item = _fetch(target)
        if "error" in item:
            return ToolResult(ok=False, items=[], error=item["error"])
        return ToolResult(ok=True, items=[item], error=None)

    except Exception as e:
        return ToolResult(ok=False, items=[], error=str(e))
```

- [ ] **Step 2: Run the new tests to confirm they all pass**

```bash
cd /home/petrosxen/Documents/sre-ai-agent && .venv/bin/pytest tests/test_tools_k8s.py -k "get_pod_logs" -v 2>&1 | tail -20
```

Expected: all 10 tests PASS.

- [ ] **Step 3: Run the full test suite to confirm no regressions**

```bash
cd /home/petrosxen/Documents/sre-ai-agent && .venv/bin/pytest -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
cd /home/petrosxen/Documents/sre-ai-agent && git add app/tools_k8s.py tests/test_tools_k8s.py && git commit -m "feat: add get_pod_logs tool with multi-container and previous-instance support"
```

---

### Task 3: Wire `get_pod_logs` into the agent

**Files:**
- Modify: `app/graph.py`

- [ ] **Step 1: Update the import and TOOLS list in `app/graph.py`**

Replace the current content of `app/graph.py` with:

```python
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic

from app.prompts import SYSTEM_PROMPT
from app.tools_k8s import (
    get_deployment,
    get_pod,
    get_pod_logs,
    list_deployments,
    list_events,
    list_nodes,
    list_pods,
)

TOOLS = [list_pods, list_nodes, list_events, list_deployments, get_pod, get_deployment, get_pod_logs]


def build_agent():
    llm = ChatAnthropic(model="claude-haiku-4-5-20251001")
    return create_agent(llm, TOOLS, system_prompt=SYSTEM_PROMPT)
```

- [ ] **Step 2: Run the full test suite one final time**

```bash
cd /home/petrosxen/Documents/sre-ai-agent && .venv/bin/pytest -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
cd /home/petrosxen/Documents/sre-ai-agent && git add app/graph.py && git commit -m "feat: register get_pod_logs in agent tool list"
```
