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
    assert result["items"][0]["name"] == "api-7d9f"
    assert result["items"][0]["restart_count"] == 12
    assert result["items"][1]["phase"] == "Pending"
    assert result["error"] is None
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
