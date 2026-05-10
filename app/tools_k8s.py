from kubernetes import client, config
from langchain_core.tools import tool

from app.schemas import ToolResult

try:
    config.load_kube_config()
except Exception:
    pass  # Will fail at runtime if kubeconfig is unavailable

_MAX_ITEMS = 50  # cap per tool call to stay within LLM context limits


@tool
def list_pods(namespace: str | None = None) -> dict:
    """List all pods with their status, phase, and restart counts.

    Args:
        namespace: Kubernetes namespace to query. If None, lists pods across all namespaces.
    """
    try:
        v1 = client.CoreV1Api()
        if namespace is not None:
            response = v1.list_namespaced_pod(namespace)
        else:
            response = v1.list_pod_for_all_namespaces()

        def _pod_priority(pod):
            # unhealthy phases first, then by restart count descending
            phase = pod.status.phase or ""
            healthy = phase in ("Running", "Succeeded")
            restarts = sum(cs.restart_count for cs in (pod.status.container_statuses or []))
            return (healthy, -restarts)

        sorted_pods = sorted(response.items, key=_pod_priority)

        items = []
        for pod in sorted_pods[:_MAX_ITEMS]:
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
        total = len(response.items)
        result = ToolResult(ok=True, items=items, error=None)
        if total > _MAX_ITEMS:
            result["error"] = f"showing {_MAX_ITEMS} of {total} pods (prioritised unhealthy and high-restart)"
        return result
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
        for event in sorted_events[:_MAX_ITEMS]:
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
        total = len(sorted_events)
        result = ToolResult(ok=True, items=items, error=None)
        if total > _MAX_ITEMS:
            result["error"] = f"showing {_MAX_ITEMS} of {total} events (warnings first)"
        return result
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

        def _dep_priority(dep):
            # unavailable deployments first
            desired = dep.spec.replicas or 0
            ready = dep.status.ready_replicas or 0
            return ready >= desired

        sorted_deps = sorted(response.items, key=_dep_priority)

        items = []
        for dep in sorted_deps[:_MAX_ITEMS]:
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
        total = len(response.items)
        result = ToolResult(ok=True, items=items, error=None)
        if total > _MAX_ITEMS:
            result["error"] = f"showing {_MAX_ITEMS} of {total} deployments (unavailable first)"
        return result
    except Exception as e:
        return ToolResult(ok=False, items=[], error=str(e))


@tool
def get_pod(namespace: str, name: str) -> dict:
    """Get detailed information about a specific pod including container states and conditions.

    Args:
        namespace: Kubernetes namespace where the pod lives.
        name: Name of the pod.
    """
    try:
        v1 = client.CoreV1Api()
        pod = v1.read_namespaced_pod(name=name, namespace=namespace)

        item = {
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "phase": pod.status.phase,
            "node_name": pod.spec.node_name,
            "host_ip": pod.status.host_ip,
            "pod_ip": pod.status.pod_ip,
            "conditions": [
                {
                    "type": c.type,
                    "status": c.status,
                    "reason": c.reason,
                    "message": c.message,
                }
                for c in (pod.status.conditions or [])
            ],
            "container_statuses": [
                {
                    "name": cs.name,
                    "ready": cs.ready,
                    "restart_count": cs.restart_count,
                    "state": str(cs.state),
                    "last_state": str(cs.last_state),
                }
                for cs in (pod.status.container_statuses or [])
            ],
        }
        return ToolResult(ok=True, items=[item], error=None)
    except Exception as e:
        return ToolResult(ok=False, items=[], error=str(e))


@tool
def get_deployment(namespace: str, name: str) -> dict:
    """Get detailed information about a specific deployment including replica status and conditions.

    Args:
        namespace: Kubernetes namespace where the deployment lives.
        name: Name of the deployment.
    """
    try:
        apps_v1 = client.AppsV1Api()
        dep = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)

        item = {
            "name": dep.metadata.name,
            "namespace": dep.metadata.namespace,
            "desired_replicas": dep.spec.replicas,
            "ready_replicas": dep.status.ready_replicas or 0,
            "available_replicas": dep.status.available_replicas or 0,
            "updated_replicas": dep.status.updated_replicas or 0,
            "selector": dep.spec.selector.match_labels,
            "conditions": [
                {
                    "type": c.type,
                    "status": c.status,
                    "message": c.message,
                    "reason": c.reason,
                }
                for c in (dep.status.conditions or [])
            ],
        }
        return ToolResult(ok=True, items=[item], error=None)
    except Exception as e:
        return ToolResult(ok=False, items=[], error=str(e))


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
        if not container_names:
            return ToolResult(ok=False, items=[], error="Pod has no containers in spec.")
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
            if container is not None and container != container_names[0]:
                return ToolResult(
                    ok=False,
                    items=[],
                    error=f"Container '{container}' not found. Valid containers: [{container_names[0]}].",
                )
            target = container_names[0]

        item = _fetch(target)
        if "error" in item:
            return ToolResult(ok=False, items=[], error=item["error"])
        return ToolResult(ok=True, items=[item], error=None)

    except Exception as e:
        return ToolResult(ok=False, items=[], error=str(e))
