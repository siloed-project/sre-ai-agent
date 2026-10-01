from unittest.mock import patch

from app import tools_k8s


@patch("app.tools_k8s.config.load_incluster_config")
def test_load_kubernetes_config_uses_service_account_in_cluster(mock_load, monkeypatch):
    monkeypatch.setenv("KUBERNETES_ACCESS_MODE", "in_cluster")

    tools_k8s.load_kubernetes_config()

    mock_load.assert_called_once_with()


@patch("app.tools_k8s.config.load_kube_config")
def test_load_kubernetes_config_uses_kubeconfig_by_default(mock_load, monkeypatch):
    monkeypatch.delenv("KUBERNETES_ACCESS_MODE", raising=False)
    monkeypatch.setenv("KUBECONFIG", "/tmp/config")

    tools_k8s.load_kubernetes_config()

    mock_load.assert_called_once_with(config_file="/tmp/config")


def test_load_kubernetes_config_rejects_unknown_mode(monkeypatch):
    monkeypatch.setenv("KUBERNETES_ACCESS_MODE", "cloudflared")

    try:
        tools_k8s.load_kubernetes_config()
    except ValueError as error:
        assert "in_cluster" in str(error)
    else:
        raise AssertionError("expected an invalid access mode to fail")
