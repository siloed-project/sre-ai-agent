from kubernetes import client, config
from langchain_core.tools import tool

from app.schemas import ToolResult

try:
    config.load_kube_config()
except Exception:
    pass  # Will fail at runtime if kubeconfig is unavailable


@tool
def list_pods(namespace: str | None = None) -> dict:
    """List all pods with their status, phase, and restart counts.

    Args:
        namespace: Kubernetes namespace to query. If None, lists pods across all namespaces.
    """
    try:
        v1 = client.CoreV1Api()
        if namespace:
            response = v1.list_namespaced_pod(namespace)
        else:
            response = v1.list_pod_for_all_namespaces()

        items = []
        for pod in response.items:
            restart_count = sum(
                cs.restart_count for cs in (pod.status.container_statuses or [])
            )
            items.append(
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "phase": pod.status.phase,
                    "restart_count": restart_count,
                    "conditions": [
                        {"type": c.type, "status": c.status, "reason": c.reason}
                        for c in (pod.status.conditions or [])
                    ],
                    "container_statuses": [
                        {
                            "name": cs.name,
                            "ready": cs.ready,
                            "restart_count": cs.restart_count,
                            "state": str(cs.state),
                        }
                        for cs in (pod.status.container_statuses or [])
                    ],
                }
            )
        return ToolResult(ok=True, items=items, error=None)
    except Exception as e:
        return ToolResult(ok=False, items=[], error=str(e))


@tool
def list_nodes() -> dict:
    """List all cluster nodes with their conditions and resource pressure states."""
    try:
        v1 = client.CoreV1Api()
        response = v1.list_node()

        items = []
        for node in response.items:
            items.append(
                {
                    "name": node.metadata.name,
                    "conditions": [
                        {"type": c.type, "status": c.status, "message": c.message}
                        for c in (node.status.conditions or [])
                    ],
                    "allocatable": {
                        k: str(v) for k, v in (node.status.allocatable or {}).items()
                    },
                }
            )
        return ToolResult(ok=True, items=items, error=None)
    except Exception as e:
        return ToolResult(ok=False, items=[], error=str(e))


@tool
def list_events(namespace: str | None = None) -> dict:
    """List recent Kubernetes events, with warnings listed first.

    Args:
        namespace: Kubernetes namespace to query. If None, lists events across all namespaces.
    """
    try:
        v1 = client.CoreV1Api()
        if namespace is not None:
            response = v1.list_namespaced_event(namespace)
        else:
            response = v1.list_event_for_all_namespaces()

        sorted_events = sorted(
            response.items,
            key=lambda e: e.type or "",
            reverse=True,  # "Warning" sorts before "Normal"
        )

        items = []
        for event in sorted_events:
            items.append(
                {
                    "namespace": event.metadata.namespace,
                    "name": event.metadata.name,
                    "type": event.type,
                    "reason": event.reason,
                    "message": event.message,
                    "involved_object": {
                        "kind": event.involved_object.kind,
                        "name": event.involved_object.name,
                        "namespace": event.involved_object.namespace,
                    },
                    "count": event.count,
                    "last_timestamp": str(event.last_timestamp),
                }
            )
        return ToolResult(ok=True, items=items, error=None)
    except Exception as e:
        return ToolResult(ok=False, items=[], error=str(e))


@tool
def list_deployments(namespace: str | None = None) -> dict:
    """List deployments with their desired vs ready replica counts.

    Args:
        namespace: Kubernetes namespace to query. If None, lists deployments across all namespaces.
    """
    try:
        apps_v1 = client.AppsV1Api()
        if namespace is not None:
            response = apps_v1.list_namespaced_deployment(namespace)
        else:
            response = apps_v1.list_deployment_for_all_namespaces()

        items = []
        for dep in response.items:
            items.append(
                {
                    "name": dep.metadata.name,
                    "namespace": dep.metadata.namespace,
                    "desired_replicas": dep.spec.replicas,
                    "ready_replicas": dep.status.ready_replicas or 0,
                    "available_replicas": dep.status.available_replicas or 0,
                    "conditions": [
                        {"type": c.type, "status": c.status, "message": c.message}
                        for c in (dep.status.conditions or [])
                    ],
                }
            )
        return ToolResult(ok=True, items=items, error=None)
    except Exception as e:
        return ToolResult(ok=False, items=[], error=str(e))
