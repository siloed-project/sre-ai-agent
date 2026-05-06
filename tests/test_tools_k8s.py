from unittest.mock import MagicMock, patch


# --- Helpers ---

def _make_pod(name, namespace, phase, restart_count=0, ready=True):
    pod = MagicMock()
    pod.metadata.name = name
    pod.metadata.namespace = namespace
    pod.status.phase = phase
    pod.status.conditions = []
    cs = MagicMock()
    cs.name = "main"
    cs.ready = ready
    cs.restart_count = restart_count
    cs.state = MagicMock()
    cs.last_state = MagicMock()
    pod.status.container_statuses = [cs]
    return pod


def _make_node(name, conditions=None):
    node = MagicMock()
    node.metadata.name = name
    node.status.conditions = conditions or []
    node.status.allocatable = {"cpu": "4", "memory": "8Gi"}
    return node


def _make_condition(type_, status, message=""):
    cond = MagicMock()
    cond.type = type_
    cond.status = status
    cond.message = message
    return cond


# --- list_pods ---

@patch("app.tools_k8s.client.CoreV1Api")
def test_list_pods_all_namespaces(mock_api_cls):
    from app.tools_k8s import list_pods

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.list_pod_for_all_namespaces.return_value.items = [
        _make_pod("api-7d9f", "payments", "Running", restart_count=12),
        _make_pod("indexer-54b2", "search", "Pending", ready=False),
    ]

    result = list_pods.invoke({"namespace": None})

    assert result["ok"] is True
    assert len(result["items"]) == 2
    # Pending (unhealthy) pod sorts first; Running pod with restarts sorts second
    by_name = {i["name"]: i for i in result["items"]}
    assert by_name["api-7d9f"]["restart_count"] == 12
    assert by_name["indexer-54b2"]["phase"] == "Pending"
    assert result["items"][0]["phase"] == "Pending"  # unhealthy comes first
    mock_api.list_pod_for_all_namespaces.assert_called_once()


@patch("app.tools_k8s.client.CoreV1Api")
def test_list_pods_specific_namespace(mock_api_cls):
    from app.tools_k8s import list_pods

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.list_namespaced_pod.return_value.items = [
        _make_pod("worker-1", "default", "Running"),
    ]

    result = list_pods.invoke({"namespace": "default"})

    assert result["ok"] is True
    assert len(result["items"]) == 1
    mock_api.list_namespaced_pod.assert_called_once_with("default")


@patch("app.tools_k8s.client.CoreV1Api")
def test_list_pods_api_error_returns_error_result(mock_api_cls):
    from app.tools_k8s import list_pods

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.list_pod_for_all_namespaces.side_effect = Exception("connection refused")

    result = list_pods.invoke({"namespace": None})

    assert result["ok"] is False
    assert result["items"] == []
    assert "connection refused" in result["error"]


# --- list_nodes ---

@patch("app.tools_k8s.client.CoreV1Api")
def test_list_nodes_returns_node_info(mock_api_cls):
    from app.tools_k8s import list_nodes

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.list_node.return_value.items = [
        _make_node("node-1", conditions=[
            _make_condition("Ready", "True"),
            _make_condition("MemoryPressure", "False"),
        ]),
        _make_node("node-2", conditions=[
            _make_condition("Ready", "False", "node not ready"),
            _make_condition("DiskPressure", "True", "disk full"),
        ]),
    ]

    result = list_nodes.invoke({})

    assert result["ok"] is True
    assert len(result["items"]) == 2
    assert result["items"][0]["name"] == "node-1"
    conditions_node2 = {c["type"]: c for c in result["items"][1]["conditions"]}
    assert conditions_node2["DiskPressure"]["status"] == "True"
    assert result["error"] is None


@patch("app.tools_k8s.client.CoreV1Api")
def test_list_nodes_api_error_returns_error_result(mock_api_cls):
    from app.tools_k8s import list_nodes

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.list_node.side_effect = Exception("timeout")

    result = list_nodes.invoke({})

    assert result["ok"] is False
    assert "timeout" in result["error"]


# --- list_events ---

def _make_event(name, namespace, type_, reason, message, obj_name="my-pod"):
    event = MagicMock()
    event.metadata.name = name
    event.metadata.namespace = namespace
    event.type = type_
    event.reason = reason
    event.message = message
    event.involved_object.kind = "Pod"
    event.involved_object.name = obj_name
    event.involved_object.namespace = namespace
    event.count = 3
    event.last_timestamp = None
    return event


@patch("app.tools_k8s.client.CoreV1Api")
def test_list_events_all_namespaces_warnings_first(mock_api_cls):
    from app.tools_k8s import list_events

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.list_event_for_all_namespaces.return_value.items = [
        _make_event("ev-1", "default", "Normal", "Pulled", "image pulled"),
        _make_event("ev-2", "default", "Warning", "BackOff", "back-off restarting"),
    ]

    result = list_events.invoke({"namespace": None})

    assert result["ok"] is True
    assert len(result["items"]) == 2
    # Warnings should appear first
    assert result["items"][0]["type"] == "Warning"
    assert result["error"] is None


@patch("app.tools_k8s.client.CoreV1Api")
def test_list_events_specific_namespace(mock_api_cls):
    from app.tools_k8s import list_events

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.list_namespaced_event.return_value.items = [
        _make_event("ev-3", "kube-system", "Warning", "FailedScheduling", "no nodes"),
    ]

    result = list_events.invoke({"namespace": "kube-system"})

    assert result["ok"] is True
    assert result["items"][0]["reason"] == "FailedScheduling"
    mock_api.list_namespaced_event.assert_called_once_with("kube-system")


@patch("app.tools_k8s.client.CoreV1Api")
def test_list_events_api_error(mock_api_cls):
    from app.tools_k8s import list_events

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.list_event_for_all_namespaces.side_effect = Exception("forbidden")

    result = list_events.invoke({"namespace": None})

    assert result["ok"] is False
    assert "forbidden" in result["error"]


# --- list_deployments ---

def _make_deployment(name, namespace, desired, ready, available=None):
    dep = MagicMock()
    dep.metadata.name = name
    dep.metadata.namespace = namespace
    dep.spec.replicas = desired
    dep.status.ready_replicas = ready
    dep.status.available_replicas = available if available is not None else ready
    dep.status.conditions = []
    return dep


@patch("app.tools_k8s.client.AppsV1Api")
def test_list_deployments_all_namespaces(mock_api_cls):
    from app.tools_k8s import list_deployments

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.list_deployment_for_all_namespaces.return_value.items = [
        _make_deployment("api", "payments", desired=3, ready=3),
        _make_deployment("worker", "search", desired=2, ready=0),
    ]

    result = list_deployments.invoke({"namespace": None})

    assert result["ok"] is True
    assert len(result["items"]) == 2
    # Unavailable deployment (worker) sorts first
    assert result["items"][0]["ready_replicas"] == 0
    assert result["items"][0]["desired_replicas"] == 2
    assert result["error"] is None


@patch("app.tools_k8s.client.AppsV1Api")
def test_list_deployments_specific_namespace(mock_api_cls):
    from app.tools_k8s import list_deployments

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.list_namespaced_deployment.return_value.items = [
        _make_deployment("frontend", "default", desired=1, ready=1),
    ]

    result = list_deployments.invoke({"namespace": "default"})

    assert result["ok"] is True
    mock_api.list_namespaced_deployment.assert_called_once_with("default")


@patch("app.tools_k8s.client.AppsV1Api")
def test_list_deployments_api_error(mock_api_cls):
    from app.tools_k8s import list_deployments

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.list_deployment_for_all_namespaces.side_effect = Exception("unauthorized")

    result = list_deployments.invoke({"namespace": None})

    assert result["ok"] is False
    assert "unauthorized" in result["error"]


# --- get_pod ---

@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_returns_detail(mock_api_cls):
    from app.tools_k8s import get_pod

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api

    pod = _make_pod("api-7d9f", "payments", "Running", restart_count=5)
    pod.spec.node_name = "node-1"
    pod.status.host_ip = "10.0.0.1"
    pod.status.pod_ip = "192.168.1.1"
    pod.status.container_statuses[0].last_state = MagicMock()
    mock_api.read_namespaced_pod.return_value = pod

    result = get_pod.invoke({"namespace": "payments", "name": "api-7d9f"})

    assert result["ok"] is True
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["name"] == "api-7d9f"
    assert item["namespace"] == "payments"
    assert item["node_name"] == "node-1"
    assert item["container_statuses"][0]["restart_count"] == 5
    mock_api.read_namespaced_pod.assert_called_once_with(
        name="api-7d9f", namespace="payments"
    )


@patch("app.tools_k8s.client.CoreV1Api")
def test_get_pod_not_found_returns_error(mock_api_cls):
    from app.tools_k8s import get_pod

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_pod.side_effect = Exception("not found")

    result = get_pod.invoke({"namespace": "payments", "name": "nonexistent"})

    assert result["ok"] is False
    assert "not found" in result["error"]


# --- get_deployment ---

@patch("app.tools_k8s.client.AppsV1Api")
def test_get_deployment_returns_detail(mock_api_cls):
    from app.tools_k8s import get_deployment

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api

    dep = _make_deployment("api", "payments", desired=3, ready=1, available=1)
    dep.status.updated_replicas = 1
    dep.spec.selector.match_labels = {"app": "api"}
    mock_api.read_namespaced_deployment.return_value = dep

    result = get_deployment.invoke({"namespace": "payments", "name": "api"})

    assert result["ok"] is True
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["desired_replicas"] == 3
    assert item["ready_replicas"] == 1
    assert item["selector"] == {"app": "api"}
    mock_api.read_namespaced_deployment.assert_called_once_with(
        name="api", namespace="payments"
    )


@patch("app.tools_k8s.client.AppsV1Api")
def test_get_deployment_not_found_returns_error(mock_api_cls):
    from app.tools_k8s import get_deployment

    mock_api = MagicMock()
    mock_api_cls.return_value = mock_api
    mock_api.read_namespaced_deployment.side_effect = Exception("not found")

    result = get_deployment.invoke({"namespace": "default", "name": "ghost"})

    assert result["ok"] is False
    assert "not found" in result["error"]
