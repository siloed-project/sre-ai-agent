from unittest.mock import MagicMock, patch


@patch("app.tools_k8s_mutations.client.AppsV1Api")
@patch("app.tools_k8s_mutations.interrupt", return_value=False)
def test_restart_rejected_before_api_call(mock_interrupt, mock_api_cls):
    from app.tools_k8s_mutations import restart_deployment

    result = restart_deployment.invoke({"namespace": "default", "name": "api"})

    assert result["ok"] is False
    assert "rejected" in result["error"].lower()
    mock_api_cls.assert_not_called()
    assert mock_interrupt.call_args.args[0]["action"] == "restart_deployment"


@patch("app.tools_k8s_mutations.client.AppsV1Api")
@patch("app.tools_k8s_mutations.interrupt", return_value={"approved": True})
def test_restart_approved_patches_deployment(mock_interrupt, mock_api_cls):
    from app.tools_k8s_mutations import restart_deployment

    api = MagicMock()
    mock_api_cls.return_value = api
    result = restart_deployment.invoke({"namespace": "default", "name": "api"})

    assert result["ok"] is True
    kwargs = api.patch_namespaced_deployment.call_args.kwargs
    assert kwargs["name"] == "api"
    assert kwargs["namespace"] == "default"
    assert kwargs["_request_timeout"] == (5, 15)
    assert "kubectl.kubernetes.io/restartedAt" in kwargs["body"]["spec"]["template"]["metadata"]["annotations"]


@patch("app.tools_k8s_mutations.client.AppsV1Api")
@patch("app.tools_k8s_mutations.interrupt", return_value=True)
def test_scale_approved_patches_scale_subresource(mock_interrupt, mock_api_cls):
    from app.tools_k8s_mutations import scale_deployment

    api = MagicMock()
    mock_api_cls.return_value = api
    result = scale_deployment.invoke(
        {"namespace": "default", "name": "api", "replicas": 3}
    )

    assert result["ok"] is True
    api.patch_namespaced_deployment_scale.assert_called_once_with(
        name="api",
        namespace="default",
        body={"spec": {"replicas": 3}},
        _request_timeout=(5, 15),
    )


@patch("app.tools_k8s_mutations.interrupt")
def test_scale_rejects_out_of_range_before_approval(mock_interrupt):
    from app.tools_k8s_mutations import scale_deployment

    result = scale_deployment.invoke(
        {"namespace": "default", "name": "api", "replicas": 21}
    )

    assert result["ok"] is False
    mock_interrupt.assert_not_called()


@patch("app.tools_k8s_mutations.interrupt")
def test_protected_namespace_is_rejected_before_approval(mock_interrupt):
    from app.tools_k8s_mutations import delete_pod

    result = delete_pod.invoke({"namespace": "kube-system", "name": "coredns"})

    assert result["ok"] is False
    assert "protected namespace" in result["error"]
    mock_interrupt.assert_not_called()


@patch("app.tools_k8s_mutations.client.CoreV1Api")
@patch("app.tools_k8s_mutations.interrupt", return_value=True)
def test_delete_pod_approved_calls_api(mock_interrupt, mock_api_cls):
    from app.tools_k8s_mutations import delete_pod

    api = MagicMock()
    mock_api_cls.return_value = api
    result = delete_pod.invoke({"namespace": "default", "name": "api-123"})

    assert result["ok"] is True
    api.delete_namespaced_pod.assert_called_once_with(
        name="api-123",
        namespace="default",
        _request_timeout=(5, 15),
    )
