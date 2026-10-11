from datetime import datetime, timezone

from kubernetes import client
from langchain_core.tools import tool
from langgraph.types import interrupt

from app.schemas import ToolResult

_REQUEST_TIMEOUT = (5, 15)
_PROTECTED_NAMESPACES = frozenset({"kube-system", "kube-public", "kube-node-lease"})


def _approved(payload: dict) -> bool:
    decision = interrupt(payload)
    return decision is True or (
        isinstance(decision, dict) and decision.get("approved") is True
    )


def _namespace_error(namespace: str) -> ToolResult | None:
    if namespace in _PROTECTED_NAMESPACES:
        return ToolResult(
            ok=False,
            items=[],
            error=f"Mutations in protected namespace '{namespace}' are not allowed.",
        )
    return None


@tool
def restart_deployment(namespace: str, name: str) -> dict:
    """Request approval, then restart a Kubernetes deployment.

    Use only when a deployment restart is a justified remediation. The operation
    never executes until the Telegram user explicitly approves it.
    """
    if error := _namespace_error(namespace):
        return error

    payload = {
        "kind": "mutation_approval",
        "action": "restart_deployment",
        "summary": f"Restart deployment {namespace}/{name}",
        "parameters": {"namespace": namespace, "name": name},
    }
    if not _approved(payload):
        return ToolResult(ok=False, items=[], error="Mutation rejected by the user.")

    try:
        restarted_at = datetime.now(timezone.utc).isoformat()
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": restarted_at,
                        }
                    }
                }
            }
        }
        client.AppsV1Api().patch_namespaced_deployment(
            name=name,
            namespace=namespace,
            body=body,
            _request_timeout=_REQUEST_TIMEOUT,
        )
        return ToolResult(
            ok=True,
            items=[{"namespace": namespace, "name": name, "restarted_at": restarted_at}],
            error=None,
        )
    except Exception as exc:
        return ToolResult(ok=False, items=[], error=str(exc))


@tool
def scale_deployment(namespace: str, name: str, replicas: int) -> dict:
    """Request approval, then scale a Kubernetes deployment to 0-20 replicas."""
    if replicas < 0 or replicas > 20:
        return ToolResult(ok=False, items=[], error="replicas must be between 0 and 20")
    if error := _namespace_error(namespace):
        return error

    payload = {
        "kind": "mutation_approval",
        "action": "scale_deployment",
        "summary": f"Scale deployment {namespace}/{name} to {replicas} replicas",
        "parameters": {"namespace": namespace, "name": name, "replicas": replicas},
    }
    if not _approved(payload):
        return ToolResult(ok=False, items=[], error="Mutation rejected by the user.")

    try:
        client.AppsV1Api().patch_namespaced_deployment_scale(
            name=name,
            namespace=namespace,
            body={"spec": {"replicas": replicas}},
            _request_timeout=_REQUEST_TIMEOUT,
        )
        return ToolResult(
            ok=True,
            items=[{"namespace": namespace, "name": name, "replicas": replicas}],
            error=None,
        )
    except Exception as exc:
        return ToolResult(ok=False, items=[], error=str(exc))


@tool
def delete_pod(namespace: str, name: str) -> dict:
    """Request approval, then delete a pod so its controller can recreate it."""
    if error := _namespace_error(namespace):
        return error

    payload = {
        "kind": "mutation_approval",
        "action": "delete_pod",
        "summary": f"Delete pod {namespace}/{name}",
        "parameters": {"namespace": namespace, "name": name},
    }
    if not _approved(payload):
        return ToolResult(ok=False, items=[], error="Mutation rejected by the user.")

    try:
        client.CoreV1Api().delete_namespaced_pod(
            name=name,
            namespace=namespace,
            _request_timeout=_REQUEST_TIMEOUT,
        )
        return ToolResult(
            ok=True,
            items=[{"namespace": namespace, "name": name, "deleted": True}],
            error=None,
        )
    except Exception as exc:
        return ToolResult(ok=False, items=[], error=str(exc))
